"""Utilidades compartidas por las pruebas."""

import secrets
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

import httpx2
import openai
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.core.security import hash_password
from backend.integrations.base import (
    ClassificationResult,
    OutgoingMessage,
    SendResult,
    TicketText,
)
from backend.integrations.mock_provider import MockProvider
from backend.integrations.rule_provider import RuleProvider
from backend.integrations.simulated_whatsapp import SimulatedWhatsApp
from backend.models import Notification, OutboxJob, Ticket, TicketEvent, User
from backend.models.enums import ClassificationProvider as ClassificationProviderName
from backend.models.enums import (
    ConfirmationAnswer,
    ConfirmationSource,
    EventType,
    NotificationChannel,
)
from backend.repositories import event_repository, notification_repository, outbox_repository
from backend.schemas.ticket import TicketCreate
from backend.services import assignment_service, confirmation_service, ticket_service
from backend.services.confirmation_service import AnswerOutcome
from backend.workers.process_outbox import Providers

# Contraseña aleatoria por corrida; el hash se calcula una vez porque argon2id es lento a propósito.
TEST_PASSWORD = secrets.token_urlsafe(16)
TEST_PASSWORD_HASH = hash_password(TEST_PASSWORD)

VALID_TICKET = {
    "title": "Laboratorio 3 sin internet",
    "description": "El laboratorio de cómputo 3 no tiene internet y hay clase en una hora.",
    "location": "Laboratorio de cómputo 3",
}


def count_rows(db: Session) -> dict[str, int]:
    """Conteo de las tablas que toca el alta, para comprobar que no se guardó nada."""
    return {
        "tickets": db.scalar(select(func.count(Ticket.id))) or 0,
        "events": db.scalar(select(func.count(TicketEvent.id))) or 0,
        "jobs": db.scalar(select(func.count(OutboxJob.id))) or 0,
    }


# --- Flujo de trabajo: llevan un ticket a cada estado usando los servicios reales -------------

RESOLUTION_TEXT = "Se reinició el switch del laboratorio y se verificó la conexión."


@dataclass
class Actors:
    requester: User
    technician: User
    other_technician: User
    admin: User


def new_ticket(db: Session, requester: User, **overrides: str) -> Ticket:
    data = TicketCreate.model_validate({**VALID_TICKET, **overrides})
    return ticket_service.create_ticket(db, requester, data)


def assigned_ticket(db: Session, actors: Actors, **overrides: str) -> Ticket:
    ticket = new_ticket(db, actors.requester, **overrides)
    return assignment_service.assign_ticket(db, ticket, actors.admin, actors.technician.id)


def in_progress_ticket(db: Session, actors: Actors) -> Ticket:
    return ticket_service.start_work(db, assigned_ticket(db, actors), actors.technician)


def pending_confirmation_ticket(db: Session, actors: Actors) -> Ticket:
    ticket = in_progress_ticket(db, actors)
    return ticket_service.propose_resolution(db, ticket, actors.technician, RESOLUTION_TEXT)


def answer(
    db: Session,
    ticket: Ticket,
    responder: User,
    value: ConfirmationAnswer,
    *,
    provider_event_id: str | None = None,
    source: ConfirmationSource = ConfirmationSource.WEB,
) -> AnswerOutcome:
    return confirmation_service.register_answer(
        db,
        ticket=ticket,
        responder=responder,
        answer=value,
        source=source,
        provider_event_id=provider_event_id,
    )


def events_of(
    db: Session, ticket: Ticket, event_type: EventType | None = None
) -> list[TicketEvent]:
    return list(event_repository.list_for_ticket(db, ticket.id, event_type=event_type))


def event_types(db: Session, ticket: Ticket) -> list[EventType]:
    return [event.event_type for event in events_of(db, ticket)]


def notifications_of(db: Session, ticket: Ticket) -> list[Notification]:
    return list(notification_repository.list_for_ticket(db, ticket.id))


def jobs_of(db: Session, ticket: Ticket) -> list[OutboxJob]:
    return list(outbox_repository.list_for_ticket(db, ticket.id))


# --- Proveedores falsos para simular fallas (nunca se llama a servicios reales) ---------------


class FailingClassifier:
    """Clasificador que falla con la excepción indicada o devuelve una salida inválida."""

    name = ClassificationProviderName.OPENAI
    model_version = "fake-model"

    def __init__(self, error: Exception | None = None, invalid_output: bool = False) -> None:
        self.error = error
        self.invalid_output = invalid_output
        self.calls = 0

    def classify(self, text: TicketText) -> ClassificationResult:
        self.calls += 1
        if self.invalid_output:
            return {"category": "INVENTADA", "impact": "AREA", "urgency": "ALTA"}  # type: ignore[return-value]
        raise self.error or RuntimeError("falla simulada del proveedor")


class FailingNotifier:
    """Proveedor de mensajes que falla las primeras `failures` veces."""

    channel = NotificationChannel.SIMULATED

    def __init__(self, failures: int = 10**6) -> None:
        self.failures = failures
        self.calls = 0
        self._ok = SimulatedWhatsApp()

    def send(self, message: OutgoingMessage) -> SendResult:
        self.calls += 1
        if self.calls <= self.failures:
            raise ConnectionError("falla simulada de WhatsApp")
        return self._ok.send(message)


def fake_providers(**overrides: object) -> Providers:
    """Proveedores de prueba: mock + reglas + simulador, salvo los que se reemplacen."""
    values: dict[str, object] = {
        "classifier": MockProvider(),
        "fallback_classifier": RuleProvider(),
        "notifier": SimulatedWhatsApp(),
    }
    values.update(overrides)
    return Providers(**values)  # type: ignore[arg-type]


# --- Cliente falso de OpenAI: imita `client.responses.parse(...)` sin red -------------------

OPENAI_URL = "https://api.openai.com/v1/responses"


class FakeOpenAIClient:
    """Devuelve `parsed` (o lanza `error`) y guarda los argumentos de cada llamada."""

    def __init__(
        self, *, parsed: Any = None, error: Exception | None = None, model: str = "gpt-falso-1"
    ) -> None:
        self.parsed = parsed
        self.error = error
        self.model = model
        self.calls: list[dict[str, Any]] = []
        self.responses = SimpleNamespace(parse=self._parse)

    def _parse(self, **kwargs: Any) -> SimpleNamespace:
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return SimpleNamespace(output_parsed=self.parsed, model=self.model)


def openai_timeout() -> openai.APITimeoutError:
    return openai.APITimeoutError(request=httpx2.Request("POST", OPENAI_URL))


def openai_server_error() -> openai.InternalServerError:
    request = httpx2.Request("POST", OPENAI_URL)
    return openai.InternalServerError(
        "Error del servidor", response=httpx2.Response(500, request=request), body=None
    )


class FakeComposer:
    """Redactor externo falso: devuelve `text` o lanza `error`."""

    name = "openai"

    def __init__(self, text: str = "", error: Exception | None = None) -> None:
        self.text = text
        self.error = error
        self.requests: list[Any] = []

    def compose(self, request: Any) -> str:
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        return self.text.replace("{codigo}", request.ticket_code)
