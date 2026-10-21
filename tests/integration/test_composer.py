"""Sección 13.2 y regla 6: redacción con GPT supervisada y respaldo con plantilla."""

from datetime import timedelta

import pytest
from sqlalchemy.orm import Session

from backend.core.clock import utcnow
from backend.integrations.openai_provider import ComposedMessage, OpenAIComposer
from backend.models.enums import EventType, MessageType, NotificationStatus
from backend.services import message_service
from backend.workers.process_outbox import drain, process_batch
from tests.helpers import (
    Actors,
    FailingNotifier,
    FakeComposer,
    FakeOpenAIClient,
    events_of,
    fake_providers,
    new_ticket,
    notifications_of,
    openai_timeout,
)


def _a1(db: Session, ticket):  # noqa: ANN001, ANN202
    return next(n for n in notifications_of(db, ticket) if n.message_type == MessageType.A1)


def _sent_details(db: Session, ticket, notification_id: int) -> dict:  # noqa: ANN001
    return next(
        e.safe_details_json
        for e in events_of(db, ticket, EventType.NOTIFICATION_SENT)
        if e.safe_details_json["notification_id"] == notification_id
    )


def test_rf12_mensaje_redactado_y_valido_se_envia(db: Session, actors: Actors) -> None:
    ticket = new_ticket(db, actors.requester)
    composer = FakeComposer(text="¡Recibimos tu solicitud {codigo}! Pronto la asignaremos.")

    drain(db, providers=fake_providers(composer=composer))

    a1 = _a1(db, ticket)
    assert a1.body == f"¡Recibimos tu solicitud {ticket.public_code}! Pronto la asignaremos."
    assert a1.status == NotificationStatus.SIMULATED
    assert _sent_details(db, ticket, a1.id)["composer"] == "openai"
    # RN-14: el redactor no recibió el nombre del solicitante.
    assert actors.requester.full_name.split()[0] not in composer.requests[0].base_message


@pytest.mark.parametrize(
    ("text", "reason"),
    [
        ("Recibimos tu solicitud. Pronto la asignaremos.", "missing_code"),
        ("Tu solicitud {codigo} ya está resuelta.", "claims_closed"),
        ("Revisa {codigo} en https://traza.example", "contains_url"),
        ("{codigo} " + "x" * 600, "too_long"),
    ],
)
def test_rf12_mensaje_invalido_usa_la_plantilla(
    db: Session, actors: Actors, text: str, reason: str
) -> None:
    ticket = new_ticket(db, actors.requester)
    template = _a1(db, ticket).body

    drain(db, providers=fake_providers(composer=FakeComposer(text=text)))

    a1 = _a1(db, ticket)
    assert a1.body == template
    assert _sent_details(db, ticket, a1.id) == {
        "notification_id": a1.id,
        "message_type": "A1",
        "channel": "SIMULATED",
        "composer": "templates",
        "composer_fallback": reason,
    }


def test_regla6_falla_de_gpt_usa_la_plantilla(db: Session, actors: Actors) -> None:
    ticket = new_ticket(db, actors.requester)
    template = _a1(db, ticket).body
    composer = OpenAIComposer(FakeOpenAIClient(error=openai_timeout()), "gpt-falso")

    drain(db, providers=fake_providers(composer=composer))

    a1 = _a1(db, ticket)
    assert a1.body == template
    assert a1.status == NotificationStatus.SIMULATED  # el envío no se bloqueó
    assert _sent_details(db, ticket, a1.id)["composer_fallback"] == "timeout"


def test_openai_composer_de_punta_a_punta(db: Session, actors: Actors) -> None:
    ticket = new_ticket(db, actors.requester)
    client = FakeOpenAIClient(parsed=ComposedMessage(text="Tu solicitud ya quedó registrada."))

    drain(db, providers=fake_providers(composer=OpenAIComposer(client, "gpt-falso")))

    # El modelo olvidó el código: el validador lo rechaza y sale la plantilla.
    a1 = _a1(db, ticket)
    assert ticket.public_code in a1.body
    assert _sent_details(db, ticket, a1.id)["composer_fallback"] == "missing_code"
    assert client.calls  # sí se le pidió el texto


def test_reintento_no_vuelve_a_llamar_al_redactor(db: Session, actors: Actors) -> None:
    ticket = new_ticket(db, actors.requester)
    composer = FakeComposer(text="Recibimos {codigo}.")
    providers = fake_providers(composer=composer, notifier=FailingNotifier(failures=1))
    start = utcnow()

    process_batch(db, providers=providers, now=start)  # redacta y falla el envío
    drain(db, providers=providers, now=start + timedelta(minutes=2))  # reintenta

    a1 = _a1(db, ticket)
    assert a1.status == NotificationStatus.SIMULATED
    assert a1.body == f"Recibimos {ticket.public_code}."
    a1_requests = [r for r in composer.requests if r.message_type == MessageType.A1]
    assert len(a1_requests) == 1


def test_sin_redactor_externo_se_envia_la_plantilla(db: Session, actors: Actors) -> None:
    ticket = new_ticket(db, actors.requester)
    drain(db, providers=fake_providers())
    a1 = _a1(db, ticket)
    assert _sent_details(db, ticket, a1.id)["composer"] == "templates"
    assert message_service.validate_message(a1.body, ticket.public_code, ticket.status) is None
