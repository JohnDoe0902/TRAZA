"""Páginas web (Jinja2 + Bootstrap): /login, /tickets, /tickets/nuevo, /tickets/{code}."""

from typing import Annotated

from fastapi import APIRouter, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from pydantic import ValidationError

from backend.api.deps import CurrentUser, DbSession, OptionalUser
from backend.core.errors import NotAuthenticated
from backend.core.permissions import ensure_role
from backend.core.security import SESSION_USER_KEY
from backend.core.templating import templates
from backend.models.enums import Role, TicketStatus
from backend.schemas.errors import field_errors_es
from backend.schemas.ticket import TicketCreate
from backend.services import auth_service, ticket_service

router = APIRouter(include_in_schema=False)


def _redirect(url: str) -> RedirectResponse:
    return RedirectResponse(url, status_code=status.HTTP_303_SEE_OTHER)


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


@router.get("/tickets", response_class=HTMLResponse)
def tickets_page(
    request: Request, user: CurrentUser, db: DbSession, estado: str | None = None
) -> Response:
    status_filter = TicketStatus(estado) if estado in TicketStatus.__members__ else None
    tickets = ticket_service.list_tickets_for_user(db, user, status=status_filter)
    return templates.TemplateResponse(
        request,
        "tickets/list.html",
        {"user": user, "tickets": tickets, "status_filter": status_filter},
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
    return _redirect(f"/tickets/{ticket.public_code}")


@router.get("/tickets/{code}", response_class=HTMLResponse)
def ticket_detail_page(request: Request, code: str, user: CurrentUser, db: DbSession) -> Response:
    ticket = ticket_service.get_ticket_for_user(db, user, code)
    return templates.TemplateResponse(
        request, "tickets/detail.html", {"user": user, "ticket": ticket}
    )
