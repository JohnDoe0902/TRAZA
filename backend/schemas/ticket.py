from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.models.enums import Category, Impact, Priority, TicketStatus, Urgency


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
    reopen_count: int
    created_at: datetime
    updated_at: datetime
