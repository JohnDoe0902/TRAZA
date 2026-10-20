"""RNF-01: contraseñas con argon2id."""

from backend.core.security import hash_password, verify_password


def test_rnf01_hash_usa_argon2id() -> None:
    password_hash = hash_password("una-clave-de-prueba")
    assert password_hash.startswith("$argon2id$")
    assert "una-clave-de-prueba" not in password_hash


def test_rnf01_verifica_contrasena_correcta_e_incorrecta() -> None:
    password_hash = hash_password("una-clave-de-prueba")
    assert verify_password(password_hash, "una-clave-de-prueba")
    assert not verify_password(password_hash, "otra-clave")


def test_rnf01_hash_invalido_no_autentica() -> None:
    assert not verify_password("no-es-un-hash", "cualquier-cosa")


def test_rnf01_mismo_password_produce_hashes_distintos() -> None:
    assert hash_password("repetida-123") != hash_password("repetida-123")
