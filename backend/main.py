"""Punto de entrada: crea la app, monta routers, plantillas y estáticos."""

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from backend.api import auth, health, tickets, web
from backend.core.config import get_settings
from backend.core.errors import register_exception_handlers

STATIC_DIR = Path(__file__).resolve().parent / "static"


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="TRAZA", version="0.1.0")
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.secret_key.get_secret_value(),
        session_cookie="traza_session",
        max_age=settings.session_max_age_seconds,
        same_site="lax",
        https_only=not settings.is_development,
    )
    register_exception_handlers(app)
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(tickets.router)
    app.include_router(web.router)
    return app


app = create_app()
