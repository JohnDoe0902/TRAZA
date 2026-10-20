"""Ciclo de vida de los trabajos de `outbox_jobs` (sección 13.5)."""

import uuid
from collections.abc import Sequence
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from backend.core.config import get_settings
from backend.models import OutboxJob, Ticket
from backend.models.enums import EventType, JobStatus, JobType
from backend.repositories import outbox_repository, ticket_repository
from backend.services import audit_service, notification_service
from backend.services.uow import atomic

BACKOFF_MINUTES = (1, 2, 4, 8, 16)
STALE_AFTER = timedelta(minutes=10)
LAST_ERROR_MAX_LENGTH = 300


def recover_stale_jobs(db: Session, now: datetime) -> int:
    """Trabajos RUNNING hace más de 10 minutos vuelven a PENDING (CP-18)."""
    with atomic(db):
        return outbox_repository.release_stale_running(db, now - STALE_AFTER)


def claim_due_jobs(db: Session, now: datetime, limit: int) -> Sequence[OutboxJob]:
    """Toma trabajos vencidos con SKIP LOCKED y los marca RUNNING."""
    with atomic(db):
        jobs = outbox_repository.lock_due_jobs(db, now, limit)
        for job in jobs:
            job.status = JobStatus.RUNNING
            job.started_at = now
    return jobs


def mark_done(db: Session, job: OutboxJob, now: datetime) -> None:
    with atomic(db):
        job.status = JobStatus.DONE
        job.completed_at = now
        job.last_error = None


def backoff_for(attempts: int) -> timedelta:
    """Espera tras el intento número `attempts` (1, 2, 4, 8, 16 min)."""
    index = min(max(attempts, 1), len(BACKOFF_MINUTES)) - 1
    return timedelta(minutes=BACKOFF_MINUTES[index])


def safe_error(exc: BaseException) -> str:
    """Tipo y mensaje recortado; los mensajes de error no llevan datos personales."""
    return f"{type(exc).__name__}: {exc}"[:LAST_ERROR_MAX_LENGTH]


def mark_failed_attempt(db: Session, job_id: int, error: BaseException, now: datetime) -> None:
    """Reintento con espera exponencial; al agotar los intentos → FAILED + ADMIN_ALERT."""
    job = outbox_repository.get(db, job_id)
    if job is None:
        return
    max_attempts = get_settings().outbox_max_attempts
    with atomic(db):
        job.attempts += 1
        job.last_error = safe_error(error)
        job.started_at = None
        if job.attempts < max_attempts:
            job.status = JobStatus.PENDING
            job.next_run_at = now + backoff_for(job.attempts)
            return
        job.status = JobStatus.FAILED
        job.completed_at = now
        if job.job_type == JobType.SEND_NOTIFICATION:
            notification_service.mark_failed(db, int(job.payload_safe_json["notification_id"]))
        ticket = ticket_repository.get_by_id(db, job.ticket_id) if job.ticket_id else None
        if ticket is not None:
            _alert_admin(db, ticket, job)


def _alert_admin(db: Session, ticket: Ticket, job: OutboxJob) -> None:
    correlation = job.payload_safe_json.get("correlation_id")
    audit_service.record_event(
        db,
        ticket=ticket,
        event_type=EventType.ADMIN_ALERT,
        actor=None,
        correlation_id=uuid.UUID(correlation) if correlation else uuid.uuid4(),
        details={
            "reason": "job_failed",
            "job_id": job.id,
            "job_type": job.job_type.value,
            "attempts": job.attempts,
        },
    )
