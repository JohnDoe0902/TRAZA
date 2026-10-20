"""Matriz de prioridad (sección 7.1) y regla de revisión crítica (RN-04).

Funciones puras, sin base de datos. La IA sugiere; estas reglas deciden (regla 4).
"""

from decimal import Decimal

from backend.models.enums import Category, Impact, Priority, Urgency

RULES_VERSION = "v1"
MIN_CONFIDENCE = Decimal("0.6")

PRIORITY_MATRIX: dict[tuple[Impact, Urgency], Priority] = {
    (Impact.INDIVIDUAL, Urgency.BAJA): Priority.BAJA,
    (Impact.INDIVIDUAL, Urgency.MEDIA): Priority.MEDIA,
    (Impact.INDIVIDUAL, Urgency.ALTA): Priority.ALTA,
    (Impact.EQUIPO, Urgency.BAJA): Priority.MEDIA,
    (Impact.EQUIPO, Urgency.MEDIA): Priority.ALTA,
    (Impact.EQUIPO, Urgency.ALTA): Priority.ALTA,
    (Impact.AREA, Urgency.BAJA): Priority.ALTA,
    (Impact.AREA, Urgency.MEDIA): Priority.ALTA,
    (Impact.AREA, Urgency.ALTA): Priority.CRITICA,
}


def compute_priority(impact: Impact, urgency: Urgency) -> Priority:
    return PRIORITY_MATRIX[(Impact(impact), Urgency(urgency))]


def needs_review(
    category: Category, confidence: Decimal | None, provider_requests_review: bool = False
) -> bool:
    """RN-04: seguridad, confianza baja o pedido explícito del proveedor → revisión humana."""
    if category == Category.SEGURIDAD or provider_requests_review:
        return True
    return confidence is not None and confidence < MIN_CONFIDENCE
