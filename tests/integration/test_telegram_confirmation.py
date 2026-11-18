"""Confirmación Sí / No desde Telegram (RF-15, RF-16, reglas 1, 7 y 9)."""

import pytest
from sqlalchemy.orm import Session

from backend.core.clock import utcnow
from backend.integrations.telegram_channel import TelegramChannel, confirmation_callback_data
from backend.models import Notification, Ticket
from backend.models.enums import (
    ConfirmationAnswer,
    ConfirmationSource,
    EventType,
    MessageType,
    NotificationChannel,
    NotificationStatus,
    TicketStatus,
)
from backend.repositories import confirmation_repository
from backend.services import telegram_bot_service, ticket_service
from backend.services.confirmation_service import AnswerOutcome
from backend.workers.process_outbox import drain
from tests.helpers import (
    RESOLUTION_TEXT,
    Actors,
    events_of,
    fake_providers,
    new_ticket,
    notifications_of,
    pending_confirmation_ticket,
)
from tests.telegram_fakes import FakeTelegram, button_update, use_telegram

REQUESTER_CHAT = 700_000_001
TECHNICIAN_CHAT = 700_000_002
YES, NO = ConfirmationAnswer.YES, ConfirmationAnswer.NO


@pytest.fixture(autouse=True)
def _telegram(monkeypatch: pytest.MonkeyPatch, actors: Actors, db: Session) -> None:
    use_telegram(monkeypatch)
    actors.requester.telegram_chat_id = REQUESTER_CHAT
    actors.technician.telegram_chat_id = TECHNICIAN_CHAT
    db.flush()


def question(db: Session, ticket: Ticket) -> Notification:
    """La última pregunta A3 del ticket."""
    return [n for n in notifications_of(db, ticket) if n.message_type == MessageType.A3][-1]


def press(
    db: Session,
    bot: FakeTelegram,
    notification: Notification,
    answer: ConfirmationAnswer,
    chat_id: int = REQUESTER_CHAT,
    callback_id: str | None = None,
) -> None:
    data = confirmation_callback_data(notification.id, answer)
    update = button_update(chat_id, data, callback_id=callback_id)
    telegram_bot_service.handle_update(db, bot, update, utcnow())


def test_la_pregunta_sale_por_telegram(db: Session, actors: Actors) -> None:
    ticket = pending_confirmation_ticket(db, actors)

    assert question(db, ticket).channel == NotificationChannel.TELEGRAM


def test_si_cierra_el_ticket(db: Session, actors: Actors) -> None:
    bot = FakeTelegram()
    ticket = pending_confirmation_ticket(db, actors)

    press(db, bot, question(db, ticket), YES)

    db.refresh(ticket)
    assert ticket.status == TicketStatus.CERRADO
    (confirmation,) = confirmation_repository.list_for_ticket(db, ticket.id)
    assert confirmation.source == ConfirmationSource.TELEGRAM
    assert confirmation.provider_event_id.startswith("tg-")
    assert bot.callback_answers == [telegram_bot_service.ANSWER_REPLIES[AnswerOutcome.CLOSED]]
    assert bot.removed_buttons  # los botones desaparecen después de responder


def test_no_reabre_y_avisa_al_tecnico(db: Session, actors: Actors) -> None:
    ticket = pending_confirmation_ticket(db, actors)

    press(db, FakeTelegram(), question(db, ticket), NO)

    db.refresh(ticket)
    assert ticket.status == TicketStatus.REABIERTO
    notified = {(n.message_type, n.recipient_user_id) for n in notifications_of(db, ticket)}
    assert (MessageType.A8, actors.technician.id) in notified


def test_cp14_el_mismo_boton_repetido_cambia_una_sola_vez(db: Session, actors: Actors) -> None:
    ticket = pending_confirmation_ticket(db, actors)
    a3 = question(db, ticket)

    # Telegram puede mandar el mismo update dos veces si el bot se reinicia
    press(db, FakeTelegram(), a3, NO, callback_id="cb-repetido")
    press(db, FakeTelegram(), a3, NO, callback_id="cb-repetido")

    assert len(events_of(db, ticket, EventType.CONFIRMATION_REJECTED)) == 1
    assert len(events_of(db, ticket, EventType.DUPLICATE_ANSWER_IGNORED)) == 1


def test_pulsar_otra_vez_ya_respondido_no_cambia_nada(db: Session, actors: Actors) -> None:
    bot = FakeTelegram()
    ticket = pending_confirmation_ticket(db, actors)
    a3 = question(db, ticket)

    press(db, bot, a3, YES)
    press(db, bot, a3, NO)  # otro clic con otro id, ya cerrado

    db.refresh(ticket)
    assert ticket.status == TicketStatus.CERRADO
    assert bot.callback_answers[-1] == telegram_bot_service.ANSWER_REPLIES[AnswerOutcome.IGNORED]


def test_un_boton_de_la_ronda_anterior_no_contesta_la_nueva(db: Session, actors: Actors) -> None:
    bot = FakeTelegram()
    ticket = pending_confirmation_ticket(db, actors)
    old_question = question(db, ticket)
    press(db, bot, old_question, NO)
    ticket = ticket_service.start_work(db, ticket, actors.technician)
    ticket = ticket_service.propose_resolution(db, ticket, actors.technician, RESOLUTION_TEXT)

    press(db, bot, old_question, YES)

    db.refresh(ticket)
    assert ticket.status == TicketStatus.PENDIENTE_CONFIRMACION
    assert bot.callback_answers[-1] == telegram_bot_service.NOT_VALID_ANYMORE


def test_un_boton_desde_otro_chat_no_cuenta(db: Session, actors: Actors) -> None:
    bot = FakeTelegram()
    ticket = pending_confirmation_ticket(db, actors)

    press(db, bot, question(db, ticket), YES, chat_id=TECHNICIAN_CHAT)

    db.refresh(ticket)
    assert ticket.status == TicketStatus.PENDIENTE_CONFIRMACION
    assert bot.callback_answers == [telegram_bot_service.NOT_FOR_YOU]


def test_un_boton_inventado_no_hace_nada(db: Session, actors: Actors) -> None:
    bot = FakeTelegram()
    ticket = pending_confirmation_ticket(db, actors)

    telegram_bot_service.handle_update(
        db, bot, button_update(REQUESTER_CHAT, "c:999999:YES"), utcnow()
    )

    db.refresh(ticket)
    assert ticket.status == TicketStatus.PENDIENTE_CONFIRMACION
    assert bot.callback_answers == [telegram_bot_service.NOT_VALID_ANYMORE]


def test_quien_no_vinculo_telegram_no_recibe_avisos(db: Session, actors: Actors) -> None:
    actors.requester.telegram_chat_id = None
    db.flush()

    ticket = new_ticket(db, actors.requester)

    assert notifications_of(db, ticket) == []


# --- Con el worker de verdad y Telegram falso ---------------------------------------------------


def test_ciclo_completo_por_telegram(db: Session, actors: Actors) -> None:
    telegram = FakeTelegram()
    providers = fake_providers(notifier=TelegramChannel(telegram))  # type: ignore[arg-type]
    ticket = pending_confirmation_ticket(db, actors)

    drain(db, providers=providers)

    a3 = question(db, ticket)
    assert a3.status == NotificationStatus.SENT  # regla 9: enviado, no "entregado"
    asked = [m for m in telegram.sent if m.buttons]
    assert asked and asked[-1].chat_id == REQUESTER_CHAT

    press(db, telegram, a3, YES)
    drain(db, providers=providers)

    db.refresh(ticket)
    assert ticket.status == TicketStatus.CERRADO
    assert any("quedó cerrada" in m.text for m in telegram.sent if m.chat_id == REQUESTER_CHAT)


def test_si_telegram_cae_el_aviso_queda_en_reintento(db: Session, actors: Actors) -> None:
    telegram = FakeTelegram(fail_sends=True)
    providers = fake_providers(notifier=TelegramChannel(telegram))  # type: ignore[arg-type]
    ticket = new_ticket(db, actors.requester)

    drain(db, providers=providers)

    a1 = next(n for n in notifications_of(db, ticket) if n.message_type == MessageType.A1)
    assert a1.status == NotificationStatus.RETRYING
    assert events_of(db, ticket, EventType.NOTIFICATION_FAILED)
