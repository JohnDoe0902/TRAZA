"""Hash de contraseñas (argon2id) y datos guardados en la sesión web."""

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

SESSION_USER_KEY = "user_id"

# PasswordHasher usa argon2id por defecto.
_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


# Hash fijo para comparar cuando el correo no existe, y así no revelar por el tiempo
# de respuesta si una cuenta existe o no.
DUMMY_PASSWORD_HASH = hash_password("traza-dummy-password")
