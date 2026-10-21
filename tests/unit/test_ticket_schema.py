"""RF-02 / RN-01: validación de los datos de alta (sección 9.1)."""

import pytest
from pydantic import ValidationError

from backend.schemas.errors import field_errors_es
from backend.schemas.ticket import TicketCreate
from tests.helpers import VALID_TICKET


def test_rf02_datos_validos() -> None:
    data = TicketCreate.model_validate(VALID_TICKET)
    assert data.title == VALID_TICKET["title"]
    assert data.location == VALID_TICKET["location"]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("title", "Hola"),  # menos de 5
        ("title", "x" * 121),
        ("title", "     "),  # solo espacios
        ("description", ""),
        ("description", "corta"),  # menos de 10
        ("description", "x" * 2001),
        ("location", "x" * 121),
    ],
)
def test_rf02_datos_invalidos(field: str, value: str) -> None:
    with pytest.raises(ValidationError) as exc_info:
        TicketCreate.model_validate({**VALID_TICKET, field: value})
    assert field in field_errors_es(exc_info.value)


def test_rf02_limites_exactos_son_validos() -> None:
    TicketCreate(title="x" * 5, description="y" * 10, location="z" * 120)
    TicketCreate(title="x" * 120, description="y" * 2000)


def test_rf02_ubicacion_vacia_se_guarda_como_nula() -> None:
    assert TicketCreate.model_validate({**VALID_TICKET, "location": "   "}).location is None


def test_rnf07_mensajes_de_error_en_espanol() -> None:
    with pytest.raises(ValidationError) as exc_info:
        TicketCreate(title="Hola", description="", location="x" * 121)
    errors = field_errors_es(exc_info.value)
    assert errors["title"] == "Debe tener al menos 5 caracteres."
    assert errors["description"] == "Debe tener al menos 10 caracteres."
    assert errors["location"] == "No puede superar los 120 caracteres."
