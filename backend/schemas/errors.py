"""Mensajes de validación en español para los formularios web (RNF-07)."""

from pydantic import ValidationError


def field_errors_es(exc: ValidationError) -> dict[str, str]:
    """Primer error legible de cada campo, en español."""
    errors: dict[str, str] = {}
    for error in exc.errors():
        field = str(error["loc"][0]) if error["loc"] else "__all__"
        if field not in errors:
            errors[field] = _message_es(error["type"], error.get("ctx") or {})
    return errors


def _message_es(error_type: str, ctx: dict[str, object]) -> str:
    if error_type == "missing":
        return "Este campo es obligatorio."
    if error_type == "string_too_short":
        min_length = ctx.get("min_length", 1)
        if min_length == 1:
            return "Este campo es obligatorio."
        return f"Debe tener al menos {min_length} caracteres."
    if error_type == "string_too_long":
        return f"No puede superar los {ctx.get('max_length')} caracteres."
    return "El valor no es válido."
