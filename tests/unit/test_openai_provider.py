"""RF-21, RN-05 y RN-14: adaptador de OpenAI con un cliente falso (nunca la API real)."""

from decimal import Decimal

import pytest
from openai.lib._parsing._responses import type_to_text_format_param
from pydantic import ValidationError

from backend.integrations.base import ComposeRequest, ProviderOutputError, TicketText
from backend.integrations.openai_provider import (
    CLASSIFIER_INSTRUCTIONS,
    MAX_OUTPUT_TOKENS,
    ComposedMessage,
    OpenAIClassificationOutput,
    OpenAIComposer,
    OpenAIProvider,
)
from backend.integrations.privacy import redact_personal_data
from backend.models.enums import Category, ClassificationProvider, Impact, MessageType, Urgency
from tests.helpers import FakeOpenAIClient, openai_server_error, openai_timeout

TEXT = TicketText(
    title="Laboratorio 3 sin internet",
    description="Hay clase en una hora. Escríbanme a elena.quispe@unmsm.edu.pe o al 987 654 321.",
    location="Laboratorio de cómputo 3",
)


def valid_output(**overrides: object) -> OpenAIClassificationOutput:
    values: dict[str, object] = {
        "category": Category.REDES,
        "impact": Impact.AREA,
        "urgency": Urgency.ALTA,
        "human_review_required": False,
        "confidence": 0.914,
        "rationale": "Laboratorio completo sin conexión y con clase próxima.",
    }
    values.update(overrides)
    return OpenAIClassificationOutput.model_validate(values)


def test_rf21_respuesta_valida_se_convierte_al_esquema_13_1() -> None:
    client = FakeOpenAIClient(parsed=valid_output(), model="gpt-falso-2026-10")
    provider = OpenAIProvider(client, "gpt-falso")

    result = provider.classify(TEXT)

    assert provider.name == ClassificationProvider.OPENAI
    assert (result.category, result.impact, result.urgency) == (
        Category.REDES,
        Impact.AREA,
        Urgency.ALTA,
    )
    assert result.confidence == Decimal("0.91")
    assert result.rationale.startswith("Laboratorio completo")
    assert provider.model_version == "gpt-falso-2026-10"  # el modelo que respondió


def test_rf21_peticion_con_esquema_estricto_y_sin_guardar() -> None:
    client = FakeOpenAIClient(parsed=valid_output())

    OpenAIProvider(client, "gpt-falso").classify(TEXT)

    call = client.calls[0]
    assert call["model"] == "gpt-falso"
    assert call["text_format"] is OpenAIClassificationOutput
    assert call["store"] is False
    assert call["max_output_tokens"] == MAX_OUTPUT_TOKENS
    assert call["instructions"] == CLASSIFIER_INSTRUCTIONS
    assert "SEGURIDAD" in call["instructions"] and "human_review_required" in call["instructions"]


def test_rf21_el_esquema_enviado_es_estricto_y_cerrado() -> None:
    fmt = type_to_text_format_param(OpenAIClassificationOutput)
    schema = fmt["schema"]

    assert fmt["strict"] is True
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == {
        "category",
        "impact",
        "urgency",
        "human_review_required",
        "confidence",
        "rationale",
    }
    assert "priority" not in schema["properties"]  # regla 4: la IA no decide la prioridad
    assert type_to_text_format_param(ComposedMessage)["strict"] is True


def test_rn14_no_se_envian_correos_ni_telefonos() -> None:
    client = FakeOpenAIClient(parsed=valid_output())

    OpenAIProvider(client, "gpt-falso").classify(TEXT)

    sent = client.calls[0]["input"]
    assert "elena.quispe@unmsm.edu.pe" not in sent
    assert "987 654 321" not in sent
    assert "[correo]" in sent and "[número]" in sent
    assert "Laboratorio de cómputo 3" in sent  # el resto del texto se conserva


def test_rn05_timeout_se_traduce_a_timeout_error() -> None:
    provider = OpenAIProvider(FakeOpenAIClient(error=openai_timeout()), "gpt-falso")
    with pytest.raises(TimeoutError):
        provider.classify(TEXT)


def test_rn05_rechazo_o_salida_vacia_es_salida_invalida() -> None:
    provider = OpenAIProvider(FakeOpenAIClient(parsed=None), "gpt-falso")
    with pytest.raises(ProviderOutputError):
        provider.classify(TEXT)


def test_rn05_confianza_fuera_de_rango_no_pasa_el_esquema() -> None:
    provider = OpenAIProvider(FakeOpenAIClient(parsed=valid_output(confidence=1.7)), "gpt-falso")
    with pytest.raises(ValidationError):
        provider.classify(TEXT)


def test_rn05_error_del_servidor_se_propaga_para_el_fallback() -> None:
    provider = OpenAIProvider(FakeOpenAIClient(error=openai_server_error()), "gpt-falso")
    with pytest.raises(Exception, match="Error del servidor"):
        provider.classify(TEXT)


def test_justificacion_larga_se_recorta_a_200() -> None:
    client = FakeOpenAIClient(parsed=valid_output(rationale="x" * 500))
    assert len(OpenAIProvider(client, "gpt-falso").classify(TEXT).rationale) == 200


# --- Redactor ---------------------------------------------------------------------------------

REQUEST = ComposeRequest(
    message_type=MessageType.A3,
    purpose="Preguntar si el problema quedó solucionado.",
    ticket_code="TRZ-0042",
    status_label="Pendiente de confirmación",
    base_message="El equipo técnico registró una solución para TRZ-0042. ¿Quedó solucionado?",
)


def test_redactor_devuelve_el_texto_y_no_envia_nombres() -> None:
    client = FakeOpenAIClient(parsed=ComposedMessage(text="  ¿Se solucionó TRZ-0042?  "))

    text = OpenAIComposer(client, "gpt-falso").compose(REQUEST)

    assert text == "¿Se solucionó TRZ-0042?"
    sent = client.calls[0]["input"]
    assert "TRZ-0042" in sent and "Pendiente de confirmación" in sent
    assert client.calls[0]["text_format"] is ComposedMessage


def test_redactor_sin_texto_es_salida_invalida() -> None:
    client = FakeOpenAIClient(parsed=ComposedMessage(text="   "))
    with pytest.raises(ProviderOutputError):
        OpenAIComposer(client, "gpt-falso").compose(REQUEST)


def test_redactor_timeout() -> None:
    with pytest.raises(TimeoutError):
        OpenAIComposer(FakeOpenAIClient(error=openai_timeout()), "gpt-falso").compose(REQUEST)


# --- Enmascarado de datos personales -----------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Escríbeme a ana.torres@unmsm.edu.pe", "Escríbeme a [correo]"),
        ("Llámame al 987 654 321", "Llámame al [número]"),
        ("Mi celular es +51 900-000-001", "Mi celular es [número]"),
        ("DNI 45678912", "DNI [número]"),
        (
            "Laboratorio 3, aula 105, TRZ-0001, año 2026",
            "Laboratorio 3, aula 105, TRZ-0001, año 2026",
        ),
    ],
)
def test_rn14_enmascarado(text: str, expected: str) -> None:
    assert redact_personal_data(text) == expected
