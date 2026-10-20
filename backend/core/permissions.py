"""Permisos por rol y por objeto (sección 2 de la especificación)."""

from dataclasses import dataclass

from backend.core.errors import NotAuthorized
from backend.models import Ticket, User
from backend.models.enums import Role


@dataclass(frozen=True)
class TicketScope:
    """Filtro de visibilidad de tickets. `None` en ambos campos = ve todos."""

    requester_id: int | None = None
    technician_id: int | None = None


def ticket_scope_for(user: User) -> TicketScope:
    if user.role == Role.ADMIN:
        return TicketScope()
    if user.role == Role.TECHNICIAN:
        return TicketScope(technician_id=user.id)
    return TicketScope(requester_id=user.id)


def can_view_ticket(user: User, ticket: Ticket) -> bool:
    if user.role == Role.ADMIN:
        return True
    if user.role == Role.TECHNICIAN:
        return ticket.assigned_technician_id == user.id
    return ticket.requester_id == user.id


def ensure_can_view_ticket(user: User, ticket: Ticket) -> None:
    if not can_view_ticket(user, ticket):
        raise NotAuthorized("No tienes permiso para ver este ticket.")


def ensure_role(user: User, *roles: Role) -> None:
    if user.role not in roles:
        raise NotAuthorized()
