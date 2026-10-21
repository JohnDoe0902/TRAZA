"""Seed de la sección 19 y endpoint /health."""

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.models import Ticket, TicketEvent, User
from backend.models.enums import Role, TicketStatus
from backend.scripts.seed import SEED_TICKETS, SEED_USERS, seed
from backend.services import auth_service


def test_seed_crea_usuarios_y_tickets_de_la_seccion_19(db: Session) -> None:
    assert seed(db, "clave-de-seed-para-prueba") is True

    users = db.scalars(select(User)).all()
    roles = [user.role for user in users]
    assert roles.count(Role.ADMIN) == 1
    assert roles.count(Role.REQUESTER) == 3
    technicians = [user for user in users if user.role == Role.TECHNICIAN]
    assert sorted(t.is_active for t in technicians) == [False, True, True]
    requesters = [user for user in users if user.role == Role.REQUESTER]
    assert sorted(r.whatsapp_opt_in for r in requesters) == [False, True, True]
    assert all(user.email.endswith("@traza.test") for user in users)

    tickets = db.scalars(select(Ticket).order_by(Ticket.id)).all()
    assert len(tickets) == len(SEED_TICKETS) == 5
    assert all(ticket.status == TicketStatus.PENDIENTE for ticket in tickets)
    assert db.scalar(select(func.count(TicketEvent.id))) == 5

    # Los usuarios activos entran con la contraseña del seed.
    admin = auth_service.authenticate(db, "admin@traza.test", "clave-de-seed-para-prueba")
    assert admin.role == Role.ADMIN


def test_seed_es_idempotente(db: Session) -> None:
    assert seed(db, "clave-de-seed-para-prueba") is True
    assert seed(db, "clave-de-seed-para-prueba") is False
    assert db.scalar(select(func.count(User.id))) == len(SEED_USERS)


def test_health_informa_base_disponible(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}
