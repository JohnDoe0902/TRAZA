"""RN-02: formato del código público."""

import pytest

from backend.services.ticket_service import format_ticket_code


@pytest.mark.parametrize(
    ("number", "expected"),
    [(1, "TRZ-0001"), (42, "TRZ-0042"), (999, "TRZ-0999"), (9999, "TRZ-9999")],
)
def test_rn02_codigo_con_cuatro_digitos_minimo(number: int, expected: str) -> None:
    assert format_ticket_code(number) == expected


def test_rn02_codigo_no_se_trunca_con_mas_de_cuatro_digitos() -> None:
    assert format_ticket_code(10000) == "TRZ-10000"
    assert format_ticket_code(123456) == "TRZ-123456"
