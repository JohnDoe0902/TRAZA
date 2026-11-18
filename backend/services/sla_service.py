"""Control del tiempo: plazos de primera atención y recordatorios (secciones 7.2 y 8.2).

El worker llama a `run_checks` en cada ciclo.

- Plazo vencido (RN-13): ticket con prioridad y sin primera atención (`first_response_at`) cuyo
  plazo ya pasó → `SLA_BREACHED` una sola vez (`sla_breached_at`). CRITICA y ALTA alertan al
  administrador; MEDIA y BAJA dejan un recordatorio para el técnico (o alertan al administrador
  si todavía no hay técnico).
- Sin respuesta (RN-12): ticket en `PENDIENTE_CONFIRMACION` sin respuesta tras
  `REMINDER_AFTER_MINUTES` → mensaje A7 al solicitante, `CONFIRMATION_REMINDER` y `ADMIN_ALERT`,
  una vez por ciclo de confirmación. El silencio nunca cierra el ticket (regla 1).

Cada ticket se revisa en su propia transacción y con su fila bloqueada (SKIP LOCKED): dos
workers a la vez no duplican avisos, y un ticket con problemas no frena a los demás.
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from backend.core.config import get_settings
from backend.core.errors import ConcurrencyConflict
from backend.models import Ticket, TicketEvent
from backend.models.enums import EventType, MessageType, Priority, TicketStatus
from backend.repositories import (
    confirmation_repository,
    event_repository,
    ticket_repository,
    user_repository,
)
from backend.services import audit_service, notification_service
from backend.services.uow import atomic

logger = logging.getLogger("traza.sla")

ADMIN_ALERT_PRIORITIES = (Priority.CRITICA, Priority.ALTA)


@dataclass(frozen=True)
class CheckResult:
    sla_breached: int = 0
    reminders: int = 0


def deadline_minutes(priority: Priority) -> int:
    """Plazo de primera atención en minutos, según la configuración (tabla 7.2)."""
    settings = get_settings()
    return {
        Priority.CRITICA: settings.sla_critica_minutes,
        Priority.ALTA: settings.sla_alta_minutes,
        Priority.MEDIA: settings.sla_media_minutes,
        Priority.BAJA: settings.sla_baja_minutes,
    }[priority]


def due_at(ticket: Ticket) -> datetime | None:
    """Momento en que vence la primera atención; None si el ticket aún no tiene prioridad."""
    if ticket.priority is None:
        return None
    return ticket.created_at + timedelta(minutes=deadline_minutes(ticket.priority))


def confirmation_round(ticket: Ticket) -> int:
    """Ciclo de confirmación vigente: 1 al principio, 2 tras la primera reapertura…"""
    return ticket.reopen_count + 1


def run_checks(db: Session, now: datetime) -> CheckResult:
    """Revisa plazos y recordatorios. Repetirlo con la misma hora no duplica nada.

    Corre cada pocos segundos así que primero la base filtra lo que de verdad venció.
    Si no hay nada son solo dos consultas aunque haya miles de tickets.
    """
    overdue = ticket_repository.list_sla_due(db, sla_cutoffs(now))
    breached = sum(_check_sla(db, ticket.id, now) for ticket in overdue)
    waiting = ticket_repository.list_reminder_due(db, now - _reminder_delay())
    reminders = sum(_check_reminder(db, ticket.id, now) for ticket in waiting)
    return CheckResult(sla_breached=breached, reminders=reminders)


def sla_cutoffs(now: datetime) -> dict[Priority, datetime]:
    """Para cada prioridad, un ticket creado antes de esta hora ya venció."""
    return {priority: now - timedelta(minutes=deadline_minutes(priority)) for priority in Priority}


# --- Plazo de primera atención ----------------------------------------------------------------


def _check_sla(db: Session, ticket_id: int, now: datetime) -> bool:
    try:
        with atomic(db):
            ticket = ticket_repository.lock_for_update(db, ticket_id)
            if ticket is None or not _sla_still_due(ticket, now):
                return False
            _register_breach(db, ticket, now)
    except ConcurrencyConflict:
        logger.info("Ticket %s cambió durante la revisión de plazo; sigue en otro ciclo", ticket_id)
        return False
    return True


def _sla_still_due(ticket: Ticket, now: datetime) -> bool:
    """Vuelve a comprobar con la fila bloqueada: otro proceso pudo atenderlo o marcarlo."""
    deadline = due_at(ticket)
    return (
        deadline is not None
        and deadline <= now
        and ticket.first_response_at is None
        and ticket.sla_breached_at is None
        and ticket.status != TicketStatus.CERRADO
    )


def _register_breach(db: Session, ticket: Ticket, now: datetime) -> None:
    assert ticket.priority is not None
    correlation_id = uuid.uuid4()
    alert_admin = ticket.priority in ADMIN_ALERT_PRIORITIES or ticket.assigned_technician_id is None
    ticket.sla_breached_at = now
    audit_service.record_event(
        db,
        ticket=ticket,
        event_type=EventType.SLA_BREACHED,
        actor=None,
        correlation_id=correlation_id,
        details={
            "priority": ticket.priority.value,
            "deadline_minutes": deadline_minutes(ticket.priority),
            "action": "admin_alert" if alert_admin else "technician_reminder",
            "technician_id": ticket.assigned_technician_id,
        },
    )
    if alert_admin:
        audit_service.record_event(
            db,
            ticket=ticket,
            event_type=EventType.ADMIN_ALERT,
            actor=None,
            correlation_id=correlation_id,
            details={"reason": "sla_breached", "priority": ticket.priority.value},
        )
    else:
        _remind_technician(db, ticket, correlation_id)


def _remind_technician(db: Session, ticket: Ticket, correlation_id: uuid.UUID) -> None:
    # Mensaje A9 al técnico. Si no puede recibir por el canal activo queda solo el evento
    assert ticket.assigned_technician_id is not None
    technician = user_repository.get_by_id(db, ticket.assigned_technician_id)
    if technician is not None:
        notification_service.enqueue(
            db,
            ticket=ticket,
            recipient=technician,
            message_type=MessageType.A9,
            correlation_id=correlation_id,
        )


# --- Recordatorio de confirmación -------------------------------------------------------------


def _check_reminder(db: Session, ticket_id: int, now: datetime) -> bool:
    with atomic(db):
        ticket = ticket_repository.lock_for_update(db, ticket_id)
        if ticket is None or ticket.status != TicketStatus.PENDIENTE_CONFIRMACION:
            return False
        current_round = confirmation_round(ticket)
        if confirmation_repository.get_for_round(db, ticket.id, current_round) is not None:
            return False
        requested = _event_of_round(db, ticket, EventType.CONFIRMATION_REQUESTED, current_round)
        if requested is None or requested.created_at > now - _reminder_delay():
            return False
        if _event_of_round(db, ticket, EventType.CONFIRMATION_REMINDER, current_round):
            return False
        _send_reminder(db, ticket, current_round, requested.created_at)
    return True


def _reminder_delay() -> timedelta:
    return timedelta(minutes=get_settings().reminder_after_minutes)


def _event_of_round(
    db: Session, ticket: Ticket, event_type: EventType, current_round: int
) -> TicketEvent | None:
    """Último evento de ese tipo que pertenece al ciclo de confirmación indicado."""
    events = event_repository.list_for_ticket(db, ticket.id, event_type=event_type)
    matching = [e for e in events if e.safe_details_json.get("confirmation_round") == current_round]
    return matching[-1] if matching else None


def _send_reminder(db: Session, ticket: Ticket, current_round: int, requested_at: datetime) -> None:
    correlation_id = uuid.uuid4()
    requester = user_repository.get_by_id(db, ticket.requester_id)
    assert requester is not None
    notification = notification_service.enqueue(
        db,
        ticket=ticket,
        recipient=requester,
        message_type=MessageType.A7,
        correlation_id=correlation_id,
    )
    audit_service.record_event(
        db,
        ticket=ticket,
        event_type=EventType.CONFIRMATION_REMINDER,
        actor=None,
        correlation_id=correlation_id,
        details={
            "confirmation_round": current_round,
            "notification_id": notification.id if notification else None,
            "requested_at": requested_at.isoformat(),
        },
    )
    audit_service.record_event(
        db,
        ticket=ticket,
        event_type=EventType.ADMIN_ALERT,
        actor=None,
        correlation_id=correlation_id,
        details={"reason": "confirmation_pending", "confirmation_round": current_round},
    )
