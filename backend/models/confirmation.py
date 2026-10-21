from datetime import datetime

from sqlalchemy import ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from backend.models.base import Base, CommonColumnsMixin, str_enum, tz_datetime
from backend.models.enums import ConfirmationAnswer, ConfirmationSource


class Confirmation(CommonColumnsMixin, Base):
    __tablename__ = "confirmations"
    # Una sola respuesta válida por ciclo de confirmación.
    __table_args__ = (UniqueConstraint("ticket_id", "confirmation_round"),)

    ticket_id: Mapped[int] = mapped_column(ForeignKey("tickets.id"))
    requester_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    notification_id: Mapped[int | None] = mapped_column(ForeignKey("notifications.id"))
    answer: Mapped[ConfirmationAnswer] = mapped_column(str_enum(ConfirmationAnswer, "answer"))
    source: Mapped[ConfirmationSource] = mapped_column(str_enum(ConfirmationSource, "source"))
    # Nulo para respuestas web; PostgreSQL permite varios NULL en una columna UNIQUE.
    provider_event_id: Mapped[str | None] = mapped_column(String(200), unique=True)
    confirmation_round: Mapped[int]
    responded_at: Mapped[datetime] = mapped_column(tz_datetime(), server_default=func.now())
