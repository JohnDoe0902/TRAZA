"""Clasificador simulado para demo y pruebas: respuestas fijas por palabra clave.

Reproduce la clasificación esperada de los tickets del seed (sección 19). Si ninguna palabra
clave coincide, devuelve el mismo resultado que `RuleProvider`.
"""

from decimal import Decimal

from backend.integrations.base import ClassificationResult, TicketText
from backend.integrations.rule_provider import RuleProvider, normalize
from backend.models.enums import Category, ClassificationProvider, Impact, Urgency

FIXED_ANSWERS: tuple[tuple[str, ClassificationResult], ...] = (
    (
        "sin internet",
        ClassificationResult(
            category=Category.REDES,
            impact=Impact.AREA,
            urgency=Urgency.ALTA,
            confidence=Decimal("0.93"),
            rationale="Laboratorio completo sin conexión y con clase próxima.",
        ),
    ),
    (
        "sin tinta",
        ClassificationResult(
            category=Category.HARDWARE,
            impact=Impact.INDIVIDUAL,
            urgency=Urgency.BAJA,
            confidence=Decimal("0.90"),
            rationale="Consumible de una impresora personal.",
        ),
    ),
    (
        "plataforma interna",
        ClassificationResult(
            category=Category.ACCESOS,
            impact=Impact.INDIVIDUAL,
            urgency=Urgency.MEDIA,
            confidence=Decimal("0.85"),
            rationale="Una persona sin acceso a un sistema interno.",
        ),
    ),
    (
        "sistema de tramites",
        ClassificationResult(
            category=Category.SOFTWARE,
            impact=Impact.EQUIPO,
            urgency=Urgency.ALTA,
            confidence=Decimal("0.82"),
            rationale="Varias personas sin acceso al sistema de trámites.",
        ),
    ),
    (
        "credenciales",
        ClassificationResult(
            category=Category.SEGURIDAD,
            impact=Impact.INDIVIDUAL,
            urgency=Urgency.ALTA,
            human_review_required=True,
            confidence=Decimal("0.55"),
            rationale="Posible incidente de seguridad; el impacto debe evaluarlo una persona.",
        ),
    ),
)


class MockProvider:
    name = ClassificationProvider.MOCK
    model_version: str | None = "mock-v1"

    def __init__(self) -> None:
        self._rules = RuleProvider()

    def classify(self, text: TicketText) -> ClassificationResult:
        content = normalize(f"{text.title}\n{text.description}")
        for keyword, answer in FIXED_ANSWERS:
            if keyword in content:
                return answer.model_copy()
        return self._rules.classify(text)
