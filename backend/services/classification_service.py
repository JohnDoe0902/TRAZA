"""Clasificación de tickets (RF-05 a RF-07).

La IA (o el mock) sugiere categoría, impacto y urgencia; la prioridad sale de la matriz y la
revisión humana de RN-04 (regla 4). Si el proveedor falla o su salida no valida, se clasifica
con reglas y se registra CLASSIFICATION_FALLBACK (regla 6).
"""

import uuid
from decimal import ROUND_HALF_UP, Decimal

from pydantic import ValidationError
from sqlalchemy.orm import Session

from backend.integrations.base import ClassificationProvider, ClassificationResult, TicketText
from backend.models import Classification, OutboxJob, Ticket
from backend.models.enums import ActorType, EventType, JobType
from backend.repositories import classification_repository, outbox_repository, ticket_repository
from backend.services import audit_service
from backend.services.priority_rules import RULES_VERSION, compute_priority, needs_review
from backend.services.uow import atomic


def _fallback_reason(exc: Exception) -> str:
    if isinstance(exc, TimeoutError):
        return "timeout"
    if isinstance(exc, ValidationError):
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
