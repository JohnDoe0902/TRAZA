"""Estado del sistema para /health (sección 15).

Sirve para saber de un vistazo si la base responde y cómo va la cola del worker.
Más adelante se suma el latido del worker cuando exista la tabla worker_heartbeats.
"""

from dataclasses import dataclass, field

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.models.enums import JobStatus
from backend.repositories import health_repository, outbox_repository


@dataclass(frozen=True)
class QueueStatus:
    pending: int = 0
    failed: int = 0


@dataclass(frozen=True)
class HealthReport:
    database_ok: bool
    queue: QueueStatus = field(default_factory=QueueStatus)

    @property
    def is_healthy(self) -> bool:
        # Por ahora todo depende de la base. Con el latido también contará el worker
        return self.database_ok

    def as_dict(self) -> dict[str, object]:
        report: dict[str, object] = {
            "status": "ok" if self.is_healthy else "degraded",
            "database": "ok" if self.database_ok else "error",
        }
        # Si la base no responde no tenemos cifras reales de la cola y mejor no inventarlas
        if self.database_ok:
            report["queue"] = {"pending": self.queue.pending, "failed": self.queue.failed}
        return report


def check(db: Session) -> HealthReport:
    try:
        health_repository.ping(db)
        counts = outbox_repository.count_by_status(db)
    except SQLAlchemyError:
        db.rollback()
        return HealthReport(database_ok=False)
    queue = QueueStatus(
        pending=counts.get(JobStatus.PENDING, 0),
        failed=counts.get(JobStatus.FAILED, 0),
    )
    return HealthReport(database_ok=True, queue=queue)
