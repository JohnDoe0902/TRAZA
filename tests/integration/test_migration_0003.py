"""Migración 0003: lo nuevo para Telegram, el latido del worker y la plantilla A9."""

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.core.clock import utcnow
from backend.models import Notification, WorkerHeartbeat
from backend.models.enums import MessageType, NotificationChannel, NotificationStatus
from tests.helpers import Actors, new_ticket


def test_notificacion_acepta_telegram_y_a9(db: Session, actors: Actors) -> None:
    ticket = new_ticket(db, actors.requester)
    db.add(
        Notification(
            ticket_id=ticket.id,
            channel=NotificationChannel.TELEGRAM,
            recipient_user_id=actors.technician.id,
            message_type=MessageType.A9,
            body=f"Recordatorio: {ticket.public_code} superó su plazo.",
            status=NotificationStatus.PENDING,
            attempt_count=0,
            idempotency_key=f"prueba-0003-{ticket.id}",
        )
    )
    db.flush()  # si el CHECK no aceptara los valores nuevos fallaría aquí


def test_el_chat_de_telegram_no_se_repite(db: Session, actors: Actors) -> None:
    actors.requester.telegram_chat_id = 123456789012
    db.flush()

    # Dos personas con el mismo chat sería mandarle avisos ajenos a alguien
    actors.technician.telegram_chat_id = 123456789012
    with pytest.raises(IntegrityError):
        db.flush()


def test_tabla_de_latidos_existe(db: Session) -> None:
    now = utcnow()
    db.add(WorkerHeartbeat(worker_id="pc-prueba:1", started_at=now, last_seen_at=now))
    db.flush()

    assert db.get(WorkerHeartbeat, "pc-prueba:1") is not None
