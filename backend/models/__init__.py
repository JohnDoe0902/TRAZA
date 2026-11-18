"""Modelos SQLAlchemy. Importarlos aquí registra todas las tablas en `Base.metadata`."""

from backend.models.assignment import Assignment
from backend.models.base import Base
from backend.models.classification import Classification
from backend.models.confirmation import Confirmation
from backend.models.notification import Notification
from backend.models.outbox_job import OutboxJob
from backend.models.ticket import Ticket, ticket_code_seq
from backend.models.ticket_event import TicketEvent
from backend.models.user import User
from backend.models.worker_heartbeat import WorkerHeartbeat

__all__ = [
    "Assignment",
    "Base",
    "Classification",
    "Confirmation",
    "Notification",
    "OutboxJob",
    "Ticket",
    "TicketEvent",
    "User",
    "WorkerHeartbeat",
    "ticket_code_seq",
]
