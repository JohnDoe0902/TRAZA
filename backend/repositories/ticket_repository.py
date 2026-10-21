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


def get_by_code(db: Session, public_code: str) -> Ticket | None:
    return db.scalar(select(Ticket).where(Ticket.public_code == public_code))


def list_tickets(
    db: Session,
    *,
    requester_id: int | None = None,
    technician_id: int | None = None,
    status: TicketStatus | None = None,
    priority: Priority | None = None,
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
    return db.scalars(query.order_by(Ticket.created_at.desc(), Ticket.id.desc())).all()
