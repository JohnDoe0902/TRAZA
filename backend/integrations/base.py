"""Interfaces (Protocol) de los servicios externos y sus tipos de datos.

Los servicios dependen de estas interfaces, nunca de un cliente HTTP concreto.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from backend.models.enums import (
    Category,
    Impact,
    MessageType,
    NotificationChannel,
    NotificationStatus,
    Urgency,
)
from backend.models.enums import (
    ClassificationProvider as ProviderName,
)


@dataclass(frozen=True)
class TicketText:
    """Lo único que se envía a un clasificador: nunca nombres, teléfonos ni correos (RN-14)."""

    title: str
    description: str
    location: str | None = None


class ClassificationResult(BaseModel):
    """Esquema de salida de la sección 13.1, común a todos los proveedores."""

    model_config = ConfigDict(extra="forbid")

    category: Category
    impact: Impact
    urgency: Urgency
    human_review_required: bool = False
    confidence: Decimal | None = Field(default=None, ge=0, le=1)
    rationale: str | None = Field(default=None, max_length=200)


class ClassificationProvider(Protocol):
    name: ProviderName
    model_version: str | None

    def classify(self, text: TicketText) -> ClassificationResult: ...


@dataclass(frozen=True)
class OutgoingMessage:
    """Datos mínimos para transportar un mensaje; el teléfono solo si hay opt-in."""

    notification_id: int
    message_type: MessageType
    body: str
    phone_e164: str | None


@dataclass(frozen=True)
class SendResult:
    status: NotificationStatus
    provider_message_id: str | None


class NotificationProvider(Protocol):
    channel: NotificationChannel

    def send(self, message: OutgoingMessage) -> SendResult: ...
