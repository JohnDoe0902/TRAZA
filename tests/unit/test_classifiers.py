"""Proveedores locales de clasificación: reglas (sección 13.1) y mock (sección 19)."""

import pytest

from backend.integrations.base import TicketText
from backend.integrations.mock_provider import MockProvider
from backend.integrations.rule_provider import RuleProvider
from backend.models.enums import Category, Impact, Priority, Urgency
from backend.scripts.seed import SEED_TICKETS
from backend.services.priority_rules import compute_priority, needs_review

rules = RuleProvider()


def classify_rules(description: str, title: str = "Solicitud de soporte") -> tuple:
    result = rules.classify(TicketText(title=title, description=description))
    return result.category, result.impact, result.urgency


@pytest.mark.parametrize(
    ("description", "category"),
    [
        ("No hay internet en mi oficina", Category.REDES),
        ("El wifi se cae a cada rato", Category.REDES),
        ("La impresora atasca las hojas", Category.HARDWARE),
        ("El monitor no enciende", Category.HARDWARE),
        ("Olvidé mi contraseña del correo", Category.ACCESOS),
        ("Me llegó un correo de phishing pidiendo credenciales", Category.SEGURIDAD),
        ("Creo que la PC tiene un virus", Category.SEGURIDAD),
        ("Necesito instalar un programa estadístico", Category.SOFTWARE),
        ("La silla está rota", Category.OTROS),
    ],
)
def test_reglas_categoria_por_palabras(description: str, category: Category) -> None:
    assert classify_rules(description)[0] == category


@pytest.mark.parametrize(
    ("description", "impact"),
    [
        ("Todo el laboratorio sin conexión", Impact.AREA),
        ("Toda el área administrativa sin sistema", Impact.AREA),
        ("Varios equipos sin conexión", Impact.EQUIPO),
        ("Tres compañeros sin acceso al sistema", Impact.EQUIPO),
        ("4 docentes no pueden imprimir", Impact.EQUIPO),
        ("1 usuarios sin acceso", Impact.INDIVIDUAL),
        ("Mi teclado no responde", Impact.INDIVIDUAL),
    ],
)
def test_reglas_impacto(description: str, impact: Impact) -> None:
    assert classify_rules(description)[1] == impact


@pytest.mark.parametrize(
    ("description", "urgency"),
    [
        ("Es urgente, no funciona la red", Urgency.ALTA),
        ("Tengo clase en una hora y no hay proyector", Urgency.ALTA),
        ("Mañana hay examen y el sistema falla", Urgency.ALTA),
        ("No funciona nada en la oficina", Urgency.ALTA),
        ("Cuando puedan revisen el mouse", Urgency.MEDIA),
    ],
)
def test_reglas_urgencia(description: str, urgency: Urgency) -> None:
    assert classify_rules(description)[2] == urgency


def test_reglas_valores_por_defecto() -> None:
    assert classify_rules("La silla está rota") == (
        Category.OTROS,
        Impact.INDIVIDUAL,
        Urgency.MEDIA,
    )


def test_reglas_no_dependen_de_tildes_ni_mayusculas() -> None:
    assert classify_rules("CONTRASEÑA BLOQUEADA")[0] == classify_rules("contrasena bloqueada")[0]


def test_reglas_ignoran_la_ubicacion() -> None:
    result = rules.classify(
        TicketText(title="Impresora", description="Sin tinta", location="Oficina de grados")
    )
    assert result.impact == Impact.INDIVIDUAL


# Clasificación esperada de la sección 19, en el orden de SEED_TICKETS.
SECTION_19 = [
    (Category.REDES, Impact.AREA, Urgency.ALTA, Priority.CRITICA, False),
    (Category.HARDWARE, Impact.INDIVIDUAL, Urgency.BAJA, Priority.BAJA, False),
    (Category.ACCESOS, Impact.INDIVIDUAL, Urgency.MEDIA, Priority.MEDIA, False),
    (Category.SOFTWARE, Impact.EQUIPO, Urgency.ALTA, Priority.ALTA, False),
    (Category.SEGURIDAD, Impact.INDIVIDUAL, Urgency.ALTA, Priority.ALTA, True),
]


@pytest.mark.parametrize(
    ("seed_ticket", "expected"), list(zip(SEED_TICKETS, SECTION_19, strict=True))
)
def test_mock_reproduce_la_clasificacion_de_la_seccion_19(
    seed_ticket: tuple, expected: tuple
) -> None:
    _, title, description, location = seed_ticket
    result = MockProvider().classify(
        TicketText(title=title, description=description, location=location)
    )
    category, impact, urgency, priority, review = expected
    assert (result.category, result.impact, result.urgency) == (category, impact, urgency)
    assert compute_priority(result.impact, result.urgency) == priority
    assert needs_review(result.category, result.confidence, result.human_review_required) is review


def test_mock_sin_coincidencias_usa_las_reglas() -> None:
    text = TicketText(title="Monitor", description="El monitor parpadea")
    assert MockProvider().classify(text).category == rules.classify(text).category
