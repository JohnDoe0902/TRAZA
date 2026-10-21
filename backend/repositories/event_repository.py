from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.models import TicketEvent
from backend.models.enums import EventType


def add(db: Session, event: TicketEvent) -> TicketEvent:
    """Inserta un evento. No existen funciones para actualizar ni borrar eventos."""
    db.add(event)
    db.flush()
    return event


def list_for_ticket(
    db: Session, ticket_id: int, event_type: EventType | None = None
) -> Sequence[TicketEvent]:
    """Eventos en orden cronológico (el id desempata los de una misma transacción)."""
    query = select(TicketEvent).where(TicketEvent.ticket_id == ticket_id)
    if event_type is not None:
        query = query.where(TicketEvent.event_type == event_type)
    return db.scalars(query.order_by(TicketEvent.created_at, TicketEvent.id)).all()
