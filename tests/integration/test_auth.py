"""RF-01: autenticación con rol, por la API y por el formulario web."""

from collections.abc import Callable

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.models import User
from backend.models.enums import Role
from tests.helpers import TEST_PASSWORD

MakeUser = Callable[..., User]
Login = Callable[[User], TestClient]


def test_rf01_credenciales_validas_entran_con_su_rol(
    client: TestClient, make_user: MakeUser
) -> None:
    user = make_user(Role.TECHNICIAN)

    response = client.post("/api/auth/login", json={"email": user.email, "password": TEST_PASSWORD})

    assert response.status_code == 200
    assert response.json()["role"] == "TECHNICIAN"
    assert "password_hash" not in response.json()
    me = client.get("/api/me")
    assert me.status_code == 200
    assert me.json()["id"] == user.id


def test_rf01_correo_sin_distinguir_mayusculas(client: TestClient, make_user: MakeUser) -> None:
    user = make_user(Role.REQUESTER)
    response = client.post(
        "/api/auth/login", json={"email": user.email.upper(), "password": TEST_PASSWORD}
    )
    assert response.status_code == 200


def test_rf01_contrasena_incorrecta_no_entra(client: TestClient, make_user: MakeUser) -> None:
    user = make_user(Role.REQUESTER)

    response = client.post("/api/auth/login", json={"email": user.email, "password": "otra"})

    assert response.status_code == 401
    assert response.json()["detail"] == "Correo o contraseña incorrectos."
    assert client.get("/api/me").status_code == 401


def test_rf01_usuario_inactivo_no_entra(client: TestClient, make_user: MakeUser) -> None:
    user = make_user(Role.TECHNICIAN, is_active=False)

    response = client.post("/api/auth/login", json={"email": user.email, "password": TEST_PASSWORD})

    assert response.status_code == 401
    # Mismo mensaje que con contraseña incorrecta: no revela si la cuenta existe.
    assert response.json()["detail"] == "Correo o contraseña incorrectos."


def test_rf01_correo_inexistente_no_entra(client: TestClient) -> None:
    response = client.post(
        "/api/auth/login", json={"email": "nadie@traza.test", "password": TEST_PASSWORD}
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Correo o contraseña incorrectos."


def test_rf01_usuario_desactivado_pierde_la_sesion(
    db: Session, make_user: MakeUser, login: Login
) -> None:
    user = make_user(Role.REQUESTER)
    client = login(user)
    assert client.get("/api/me").status_code == 200

    user.is_active = False
    db.flush()

    assert client.get("/api/me").status_code == 401


def test_logout_cierra_la_sesion(make_user: MakeUser, login: Login) -> None:
    client = login(make_user(Role.ADMIN))

    assert client.post("/api/auth/logout").status_code == 204
    assert client.get("/api/me").status_code == 401


def test_rutas_api_sin_sesion_responden_401(client: TestClient) -> None:
    assert client.get("/api/me").status_code == 401
    assert client.get("/api/tickets").status_code == 401
    assert client.get("/api/tickets/TRZ-0001").status_code == 401


def test_cookie_de_sesion_es_httponly_y_samesite(client: TestClient, make_user: MakeUser) -> None:
    user = make_user(Role.REQUESTER)
    response = client.post("/api/auth/login", json={"email": user.email, "password": TEST_PASSWORD})
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie
    assert "samesite=lax" in cookie


# --- Formulario web ------------------------------------------------------------------------


def test_rf01_login_web_valido_redirige_a_tickets(client: TestClient, make_user: MakeUser) -> None:
    user = make_user(Role.REQUESTER)

    response = client.post(
        "/login",
        data={"email": user.email, "password": TEST_PASSWORD},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/tickets"


def test_rf01_login_web_invalido_muestra_error(client: TestClient, make_user: MakeUser) -> None:
    user = make_user(Role.REQUESTER)

    response = client.post("/login", data={"email": user.email, "password": "otra"})

    assert response.status_code == 401
    assert "Correo o contraseña incorrectos." in response.text
    assert "otra" not in response.text  # la contraseña no se devuelve en la página


def test_paginas_sin_sesion_redirigen_a_login(client: TestClient) -> None:
    for path in ("/tickets", "/tickets/nuevo", "/tickets/TRZ-0001"):
        response = client.get(path, follow_redirects=False)
        assert response.status_code == 303, path
        assert response.headers["location"] == "/login"
