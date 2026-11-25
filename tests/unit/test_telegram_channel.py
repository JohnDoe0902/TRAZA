"""Canal de Telegram y el formato de los botones Sí / No."""

import pytest

from backend.integrations.base import OutgoingMessage
from backend.integrations.telegram_channel import (
    TelegramChannel,
    confirmation_callback_data,
    parse_confirmation_callback,
)
from backend.integrations.telegram_client import TelegramError
from backend.models.enums import ConfirmationAnswer, MessageType, NotificationStatus
from tests.telegram_fakes import FakeTelegram


def message(message_type: MessageType, chat_id: int | None = 55) -> OutgoingMessage:
    return OutgoingMessage(
        notification_id=10,
        message_type=message_type,
        body="TRZ-0001 texto",
        phone_e164=None,
        telegram_chat_id=chat_id,
    )


def test_la_pregunta_a3_lleva_botones_si_y_no() -> None:
    fake = FakeTelegram()

    result = TelegramChannel(fake).send(message(MessageType.A3))  # type: ignore[arg-type]

    (sent,) = fake.sent
    assert sent.chat_id == 55
    assert [b.callback_data for b in sent.buttons or []] == ["c:10:YES", "c:10:NO"]
    # Regla 9: enviado no es entregado
    assert result.status == NotificationStatus.SENT
    assert result.provider_message_id == "1"


def test_los_demas_avisos_van_sin_botones() -> None:
    fake = FakeTelegram()

    TelegramChannel(fake).send(message(MessageType.A1))  # type: ignore[arg-type]

    assert fake.sent[0].buttons is None


def test_sin_chat_vinculado_no_envia() -> None:
    with pytest.raises(TelegramError):
        TelegramChannel(FakeTelegram()).send(message(MessageType.A1, chat_id=None))  # type: ignore[arg-type]


def test_el_boton_se_lee_igual_que_se_escribe() -> None:
    data = confirmation_callback_data(42, ConfirmationAnswer.NO)

    parsed = parse_confirmation_callback(data)

    assert parsed is not None
    assert (parsed.notification_id, parsed.answer) == (42, ConfirmationAnswer.NO)
    assert len(data.encode()) <= 64  # límite de Telegram


@pytest.mark.parametrize("data", ["", "c:1", "x:1:YES", "c:abc:YES", "c:1:QUIZAS", "c:1:YES:extra"])
def test_botones_raros_se_ignoran(data: str) -> None:
    assert parse_confirmation_callback(data) is None
