"""Errores de dominio y su traducción a HTTP en un único manejador."""

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse, RedirectResponse, Response


class DomainError(Exception):
    status_code: int = status.HTTP_400_BAD_REQUEST
    default_message: str = "La operación no es válida."

    def __init__(self, message: str | None = None) -> None:
        self.message = message or self.default_message
        super().__init__(self.message)


class NotAuthenticated(DomainError):
    status_code = status.HTTP_401_UNAUTHORIZED
    default_message = "Debes iniciar sesión."


class NotAuthorized(DomainError):
    status_code = status.HTTP_403_FORBIDDEN
    default_message = "No tienes permiso para realizar esta acción."


class NotFound(DomainError):
    status_code = status.HTTP_404_NOT_FOUND
    default_message = "No se encontró el recurso solicitado."


class InvalidTransition(DomainError):
    status_code = status.HTTP_409_CONFLICT
    default_message = "El cambio de estado solicitado no está permitido."


class ConcurrencyConflict(DomainError):
    status_code = status.HTTP_409_CONFLICT
    default_message = "El ticket fue modificado por otra persona. Recarga e inténtalo de nuevo."


def _is_api_request(request: Request) -> bool:
    return request.url.path.startswith("/api") or request.url.path.startswith("/webhooks")


async def domain_error_handler(request: Request, exc: Exception) -> Response:
    assert isinstance(exc, DomainError)
    if _is_api_request(request):
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.message})
    if isinstance(exc, NotAuthenticated):
        return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)

    from backend.core.templating import templates

    return templates.TemplateResponse(
        request,
        "error.html",
        {"status_code": exc.status_code, "message": exc.message},
        status_code=exc.status_code,
    )


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(DomainError, domain_error_handler)
