"""Rutas JSON de tickets (sección 14)."""

from fastapi import APIRouter, status

from backend.api.deps import CurrentUser, DbSession
from backend.models.enums import ConfirmationSource, EventType, Priority, TicketStatus
from backend.repositories import event_repository
from backend.schemas.ticket import (
    AssignIn,
    ClassificationIn,
    ConfirmIn,
    ConfirmOut,
    EventOut,
    ResolveIn,
    TicketCreate,
    TicketOut,
    VersionIn,
)
from backend.services import (
    assignment_service,
    classification_service,
    confirmation_service,
    ticket_service,
)

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


@router.get("/{code}/events", response_model=list[EventOut])
def list_events(
    code: str, user: CurrentUser, db: DbSession, type: EventType | None = None
) -> list[EventOut]:
    """Bitácora del ticket en orden cronológico, filtrable por tipo (RF-17)."""
    ticket = ticket_service.get_ticket_for_user(db, user, code)
    events = event_repository.list_for_ticket(db, ticket.id, event_type=type)
    return [EventOut.model_validate(event) for event in events]


@router.post("/{code}/classification", response_model=TicketOut)
def validate_classification(
    code: str, payload: ClassificationIn, user: CurrentUser, db: DbSession
) -> TicketOut:
    """El admin confirma o corrige la clasificación (RN-04)."""
    ticket = ticket_service.get_ticket_for_user(db, user, code)
    classification_service.validate_classification(
        db,
        ticket,
        user,
        category=payload.category,
        impact=payload.impact,
        urgency=payload.urgency,
        expected_version=payload.version,
    )
    return TicketOut.model_validate(ticket)


@router.post("/{code}/assign", response_model=TicketOut)
def assign_ticket(code: str, payload: AssignIn, user: CurrentUser, db: DbSession) -> TicketOut:
    ticket = ticket_service.get_ticket_for_user(db, user, code)
    assignment_service.assign_ticket(
        db,
        ticket,
        user,
        payload.technician_id,
        reason=payload.reason,
        expected_version=payload.version,
    )
    return TicketOut.model_validate(ticket)


@router.post("/{code}/start", response_model=TicketOut)
def start_ticket(code: str, payload: VersionIn, user: CurrentUser, db: DbSession) -> TicketOut:
    ticket = ticket_service.get_ticket_for_user(db, user, code)
    ticket_service.start_work(db, ticket, user, expected_version=payload.version)
    return TicketOut.model_validate(ticket)


@router.post("/{code}/resolve", response_model=TicketOut)
def resolve_ticket(code: str, payload: ResolveIn, user: CurrentUser, db: DbSession) -> TicketOut:
    ticket = ticket_service.get_ticket_for_user(db, user, code)
    ticket_service.propose_resolution(
        db, ticket, user, payload.resolution_text, expected_version=payload.version
    )
    return TicketOut.model_validate(ticket)


@router.post("/{code}/confirm", response_model=ConfirmOut)
def confirm_ticket(code: str, payload: ConfirmIn, user: CurrentUser, db: DbSession) -> ConfirmOut:
    """Respuesta Sí/No del solicitante por la web. Una respuesta repetida → result IGNORED."""
    ticket = ticket_service.get_ticket_for_user(db, user, code)
    outcome = confirmation_service.register_answer(
        db, ticket=ticket, responder=user, answer=payload.answer, source=ConfirmationSource.WEB
    )
    return ConfirmOut(result=outcome.value, status=ticket.status)
