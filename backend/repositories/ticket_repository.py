from collections.abc import Mapping, Sequence
from datetime import datetime

from sqlalchemy import Exists, and_, exists, or_, select
from sqlalchemy.orm import Session

from backend.models import Confirmation, Ticket, TicketEvent, ticket_code_seq
from backend.models.enums import EventType, Priority, TicketStatus


def next_code_number(db: Session) -> int:
    """Siguiente valor de `ticket_code_seq`. `nextval` es atómico entre conexiones."""
    return int(db.scalar(select(ticket_code_seq.next_value())))


def add(db: Session, ticket: Ticket) -> Ticket:
    db.add(ticket)
    db.flush()
    return ticket


def get_by_id(db: Session, ticket_id: int) -> Ticket | None:
    return db.get(Ticket, ticket_id)


def get_by_code(db: Session, public_code: str) -> Ticket | None:
    return db.scalar(select(Ticket).where(Ticket.public_code == public_code))


def list_tickets(
    db: Session,
    *,
    requester_id: int | None = None,
    technician_id: int | None = None,
    status: TicketStatus | None = None,
    priority: Priority | None = None,
    review_required: bool | None = None,
) -> Sequence[Ticket]:
    query = select(Ticket)
    if requester_id is not None:
        query = query.where(Ticket.requester_id == requester_id)
    if technician_id is not None:
        query = query.where(Ticket.assigned_technician_id == technician_id)
    if status is not None:
        query = query.where(Ticket.status == status)
    if priority is not None:
        query = query.where(Ticket.priority == priority)
    if review_required is not None:
        query = query.where(Ticket.review_required.is_(review_required))
    return db.scalars(query.order_by(Ticket.created_at.desc(), Ticket.id.desc())).all()


def list_sla_due(db: Session, cutoffs: Mapping[Priority, datetime]) -> Sequence[Ticket]:
    """Tickets cuyo plazo de primera atención ya venció y aún no se registró.

    `cutoffs` dice para cada prioridad desde cuándo se considera vencido. Así la base
    filtra todo en una consulta en vez de traer los tickets y revisarlos uno por uno.
    """
    overdue = or_(
        *(
            and_(Ticket.priority == priority, Ticket.created_at <= cutoff)
            for priority, cutoff in cutoffs.items()
        )
    )
    query = select(Ticket).where(
        overdue,
        Ticket.first_response_at.is_(None),
        Ticket.sla_breached_at.is_(None),
        Ticket.status != TicketStatus.CERRADO,
    )
    return db.scalars(query.order_by(Ticket.created_at, Ticket.id)).all()


def list_reminder_due(db: Session, requested_before: datetime) -> Sequence[Ticket]:
    """Tickets que esperan confirmación desde antes de `requested_before` sin respuesta ni
    recordatorio en su ronda actual. Todo en una consulta con EXISTS sobre la bitácora."""
    current_round = Ticket.reopen_count + 1

    def event_of_round(event_type: EventType) -> Exists:
        return exists().where(
            TicketEvent.ticket_id == Ticket.id,
            TicketEvent.event_type == event_type,
            TicketEvent.safe_details_json["confirmation_round"].as_integer() == current_round,
        )

    answered = exists().where(
        Confirmation.ticket_id == Ticket.id,
        Confirmation.confirmation_round == current_round,
    )
    asked_long_ago = event_of_round(EventType.CONFIRMATION_REQUESTED).where(
        TicketEvent.created_at <= requested_before
    )
    query = select(Ticket).where(
        Ticket.status == TicketStatus.PENDIENTE_CONFIRMACION,
        asked_long_ago,
        ~event_of_round(EventType.CONFIRMATION_REMINDER),
        ~answered,
    )
    return db.scalars(query.order_by(Ticket.id)).all()


def lock_for_update(db: Session, ticket_id: int) -> Ticket | None:
    """Bloquea la fila del ticket; None si otro proceso ya la tiene (SKIP LOCKED)."""
    query = (
        select(Ticket)
        .where(Ticket.id == ticket_id)
        .with_for_update(skip_locked=True)
        .execution_options(populate_existing=True)
    )
    return db.scalar(query)
