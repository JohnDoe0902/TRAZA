"""Rutas JSON de tickets (sección 14)."""

from fastapi import APIRouter, status

from backend.api.deps import CurrentUser, DbSession
from backend.models.enums import Priority, TicketStatus
from backend.schemas.ticket import TicketCreate, TicketOut
from backend.services import ticket_service

router = APIRouter(prefix="/api/tickets", tags=["tickets"])


@router.post("", response_model=TicketOut, status_code=status.HTTP_201_CREATED)
def create_ticket(payload: TicketCreate, user: CurrentUser, db: DbSession) -> TicketOut:
    ticket = ticket_service.create_ticket(db, user, payload)
    return TicketOut.model_validate(ticket)


@router.get("", response_model=list[TicketOut])
def list_tickets(
    user: CurrentUser,
    db: DbSession,
    status: TicketStatus | None = None,
    priority: Priority | None = None,
) -> list[TicketOut]:
    tickets = ticket_service.list_tickets_for_user(db, user, status=status, priority=priority)
    return [TicketOut.model_validate(ticket) for ticket in tickets]


@router.get("/{code}", response_model=TicketOut)
def get_ticket(code: str, user: CurrentUser, db: DbSession) -> TicketOut:
    return TicketOut.model_validate(ticket_service.get_ticket_for_user(db, user, code))
