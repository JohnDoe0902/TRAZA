"""Clasificador local por palabras clave (sección 13.1). Es también el fallback de la IA."""

import re
import unicodedata

from backend.integrations.base import ClassificationResult, TicketText
from backend.models.enums import Category, ClassificationProvider, Impact, Urgency

URGENT_TERMS = ("urgente", "clase", "examen", "no funciona nada")
AREA_TERMS = ("laboratorio", "todo", "todos", "toda el area", "toda la oficina", "oficina")
TEAM_TERMS = ("varios", "varias", "equipo")
PEOPLE_TERMS = (
    "personas",
    "companeros",
    "companeras",
    "usuarios",
    "docentes",
    "alumnos",
    "estudiantes",
    "colegas",
)
NUMBER_WORDS = ("dos", "tres", "cuatro", "cinco", "seis", "siete", "ocho", "nueve", "diez")

# El orden importa: seguridad primero, porque un correo de phishing también menciona "acceso".
CATEGORY_TERMS: tuple[tuple[Category, tuple[str, ...]], ...] = (
    (Category.SEGURIDAD, ("phishing", "credenciales", "virus", "malware", "sospechoso")),
    (Category.REDES, ("red", "internet", "wifi", "conexion")),
    (Category.HARDWARE, ("impresora", "monitor", "teclado", "mouse", "proyector")),
    (Category.ACCESOS, ("contrasena", "acceso", "cuenta", "entrar", "usuario bloqueado")),
    (Category.SOFTWARE, ("sistema", "programa", "aplicacion", "instalar", "software")),
)


def normalize(text: str) -> str:
    """Minúsculas y sin tildes, para comparar palabras clave."""
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def _contains(text: str, terms: tuple[str, ...]) -> bool:
    return any(re.search(rf"\b{re.escape(term)}\b", text) for term in terms)


def _mentions_several_people(text: str) -> bool:
    people = "|".join(PEOPLE_TERMS)
    numbers = "|".join(NUMBER_WORDS)
    if re.search(rf"\b({numbers})\s+({people})\b", text):
        return True
    return any(int(n) > 1 for n in re.findall(rf"\b(\d+)\s+(?:{people})\b", text))


class RuleProvider:
    name = ClassificationProvider.RULES
    model_version: str | None = None

    def classify(self, text: TicketText) -> ClassificationResult:
        # Solo título y descripción: la ubicación ("Oficina...") no indica a cuántos afecta.
        content = normalize(f"{text.title}\n{text.description}")

        category = next(
            (cat for cat, terms in CATEGORY_TERMS if _contains(content, terms)), Category.OTROS
        )
        if _contains(content, AREA_TERMS):
            impact = Impact.AREA
        elif _contains(content, TEAM_TERMS) or _mentions_several_people(content):
            impact = Impact.EQUIPO
        else:
            impact = Impact.INDIVIDUAL
        urgency = Urgency.ALTA if _contains(content, URGENT_TERMS) else Urgency.MEDIA

        return ClassificationResult(
            category=category,
            impact=impact,
            urgency=urgency,
            human_review_required=False,
            confidence=None,
            rationale="Clasificación por palabras clave.",
        )
