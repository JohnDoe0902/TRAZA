"""Prueba de aceptación del ciclo completo con el simulador (sección 17).

alta → clasificación → asignación → atención → solución → No → retoma → solución → Sí → cerrado

Se usa la API HTTP como lo haría cada persona y el worker para lo automático. Nunca se llama a
OpenAI ni a WhatsApp: clasificador mock y WhatsApp simulado.
"""

from collections.abc import Callable

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.models import Ticket, User
from backend.models.enums import MessageType, NotificationStatus, Priority, TicketStatus
from backend.repositories import ticket_repository
from backend.workers.process_outbox import drain
from tests.helpers import VALID_TICKET, Actors, fake_providers, notifications_of

Login = Callable[[User], TestClient]


def _run_worker(db: Session) -> None:
    drain(db, providers=fake_providers())


def _latest_question_id(db: Session, ticket: Ticket) -> int:
    questions = [n for n in notifications_of(db, ticket) if n.message_type == MessageType.A3]
    assert questions[-1].status == NotificationStatus.SIMULATED
    return questions[-1].id


def test_ciclo_completo_con_simulador(db: Session, actors: Actors, login: Login) -> None:
    requester = login(actors.requester)
    admin = login(actors.admin)

    # 1. Alta del solicitante.
    created = requester.post("/api/tickets", json=VALID_TICKET)
    assert created.status_code == 201
    code = created.json()["public_code"]
    ticket = ticket_repository.get_by_code(db, code)
    assert ticket is not None

    # 2-3. El worker clasifica (prioridad por matriz) y asigna al técnico con menos carga.
    _run_worker(db)
    db.refresh(ticket)
    assert ticket.priority == Priority.CRITICA
    assert ticket.status == TicketStatus.ASIGNADO
    # RN-07: ambos técnicos sin carga → el de menor id (el primero creado).
    assert ticket.assigned_technician_id == actors.technician.id
    technician_user = actors.technician
    technician = login(technician_user)

    # 4-5. El técnico atiende y propone una solución.
    assert technician.post(f"/api/tickets/{code}/start", json={}).status_code == 200
    resolved = technician.post(
        f"/api/tickets/{code}/resolve",
        json={"resolution_text": "Se reinició el switch del laboratorio 3."},
    )
    assert resolved.json()["status"] == "PENDIENTE_CONFIRMACION"
    _run_worker(db)

    # 6. El solicitante responde "No, continúa" desde el simulador.
    response = requester.post(
        "/simulador/responder",
        data={"notification_id": _latest_question_id(db, ticket), "answer": "NO"},
    )
    assert response.status_code == 200
    db.refresh(ticket)
    assert ticket.status == TicketStatus.REABIERTO
    _run_worker(db)

    # 7-8. El técnico retoma y propone otra solución.
    assert technician.post(f"/api/tickets/{code}/start", json={}).status_code == 200
    technician.post(
        f"/api/tickets/{code}/resolve",
        json={"resolution_text": "Se reemplazó el cable dañado del rack del laboratorio."},
    )
    _run_worker(db)

    # 9. "Sí, se solucionó" desde el simulador → CERRADO.
    requester.post(
        "/simulador/responder",
        data={"notification_id": _latest_question_id(db, ticket), "answer": "YES"},
    )
    _run_worker(db)
    db.refresh(ticket)
    assert ticket.status == TicketStatus.CERRADO
    assert ticket.reopen_count == 1
    assert ticket.closed_at is not None

    # La bitácora reconstruye todo el ciclo, en orden.
    events = admin.get(f"/api/tickets/{code}/events").json()
    state_path = [
        (e["old_state"], e["new_state"])
        for e in events
        if e["event_type"] in ("TICKET_STATUS_CHANGED", "TICKET_REOPENED")
    ]
    assert state_path == [
        ("PENDIENTE", "ASIGNADO"),
        ("ASIGNADO", "EN_PROCESO"),
        ("EN_PROCESO", "PENDIENTE_CONFIRMACION"),
        ("PENDIENTE_CONFIRMACION", "REABIERTO"),
        ("REABIERTO", "EN_PROCESO"),
        ("EN_PROCESO", "PENDIENTE_CONFIRMACION"),
        ("PENDIENTE_CONFIRMACION", "CERRADO"),
    ]
    types = [e["event_type"] for e in events]
    for expected in (
        "TICKET_CREATED",
        "TICKET_CLASSIFIED",
        "TICKET_ASSIGNED",
        "RESOLUTION_PROPOSED",
        "CONFIRMATION_REQUESTED",
        "CONFIRMATION_REJECTED",
        "TICKET_REOPENED",
        "CONFIRMATION_ACCEPTED",
        "NOTIFICATION_SENT",
    ):
        assert expected in types, expected
    assert types.count("CONFIRMATION_ACCEPTED") == 1

    # Mensajes: el solicitante recibió A1-A5 y el técnico el aviso A8; todos simulados.
    notifications = notifications_of(db, ticket)
    to_requester = [
        n.message_type for n in notifications if n.recipient_user_id == actors.requester.id
    ]
    assert to_requester == [
        MessageType.A1,
        MessageType.A2,
        MessageType.A3,
        MessageType.A5,
        MessageType.A3,
        MessageType.A4,
    ]
    to_technician = [
        n.message_type for n in notifications if n.recipient_user_id == technician_user.id
    ]
    assert to_technician == [MessageType.A8]
    assert {n.status for n in notifications} == {NotificationStatus.SIMULATED}
