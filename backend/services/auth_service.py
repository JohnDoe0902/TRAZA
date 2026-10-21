"""Autenticación de usuarios (RF-01)."""

from sqlalchemy.orm import Session

from backend.core.errors import NotAuthenticated
from backend.core.security import DUMMY_PASSWORD_HASH, verify_password
from backend.models import User
from backend.repositories import user_repository

INVALID_CREDENTIALS = "Correo o contraseña incorrectos."


def authenticate(db: Session, email: str, password: str) -> User:
    """Devuelve el usuario si las credenciales son válidas y está activo.

    El mensaje de error es el mismo en todos los casos para no revelar qué cuentas existen.
    """
    user = user_repository.get_by_email(db, email)
    if user is None:
        verify_password(DUMMY_PASSWORD_HASH, password)
        raise NotAuthenticated(INVALID_CREDENTIALS)
    if not verify_password(user.password_hash, password) or not user.is_active:
        raise NotAuthenticated(INVALID_CREDENTIALS)
    return user


def get_active_user(db: Session, user_id: int) -> User | None:
    user = user_repository.get_by_id(db, user_id)
    if user is None or not user.is_active:
        return None
    return user
