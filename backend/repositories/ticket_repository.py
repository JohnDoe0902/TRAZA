from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.models import Ticket, ticket_code_seq
from backend.models.enums import Priority, TicketStatus


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


def list_sla_candidates(db: Session) -> Sequence[Ticket]:
    """Tickets abiertos con prioridad, sin primera atención y sin plazo vencido registrado."""
    query = select(Ticket).where(
        Ticket.priority.is_not(None),
        Ticket.first_response_at.is_(None),
        Ticket.sla_breached_at.is_(None),
        Ticket.status != TicketStatus.CERRADO,
    )
    return db.scalars(query.order_by(Ticket.created_at, Ticket.id)).all()


def lock_for_update(db: Session, ticket_id: int) -> Ticket | None:
    """Bloquea la fila del ticket; None si otro proceso ya la tiene (SKIP LOCKED)."""
    query = (
        select(Ticket)
        .where(Ticket.id == ticket_id)
        .with_for_update(skip_locked=True)
        .execution_options(populate_existing=True)
    )
    return db.scalar(query)
