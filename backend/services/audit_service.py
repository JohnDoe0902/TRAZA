"""Registro de eventos de auditoría (regla 3). Siempre dentro de la transacción del cambio."""

import uuid
from typing import Any

from sqlalchemy.orm import Session

from backend.models import Ticket, TicketEvent, User
from backend.models.enums import ActorType, EventType, TicketStatus
from backend.repositories import event_repository


def record_event(
    db: Session,
    *,
    ticket: Ticket,
    event_type: EventType,
    actor: User | None,
    correlation_id: uuid.UUID,
    actor_type: ActorType | None = None,
    old_state: TicketStatus | None = None,
    new_state: TicketStatus | None = None,
    details: dict[str, Any] | None = None,
) -> TicketEvent:
    """Agrega un evento sin confirmar la transacción: quien llama hace el commit del cambio."""
    event = TicketEvent(
        ticket_id=ticket.id,
        event_type=event_type,
        actor_type=actor_type or (ActorType.USER if actor else ActorType.SYSTEM),
        actor_id=actor.id if actor else None,
        old_state=old_state,
        new_state=new_state,
        safe_details_json=details or {},
        correlation_id=correlation_id,
    )
    return event_repository.add(db, event)
