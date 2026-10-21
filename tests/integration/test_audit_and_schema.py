"""Regla 3 / RN-08 a nivel de base y comprobaciones del esquema de la migración."""

from collections.abc import Callable

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from backend.models import TicketEvent, User
from backend.models.enums import Role
from backend.schemas.ticket import TicketCreate
from backend.services import ticket_service
from tests.helpers import VALID_TICKET

MakeUser = Callable[..., User]


@pytest.fixture
def event(db: Session, make_user: MakeUser) -> TicketEvent:
    ticket = ticket_service.create_ticket(
        db, make_user(Role.REQUESTER), TicketCreate.model_validate(VALID_TICKET)
    )
    return db.scalars(select(TicketEvent).where(TicketEvent.ticket_id == ticket.id)).one()


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE ticket_events SET event_type = 'TICKET_CLASSIFIED' WHERE id = :id",
        "DELETE FROM ticket_events WHERE id = :id",
    ],
)
def test_regla3_bitacora_no_admite_update_ni_delete(
    db: Session, event: TicketEvent, statement: str
) -> None:
    with pytest.raises(DBAPIError, match="solo de inserción"), db.begin_nested():
        db.execute(text(statement), {"id": event.id})

    db.expire_all()
    assert db.get(TicketEvent, event.id).event_type == "TICKET_CREATED"


def test_regla3_bitacora_no_admite_truncate(db: Session, event: TicketEvent) -> None:
    with pytest.raises(DBAPIError, match="solo de inserción"), db.begin_nested():
        db.execute(text("TRUNCATE ticket_events CASCADE"))


def test_check_rechaza_valores_fuera_del_enum(db: Session, make_user: MakeUser) -> None:
    user = make_user(Role.REQUESTER)
    with pytest.raises(IntegrityError, match="ck_users_role"), db.begin_nested():
        db.execute(text("UPDATE users SET role = 'SUPERADMIN' WHERE id = :id"), {"id": user.id})


def test_secuencia_ticket_code_seq_existe(db: Session) -> None:
    assert db.scalar(text("SELECT nextval('ticket_code_seq')")) >= 1
