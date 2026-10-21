import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.models.enums import (
    ActorType,
    Category,
    ConfirmationAnswer,
    EventType,
    Impact,
    Priority,
    TicketStatus,
    Urgency,
)


class TicketCreate(BaseModel):
    """Datos de alta (sección 9.1). Los espacios al inicio y al final no cuentan."""

    model_config = ConfigDict(str_strip_whitespace=True)

    title: str = Field(min_length=5, max_length=120)
    description: str = Field(min_length=10, max_length=2000)
    location: str | None = Field(default=None, max_length=120)

    @field_validator("location", mode="before")
    @classmethod
    def empty_location_is_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value


class TicketOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    public_code: str
    title: str
    description: str
    location: str | None
    status: TicketStatus
    category: Category | None
    impact: Impact | None
    urgency: Urgency | None
    priority: Priority | None
    review_required: bool
    requester_id: int
    assigned_technician_id: int | None
    resolution_text: str | None
    reopen_count: int
    version: int
    created_at: datetime
    updated_at: datetime
    first_response_at: datetime | None
    closed_at: datetime | None


class VersionIn(BaseModel):
    """Versión leída por el cliente; si no coincide con la actual → 409 (bloqueo optimista)."""

    version: int | None = None


class AssignIn(VersionIn):
    model_config = ConfigDict(str_strip_whitespace=True)

    technician_id: int
    reason: str | None = Field(default=None, max_length=500)


class ResolveIn(VersionIn):
    model_config = ConfigDict(str_strip_whitespace=True)

    resolution_text: str = Field(min_length=10, max_length=2000)


class ClassificationIn(VersionIn):
    """Clasificación confirmada o corregida por el admin; la prioridad la calcula la matriz."""

    category: Category
    impact: Impact
    urgency: Urgency


class ConfirmIn(BaseModel):
    answer: ConfirmationAnswer


class ConfirmOut(BaseModel):
    result: str
    status: TicketStatus


class EventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    event_type: EventType
    actor_type: ActorType
    actor_id: int | None
    old_state: TicketStatus | None
    new_state: TicketStatus | None
    safe_details_json: dict[str, Any]
    correlation_id: uuid.UUID
    created_at: datetime
