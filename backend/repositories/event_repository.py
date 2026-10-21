from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.models import TicketEvent


def add(db: Session, event: TicketEvent) -> TicketEvent:
    """Inserta un evento. No existen funciones para actualizar ni borrar eventos."""
    db.add(event)
    db.flush()
    return event


def list_for_ticket(db: Session, ticket_id: int) -> Sequence[TicketEvent]:
    query = (
        select(TicketEvent)
        .where(TicketEvent.ticket_id == ticket_id)
        .order_by(TicketEvent.created_at, TicketEvent.id)
    )
    return db.scalars(query).all()
