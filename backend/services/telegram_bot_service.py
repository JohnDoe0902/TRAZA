"""Qué hace TRAZA con lo que le llega al bot de Telegram.

Solo atiende dos cosas:
- "/start <token>" para vincular la cuenta (ver telegram_link_service).
- Los botones Sí / No de la pregunta A3, que van a confirmation_service.register_answer.

Las respuestas repetidas no hacen daño. Cada botón pulsado trae un id propio de Telegram que
guardamos como provider_event_id, y si el ticket ya no espera respuesta se ignora (regla 7).
No escribimos chat_id ni textos completos en los logs (RN-14).
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from backend.integrations.base import TelegramBot
from backend.integrations.telegram_channel import parse_confirmation_callback
from backend.models import Notification, Ticket
from backend.models.enums import ConfirmationSource, MessageType, NotificationChannel, TicketStatus
from backend.repositories import notification_repository, ticket_repository, user_repository
from backend.services import confirmation_service, telegram_link_service
from backend.services.confirmation_service import AnswerOutcome
from backend.services.telegram_link_service import LinkOutcome

logger = logging.getLogger("traza.telegram")

HELP_TEXT = (
    "👋 Hola, soy el bot de avisos de TRAZA.\n\n"
    "Para recibir aquí tus avisos:\n"
    "1. Entra a TRAZA con tu cuenta.\n"
    "2. Abre la opción Telegram del menú.\n"
    "3. Pulsa Vincular y abre el enlace."
)

LINK_REPLIES = {
    LinkOutcome.LINKED: (
        "✅ ¡Listo! Tu cuenta de TRAZA quedó vinculada.\n\n"
        "Desde ahora te llegarán aquí los avisos de tus solicitudes."
    ),
    LinkOutcome.ALREADY_LINKED: "👌 Tu cuenta ya estaba vinculada. No hace falta hacer nada más.",
    LinkOutcome.INVALID: "⚠️ Ese enlace no es válido. Pide uno nuevo desde TRAZA.",
    LinkOutcome.EXPIRED: "⌛ Ese enlace ya venció. Pide uno nuevo desde TRAZA.",
    LinkOutcome.CHAT_IN_USE: "🚫 Este Telegram ya está vinculado a otra cuenta de TRAZA.",
}

# Estos salen como aviso corto arriba del chat. Telegram los corta a 200 caracteres
ANSWER_REPLIES = {
    AnswerOutcome.CLOSED: "✅ Gracias por confirmar. Cerramos tu solicitud.",
    AnswerOutcome.REOPENED: "🔄 Entendido. Reabrimos tu solicitud y avisamos al técnico.",
    AnswerOutcome.IGNORED: "👌 Ya teníamos tu respuesta. No cambiamos nada.",
}

NOT_VALID_ANYMORE = "⌛ Esta pregunta ya no está vigente."
NOT_FOR_YOU = "🚫 Este botón no es para ti."


# --- Lo que llega de Telegram, ya ordenado ----------------------------------------------------


@dataclass(frozen=True)
class IncomingMessage:
    chat_id: int
    text: str


@dataclass(frozen=True)
class IncomingCallback:
    callback_id: str
    chat_id: int
    message_id: int
    data: str


def parse_update(update: dict[str, Any]) -> IncomingMessage | IncomingCallback | None:
    """Saca lo que nos sirve de un update. Grupos, fotos y demás se ignoran."""
    if callback := update.get("callback_query"):
        message = callback.get("message") or {}
        chat_id = (message.get("chat") or {}).get("id")
        if chat_id is None or "message_id" not in message:
            return None
        return IncomingCallback(
            callback_id=str(callback["id"]),
            chat_id=int(chat_id),
            message_id=int(message["message_id"]),
            data=str(callback.get("data") or ""),
        )
    message = update.get("message") or {}
    chat = message.get("chat") or {}
    # Solo chats privados. Un aviso de soporte no debe terminar en un grupo
    if chat.get("type") != "private" or not isinstance(message.get("text"), str):
        return None
    return IncomingMessage(chat_id=int(chat["id"]), text=message["text"].strip())


# --- Punto de entrada -------------------------------------------------------------------------


def handle_update(db: Session, bot: TelegramBot, update: dict[str, Any], now: datetime) -> None:
    incoming = parse_update(update)
    if isinstance(incoming, IncomingCallback):
        _handle_callback(db, bot, incoming)
    elif isinstance(incoming, IncomingMessage):
        _handle_message(db, bot, incoming, now)


def _handle_message(db: Session, bot: TelegramBot, message: IncomingMessage, now: datetime) -> None:
    command, _, argument = message.text.partition(" ")
    if command != "/start" or not argument.strip():
        _safe(bot.send_message, message.chat_id, HELP_TEXT)
        return
    result = telegram_link_service.link_chat(db, argument.strip(), message.chat_id, now)
    _safe(bot.send_message, message.chat_id, LINK_REPLIES[result.outcome])


def _handle_callback(db: Session, bot: TelegramBot, callback: IncomingCallback) -> None:
    parsed = parse_confirmation_callback(callback.data)
    notification = notification_repository.get(db, parsed.notification_id) if parsed else None
    if parsed is None or notification is None or not _is_telegram_question(notification):
        _safe(bot.answer_callback, callback.callback_id, NOT_VALID_ANYMORE)
        return

    recipient = user_repository.get_by_id(db, notification.recipient_user_id)
    if recipient is None or recipient.telegram_chat_id != callback.chat_id:
        # El botón se pulsó desde un chat que no es el del destinatario
        _safe(bot.answer_callback, callback.callback_id, NOT_FOR_YOU)
        return

    ticket = ticket_repository.get_by_id(db, notification.ticket_id)
    assert ticket is not None
    if not _is_current_question(db, ticket, notification):
        # Botón de una ronda anterior. No debe contestar la pregunta nueva
        _safe(bot.answer_callback, callback.callback_id, NOT_VALID_ANYMORE)
        _safe(bot.remove_buttons, callback.chat_id, callback.message_id)
        return

    outcome = confirmation_service.register_answer(
        db,
        ticket=ticket,
        responder=recipient,
        answer=parsed.answer,
        source=ConfirmationSource.TELEGRAM,
        provider_event_id=f"tg-{callback.callback_id}",
        notification_id=notification.id,
    )
    logger.info("Respuesta de Telegram para %s: %s", ticket.public_code, outcome.value)
    _safe(bot.answer_callback, callback.callback_id, ANSWER_REPLIES[outcome])
    _safe(bot.remove_buttons, callback.chat_id, callback.message_id)


def _is_telegram_question(notification: Notification) -> bool:
    return (
        notification.channel == NotificationChannel.TELEGRAM
        and notification.message_type == MessageType.A3
    )


def _is_current_question(db: Session, ticket: Ticket, notification: Notification) -> bool:
    """Solo la última A3 del ticket vale, y solo mientras espera confirmación."""
    if ticket.status != TicketStatus.PENDIENTE_CONFIRMACION:
        # Igual dejamos que register_answer lo registre como respuesta ignorada
        return True
    questions = [
        n.id
        for n in notification_repository.list_for_ticket(db, ticket.id)
        if n.message_type == MessageType.A3
        and n.recipient_user_id == notification.recipient_user_id
    ]
    return bool(questions) and questions[-1] == notification.id


def _safe(action: Callable[..., object], *args: Any) -> None:
    """Las respuestas al chat son cortesía. Si Telegram falla el cambio ya quedó guardado."""
    try:
        action(*args)
    except Exception as exc:
        logger.warning("No se pudo responder en Telegram: %s", type(exc).__name__)
