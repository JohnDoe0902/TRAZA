from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from backend.models import WorkerHeartbeat


def upsert(db: Session, worker_id: str, started_at: datetime, now: datetime) -> None:
    """Crea la fila del worker o le actualiza la hora. Va en una sola sentencia y no hay carrera."""
    statement = (
        insert(WorkerHeartbeat)
        .values(worker_id=worker_id, started_at=started_at, last_seen_at=now)
        .on_conflict_do_update(
            index_elements=[WorkerHeartbeat.worker_id],
            set_={"started_at": started_at, "last_seen_at": now},
        )
    )
    db.execute(statement)


def latest_seen_at(db: Session) -> datetime | None:
    """Hora del latido más reciente de cualquier worker."""
    return db.scalar(select(func.max(WorkerHeartbeat.last_seen_at)))
