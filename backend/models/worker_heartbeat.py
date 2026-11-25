from datetime import datetime

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from backend.models.base import Base, tz_datetime


class WorkerHeartbeat(Base):
    """Última señal de vida de cada worker. /health la usa para saber si la cola avanza."""

    __tablename__ = "worker_heartbeats"

    # Nombre del equipo más el pid. Así dos workers en la misma PC no se pisan
    worker_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    started_at: Mapped[datetime] = mapped_column(tz_datetime())
    last_seen_at: Mapped[datetime] = mapped_column(tz_datetime())

    def __repr__(self) -> str:
        return f"<WorkerHeartbeat {self.worker_id} {self.last_seen_at}>"
