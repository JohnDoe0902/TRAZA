"""Regla 8: permisos por objeto, sin base de datos."""

import pytest

from backend.core.errors import NotAuthorized
from backend.core.permissions import (
    TicketScope,
    can_view_ticket,
    ensure_can_view_ticket,
    ensure_role,
    ticket_scope_for,
)
from backend.models import Ticket, User
from backend.models.enums import Role

REQUESTER = User(id=1, role=Role.REQUESTER)
OTHER_REQUESTER = User(id=2, role=Role.REQUESTER)
TECHNICIAN = User(id=3, role=Role.TECHNICIAN)
OTHER_TECHNICIAN = User(id=4, role=Role.TECHNICIAN)
ADMIN = User(id=5, role=Role.ADMIN)

TICKET = Ticket(requester_id=REQUESTER.id, assigned_technician_id=TECHNICIAN.id)
UNASSIGNED_TICKET = Ticket(requester_id=REQUESTER.id, assigned_technician_id=None)


@pytest.mark.parametrize(
    ("user", "ticket", "allowed"),
    [
        (REQUESTER, TICKET, True),
        (OTHER_REQUESTER, TICKET, False),
        (TECHNICIAN, TICKET, True),
        (OTHER_TECHNICIAN, TICKET, False),
        (TECHNICIAN, UNASSIGNED_TICKET, False),
        (ADMIN, TICKET, True),
        (ADMIN, UNASSIGNED_TICKET, True),
    ],
)
def test_regla8_quien_puede_ver_un_ticket(user: User, ticket: Ticket, allowed: bool) -> None:
    assert can_view_ticket(user, ticket) is allowed


def test_regla8_acceso_indebido_lanza_not_authorized() -> None:
    with pytest.raises(NotAuthorized):
        ensure_can_view_ticket(OTHER_REQUESTER, TICKET)


def test_rf04_alcance_del_listado_por_rol() -> None:
    assert ticket_scope_for(REQUESTER) == TicketScope(requester_id=REQUESTER.id)
    assert ticket_scope_for(TECHNICIAN) == TicketScope(technician_id=TECHNICIAN.id)
    assert ticket_scope_for(ADMIN) == TicketScope()


def test_ensure_role_rechaza_otros_roles() -> None:
    ensure_role(REQUESTER, Role.REQUESTER)
    with pytest.raises(NotAuthorized):
        ensure_role(TECHNICIAN, Role.REQUESTER)
