"""Página /telegram: cada usuario vincula o desvincula su chat de Telegram.

La lógica vive en telegram_link_service. Aquí solo se arma la página.
"""

from fastapi import APIRouter, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from backend.api.deps import CurrentUser, DbSession
from backend.core.clock import utcnow
from backend.core.config import get_settings
from backend.core.errors import BusinessRuleViolation
from backend.core.templating import templates
from backend.services import telegram_link_service

router = APIRouter(include_in_schema=False)

FLASH_KEY = "flash"


def _page(request: Request, user: CurrentUser, **extra: object) -> Response:
    context = {
        "user": user,
        "linked": telegram_link_service.is_linked(user),
        "bot_username": get_settings().telegram_bot_username,
        "flash": request.session.pop(FLASH_KEY, None),
        "link": None,
        **extra,
    }
    return templates.TemplateResponse(request, "telegram.html", context)


@router.get("/telegram", response_class=HTMLResponse)
def telegram_page(request: Request, user: CurrentUser) -> Response:
    return _page(request, user)


@router.post("/telegram/vincular", response_class=HTMLResponse)
def create_link(request: Request, user: CurrentUser, db: DbSession) -> Response:
    try:
        link = telegram_link_service.create_link(db, user, utcnow())
    except BusinessRuleViolation as exc:
        return _page(request, user, flash={"kind": "danger", "text": exc.message})
    # Mostramos el enlace en la respuesta y no lo guardamos en la sesión porque es un secreto
    return _page(request, user, link=link)


@router.post("/telegram/desvincular")
def unlink(request: Request, user: CurrentUser, db: DbSession) -> RedirectResponse:
    telegram_link_service.unlink(db, user)
    request.session[FLASH_KEY] = {
        "kind": "secondary",
        "text": "Desvinculaste tu Telegram. Ya no te llegarán avisos por ahí.",
    }
    return RedirectResponse("/telegram", status_code=status.HTTP_303_SEE_OTHER)
