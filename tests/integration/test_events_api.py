"""RF-17: bitácora consultable en orden cronológico y filtrable por tipo."""

from collections.abc import Callable

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.models import User
from backend.models.enums import Role
from tests.helpers import Actors, pending_confirmation_ticket

MakeUser = Callable[..., User]
Login = Callable[[User], TestClient]


def test_rf17_eventos_en_orden_cronologico(db: Session, actors: Actors, login: Login) -> None:
    ticket = pending_confirmation_ticket(db, actors)

    response = login(actors.requester).get(f"/api/tickets/{ticket.public_code}/events")

    assert response.status_code == 200
    events = response.json()
    assert [e["event_type"] for e in events] == [
        "TICKET_CREATED",
        "TICKET_ASSIGNED",
        "TICKET_STATUS_CHANGED",
        "TICKET_STATUS_CHANGED",
        "RESOLUTION_PROPOSED",
        "TICKET_STATUS_CHANGED",
        "CONFIRMATION_REQUESTED",
    ]
    timestamps = [e["created_at"] for e in events]
    assert timestamps == sorted(timestamps)
    assert all(e["correlation_id"] for e in events)


def test_rf17_filtro_por_tipo(db: Session, actors: Actors, login: Login) -> None:
    ticket = pending_confirmation_ticket(db, actors)

    response = login(actors.admin).get(
        f"/api/tickets/{ticket.public_code}/events", params={"type": "TICKET_STATUS_CHANGED"}
    )

    states = [(e["old_state"], e["new_state"]) for e in response.json()]
    assert states == [
        ("PENDIENTE", "ASIGNADO"),
        ("ASIGNADO", "EN_PROCESO"),
        ("EN_PROCESO", "PENDIENTE_CONFIRMACION"),
    ]


def test_rf17_bitacora_ajena_403(
    db: Session, actors: Actors, make_user: MakeUser, login: Login
) -> None:
    ticket = pending_confirmation_ticket(db, actors)
    for intruder in (make_user(Role.REQUESTER), actors.other_technician):
        response = login(intruder).get(f"/api/tickets/{ticket.public_code}/events")
        assert response.status_code == 403
