"""Protección de datos antes de enviar texto a un servicio externo (RN-14)."""

import re

EMAIL_PATTERN = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
# Siete o más dígitos, con o sin "+", espacios o guiones: teléfonos, DNI y similares.
PHONE_PATTERN = re.compile(r"\+?\d(?:[\s-]?\d){6,}")


def redact_personal_data(text: str) -> str:
    """Reemplaza correos y números largos por marcadores; el resto del texto no cambia."""
    text = EMAIL_PATTERN.sub("[correo]", text)
    return PHONE_PATTERN.sub("[número]", text)
