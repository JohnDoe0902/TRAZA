"""CP-05 y RN-04: matriz de prioridad (sección 7.1) y revisión humana."""

from decimal import Decimal

import pytest

from backend.models.enums import Category, Impact, Priority, Urgency
from backend.services.priority_rules import RULES_VERSION, compute_priority, needs_review


@pytest.mark.parametrize(
    ("impact", "urgency", "expected"),
    [
        (Impact.INDIVIDUAL, Urgency.BAJA, Priority.BAJA),
        (Impact.INDIVIDUAL, Urgency.MEDIA, Priority.MEDIA),
        (Impact.INDIVIDUAL, Urgency.ALTA, Priority.ALTA),
        (Impact.EQUIPO, Urgency.BAJA, Priority.MEDIA),
        (Impact.EQUIPO, Urgency.MEDIA, Priority.ALTA),
        (Impact.EQUIPO, Urgency.ALTA, Priority.ALTA),
        (Impact.AREA, Urgency.BAJA, Priority.ALTA),
        (Impact.AREA, Urgency.MEDIA, Priority.ALTA),
        (Impact.AREA, Urgency.ALTA, Priority.CRITICA),
    ],
)
def test_matriz_de_prioridad_completa(impact: Impact, urgency: Urgency, expected: Priority) -> None:
    assert compute_priority(impact, urgency) == expected


def test_cp05_area_y_urgencia_alta_es_critica() -> None:
    assert compute_priority(Impact.AREA, Urgency.ALTA) == Priority.CRITICA


def test_version_de_reglas() -> None:
    assert RULES_VERSION == "v1"


@pytest.mark.parametrize(
    ("category", "confidence", "provider_flag", "expected"),
    [
        (Category.SEGURIDAD, Decimal("0.99"), False, True),  # seguridad siempre se revisa
        (Category.REDES, Decimal("0.59"), False, True),  # confianza menor a 0,6
        (Category.REDES, Decimal("0.60"), False, False),  # el límite no requiere revisión
        (Category.REDES, None, False, False),  # reglas: sin confianza
        (Category.OTROS, Decimal("0.95"), True, True),  # el proveedor la pide
    ],
)
def test_rn04_revision_humana(
    category: Category, confidence: Decimal | None, provider_flag: bool, expected: bool
) -> None:
    assert needs_review(category, confidence, provider_flag) is expected
