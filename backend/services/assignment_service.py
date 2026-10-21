"""Asignación manual (admin) y automática (sistema) de técnicos (RF-08, RN-07)."""

import uuid

from sqlalchemy.orm import Session

from backend.core.clock import utcnow
from backend.core.errors import BusinessRuleViolation
from backend.core.permissions import ensure_role
from backend.models import Assignment, Ticket, User
from backend.models.enums import EventType, MessageType, Role, TicketStatus
from backend.repositories import assignment_repository, ticket_repository, user_repository
from backend.services import audit_service, notification_service, ticket_service
from backend.services.uow import atomic

AUTO_ASSIGN_REASON = "Asignación automática por menor carga abierta"
MANUAL_ASSIGN_REASON = "Asignación manual"


def _require_active_technician(db: Session, technician_id: int) -> User:
    """CP-07: solo técnicos activos pueden recibir tickets."""
    technician = user_repository.get_by_id(db, technician_id)
    if technician is None or technician.role != Role.TECHNICIAN:
        raise BusinessRuleViolation("El usuario elegido no es un técnico.")
    if not technician.is_active:
        raise BusinessRuleViolation("No se puede asignar un ticket a un técnico inactivo.")
    return technician


def _apply_assignment(
    db: Session,
    ticket: Ticket,
    technician: User,
    *,
    actor: User | None,
    reason: str,
    correlation_id: uuid.UUID,
    expected_version: int | None,
) -> None:
    """Registra la asignación y su transición a ASIGNADO, sin confirmar."""
    was_pending = ticket.status == TicketStatus.PENDIENTE
    # Se valida antes de escribir para que TICKET_ASSIGNED quede antes del cambio de estado.
    ticket_service.validate_transition(
        ticket,
        TicketStatus.ASIGNADO,
        actor,
        reason=None if was_pending else reason,
        expected_version=expected_version,
    )
    if ticket.assigned_technician_id == technician.id:
        raise BusinessRuleViolation("El ticket ya está asignado a ese técnico.")

    now = utcnow()
    current = assignment_repository.current_for_ticket(db, ticket.id)
    if current is not None:
        current.released_at = now
    assignment_repository.add(
        db,
        Assignment(
            ticket_id=ticket.id,
            technician_id=technician.id,
            assigned_by=actor.id if actor else None,
            reason=reason,
            assigned_at=now,
        ),
    )
    ticket.assigned_technician_id = technician.id
    audit_service.record_event(
        db,
        ticket=ticket,
        event_type=EventType.TICKET_ASSIGNED,
        actor=actor,
        correlation_id=correlation_id,
        details={
            "technician_id": technician.id,
            "previous_technician_id": current.technician_id if current else None,
            "reason": reason,
        },
    )
    # La versión se comprobó al inicio; el flush de la asignación ya la incrementó.
    ticket_service.transition(
        db,
        ticket,
        TicketStatus.ASIGNADO,
        actor,
        correlation_id=correlation_id,
        reason=None if was_pending else reason,
    )
    if was_pending:
        requester = user_repository.get_by_id(db, ticket.requester_id)
        assert requester is not None
        notification_service.enqueue(
            db,
            ticket=ticket,
            recipient=requester,
            message_type=MessageType.A2,
            correlation_id=correlation_id,
        )


def assign_ticket(
    db: Session,
    ticket: Ticket,
    admin: User,
    technician_id: int,
    *,
    reason: str | None = None,
    expected_version: int | None = None,
) -> Ticket:
    """Asignación o reasignación manual por el administrador (con motivo si es reasignación)."""
    ensure_role(admin, Role.ADMIN)
    clean_reason = (reason or "").strip()
    # Primero la tabla de estados (409) y el motivo de la reasignación, con lo que envió el admin.
    ticket_service.validate_transition(
        ticket,
        TicketStatus.ASIGNADO,
        admin,
        reason=clean_reason or None,
        expected_version=expected_version,
    )
    technician = _require_active_technician(db, technician_id)
    with atomic(db):
        _apply_assignment(
            db,
            ticket,
            technician,
            actor=admin,
            reason=clean_reason or MANUAL_ASSIGN_REASON,
            correlation_id=uuid.uuid4(),
            expected_version=expected_version,
        )
    return ticket


def auto_assign(db: Session, ticket_id: int, correlation_id: uuid.UUID) -> User | None:
    """Trabajo AUTO_ASSIGN: técnico activo con menor carga (empate: menor id).

    Idempotente: si el ticket ya no está PENDIENTE o requiere revisión, no hace nada.
    """
    ticket = ticket_repository.get_by_id(db, ticket_id)
    if ticket is None or ticket.status != TicketStatus.PENDIENTE or ticket.review_required:
        return None

    technician = assignment_repository.least_loaded_active_technician(db)
    with atomic(db):
        if technician is None:
            audit_service.record_event(
                db,
                ticket=ticket,
                event_type=EventType.ADMIN_ALERT,
                actor=None,
                correlation_id=correlation_id,
                details={"reason": "sin_tecnicos_activos"},
            )
            return None
        _apply_assignment(
            db,
            ticket,
            technician,
            actor=None,
            reason=AUTO_ASSIGN_REASON,
            correlation_id=correlation_id,
            expected_version=None,
        )
    return technician
