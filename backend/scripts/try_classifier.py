"""Prueba manual del clasificador configurado con los 5 textos del seed (sección 19).

Uso: python -m backend.scripts.try_classifier

Con CLASSIFIER_PROVIDER=openai llama a la API real (consume créditos): sirve como evidencia de
la demo con GPT. Nunca se ejecuta en pytest. Si el proveedor falla, muestra qué haría el
sistema: clasificar con reglas (RN-05).
"""

import sys

from backend.core.config import ConfigurationError, get_settings
from backend.integrations import factory
from backend.integrations.base import TicketText
from backend.scripts.seed import SEED_TICKETS
from backend.services.priority_rules import compute_priority, needs_review

# Valores esperados de la sección 19, en el orden de SEED_TICKETS.
EXPECTED = (
    ("REDES", "AREA", "ALTA", "CRITICA"),
    ("HARDWARE", "INDIVIDUAL", "BAJA", "BAJA"),
    ("ACCESOS", "INDIVIDUAL", "MEDIA", "MEDIA"),
    ("SOFTWARE", "EQUIPO", "ALTA", "ALTA"),
    ("SEGURIDAD", "(por evaluar)", "ALTA", "Revisión humana"),
)


def main() -> int:
    settings = get_settings()
    try:
        provider = factory.get_classifier(settings)
    except ConfigurationError as exc:
        print(f"Error de configuración: {exc}")
        return 2
    fallback = factory.get_fallback_classifier()
    print(
        f"Proveedor: {provider.name.value}"
        + (f" · modelo {settings.openai_model}" if provider.name.value == "openai" else "")
    )

    matches = 0
    for (_, title, description, location), expected in zip(SEED_TICKETS, EXPECTED, strict=True):
        text = TicketText(title=title, description=description, location=location)
        try:
            result, used = provider.classify(text), provider.name.value
        except Exception as exc:  # se muestra igual que lo trataría el sistema
            print(f"  {title}: falló ({type(exc).__name__}); se usaría el respaldo por reglas")
            result, used = fallback.classify(text), "rules"
        priority = compute_priority(result.impact, result.urgency)
        review = needs_review(result.category, result.confidence, result.human_review_required)
        got_priority = "Revisión humana" if review else priority.value
        ok = result.category.value == expected[0] and got_priority == expected[3]
        matches += ok
        print(
            f"{'OK ' if ok else '-- '}{title}\n"
            f"    obtenido: {result.category.value} · {result.impact.value} · "
            f"{result.urgency.value} -> {got_priority} ({used}"
            f"{f', confianza {result.confidence}' if result.confidence is not None else ''})\n"
            f"    esperado: {' · '.join(expected[:3])} -> {expected[3]}"
        )
    print(f"\nCoinciden en categoría y prioridad: {matches} de {len(EXPECTED)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
