"""Dependencias comunes de los routers: sesión de base de datos y usuario actual."""

from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from backend.core.db import get_db
from backend.core.errors import NotAuthenticated
from backend.core.security import SESSION_USER_KEY
from backend.models import User
from backend.services import auth_service

DbSession = Annotated[Session, Depends(get_db)]


def get_current_user(request: Request, db: DbSession) -> User:
    """Usuario de la cookie de sesión. Sin sesión válida → 401 (API) o redirección (web)."""
    user_id = request.session.get(SESSION_USER_KEY)
    user = auth_service.get_active_user(db, user_id) if isinstance(user_id, int) else None
    if user is None:
        request.session.clear()
        raise NotAuthenticated()
    return user


def get_optional_user(request: Request, db: DbSession) -> User | None:
    user_id = request.session.get(SESSION_USER_KEY)
    return auth_service.get_active_user(db, user_id) if isinstance(user_id, int) else None


CurrentUser = Annotated[User, Depends(get_current_user)]
OptionalUser = Annotated[User | None, Depends(get_optional_user)]
