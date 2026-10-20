"""Worker de outbox (sección 13.5): CP-18, reintentos, regla 5 y regla 9."""

from datetime import timedelta

from sqlalchemy.orm import Session

from backend.core.clock import utcnow
from backend.models.enums import (
    EventType,
    JobStatus,
    JobType,
    MessageType,
    NotificationStatus,
    Priority,
    TicketStatus,
)
from backend.workers.process_outbox import drain, process_batch
from tests.helpers import (
    Actors,
    FailingNotifier,
    events_of,
    fake_providers,
    jobs_of,
    new_ticket,
    notifications_of,
)


def test_regla5_el_alta_no_llama_a_proveedores_externos(db: Session, actors: Actors) -> None:
    notifier = FailingNotifier()
    ticket = new_ticket(db, actors.requester)
    # Nada se envió ni clasificó al registrar: todo quedó en la cola.
    assert notifier.calls == 0
    assert ticket.priority is None
    assert {job.status for job in jobs_of(db, ticket)} == {JobStatus.PENDING}
    assert {n.status for n in notifications_of(db, ticket)} == {NotificationStatus.PENDING}


def test_worker_clasifica_asigna_y_notifica(db: Session, actors: Actors) -> None:
    ticket = new_ticket(db, actors.requester)

    drain(db, providers=fake_providers())

    db.refresh(ticket)
    assert ticket.priority == Priority.CRITICA
    assert ticket.status == TicketStatus.ASIGNADO
    assert ticket.assigned_technician_id in (actors.technician.id, actors.other_technician.id)
    jobs = jobs_of(db, ticket)
    assert {job.job_type for job in jobs} == {
        JobType.CLASSIFY_TICKET,
        JobType.SEND_NOTIFICATION,
        JobType.AUTO_ASSIGN,
    }
    assert all(job.status == JobStatus.DONE for job in jobs)
    sent = {n.message_type: n for n in notifications_of(db, ticket)}
    assert set(sent) == {MessageType.A1, MessageType.A2}


def test_regla9_el_simulador_deja_estado_simulated_con_id(db: Session, actors: Actors) -> None:
    ticket = new_ticket(db, actors.requester)
    drain(db, providers=fake_providers())

    a1 = next(n for n in notifications_of(db, ticket) if n.message_type == MessageType.A1)
    assert a1.status == NotificationStatus.SIMULATED  # nunca DELIVERED sin evidencia
    assert a1.provider_message_id.startswith("sim-")
    assert a1.sent_at is not None
    assert a1.attempt_count == 1
    sent_event = events_of(db, ticket, EventType.NOTIFICATION_SENT)[0]
    assert sent_event.actor_type == "INTEGRATION"


def test_cp18_trabajo_running_abandonado_se_retoma(db: Session, actors: Actors) -> None:
    ticket = new_ticket(db, actors.requester)
    now = utcnow()
    classify_job = next(j for j in jobs_of(db, ticket) if j.job_type == JobType.CLASSIFY_TICKET)
    # Simula un worker que tomó el trabajo hace 11 minutos y murió.
    classify_job.status = JobStatus.RUNNING
    classify_job.started_at = now - timedelta(minutes=11)
    db.commit()

    drain(db, providers=fake_providers(), now=now)

    db.refresh(classify_job)
    db.refresh(ticket)
    assert classify_job.status == JobStatus.DONE
    assert ticket.priority is not None  # el ticket no se perdió y se clasificó una sola vez
    assert len(events_of(db, ticket, EventType.TICKET_CLASSIFIED)) == 1


def test_trabajo_running_reciente_no_se_toca(db: Session, actors: Actors) -> None:
    ticket = new_ticket(db, actors.requester)
    now = utcnow()
    job = next(j for j in jobs_of(db, ticket) if j.job_type == JobType.CLASSIFY_TICKET)
    job.status = JobStatus.RUNNING
    job.started_at = now - timedelta(minutes=5)
    db.commit()

    process_batch(db, providers=fake_providers(), now=now)

    db.refresh(job)
    assert job.status == JobStatus.RUNNING


def test_reintentos_con_espera_y_falla_definitiva(db: Session, actors: Actors) -> None:
    ticket = new_ticket(db, actors.requester)
    notifier = FailingNotifier()
    providers = fake_providers(notifier=notifier)
    start = utcnow()
    send_job = next(j for j in jobs_of(db, ticket) if j.job_type == JobType.SEND_NOTIFICATION)

    # Intento 1: falla y se reprograma en 1 minuto.
    process_batch(db, providers=providers, now=start)
    db.refresh(send_job)
    assert send_job.status == JobStatus.PENDING
    assert send_job.attempts == 1
    assert send_job.next_run_at == start + timedelta(minutes=1)
    assert "ConnectionError" in send_job.last_error
    a1 = next(n for n in notifications_of(db, ticket) if n.message_type == MessageType.A1)
    assert a1.status == NotificationStatus.RETRYING

    # Antes de la espera no se reintenta.
    calls = notifier.calls
    process_batch(db, providers=providers, now=start + timedelta(seconds=30))
    assert notifier.calls == calls

    # Intentos 2 a 5 con espera 1, 2, 4, 8 minutos; el quinto la marca FAILED.
    when = start
    for wait in (1, 2, 4, 8):
        when += timedelta(minutes=wait)
        process_batch(db, providers=providers, now=when)
    db.refresh(send_job)
    db.refresh(a1)
    assert send_job.attempts == 5
    assert send_job.status == JobStatus.FAILED
    assert a1.status == NotificationStatus.FAILED
    a1_failures = [
        e
        for e in events_of(db, ticket, EventType.NOTIFICATION_FAILED)
        if e.safe_details_json["notification_id"] == a1.id
    ]
    assert [e.safe_details_json["attempt"] for e in a1_failures] == [1, 2, 3, 4, 5]
    alert = events_of(db, ticket, EventType.ADMIN_ALERT)
    assert alert[0].safe_details_json["reason"] == "job_failed"
    db.refresh(ticket)
    assert ticket.status != TicketStatus.CERRADO  # la falla de mensajería no toca el ticket


def test_falla_temporal_se_recupera_al_reintentar(db: Session, actors: Actors) -> None:
    ticket = new_ticket(db, actors.requester)
    providers = fake_providers(notifier=FailingNotifier(failures=1))
    start = utcnow()

    process_batch(db, providers=providers, now=start)
    drain(db, providers=providers, now=start + timedelta(minutes=2))

    a1 = next(n for n in notifications_of(db, ticket) if n.message_type == MessageType.A1)
    assert a1.status == NotificationStatus.SIMULATED
    assert a1.attempt_count == 2


def test_reprocesar_un_envio_no_duplica_el_mensaje(db: Session, actors: Actors) -> None:
    ticket = new_ticket(db, actors.requester)
    drain(db, providers=fake_providers())
    send_job = next(j for j in jobs_of(db, ticket) if j.job_type == JobType.SEND_NOTIFICATION)

    # Se fuerza a repetir el trabajo ya hecho (como tras una recuperación).
    send_job.status = JobStatus.PENDING
    db.commit()
    drain(db, providers=fake_providers())

    a1 = next(n for n in notifications_of(db, ticket) if n.message_type == MessageType.A1)
    assert a1.attempt_count == 1
    sent = [
        e
        for e in events_of(db, ticket, EventType.NOTIFICATION_SENT)
        if e.safe_details_json["notification_id"] == a1.id
    ]
    assert len(sent) == 1
