from datetime import datetime

from sqlalchemy import ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from backend.models.base import Base, CommonColumnsMixin, tz_datetime


class Assignment(CommonColumnsMixin, Base):
    __tablename__ = "assignments"

    ticket_id: Mapped[int] = mapped_column(ForeignKey("tickets.id"), index=True)
    technician_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    # Nulo cuando la asignación la hizo el sistema.
    assigned_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    reason: Mapped[str] = mapped_column(String(500))
    assigned_at: Mapped[datetime] = mapped_column(tz_datetime(), server_default=func.now())
    released_at: Mapped[datetime | None] = mapped_column(tz_datetime())
