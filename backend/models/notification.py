from datetime import datetime

from sqlalchemy import ForeignKey, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from backend.models.base import Base, CommonColumnsMixin, str_enum, tz_datetime
from backend.models.enums import MessageType, NotificationChannel, NotificationStatus


class Notification(CommonColumnsMixin, Base):
    __tablename__ = "notifications"

    ticket_id: Mapped[int] = mapped_column(ForeignKey("tickets.id"), index=True)
    channel: Mapped[NotificationChannel] = mapped_column(str_enum(NotificationChannel, "channel"))
    recipient_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    message_type: Mapped[MessageType] = mapped_column(str_enum(MessageType, "message_type"))
    body: Mapped[str] = mapped_column(Text)
    provider_message_id: Mapped[str | None] = mapped_column(String(200), index=True)
    status: Mapped[NotificationStatus] = mapped_column(
        str_enum(NotificationStatus, "status"), default=NotificationStatus.PENDING
    )
    attempt_count: Mapped[int] = mapped_column(default=0, server_default=text("0"))
    last_error_code: Mapped[str | None] = mapped_column(String(50))
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True)
    sent_at: Mapped[datetime | None] = mapped_column(tz_datetime())
    delivered_at: Mapped[datetime | None] = mapped_column(tz_datetime())
