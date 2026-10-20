from datetime import datetime

from sqlalchemy import ForeignKey, Index, Sequence, String, Text, false, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.models.base import Base, CommonColumnsMixin, str_enum, tz_datetime
from backend.models.enums import Category, Impact, Priority, TicketStatus, Urgency
from backend.models.user import User

# Fuente del número del código público (RN-02). Se crea en la migración inicial.
ticket_code_seq = Sequence("ticket_code_seq", metadata=Base.metadata)


class Ticket(CommonColumnsMixin, Base):
    __tablename__ = "tickets"
    __table_args__ = (Index("ix_tickets_created_at", "created_at"),)

    public_code: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    requester_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text)
    location: Mapped[str | None] = mapped_column(String(120))

    category: Mapped[Category | None] = mapped_column(str_enum(Category, "category"))
    impact: Mapped[Impact | None] = mapped_column(str_enum(Impact, "impact"))
    urgency: Mapped[Urgency | None] = mapped_column(str_enum(Urgency, "urgency"))
    priority: Mapped[Priority | None] = mapped_column(str_enum(Priority, "priority"))
    review_required: Mapped[bool] = mapped_column(default=False, server_default=false())

    status: Mapped[TicketStatus] = mapped_column(
        str_enum(TicketStatus, "status"), default=TicketStatus.PENDIENTE, index=True
    )
    assigned_technician_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    resolution_text: Mapped[str | None] = mapped_column(Text)
    reopen_count: Mapped[int] = mapped_column(default=0, server_default=text("0"))
    version: Mapped[int] = mapped_column(server_default=text("1"))

    updated_at: Mapped[datetime] = mapped_column(
        tz_datetime(), server_default=func.now(), onupdate=func.now()
    )
    first_response_at: Mapped[datetime | None] = mapped_column(tz_datetime())
    closed_at: Mapped[datetime | None] = mapped_column(tz_datetime())
    sla_breached_at: Mapped[datetime | None] = mapped_column(tz_datetime())

    requester: Mapped[User] = relationship(foreign_keys=[requester_id])
    assigned_technician: Mapped[User | None] = relationship(foreign_keys=[assigned_technician_id])

    # Bloqueo optimista (sección 8.2): cada UPDATE exige la versión leída y la incrementa.
    __mapper_args__ = {"version_id_col": version}

    def __repr__(self) -> str:
        return f"<Ticket {self.public_code} {self.status}>"
