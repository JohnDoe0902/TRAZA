"""Páginas web (Jinja2 + Bootstrap).

/login, /tickets, /tickets/nuevo, /tickets/{code} (detalle, bitácora y acciones), /simulador.
"""

from typing import Annotated

from fastapi import APIRouter, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from pydantic import ValidationError

from backend.api.deps import CurrentUser, DbSession, OptionalUser
from backend.core.errors import (
    BusinessRuleViolation,
    ConcurrencyConflict,
    InvalidState,
    InvalidTransition,
    NotAuthenticated,
)
from backend.core.permissions import ensure_role
from backend.core.security import SESSION_USER_KEY
from backend.core.templating import templates
from backend.models.enums import (
    Category,
    ConfirmationAnswer,
    ConfirmationSource,
    Impact,
    Priority,
    Role,
    TicketStatus,
    Urgency,
)
from backend.repositories import classification_repository, event_repository, user_repository
from backend.schemas.errors import field_errors_es
from backend.schemas.ticket import ResolveIn, TicketCreate
from backend.services import (
    assignment_service,
    auth_service,
    classification_service,
    confirmation_service,
    simulator_service,
    ticket_service,
)
from backend.services.confirmation_service import AnswerOutcome

router = APIRouter(include_in_schema=False)

# Errores de una acción que se muestran como aviso en la misma página (no como página de error).
RECOVERABLE_ERRORS = (BusinessRuleViolation, ConcurrencyConflict, InvalidState, InvalidTransition)

OUTCOME_MESSAGES = {
    AnswerOutcome.CLOSED: ("success", "Gracias por confirmar. El ticket quedó cerrado."),
    AnswerOutcome.REOPENED: ("warning", "El ticket fue reabierto y se avisó al técnico."),
    AnswerOutcome.IGNORED: ("secondary", "La respuesta ya se había registrado; no hubo cambios."),
}


def _redirect(url: str) -> RedirectResponse:
    return RedirectResponse(url, status_code=status.HTTP_303_SEE_OTHER)


def _flash(request: Request, kind: str, text: str) -> None:
    request.session["flash"] = {"kind": kind, "text": text}


def _pop_flash(request: Request) -> dict[str, str] | None:
    return request.session.pop("flash", None)


def _parse_enum[E: (TicketStatus, Priority)](enum_cls: type[E], value: str | None) -> E | None:
    return enum_cls(value) if value in enum_cls.__members__ else None


# --- Sesión --------------------------------------------------------------------------------


@router.get("/")
def home() -> RedirectResponse:
    return _redirect("/tickets")


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request, user: OptionalUser) -> Response:
    if user is not None:
        return _redirect("/tickets")
    return templates.TemplateResponse(request, "login.html", {"email": "", "error": None})


@router.post("/login", response_class=HTMLResponse)
def login_submit(
    request: Request,
    db: DbSession,
    email: Annotated[str, Form()] = "",
    password: Annotated[str, Form()] = "",
) -> Response:
    try:
        user = auth_service.authenticate(db, email.strip(), password)
    except NotAuthenticated as exc:
        return templates.TemplateResponse(
            request,
            "login.html",
            {"email": email, "error": exc.message},
            status_code=status.HTTP_401_UNAUTHORIZED,
        )
    request.session.clear()
    request.session[SESSION_USER_KEY] = user.id
    return _redirect("/tickets")


@router.post("/logout")
def logout(request: Request) -> RedirectResponse:
    request.session.clear()
    return _redirect("/login")


# --- Tickets -------------------------------------------------------------------------------


@router.get("/tickets", response_class=HTMLResponse)
def tickets_page(
    request: Request,
    user: CurrentUser,
    db: DbSession,
    estado: str | None = None,
    prioridad: str | None = None,
    revision: str | None = None,
) -> Response:
    status_filter = _parse_enum(TicketStatus, estado)
    priority_filter = _parse_enum(Priority, prioridad)
    review_filter = True if revision == "1" else None
    tickets = ticket_service.list_tickets_for_user(
        db, user, status=status_filter, priority=priority_filter, review_required=review_filter
    )
    return templates.TemplateResponse(
        request,
        "tickets/list.html",
        {
            "user": user,
            "tickets": tickets,
            "status_filter": status_filter,
            "priority_filter": priority_filter,
            "review_filter": review_filter,
        },
    )


@router.get("/tickets/nuevo", response_class=HTMLResponse)
def new_ticket_page(request: Request, user: CurrentUser) -> Response:
    ensure_role(user, Role.REQUESTER)
    return templates.TemplateResponse(
        request, "tickets/new.html", {"user": user, "form": {}, "errors": {}}
    )


@router.post("/tickets/nuevo", response_class=HTMLResponse)
def new_ticket_submit(
    request: Request,
    user: CurrentUser,
    db: DbSession,
    title: Annotated[str, Form()] = "",
    description: Annotated[str, Form()] = "",
    location: Annotated[str, Form()] = "",
) -> Response:
    ensure_role(user, Role.REQUESTER)
    form = {"title": title, "description": description, "location": location}
    try:
        data = TicketCreate.model_validate(form)
    except ValidationError as exc:
        return templates.TemplateResponse(
            request,
            "tickets/new.html",
            {"user": user, "form": form, "errors": field_errors_es(exc)},
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        )
    ticket = ticket_service.create_ticket(db, user, data)
    _flash(request, "success", f"Registramos tu solicitud {ticket.public_code}.")
    return _redirect(f"/tickets/{ticket.public_code}")


@router.get("/tickets/{code}", response_class=HTMLResponse)
def ticket_detail_page(request: Request, code: str, user: CurrentUser, db: DbSession) -> Response:
    ticket = ticket_service.get_ticket_for_user(db, user, code)
    events = event_repository.list_for_ticket(db, ticket.id)
    actions = ticket_service.available_actions(ticket, user)
    user_ids = {e.actor_id for e in events if e.actor_id}
    user_ids |= {e.safe_details_json.get("technician_id") for e in events} - {None}
    return templates.TemplateResponse(
        request,
        "tickets/detail.html",
        {
            "user": user,
            "ticket": ticket,
            "events": events,
            "users": user_repository.get_many(db, user_ids),
            "actions": actions,
            "technicians": (
                user_repository.list_active_technicians(db) if actions.can_assign else []
            ),
            "classification": (
                classification_repository.latest_for_ticket(db, ticket.id)
                if user.role == Role.ADMIN
                else None
            ),
            "flash": _pop_flash(request),
        },
    )


@router.post("/tickets/{code}/clasificacion")
def classification_submit(
    request: Request,
    code: str,
    user: CurrentUser,
    db: DbSession,
    category: Annotated[Category, Form()],
    impact: Annotated[Impact, Form()],
    urgency: Annotated[Urgency, Form()],
    version: Annotated[int | None, Form()] = None,
) -> RedirectResponse:
    ticket = ticket_service.get_ticket_for_user(db, user, code)
    try:
        classification_service.validate_classification(
            db,
            ticket,
            user,
            category=category,
            impact=impact,
            urgency=urgency,
            expected_version=version,
        )
        _flash(request, "success", "Clasificación validada. La prioridad se recalculó.")
    except RECOVERABLE_ERRORS as exc:
        _flash(request, "danger", exc.message)
    return _redirect(f"/tickets/{code}")


@router.post("/tickets/{code}/asignar")
def assign_submit(
    request: Request,
    code: str,
    user: CurrentUser,
    db: DbSession,
    technician_id: Annotated[int, Form()],
    reason: Annotated[str, Form()] = "",
    version: Annotated[int | None, Form()] = None,
) -> RedirectResponse:
    ticket = ticket_service.get_ticket_for_user(db, user, code)
    try:
        assignment_service.assign_ticket(
            db, ticket, user, technician_id, reason=reason, expected_version=version
        )
        _flash(request, "success", "Técnico asignado.")
    except RECOVERABLE_ERRORS as exc:
        _flash(request, "danger", exc.message)
    return _redirect(f"/tickets/{code}")


@router.post("/tickets/{code}/iniciar")
def start_submit(
    request: Request,
    code: str,
    user: CurrentUser,
    db: DbSession,
    version: Annotated[int | None, Form()] = None,
) -> RedirectResponse:
    ticket = ticket_service.get_ticket_for_user(db, user, code)
    try:
        ticket_service.start_work(db, ticket, user, expected_version=version)
        _flash(request, "success", "Atención iniciada.")
    except RECOVERABLE_ERRORS as exc:
        _flash(request, "danger", exc.message)
    return _redirect(f"/tickets/{code}")


@router.post("/tickets/{code}/resolver")
def resolve_submit(
    request: Request,
    code: str,
    user: CurrentUser,
    db: DbSession,
    resolution_text: Annotated[str, Form()] = "",
    version: Annotated[int | None, Form()] = None,
) -> RedirectResponse:
    ticket = ticket_service.get_ticket_for_user(db, user, code)
    try:
        data = ResolveIn(resolution_text=resolution_text, version=version)
        ticket_service.propose_resolution(
            db, ticket, user, data.resolution_text, expected_version=data.version
        )
        _flash(request, "success", "Solución registrada. Falta la confirmación del solicitante.")
    except ValidationError as exc:
        message = field_errors_es(exc).get("resolution_text", "Revisa el texto de la solución.")
        _flash(request, "danger", f"Solución: {message}")
    except RECOVERABLE_ERRORS as exc:
        _flash(request, "danger", exc.message)
    return _redirect(f"/tickets/{code}")


@router.post("/tickets/{code}/confirmar")
def confirm_submit(
    request: Request,
    code: str,
    user: CurrentUser,
    db: DbSession,
    answer: Annotated[ConfirmationAnswer, Form()],
) -> RedirectResponse:
    ticket = ticket_service.get_ticket_for_user(db, user, code)
    outcome = confirmation_service.register_answer(
        db, ticket=ticket, responder=user, answer=answer, source=ConfirmationSource.WEB
    )
    _flash(request, *OUTCOME_MESSAGES[outcome])
    return _redirect(f"/tickets/{code}")


# --- Simulador de WhatsApp (sección 13.4) ----------------------------------------------------


@router.get("/simulador", response_class=HTMLResponse)
def simulator_page(
    request: Request, user: CurrentUser, db: DbSession, usuario: int | None = None
) -> Response:
    simulator_service.ensure_enabled()
    recipients = simulator_service.visible_recipients(db, user)
    selected = next((r for r in recipients if r.id == usuario), None)
    if selected is None and recipients:
        selected = recipients[0]
    if selected is not None:
        simulator_service.ensure_can_view_chat(user, selected)
    return templates.TemplateResponse(
        request,
        "simulator.html",
        {
            "user": user,
            "recipients": recipients,
            "selected": selected,
            "messages": simulator_service.chat_for(db, selected) if selected else [],
            "flash": _pop_flash(request),
        },
    )


@router.post("/simulador/responder")
def simulator_answer(
    request: Request,
    user: CurrentUser,
    db: DbSession,
    notification_id: Annotated[int, Form()],
    answer: Annotated[ConfirmationAnswer, Form()],
) -> RedirectResponse:
    simulator_service.ensure_enabled()
    try:
        recipient, outcome = simulator_service.answer(db, user, notification_id, answer)
    except BusinessRuleViolation as exc:
        _flash(request, "danger", exc.message)
        return _redirect("/simulador")
    _flash(request, *OUTCOME_MESSAGES[outcome])
    return _redirect(f"/simulador?usuario={recipient.id}")
