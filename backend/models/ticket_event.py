import uuid
from typing import Any

from sqlalchemy import ForeignKey, Index, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from backend.models.base import Base, CommonColumnsMixin, str_enum
from backend.models.enums import ActorType, EventType, TicketStatus


class TicketEvent(CommonColumnsMixin, Base):
    """Bitácora de auditoría. Solo inserción: un trigger en la base rechaza UPDATE y DELETE."""

    __tablename__ = "ticket_events"
    __table_args__ = (Index("ix_ticket_events_ticket_id_created_at", "ticket_id", "created_at"),)

    ticket_id: Mapped[int] = mapped_column(ForeignKey("tickets.id"))
    event_type: Mapped[EventType] = mapped_column(str_enum(EventType, "event_type"))
    actor_type: Mapped[ActorType] = mapped_column(str_enum(ActorType, "actor_type"))
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    old_state: Mapped[TicketStatus | None] = mapped_column(str_enum(TicketStatus, "old_state"))
    new_state: Mapped[TicketStatus | None] = mapped_column(str_enum(TicketStatus, "new_state"))
    safe_details_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb")
    )
    correlation_id: Mapped[uuid.UUID]
