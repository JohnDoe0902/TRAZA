"""RF-08, RN-07 y CP-07: asignación manual y automática."""

import uuid
from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.core.errors import BusinessRuleViolation, NotAuthorized
from backend.models import Assignment, User
from backend.models.enums import EventType, MessageType, Role, TicketStatus
from backend.services import assignment_service, ticket_service
from tests.helpers import (
    Actors,
    assigned_ticket,
    event_types,
    events_of,
    in_progress_ticket,
    new_ticket,
    notifications_of,
)

MakeUser = Callable[..., User]
Login = Callable[[User], TestClient]


def _assignments(db: Session, ticket_id: int) -> list[Assignment]:
    query = select(Assignment).where(Assignment.ticket_id == ticket_id).order_by(Assignment.id)
    return list(db.scalars(query))


def test_rf08_asignacion_manual_crea_fila_y_eventos(db: Session, actors: Actors) -> None:
    ticket = new_ticket(db, actors.requester)

    assignment_service.assign_ticket(db, ticket, actors.admin, actors.technician.id)

    assert ticket.status == TicketStatus.ASIGNADO
    assert ticket.assigned_technician_id == actors.technician.id
    rows = _assignments(db, ticket.id)
    assert len(rows) == 1
    assert rows[0].assigned_by == actors.admin.id
    assert event_types(db, ticket)[-2:] == [
        EventType.TICKET_ASSIGNED,
        EventType.TICKET_STATUS_CHANGED,
    ]
    assert MessageType.A2 in [n.message_type for n in notifications_of(db, ticket)]


def test_cp07_tecnico_inactivo_no_se_asigna_manualmente(
    db: Session, actors: Actors, make_user: MakeUser
) -> None:
    inactive = make_user(Role.TECHNICIAN, is_active=False)
    ticket = new_ticket(db, actors.requester)

    with pytest.raises(BusinessRuleViolation, match="inactivo"):
        assignment_service.assign_ticket(db, ticket, actors.admin, inactive.id)

    db.refresh(ticket)
    assert ticket.status == TicketStatus.PENDIENTE
    assert ticket.assigned_technician_id is None
    assert _assignments(db, ticket.id) == []


def test_cp07_tecnico_inactivo_nunca_se_elige_automaticamente(
    db: Session, actors: Actors, make_user: MakeUser
) -> None:
    # El inactivo no tiene carga (sería el preferido por carga) y tiene el menor id posible
    # entre los nuevos, pero no debe elegirse.
    inactive = make_user(Role.TECHNICIAN, is_active=False)
    ticket = new_ticket(db, actors.requester)

    chosen = assignment_service.auto_assign(db, ticket.id, uuid.uuid4())

    assert chosen is not None
    assert chosen.id != inactive.id
    assert chosen.is_active


def test_cp07_por_api_tecnico_inactivo_422(
    db: Session, actors: Actors, make_user: MakeUser, login: Login
) -> None:
    inactive = make_user(Role.TECHNICIAN, is_active=False)
    ticket = new_ticket(db, actors.requester)

    response = login(actors.admin).post(
        f"/api/tickets/{ticket.public_code}/assign", json={"technician_id": inactive.id}
    )

    assert response.status_code == 422
    assert "inactivo" in response.json()["detail"]


def test_asignar_a_un_no_tecnico_es_rechazado(db: Session, actors: Actors) -> None:
    ticket = new_ticket(db, actors.requester)
    with pytest.raises(BusinessRuleViolation):
        assignment_service.assign_ticket(db, ticket, actors.admin, actors.requester.id)


def test_solo_el_admin_asigna(db: Session, actors: Actors, login: Login) -> None:
    ticket = new_ticket(db, actors.requester)
    with pytest.raises(NotAuthorized):
        assignment_service.assign_ticket(db, ticket, actors.technician, actors.technician.id)


def test_rn07_automatica_elige_menor_carga_y_desempata_por_id(db: Session, actors: Actors) -> None:
    first, second = sorted([actors.technician, actors.other_technician], key=lambda u: u.id)
    # Empate (ambos sin carga) → el de menor id.
    t1 = new_ticket(db, actors.requester)
    assert assignment_service.auto_assign(db, t1.id, uuid.uuid4()).id == first.id
    # Ahora `first` tiene un ticket abierto → el siguiente va a `second`.
    t2 = new_ticket(db, actors.requester)
    assert assignment_service.auto_assign(db, t2.id, uuid.uuid4()).id == second.id


def test_automatica_registra_actor_sistema(db: Session, actors: Actors) -> None:
    ticket = new_ticket(db, actors.requester)
    assignment_service.auto_assign(db, ticket.id, uuid.uuid4())

    assigned = events_of(db, ticket, EventType.TICKET_ASSIGNED)[0]
    assert assigned.actor_id is None
    assert assigned.actor_type == "SYSTEM"
    assert _assignments(db, ticket.id)[0].assigned_by is None


def test_automatica_no_asigna_si_requiere_revision(db: Session, actors: Actors) -> None:
    ticket = new_ticket(db, actors.requester)
    ticket.review_required = True
    db.flush()

    assert assignment_service.auto_assign(db, ticket.id, uuid.uuid4()) is None
    assert ticket.status == TicketStatus.PENDIENTE


def test_automatica_es_idempotente(db: Session, actors: Actors) -> None:
    ticket = new_ticket(db, actors.requester)
    assignment_service.auto_assign(db, ticket.id, uuid.uuid4())
    assert assignment_service.auto_assign(db, ticket.id, uuid.uuid4()) is None
    assert len(_assignments(db, ticket.id)) == 1


def test_sin_tecnicos_activos_alerta_al_admin(db: Session, make_user: MakeUser) -> None:
    ticket = new_ticket(db, make_user(Role.REQUESTER))

    assert assignment_service.auto_assign(db, ticket.id, uuid.uuid4()) is None

    alert = events_of(db, ticket, EventType.ADMIN_ALERT)
    assert alert[0].safe_details_json == {"reason": "sin_tecnicos_activos"}
    assert ticket.status == TicketStatus.PENDIENTE


def test_reasignacion_exige_motivo_y_libera_la_anterior(db: Session, actors: Actors) -> None:
    ticket = assigned_ticket(db, actors)

    with pytest.raises(BusinessRuleViolation, match="motivo"):
        assignment_service.assign_ticket(db, ticket, actors.admin, actors.other_technician.id)

    assignment_service.assign_ticket(
        db, ticket, actors.admin, actors.other_technician.id, reason="Cambio de turno"
    )

    rows = _assignments(db, ticket.id)
    assert [r.technician_id for r in rows] == [actors.technician.id, actors.other_technician.id]
    assert rows[0].released_at is not None
    assert rows[1].released_at is None
    assert ticket.status == TicketStatus.ASIGNADO
    # ASIGNADO → ASIGNADO no cambia el estado: solo TICKET_ASSIGNED.
    assert event_types(db, ticket)[-1] == EventType.TICKET_ASSIGNED


def test_reasignar_en_proceso_vuelve_a_asignado(db: Session, actors: Actors) -> None:
    ticket = in_progress_ticket(db, actors)

    assignment_service.assign_ticket(
        db, ticket, actors.admin, actors.other_technician.id, reason="Técnico de licencia"
    )

    assert ticket.status == TicketStatus.ASIGNADO
    assert event_types(db, ticket)[-2:] == [
        EventType.TICKET_ASSIGNED,
        EventType.TICKET_STATUS_CHANGED,
    ]


def test_reasignar_al_mismo_tecnico_es_rechazado(db: Session, actors: Actors) -> None:
    ticket = assigned_ticket(db, actors)
    with pytest.raises(BusinessRuleViolation):
        assignment_service.assign_ticket(
            db, ticket, actors.admin, actors.technician.id, reason="Igual"
        )


def test_asignar_ticket_pendiente_de_confirmacion_es_transicion_invalida(
    db: Session, actors: Actors, login: Login
) -> None:
    ticket = in_progress_ticket(db, actors)
    ticket_service.propose_resolution(db, ticket, actors.technician, "Se cambió el cable de red.")
    response = login(actors.admin).post(
        f"/api/tickets/{ticket.public_code}/assign",
        json={"technician_id": actors.other_technician.id, "reason": "x"},
    )
    assert response.status_code == 409


def test_asignar_y_reasignar_por_api_con_version(db: Session, actors: Actors, login: Login) -> None:
    """Regresión: la versión se valida una vez, aunque la operación escriba varias filas."""
    ticket = new_ticket(db, actors.requester)
    client = login(actors.admin)

    first = client.post(
        f"/api/tickets/{ticket.public_code}/assign",
        json={"technician_id": actors.technician.id, "version": ticket.version},
    )
    assert first.status_code == 200, first.text

    second = client.post(
        f"/api/tickets/{ticket.public_code}/assign",
        json={
            "technician_id": actors.other_technician.id,
            "reason": "Cambio de turno",
            "version": first.json()["version"],
        },
    )
    assert second.status_code == 200, second.text
    assert second.json()["assigned_technician_id"] == actors.other_technician.id

    stale = client.post(
        f"/api/tickets/{ticket.public_code}/assign",
        json={
            "technician_id": actors.technician.id,
            "reason": "Otra vez",
            "version": first.json()["version"],
        },
    )
    assert stale.status_code == 409
