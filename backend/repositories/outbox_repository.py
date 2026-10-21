from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from backend.models import OutboxJob
from backend.models.enums import JobStatus


def add(db: Session, job: OutboxJob) -> OutboxJob:
    db.add(job)
    db.flush()
    return job


def get(db: Session, job_id: int) -> OutboxJob | None:
    return db.get(OutboxJob, job_id)


def list_for_ticket(db: Session, ticket_id: int) -> Sequence[OutboxJob]:
    query = select(OutboxJob).where(OutboxJob.ticket_id == ticket_id).order_by(OutboxJob.id)
    return db.scalars(query).all()


def lock_due_jobs(db: Session, now: datetime, limit: int) -> Sequence[OutboxJob]:
    """Trabajos PENDING vencidos, bloqueados para este worker (otros workers los saltan)."""
    query = (
        select(OutboxJob)
        .where(OutboxJob.status == JobStatus.PENDING, OutboxJob.next_run_at <= now)
        .order_by(OutboxJob.next_run_at, OutboxJob.id)
        .limit(limit)
        .with_for_update(skip_locked=True)
    )
    return db.scalars(query).all()


def release_stale_running(db: Session, started_before: datetime) -> int:
    """Devuelve a PENDING los trabajos RUNNING tomados antes de `started_before`."""
    result = db.execute(
        update(OutboxJob)
        .where(OutboxJob.status == JobStatus.RUNNING, OutboxJob.started_at < started_before)
        .values(status=JobStatus.PENDING, started_at=None)
        .execution_options(synchronize_session=False)
    )
    return result.rowcount or 0
