"""Plazos y recordatorios (secciones 7.2 y 8.2): CP-15, CP-23, RN-12, RN-13 y regla 1.

La hora se controla pasando `now` a los servicios: los tickets y eventos de una prueba se crean
en la misma transacción, así que comparten la marca de tiempo de inicio.
"""

from datetime import datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from backend.models import Ticket
from backend.models.enums import (
    ConfirmationAnswer,
    EventType,
    MessageType,
    NotificationStatus,
    Priority,
    TicketStatus,
)
from backend.services import sla_service, ticket_service
from backend.services.uow import atomic
from backend.workers import process_outbox
from tests.helpers import (
    RESOLUTION_TEXT,
    Actors,
    answer,
    assigned_ticket,
    events_of,
    fake_providers,
    in_progress_ticket,
    new_ticket,
    notifications_of,
    pending_confirmation_ticket,
)


def with_priority(db: Session, ticket: Ticket, priority: Priority) -> Ticket:
    with atomic(db):
        ticket.priority = priority
    return ticket


def minutes_after(ticket: Ticket, minutes: int) -> datetime:
    return ticket.created_at + timedelta(minutes=minutes)


def reminders_of(db: Session, ticket: Ticket) -> list[int]:
    """Ciclo de confirmación de cada recordatorio registrado."""
    return [
        event.safe_details_json["confirmation_round"]
        for event in events_of(db, ticket, EventType.CONFIRMATION_REMINDER)
    ]


def alert_reasons(db: Session, ticket: Ticket) -> list[str]:
    return [e.safe_details_json["reason"] for e in events_of(db, ticket, EventType.ADMIN_ALERT)]


# --- Plazo de primera atención (RN-13) --------------------------------------------------------


def test_cp23_plazo_vencido_se_registra_una_sola_vez(db: Session, actors: Actors) -> None:
    ticket = with_priority(db, assigned_ticket(db, actors), Priority.CRITICA)

    first = sla_service.run_checks(db, minutes_after(ticket, 16))
    second = sla_service.run_checks(db, minutes_after(ticket, 60))

    assert first.sla_breached == 1
    assert second.sla_breached == 0
    db.refresh(ticket)
    assert ticket.sla_breached_at == minutes_after(ticket, 16)
    breaches = events_of(db, ticket, EventType.SLA_BREACHED)
    assert len(breaches) == 1
    assert breaches[0].safe_details_json["priority"] == "CRITICA"
    assert breaches[0].safe_details_json["deadline_minutes"] == 15
    assert alert_reasons(db, ticket) == ["sla_breached"]


def test_cp23_antes_del_plazo_no_se_registra_nada(db: Session, actors: Actors) -> None:
    ticket = with_priority(db, assigned_ticket(db, actors), Priority.CRITICA)

    result = sla_service.run_checks(db, minutes_after(ticket, 14))

    assert result.sla_breached == 0
    db.refresh(ticket)
    assert ticket.sla_breached_at is None
    assert events_of(db, ticket, EventType.SLA_BREACHED) == []


@pytest.mark.parametrize(
    ("priority", "minutes"),
    [(Priority.CRITICA, 15), (Priority.ALTA, 30), (Priority.MEDIA, 120), (Priority.BAJA, 1440)],
)
def test_cada_prioridad_vence_en_su_plazo(
    db: Session, actors: Actors, priority: Priority, minutes: int
) -> None:
    ticket = with_priority(db, assigned_ticket(db, actors), priority)

    assert sla_service.run_checks(db, minutes_after(ticket, minutes - 1)).sla_breached == 0
    assert sla_service.run_checks(db, minutes_after(ticket, minutes)).sla_breached == 1


def test_media_con_tecnico_deja_recordatorio_al_tecnico_sin_alertar(
    db: Session, actors: Actors
) -> None:
    ticket = with_priority(db, assigned_ticket(db, actors), Priority.MEDIA)

    sla_service.run_checks(db, minutes_after(ticket, 121))

    (breach,) = events_of(db, ticket, EventType.SLA_BREACHED)
    assert breach.safe_details_json["action"] == "technician_reminder"
    assert breach.safe_details_json["technician_id"] == actors.technician.id
    assert alert_reasons(db, ticket) == []
    (reminder,) = [n for n in notifications_of(db, ticket) if n.message_type == MessageType.A9]
    assert reminder.recipient_user_id == actors.technician.id


def test_baja_sin_tecnico_alerta_al_administrador(db: Session, actors: Actors) -> None:
    ticket = with_priority(db, new_ticket(db, actors.requester), Priority.BAJA)

    sla_service.run_checks(db, minutes_after(ticket, 1441))

    (breach,) = events_of(db, ticket, EventType.SLA_BREACHED)
    assert breach.safe_details_json["action"] == "admin_alert"
    assert alert_reasons(db, ticket) == ["sla_breached"]


def test_ticket_atendido_a_tiempo_no_vence(db: Session, actors: Actors) -> None:
    ticket = with_priority(db, in_progress_ticket(db, actors), Priority.CRITICA)

    sla_service.run_checks(db, minutes_after(ticket, 120))

    assert events_of(db, ticket, EventType.SLA_BREACHED) == []


def test_ticket_sin_prioridad_no_tiene_plazo(db: Session, actors: Actors) -> None:
    ticket = new_ticket(db, actors.requester)

    sla_service.run_checks(db, minutes_after(ticket, 10_000))

    assert ticket.priority is None
    assert events_of(db, ticket, EventType.SLA_BREACHED) == []


# --- Recordatorio sin respuesta (RN-12) -------------------------------------------------------


def test_cp15_sin_respuesta_envia_recordatorio_y_alerta(db: Session, actors: Actors) -> None:
    ticket = pending_confirmation_ticket(db, actors)

    result = sla_service.run_checks(db, minutes_after(ticket, 121))

    assert result.reminders == 1
    db.refresh(ticket)
    assert ticket.status == TicketStatus.PENDIENTE_CONFIRMACION
    assert reminders_of(db, ticket) == [1]
    assert alert_reasons(db, ticket) == ["confirmation_pending"]
    (reminder,) = [n for n in notifications_of(db, ticket) if n.message_type == MessageType.A7]
    assert reminder.recipient_user_id == actors.requester.id
    assert reminder.status == NotificationStatus.PENDING
    assert ticket.public_code in reminder.body


def test_cp15_antes_del_plazo_no_hay_recordatorio(db: Session, actors: Actors) -> None:
    ticket = pending_confirmation_ticket(db, actors)

    assert sla_service.run_checks(db, minutes_after(ticket, 119)).reminders == 0
    assert reminders_of(db, ticket) == []


def test_recordatorio_una_sola_vez_por_ciclo(db: Session, actors: Actors) -> None:
    ticket = pending_confirmation_ticket(db, actors)
    sla_service.run_checks(db, minutes_after(ticket, 121))
    sla_service.run_checks(db, minutes_after(ticket, 500))

    # El solicitante responde No: el ticket vuelve a atención y luego a un ciclo nuevo.
    answer(db, ticket, actors.requester, ConfirmationAnswer.NO)
    ticket = ticket_service.start_work(db, ticket, actors.technician)
    ticket = ticket_service.propose_resolution(db, ticket, actors.technician, RESOLUTION_TEXT)
    sla_service.run_checks(db, minutes_after(ticket, 600))
    sla_service.run_checks(db, minutes_after(ticket, 900))

    assert reminders_of(db, ticket) == [1, 2]
    assert [n.message_type for n in notifications_of(db, ticket)].count(MessageType.A7) == 2


def test_respondido_no_recibe_recordatorio(db: Session, actors: Actors) -> None:
    ticket = pending_confirmation_ticket(db, actors)
    answer(db, ticket, actors.requester, ConfirmationAnswer.YES)

    assert sla_service.run_checks(db, minutes_after(ticket, 121)).reminders == 0
    assert reminders_of(db, ticket) == []


def test_regla1_el_silencio_nunca_cierra(db: Session, actors: Actors) -> None:
    ticket = pending_confirmation_ticket(db, actors)

    for minutes in (121, 60 * 24, 60 * 24 * 30):
        sla_service.run_checks(db, minutes_after(ticket, minutes))

    db.refresh(ticket)
    assert ticket.status == TicketStatus.PENDIENTE_CONFIRMACION
    assert ticket.closed_at is None
    assert events_of(db, ticket, EventType.CONFIRMATION_ACCEPTED) == []
    assert reminders_of(db, ticket) == [1]


# --- Integración con el worker ----------------------------------------------------------------


def test_el_worker_revisa_plazos_y_entrega_el_recordatorio(db: Session, actors: Actors) -> None:
    ticket = pending_confirmation_ticket(db, actors)

    process_outbox.drain(db, providers=fake_providers(), now=minutes_after(ticket, 121))

    (reminder,) = [n for n in notifications_of(db, ticket) if n.message_type == MessageType.A7]
    assert reminder.status == NotificationStatus.SIMULATED
    assert reminders_of(db, ticket) == [1]


def test_si_la_revision_de_plazos_falla_la_cola_sigue(
    db: Session, actors: Actors, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(*args: object, **kwargs: object) -> None:
        raise RuntimeError("falla simulada")

    monkeypatch.setattr(sla_service, "run_checks", broken)
    ticket = new_ticket(db, actors.requester)

    processed = process_outbox.process_batch(db, providers=fake_providers())

    assert processed > 0
    db.refresh(ticket)
    assert ticket.priority is not None
