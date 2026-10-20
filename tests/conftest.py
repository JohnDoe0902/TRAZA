"""Infraestructura de pruebas.

- Usa la base `traza_test` (TEST_DATABASE_URL) y le aplica las migraciones al empezar.
- Cada prueba corre dentro de una transacción que se revierte al final: los `commit()` de los
  servicios solo liberan un SAVEPOINT, así que nada queda guardado.
- Nunca se llama a OpenAI ni a WhatsApp.
"""

import itertools
import os
import secrets
from collections.abc import Callable, Iterator
from pathlib import Path

os.environ["APP_ENV"] = "test"
os.environ.setdefault("SECRET_KEY", secrets.token_urlsafe(32))

import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import Engine, create_engine  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from backend.core.config import get_settings  # noqa: E402
from backend.core.db import get_db  # noqa: E402
from backend.models import User  # noqa: E402
from backend.models.enums import Role  # noqa: E402
from tests.helpers import TEST_PASSWORD, TEST_PASSWORD_HASH, Actors  # noqa: E402

ROOT_DIR = Path(__file__).resolve().parents[1]

_user_counter = itertools.count(1)


def _test_database_url() -> str:
    settings = get_settings()
    if not settings.test_database_url:
        pytest.exit("Falta TEST_DATABASE_URL en el entorno o en .env.", returncode=2)
    test_url = make_url(settings.test_database_url)
    if test_url.database == make_url(settings.database_url).database:
        pytest.exit(
            "TEST_DATABASE_URL apunta a la misma base que DATABASE_URL; las pruebas la borrarían.",
            returncode=2,
        )
    return settings.test_database_url


@pytest.fixture(scope="session")
def engine() -> Iterator[Engine]:
    url = _test_database_url()
    config = Config(str(ROOT_DIR / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", url)
    config.attributes["configure_logger"] = False
    # Esquema limpio en cada corrida; de paso prueba que la migración baja y sube.
    command.downgrade(config, "base")
    command.upgrade(config, "head")

    test_engine = create_engine(url, pool_size=10, max_overflow=10)
    yield test_engine
    test_engine.dispose()


@pytest.fixture
def db(engine: Engine) -> Iterator[Session]:
    with engine.connect() as connection:
        transaction = connection.begin()
        session = Session(
            bind=connection,
            join_transaction_mode="create_savepoint",
            autoflush=False,
            expire_on_commit=False,
        )
        try:
            yield session
        finally:
            session.close()
            transaction.rollback()


@pytest.fixture
def app(db: Session) -> Iterator[FastAPI]:
    from backend.main import app as fastapi_app

    fastapi_app.dependency_overrides[get_db] = lambda: db
    yield fastapi_app
    fastapi_app.dependency_overrides.clear()


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def make_user(db: Session) -> Callable[..., User]:
    def _make_user(
        role: Role = Role.REQUESTER,
        *,
        is_active: bool = True,
        whatsapp_opt_in: bool = False,
        full_name: str | None = None,
    ) -> User:
        number = next(_user_counter)
        user = User(
            full_name=full_name or f"Usuario de prueba {number}",
            email=f"{role.value.lower()}{number}-{secrets.token_hex(3)}@traza.test",
            password_hash=TEST_PASSWORD_HASH,
            role=role,
            is_active=is_active,
            whatsapp_opt_in=whatsapp_opt_in,
            phone_e164=f"+519{number:08d}" if whatsapp_opt_in else None,
        )
        db.add(user)
        db.flush()
        return user

    return _make_user


@pytest.fixture
def actors(make_user: Callable[..., User]) -> Actors:
    """Solicitante y técnico con WhatsApp, otro técnico y un administrador."""
    return Actors(
        requester=make_user(Role.REQUESTER, whatsapp_opt_in=True, full_name="Elena Quispe"),
        technician=make_user(Role.TECHNICIAN, whatsapp_opt_in=True, full_name="Bruno Salas"),
        other_technician=make_user(Role.TECHNICIAN, full_name="Carla Ríos"),
        admin=make_user(Role.ADMIN, full_name="Ana Torres"),
    )


@pytest.fixture
def login(app: FastAPI) -> Iterator[Callable[[User], TestClient]]:
    """Devuelve un TestClient con la sesión del usuario indicado (uno por usuario)."""
    clients: list[TestClient] = []

    def _login(user: User) -> TestClient:
        test_client = TestClient(app)
        response = test_client.post(
            "/api/auth/login", json={"email": user.email, "password": TEST_PASSWORD}
        )
        assert response.status_code == 200, response.text
        clients.append(test_client)
        return test_client

    yield _login
    for test_client in clients:
        test_client.close()
