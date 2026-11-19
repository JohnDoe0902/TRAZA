"""Estado del sistema para /health (sección 15).

Sirve para saber de un vistazo si la base responde, si el worker sigue vivo y cómo va la cola.

El código HTTP depende solo de la base. Si el worker se cae la web igual registra tickets
(regla 5) así que respondemos 200 pero con "status": "degraded" para que se note.
"""

import os
import socket
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.core.clock import utcnow
from backend.models.enums import JobStatus
from backend.repositories import health_repository, heartbeat_repository, outbox_repository
from backend.services.uow import atomic

# Si el último latido es más viejo que esto damos al worker por caído
WORKER_MAX_SILENCE = timedelta(seconds=60)


class WorkerState(StrEnum):
    OK = "ok"
    DOWN = "down"
    NEVER_SEEN = "never_seen"


@dataclass(frozen=True)
class QueueStatus:
    pending: int = 0
    failed: int = 0


@dataclass(frozen=True)
class WorkerStatus:
    state: WorkerState = WorkerState.NEVER_SEEN
    last_seen_at: datetime | None = None


@dataclass(frozen=True)
class HealthReport:
    database_ok: bool
    queue: QueueStatus = field(default_factory=QueueStatus)
    worker: WorkerStatus = field(default_factory=WorkerStatus)

    @property
    def http_status(self) -> int:
        return 200 if self.database_ok else 503

    @property
    def is_healthy(self) -> bool:
        return self.database_ok and self.worker.state == WorkerState.OK

    def as_dict(self) -> dict[str, object]:
        report: dict[str, object] = {
            "status": "ok" if self.is_healthy else "degraded",
            "database": "ok" if self.database_ok else "error",
        }
        # Si la base no responde no tenemos cifras reales y mejor no inventarlas
        if self.database_ok:
            last_seen = self.worker.last_seen_at
            report["worker"] = {
                "status": self.worker.state.value,
                "last_seen_at": last_seen.isoformat() if last_seen else None,
            }
            report["queue"] = {"pending": self.queue.pending, "failed": self.queue.failed}
        return report


def default_worker_id() -> str:
    """Nombre del equipo más el pid del proceso, por ejemplo 'pc-johan:4120'."""
    return f"{socket.gethostname()}:{os.getpid()}"[:100]


def record_heartbeat(db: Session, worker_id: str, started_at: datetime, now: datetime) -> None:
    with atomic(db):
        heartbeat_repository.upsert(db, worker_id, started_at, now)


def worker_status(last_seen_at: datetime | None, now: datetime) -> WorkerStatus:
    if last_seen_at is None:
        return WorkerStatus()
    alive = now - last_seen_at <= WORKER_MAX_SILENCE
    state = WorkerState.OK if alive else WorkerState.DOWN
    return WorkerStatus(state=state, last_seen_at=last_seen_at)


def check(db: Session, now: datetime | None = None) -> HealthReport:
    now = now or utcnow()
    try:
        health_repository.ping(db)
        counts = outbox_repository.count_by_status(db)
        last_seen_at = heartbeat_repository.latest_seen_at(db)
    except SQLAlchemyError:
        db.rollback()
        return HealthReport(database_ok=False)
    queue = QueueStatus(
        pending=counts.get(JobStatus.PENDING, 0),
        failed=counts.get(JobStatus.FAILED, 0),
    )
    return HealthReport(database_ok=True, queue=queue, worker=worker_status(last_seen_at, now))
