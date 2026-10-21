"""Datos de la página /simulador (sección 13.4): los mensajes simulados como un chat."""

from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy.orm import Session

from backend.core.config import get_settings
from backend.core.errors import BusinessRuleViolation, NotAuthorized, NotFound
from backend.models import Notification, Ticket, User
from backend.models.enums import (
    ConfirmationAnswer,
    ConfirmationSource,
    MessageType,
    NotificationChannel,
    NotificationStatus,
    Role,
    TicketStatus,
)
from backend.repositories import notification_repository, ticket_repository, user_repository
from backend.services import confirmation_service
from backend.services.confirmation_service import AnswerOutcome


@dataclass(frozen=True)
class ChatMessage:
    notification: Notification
    ticket_code: str
    can_answer: bool


def ensure_enabled() -> None:
    """El simulador solo existe en desarrollo y pruebas."""
    if not get_settings().is_development:
        raise NotFound()


def visible_recipients(db: Session, viewer: User) -> Sequence[User]:
    """El admin ve los chats de todos los usuarios con WhatsApp; los demás, solo el propio."""
    if viewer.role == Role.ADMIN:
        users = user_repository.list_requesters_with_opt_in(db)
        technicians = [u for u in user_repository.list_active_technicians(db) if u.whatsapp_opt_in]
        return [*users, *technicians]
    return [viewer] if viewer.whatsapp_opt_in else []


def ensure_can_view_chat(viewer: User, recipient: User) -> None:
    if viewer.role != Role.ADMIN and viewer.id != recipient.id:
        raise NotAuthorized("Solo puedes ver tu propio chat.")


def chat_for(db: Session, recipient: User) -> list[ChatMessage]:
    notifications = notification_repository.list_for_recipient(
        db, recipient.id, NotificationChannel.SIMULATED
    )
    tickets: dict[int, Ticket] = {}
    for notification in notifications:
        if notification.ticket_id not in tickets:
            ticket = ticket_repository.get_by_id(db, notification.ticket_id)
            assert ticket is not None
            tickets[notification.ticket_id] = ticket

    # Solo la última pregunta de confirmación de cada ticket admite respuesta.
    last_question: dict[int, int] = {
        n.ticket_id: n.id for n in notifications if n.message_type == MessageType.A3
    }
    messages = []
    for notification in notifications:
        ticket = tickets[notification.ticket_id]
        can_answer = (
            notification.message_type == MessageType.A3
            and notification.status == NotificationStatus.SIMULATED
            and last_question.get(ticket.id) == notification.id
            and ticket.requester_id == recipient.id
            and ticket.status == TicketStatus.PENDIENTE_CONFIRMACION
        )
        messages.append(ChatMessage(notification, ticket.public_code, can_answer))
    return messages


def answer(
    db: Session, viewer: User, notification_id: int, answer: ConfirmationAnswer
) -> tuple[User, AnswerOutcome]:
    """Botón "Sí, se solucionó" / "No, continúa": responde como el destinatario del mensaje."""
    notification = notification_repository.get(db, notification_id)
    if notification is None or notification.channel != NotificationChannel.SIMULATED:
        raise NotFound("No existe ese mensaje simulado.")
    recipient = user_repository.get_by_id(db, notification.recipient_user_id)
    ticket = ticket_repository.get_by_id(db, notification.ticket_id)
    assert recipient is not None and ticket is not None
    ensure_can_view_chat(viewer, recipient)
    if notification.message_type != MessageType.A3:
        raise BusinessRuleViolation("Ese mensaje no es una pregunta de confirmación.")
    if notification.status != NotificationStatus.SIMULATED:
        raise BusinessRuleViolation("El mensaje aún no se envió; ejecuta el worker.")

    outcome = confirmation_service.register_answer(
        db,
        ticket=ticket,
        responder=recipient,
        answer=answer,
        source=ConfirmationSource.SIMULATOR,
        provider_event_id=confirmation_service.simulator_event_id(notification.id, answer),
        notification_id=notification.id,
    )
    return recipient, outcome
