"""Páginas web de la Fase 1: lista, alta y detalle (CP-01, CP-02 y CP-03 por la interfaz)."""

from collections.abc import Callable

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.models import Ticket, User
from backend.models.enums import Role, TicketStatus
from backend.schemas.ticket import TicketCreate
from backend.services import ticket_service
from tests.helpers import VALID_TICKET, count_rows

MakeUser = Callable[..., User]
Login = Callable[[User], TestClient]


def _create_ticket(db: Session, requester: User, title: str = VALID_TICKET["title"]) -> Ticket:
    data = TicketCreate.model_validate({**VALID_TICKET, "title": title})
    return ticket_service.create_ticket(db, requester, data)


def test_cp01_alta_desde_formulario_redirige_al_detalle(
    db: Session, make_user: MakeUser, login: Login
) -> None:
    client = login(make_user(Role.REQUESTER))

    response = client.post("/tickets/nuevo", data=VALID_TICKET, follow_redirects=False)

    assert response.status_code == 303
    code = response.headers["location"].removeprefix("/tickets/")
    ticket = db.scalars(select(Ticket).where(Ticket.public_code == code)).one()
    assert ticket.status == TicketStatus.PENDIENTE

    detail = client.get(response.headers["location"])
    assert detail.status_code == 200
    assert code in detail.text
    assert "Pendiente" in detail.text  # estado con etiqueta en español (RNF-07)


def test_cp02_formulario_invalido_muestra_errores_y_no_guarda(
    db: Session, make_user: MakeUser, login: Login
) -> None:
    client = login(make_user(Role.REQUESTER))
    before = count_rows(db)

    response = client.post(
        "/tickets/nuevo", data={"title": "Hola", "description": "", "location": ""}
    )

    assert response.status_code == 422
    assert "Debe tener al menos 5 caracteres." in response.text
    assert "Debe tener al menos 10 caracteres." in response.text
    assert 'value="Hola"' in response.text  # conserva lo escrito
    assert count_rows(db) == before


def test_formulario_de_alta_solo_para_solicitantes(make_user: MakeUser, login: Login) -> None:
    assert login(make_user(Role.REQUESTER)).get("/tickets/nuevo").status_code == 200
    assert login(make_user(Role.TECHNICIAN)).get("/tickets/nuevo").status_code == 403
    response = login(make_user(Role.ADMIN)).post("/tickets/nuevo", data=VALID_TICKET)
    assert response.status_code == 403


def test_cp03_detalle_ajeno_por_web_403_sin_datos(
    db: Session, make_user: MakeUser, login: Login
) -> None:
    ticket = _create_ticket(db, make_user(Role.REQUESTER), title="Proyector del aula 105")

    response = login(make_user(Role.REQUESTER)).get(f"/tickets/{ticket.public_code}")

    assert response.status_code == 403
    assert "Acceso denegado" in response.text
    assert "Proyector del aula 105" not in response.text


def test_rf04_lista_web_muestra_solo_tickets_propios(
    db: Session, make_user: MakeUser, login: Login
) -> None:
    owner = make_user(Role.REQUESTER)
    own = _create_ticket(db, owner, title="Monitor parpadea en la oficina")
    other = _create_ticket(db, make_user(Role.REQUESTER), title="Teclado ajeno roto")

    response = login(owner).get("/tickets")

    assert response.status_code == 200
    assert own.public_code in response.text
    assert "Monitor parpadea en la oficina" in response.text
    assert other.public_code not in response.text
    assert "Teclado ajeno roto" not in response.text


def test_lista_web_filtra_por_estado(db: Session, make_user: MakeUser, login: Login) -> None:
    owner = make_user(Role.REQUESTER)
    ticket = _create_ticket(db, owner)
    client = login(owner)

    assert ticket.public_code in client.get("/tickets", params={"estado": "PENDIENTE"}).text
    assert ticket.public_code not in client.get("/tickets", params={"estado": "CERRADO"}).text
    # Un valor desconocido se ignora y muestra todos.
    assert ticket.public_code in client.get("/tickets", params={"estado": "XYZ"}).text


def test_detalle_escapa_html_del_usuario(db: Session, make_user: MakeUser, login: Login) -> None:
    owner = make_user(Role.REQUESTER)
    ticket = _create_ticket(db, owner, title="<script>alert(1)</script>")

    response = login(owner).get(f"/tickets/{ticket.public_code}")

    assert "<script>alert(1)</script>" not in response.text
    assert "&lt;script&gt;" in response.text
