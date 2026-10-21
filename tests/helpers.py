"""Utilidades compartidas por las pruebas."""

import secrets

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.core.security import hash_password
from backend.models import OutboxJob, Ticket, TicketEvent

# Contraseña aleatoria por corrida; el hash se calcula una vez porque argon2id es lento a propósito.
TEST_PASSWORD = secrets.token_urlsafe(16)
TEST_PASSWORD_HASH = hash_password(TEST_PASSWORD)

VALID_TICKET = {
    "title": "Laboratorio 3 sin internet",
    "description": "El laboratorio de cómputo 3 no tiene internet y hay clase en una hora.",
    "location": "Laboratorio de cómputo 3",
}


def count_rows(db: Session) -> dict[str, int]:
    """Conteo de las tablas que toca el alta, para comprobar que no se guardó nada."""
    return {
        "tickets": db.scalar(select(func.count(Ticket.id))) or 0,
        "events": db.scalar(select(func.count(TicketEvent.id))) or 0,
        "jobs": db.scalar(select(func.count(OutboxJob.id))) or 0,
    }
