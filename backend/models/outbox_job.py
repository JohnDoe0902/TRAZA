from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, Index, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from backend.models.base import Base, CommonColumnsMixin, str_enum, tz_datetime
from backend.models.enums import JobStatus, JobType


class OutboxJob(CommonColumnsMixin, Base):
    """Cola de trabajos que el worker procesa después de confirmar la transacción."""

    __tablename__ = "outbox_jobs"
    __table_args__ = (Index("ix_outbox_jobs_status_next_run_at", "status", "next_run_at"),)

    ticket_id: Mapped[int | None] = mapped_column(ForeignKey("tickets.id"), index=True)
    job_type: Mapped[JobType] = mapped_column(str_enum(JobType, "job_type"))
    payload_safe_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb")
    )
    status: Mapped[JobStatus] = mapped_column(
        str_enum(JobStatus, "status"), default=JobStatus.PENDING
    )
    attempts: Mapped[int] = mapped_column(default=0, server_default=text("0"))
    next_run_at: Mapped[datetime] = mapped_column(tz_datetime(), server_default=func.now())
    last_error: Mapped[str | None] = mapped_column(Text)
    completed_at: Mapped[datetime | None] = mapped_column(tz_datetime())
