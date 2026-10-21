"""Lógica de negocio de tickets: alta, listado y consulta con permisos por objeto."""

import uuid
from collections.abc import Sequence

from sqlalchemy.orm import Session

from backend.core.errors import NotAuthorized, NotFound
from backend.core.permissions import ensure_can_view_ticket, ticket_scope_for
from backend.models import OutboxJob, Ticket, User
from backend.models.enums import EventType, JobType, MessageType, Priority, Role, TicketStatus
from backend.repositories import outbox_repository, ticket_repository
from backend.schemas.ticket import TicketCreate
from backend.services import audit_service

TICKET_CODE_PREFIX = "TRZ-"


def format_ticket_code(number: int) -> str:
    """`TRZ-` + número con al menos 4 dígitos (RN-02): 1 → TRZ-0001, 12345 → TRZ-12345."""
    return f"{TICKET_CODE_PREFIX}{number:04d}"


def generate_public_code(db: Session) -> str:
    return format_ticket_code(ticket_repository.next_code_number(db))


def create_ticket(db: Session, requester: User, data: TicketCreate) -> Ticket:
    """Registra un ticket (CU-02, sección 9.1).

    En una sola transacción: ticket en PENDIENTE, evento TICKET_CREATED y trabajos de outbox.
    No llama a ningún servicio externo; la clasificación y los mensajes los hace el worker.
    """
    if requester.role != Role.REQUESTER:
        raise NotAuthorized("Solo los solicitantes pueden registrar tickets.")

    correlation_id = uuid.uuid4()
    try:
        ticket = ticket_repository.add(
            db,
            Ticket(
                public_code=generate_public_code(db),
                requester_id=requester.id,
                title=data.title,
                description=data.description,
                location=data.location,
                status=TicketStatus.PENDIENTE,
            ),
        )
        audit_service.record_event(
            db,
            ticket=ticket,
            event_type=EventType.TICKET_CREATED,
            actor=requester,
            new_state=TicketStatus.PENDIENTE,
            correlation_id=correlation_id,
        )
        _enqueue_creation_jobs(db, ticket, requester, correlation_id)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return ticket


def _enqueue_creation_jobs(
    db: Session, ticket: Ticket, requester: User, correlation_id: uuid.UUID
) -> None:
    base_payload = {"ticket_id": ticket.id, "correlation_id": str(correlation_id)}
    outbox_repository.add(
        db,
        OutboxJob(
            ticket_id=ticket.id, job_type=JobType.CLASSIFY_TICKET, payload_safe_json=base_payload
        ),
    )
    if requester.whatsapp_opt_in:
        outbox_repository.add(
            db,
            OutboxJob(
                ticket_id=ticket.id,
                job_type=JobType.SEND_NOTIFICATION,
                payload_safe_json={
                    **base_payload,
                    "message_type": MessageType.A1.value,
                    "recipient_user_id": requester.id,
                },
            ),
        )


def list_tickets_for_user(
    db: Session,
    user: User,
    *,
    status: TicketStatus | None = None,
    priority: Priority | None = None,
) -> Sequence[Ticket]:
    """Lista según el rol (RF-04): solicitante, los suyos; técnico, asignados; admin, todos."""
    scope = ticket_scope_for(user)
    return ticket_repository.list_tickets(
        db,
        requester_id=scope.requester_id,
        technician_id=scope.technician_id,
        status=status,
        priority=priority,
    )


def get_ticket_for_user(db: Session, user: User, public_code: str) -> Ticket:
    """Detalle de un ticket con permiso por objeto: acceso indebido → 403."""
    ticket = ticket_repository.get_by_code(db, public_code.upper())
    if ticket is None:
        raise NotFound(f"No existe el ticket {public_code}.")
    ensure_can_view_ticket(user, ticket)
    return ticket
