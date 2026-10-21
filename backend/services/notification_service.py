"""Notificaciones: se encolan en la transacción del cambio y el worker las entrega.

- Solo se notifica a usuarios con `whatsapp_opt_in` (RN-14).
- Cada notificación tiene `idempotency_key` y estado propio (RN-09).
- El estado solo avanza con la respuesta del proveedor o del simulador (regla 9).
"""

import uuid

from sqlalchemy.orm import Session

from backend.core.clock import utcnow
from backend.core.config import get_settings
from backend.integrations.base import NotificationProvider, OutgoingMessage
from backend.models import Notification, OutboxJob, Ticket, User
from backend.models.enums import (
    ActorType,
    EventType,
    JobType,
    MessageType,
    NotificationChannel,
    NotificationStatus,
)
from backend.repositories import notification_repository, outbox_repository, user_repository
from backend.services import audit_service, message_service
from backend.services.uow import atomic

DELIVERABLE_STATUSES = (NotificationStatus.PENDING, NotificationStatus.RETRYING)


def current_channel() -> NotificationChannel:
    if get_settings().notification_provider == "whatsapp":
        return NotificationChannel.WHATSAPP
    return NotificationChannel.SIMULATED


def enqueue(
    db: Session,
    *,
    ticket: Ticket,
    recipient: User,
    message_type: MessageType,
    correlation_id: uuid.UUID,
) -> Notification | None:
    """Crea la notificación (PENDING) y su trabajo SEND_NOTIFICATION, sin confirmar.

    Devuelve None si el destinatario no aceptó WhatsApp.
    """
    if not recipient.whatsapp_opt_in:
        return None

    key = f"{ticket.id}:{message_type.value}:{recipient.id}:{correlation_id}"
    existing = notification_repository.get_by_idempotency_key(db, key)
    if existing is not None:
        return existing

    body = message_service.compose(
        message_type,
        message_service.MessageContext(
            code=ticket.public_code, first_name=message_service.first_name(recipient.full_name)
        ),
    )
    notification = notification_repository.add(
        db,
        Notification(
            ticket_id=ticket.id,
            channel=current_channel(),
            recipient_user_id=recipient.id,
            message_type=message_type,
            body=body,
            status=NotificationStatus.PENDING,
            attempt_count=0,
            idempotency_key=key,
        ),
    )
    outbox_repository.add(
        db,
        OutboxJob(
            ticket_id=ticket.id,
            job_type=JobType.SEND_NOTIFICATION,
            payload_safe_json={
                "notification_id": notification.id,
                "ticket_id": ticket.id,
                "correlation_id": str(correlation_id),
            },
        ),
    )
    return notification


def deliver(
    db: Session,
    notification_id: int,
    provider: NotificationProvider,
    correlation_id: uuid.UUID,
) -> None:
    """Entrega una notificación (trabajo del worker). Repetirlo no reenvía lo ya enviado."""
    notification = notification_repository.get(db, notification_id)
    if notification is None or notification.status not in DELIVERABLE_STATUSES:
        return
    recipient = user_repository.get_by_id(db, notification.recipient_user_id)
    ticket = db.get(Ticket, notification.ticket_id)
    assert recipient is not None and ticket is not None

    message = OutgoingMessage(
        notification_id=notification.id,
        message_type=notification.message_type,
        body=notification.body,
        phone_e164=recipient.phone_e164 if recipient.whatsapp_opt_in else None,
    )
    try:
        result = provider.send(message)
    except Exception as exc:
        with atomic(db):
            notification.attempt_count += 1
            notification.status = NotificationStatus.RETRYING
            notification.last_error_code = type(exc).__name__[:50]
            audit_service.record_event(
                db,
                ticket=ticket,
                event_type=EventType.NOTIFICATION_FAILED,
                actor=None,
                actor_type=ActorType.INTEGRATION,
                correlation_id=correlation_id,
                details={
                    "notification_id": notification.id,
                    "error_code": notification.last_error_code,
                    "attempt": notification.attempt_count,
                },
            )
        raise

    with atomic(db):
        notification.attempt_count += 1
        notification.status = result.status
        notification.provider_message_id = result.provider_message_id
        notification.sent_at = utcnow()
        notification.last_error_code = None
        audit_service.record_event(
            db,
            ticket=ticket,
            event_type=EventType.NOTIFICATION_SENT,
            actor=None,
            actor_type=ActorType.INTEGRATION,
            correlation_id=correlation_id,
            details={
                "notification_id": notification.id,
                "message_type": notification.message_type.value,
                "channel": notification.channel.value,
            },
        )


def mark_failed(db: Session, notification_id: int) -> None:
    """Agotados los reintentos, la notificación queda FAILED (nunca 'entregada')."""
    notification = notification_repository.get(db, notification_id)
    if notification is not None and notification.status in DELIVERABLE_STATUSES:
        notification.status = NotificationStatus.FAILED
