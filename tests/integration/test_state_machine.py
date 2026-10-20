"""CP-08, CP-09 y regla 2: transiciones aplicadas sobre la base, por servicio y por API."""

import uuid
from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.core.errors import ConcurrencyConflict, InvalidTransition, NotAuthorized
from backend.models import Ticket, User
from backend.models.enums import ActorType, EventType, MessageType, TicketStatus
from backend.services import ticket_service
from tests.helpers import (
    RESOLUTION_TEXT,
    Actors,
    assigned_ticket,
    count_rows,
    event_types,
    events_of,
    in_progress_ticket,
    new_ticket,
    notifications_of,
    pending_confirmation_ticket,
)

Login = Callable[[User], TestClient]


def test_cp08_pendiente_a_cerrado_409_estado_intacto(
    db: Session, actors: Actors, login: Login
) -> None:
    ticket = new_ticket(db, actors.requester)
    before = count_rows(db)

    with pytest.raises(InvalidTransition):
        ticket_service.transition(
            db, ticket, TicketStatus.CERRADO, actors.requester, correlation_id=uuid.uuid4()
        )
    db.rollback()

    db.refresh(ticket)
    assert ticket.status == TicketStatus.PENDIENTE
    assert ticket.closed_at is None
    assert count_rows(db) == before  # sin eventos nuevos


def test_cp08_por_api_transicion_invalida_responde_409(
    db: Session, actors: Actors, login: Login
) -> None:
    ticket = assigned_ticket(db, actors)
    client = login(actors.technician)

    response = client.post(
        f"/api/tickets/{ticket.public_code}/resolve", json={"resolution_text": RESOLUTION_TEXT}
    )  # ASIGNADO → PENDIENTE_CONFIRMACION no existe: primero hay que iniciar

    assert response.status_code == 409
    db.refresh(ticket)
    assert ticket.status == TicketStatus.ASIGNADO
    assert ticket.resolution_text is None


def test_cp09_cambio_valido_deja_evento_con_actor_y_hora(db: Session, actors: Actors) -> None:
    ticket = assigned_ticket(db, actors)

    ticket_service.start_work(db, ticket, actors.technician)

    event = events_of(db, ticket, EventType.TICKET_STATUS_CHANGED)[-1]
    assert event.actor_type == ActorType.USER
    assert event.actor_id == actors.technician.id
    assert event.old_state == TicketStatus.ASIGNADO
    assert event.new_state == TicketStatus.EN_PROCESO
    assert event.created_at is not None
    assert isinstance(event.correlation_id, uuid.UUID)


def test_iniciar_atencion_registra_primera_atencion(db: Session, actors: Actors) -> None:
    ticket = in_progress_ticket(db, actors)
    assert ticket.status == TicketStatus.EN_PROCESO
    assert ticket.first_response_at is not None


def test_proponer_solucion_pasa_a_pendiente_confirmacion(db: Session, actors: Actors) -> None:
    ticket = pending_confirmation_ticket(db, actors)

    assert ticket.status == TicketStatus.PENDIENTE_CONFIRMACION
    assert ticket.resolution_text == RESOLUTION_TEXT
    assert ticket.closed_at is None  # regla 1: proponer no cierra
    assert event_types(db, ticket)[-3:] == [
        EventType.RESOLUTION_PROPOSED,
        EventType.TICKET_STATUS_CHANGED,
        EventType.CONFIRMATION_REQUESTED,
    ]
    question = [n for n in notifications_of(db, ticket) if n.message_type == MessageType.A3]
    assert len(question) == 1
    requested = events_of(db, ticket, EventType.CONFIRMATION_REQUESTED)[0]
    assert requested.safe_details_json["notification_id"] == question[0].id


def test_regla1_el_tecnico_no_puede_cerrar(db: Session, actors: Actors) -> None:
    ticket = pending_confirmation_ticket(db, actors)
    with pytest.raises(NotAuthorized):
        ticket_service.transition(
            db, ticket, TicketStatus.CERRADO, actors.technician, correlation_id=uuid.uuid4()
        )
    db.rollback()
    db.refresh(ticket)
    assert ticket.status == TicketStatus.PENDIENTE_CONFIRMACION


def test_tecnico_no_asignado_no_puede_iniciar_403(
    db: Session, actors: Actors, login: Login
) -> None:
    ticket = assigned_ticket(db, actors)
    response = login(actors.other_technician).post(
        f"/api/tickets/{ticket.public_code}/start", json={}
    )
    assert response.status_code == 403


def test_solucion_sin_texto_422_y_sin_cambios(db: Session, actors: Actors, login: Login) -> None:
    ticket = in_progress_ticket(db, actors)
    client = login(actors.technician)

    response = client.post(
        f"/api/tickets/{ticket.public_code}/resolve", json={"resolution_text": "   "}
    )

    assert response.status_code == 422
    db.refresh(ticket)
    assert ticket.status == TicketStatus.EN_PROCESO


def test_version_desactualizada_responde_409(db: Session, actors: Actors, login: Login) -> None:
    ticket = assigned_ticket(db, actors)
    stale_version = ticket.version - 1

    response = login(actors.technician).post(
        f"/api/tickets/{ticket.public_code}/start", json={"version": stale_version}
    )

    assert response.status_code == 409
    db.refresh(ticket)
    assert ticket.status == TicketStatus.ASIGNADO


def test_bloqueo_optimista_detecta_escritura_concurrente(db: Session, actors: Actors) -> None:
    """Si otra transacción cambió el ticket después de leerlo, el UPDATE no sobrescribe."""
    ticket = assigned_ticket(db, actors)
    # Simula que otra sesión ya incrementó la versión en la base.
    db.execute(
        Ticket.__table__.update()
        .where(Ticket.__table__.c.id == ticket.id)
        .values(version=ticket.version + 1)
    )

    with pytest.raises(ConcurrencyConflict):
        ticket_service.start_work(db, ticket, actors.technician)

    db.refresh(ticket)
    assert ticket.status == TicketStatus.ASIGNADO


def test_api_start_y_resolve_funcionan(db: Session, actors: Actors, login: Login) -> None:
    ticket = assigned_ticket(db, actors)
    client = login(actors.technician)

    started = client.post(
        f"/api/tickets/{ticket.public_code}/start", json={"version": ticket.version}
    )
    assert started.status_code == 200, started.text
    assert started.json()["status"] == "EN_PROCESO"

    resolved = client.post(
        f"/api/tickets/{ticket.public_code}/resolve",
        json={"resolution_text": RESOLUTION_TEXT, "version": started.json()["version"]},
    )
    assert resolved.status_code == 200, resolved.text
    assert resolved.json()["status"] == "PENDIENTE_CONFIRMACION"
