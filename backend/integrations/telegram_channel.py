"""Canal de Telegram: manda los avisos al chat vinculado de cada usuario (D-41).

Cumple el mismo Protocol que el simulador así que el resto del sistema no cambia.
La pregunta de confirmación (A3) lleva los botones Sí y No. El diseño de cada aviso
está en telegram_format.

Regla 9: enviado no es entregado. Telegram no avisa a los bots cuando alguien lee un
mensaje, así que lo más que podemos decir con evidencia es SENT.
"""

from dataclasses import dataclass

from backend.integrations.base import OutgoingMessage, SendResult
from backend.integrations.telegram_client import InlineButton, TelegramClient, TelegramError
from backend.integrations.telegram_format import format_message
from backend.models.enums import (
    ConfirmationAnswer,
    MessageType,
    NotificationChannel,
    NotificationStatus,
)

# Formato de los datos del botón: "c:<id de la notificación>:<YES|NO>". Telegram deja 64 bytes
CALLBACK_PREFIX = "c"


@dataclass(frozen=True)
class ConfirmationCallback:
    notification_id: int
    answer: ConfirmationAnswer


def confirmation_callback_data(notification_id: int, answer: ConfirmationAnswer) -> str:
    return f"{CALLBACK_PREFIX}:{notification_id}:{answer.value}"


def parse_confirmation_callback(data: str) -> ConfirmationCallback | None:
    """Lee los datos de un botón. Si no son nuestros devuelve None en vez de reventar."""
    parts = data.split(":")
    if len(parts) != 3 or parts[0] != CALLBACK_PREFIX or not parts[1].isdigit():
        return None
    try:
        answer = ConfirmationAnswer(parts[2])
    except ValueError:
        return None
    return ConfirmationCallback(notification_id=int(parts[1]), answer=answer)


def confirmation_buttons(notification_id: int) -> list[InlineButton]:
    return [
        InlineButton(
            "Sí, se solucionó",
            confirmation_callback_data(notification_id, ConfirmationAnswer.YES),
        ),
        InlineButton(
            "No, continúa",
            confirmation_callback_data(notification_id, ConfirmationAnswer.NO),
        ),
    ]


class TelegramChannel:
    channel = NotificationChannel.TELEGRAM

    def __init__(self, client: TelegramClient) -> None:
        self._client = client

    def send(self, message: OutgoingMessage) -> SendResult:
        if message.telegram_chat_id is None:
            # No debería pasar porque solo encolamos a quien vinculó su cuenta
            raise TelegramError("El destinatario no tiene Telegram vinculado.", retryable=False)
        buttons = (
            confirmation_buttons(message.notification_id)
            if message.message_type == MessageType.A3
            else None
        )
        text = format_message(message)
        message_id = self._client.send_message(message.telegram_chat_id, text, buttons, html=True)
        return SendResult(status=NotificationStatus.SENT, provider_message_id=str(message_id))
