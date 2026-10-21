"""Rutas JSON de autenticación (RF-01)."""

from fastapi import APIRouter, Request, status

from backend.api.deps import CurrentUser, DbSession
from backend.core.security import SESSION_USER_KEY
from backend.schemas.auth import LoginIn, UserOut
from backend.services import auth_service

router = APIRouter(prefix="/api", tags=["auth"])


@router.post("/auth/login", response_model=UserOut)
def login(payload: LoginIn, request: Request, db: DbSession) -> UserOut:
    user = auth_service.authenticate(db, payload.email, payload.password)
    request.session.clear()
    request.session[SESSION_USER_KEY] = user.id
    return UserOut.model_validate(user)


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request) -> None:
    request.session.clear()


@router.get("/me", response_model=UserOut)
def me(user: CurrentUser) -> UserOut:
    return UserOut.model_validate(user)
