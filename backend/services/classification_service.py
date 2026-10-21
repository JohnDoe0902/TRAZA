"""Clasificación de tickets (RF-05 a RF-07).

La IA (o el mock) sugiere categoría, impacto y urgencia; la prioridad sale de la matriz y la
revisión humana de RN-04 (regla 4). Si el proveedor falla o su salida no valida, se clasifica
con reglas y se registra CLASSIFICATION_FALLBACK (regla 6).
"""

import uuid
from decimal import ROUND_HALF_UP, Decimal

from pydantic import ValidationError
from sqlalchemy.orm import Session

from backend.core.errors import ConcurrencyConflict, InvalidState
from backend.core.permissions import ensure_role
from backend.integrations.base import (
    ClassificationProvider,
    ClassificationResult,
    ProviderOutputError,
    TicketText,
)
from backend.models import Classification, OutboxJob, Ticket, User
from backend.models.enums import (
    ActorType,
    Category,
    EventType,
    Impact,
    JobType,
    Role,
    TicketStatus,
    Urgency,
)
from backend.models.enums import ClassificationProvider as ProviderName
from backend.repositories import classification_repository, outbox_repository, ticket_repository
from backend.services import audit_service
from backend.services.priority_rules import RULES_VERSION, compute_priority, needs_review
from backend.services.uow import atomic


def _fallback_reason(exc: Exception) -> str:
    if isinstance(exc, TimeoutError):
        return "timeout"
    if isinstance(exc, ValidationError | ProviderOutputError):
        return "invalid_output"
    return "provider_error"


def _suggest(
    provider: ClassificationProvider, fallback: ClassificationProvider, text: TicketText
) -> tuple[ClassificationProvider, ClassificationResult, str | None]:
    """Devuelve (proveedor usado, resultado validado, motivo del fallback o None)."""
    try:
        raw = provider.classify(text)
        # Se revalida siempre: un proveedor externo no es fuente de verdad.
        result = ClassificationResult.model_validate(
            raw.model_dump() if isinstance(raw, ClassificationResult) else raw
        )
        return provider, result, None
    except Exception as exc:
        if provider.name == fallback.name:
            raise
        return fallback, fallback.classify(text), _fallback_reason(exc)


def classify_ticket(
    db: Session,
    ticket_id: int,
    correlation_id: uuid.UUID,
    *,
    provider: ClassificationProvider,
    fallback: ClassificationProvider,
) -> Classification | None:
    """Trabajo CLASSIFY_TICKET. Idempotente: un ticket ya clasificado no se reclasifica."""
    ticket = ticket_repository.get_by_id(db, ticket_id)
    if ticket is None or ticket.priority is not None:
        return None

    text = TicketText(title=ticket.title, description=ticket.description, location=ticket.location)
    used, result, fallback_reason = _suggest(provider, fallback, text)

    confidence = (
        result.confidence.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if result.confidence is not None
        else None
    )
    priority = compute_priority(result.impact, result.urgency)
    review_required = needs_review(result.category, confidence, result.human_review_required)

    with atomic(db):
        if fallback_reason is not None:
            audit_service.record_event(
                db,
                ticket=ticket,
                event_type=EventType.CLASSIFICATION_FALLBACK,
                actor=None,
                correlation_id=correlation_id,
                details={"reason": fallback_reason, "failed_provider": provider.name.value},
            )
        classification = classification_repository.add(
            db,
            Classification(
                ticket_id=ticket.id,
                provider=used.name,
                category_suggested=result.category,
                impact_suggested=result.impact,
                urgency_suggested=result.urgency,
                priority_computed=priority,
                confidence=confidence,
                review_required=review_required,
                rationale=result.rationale,
                rules_version=RULES_VERSION,
                model_version=used.model_version,
            ),
        )
        _apply_to_ticket(ticket, classification)
        audit_service.record_event(
            db,
            ticket=ticket,
            event_type=EventType.TICKET_CLASSIFIED,
            actor=None,
            actor_type=ActorType.SYSTEM,
            correlation_id=correlation_id,
            details={
                "provider": used.name.value,
                "category": result.category.value,
                "impact": result.impact.value,
                "urgency": result.urgency.value,
                "priority": priority.value,
                "review_required": review_required,
            },
        )
        if not review_required:
            outbox_repository.add(
                db,
                OutboxJob(
                    ticket_id=ticket.id,
                    job_type=JobType.AUTO_ASSIGN,
                    payload_safe_json={
                        "ticket_id": ticket.id,
                        "correlation_id": str(correlation_id),
                    },
                ),
            )
    return classification


def _apply_to_ticket(ticket: Ticket, classification: Classification) -> None:
    ticket.category = classification.category_suggested
    ticket.impact = classification.impact_suggested
    ticket.urgency = classification.urgency_suggested
    ticket.priority = classification.priority_computed
    ticket.review_required = classification.review_required


# --- Validación o corrección por el administrador (RN-04) -------------------------------------


def _snapshot(ticket: Ticket) -> dict[str, object]:
    return {
        "category": ticket.category.value if ticket.category else None,
        "impact": ticket.impact.value if ticket.impact else None,
        "urgency": ticket.urgency.value if ticket.urgency else None,
        "priority": ticket.priority.value if ticket.priority else None,
        "review_required": ticket.review_required,
    }


def validate_classification(
    db: Session,
    ticket: Ticket,
    admin: User,
    *,
    category: Category,
    impact: Impact,
    urgency: Urgency,
    expected_version: int | None = None,
) -> Classification:
    """El administrador confirma o corrige la clasificación sugerida.

    La prioridad se recalcula con la matriz (regla 4) y la revisión pendiente se levanta. Si el
    ticket sigue sin asignar, se encola la asignación automática que RN-04 había frenado.
    """
    ensure_role(admin, Role.ADMIN)
    if ticket.status == TicketStatus.CERRADO:
        raise InvalidState("No se puede reclasificar un ticket cerrado.")
    if expected_version is not None and expected_version != ticket.version:
        raise ConcurrencyConflict()

    previous = _snapshot(ticket)
    correlation_id = uuid.uuid4()
    with atomic(db):
        classification = classification_repository.add(
            db,
            Classification(
                ticket_id=ticket.id,
                provider=ProviderName.MANUAL,
                category_suggested=category,
                impact_suggested=impact,
                urgency_suggested=urgency,
                priority_computed=compute_priority(impact, urgency),
                confidence=None,
                review_required=False,
                rationale=None,
                rules_version=RULES_VERSION,
                model_version=None,
                validated_by=admin.id,
            ),
        )
        _apply_to_ticket(ticket, classification)
        audit_service.record_event(
            db,
            ticket=ticket,
            event_type=EventType.CLASSIFICATION_VALIDATED,
            actor=admin,
            correlation_id=correlation_id,
            details={"previous": previous, "new": _snapshot(ticket)},
        )
        if ticket.status == TicketStatus.PENDIENTE and ticket.assigned_technician_id is None:
            outbox_repository.add(
                db,
                OutboxJob(
                    ticket_id=ticket.id,
                    job_type=JobType.AUTO_ASSIGN,
                    payload_safe_json={
                        "ticket_id": ticket.id,
                        "correlation_id": str(correlation_id),
                    },
                ),
            )
    return classification
