from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.models import Notification
from backend.models.enums import NotificationChannel


def add(db: Session, notification: Notification) -> Notification:
    db.add(notification)
    db.flush()
    return notification


def get(db: Session, notification_id: int) -> Notification | None:
    return db.get(Notification, notification_id)


def get_by_idempotency_key(db: Session, key: str) -> Notification | None:
    return db.scalar(select(Notification).where(Notification.idempotency_key == key))


def list_for_recipient(
    db: Session, recipient_user_id: int, channel: NotificationChannel
) -> Sequence[Notification]:
    query = (
        select(Notification)
        .where(
            Notification.recipient_user_id == recipient_user_id,
            Notification.channel == channel,
        )
        .order_by(Notification.created_at, Notification.id)
    )
    return db.scalars(query).all()


def list_for_ticket(db: Session, ticket_id: int) -> Sequence[Notification]:
    query = select(Notification).where(Notification.ticket_id == ticket_id)
    return db.scalars(query.order_by(Notification.id)).all()
