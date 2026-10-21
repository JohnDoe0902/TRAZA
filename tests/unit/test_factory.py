"""Selección de adaptadores por configuración: OpenAI sin credenciales no arranca."""

import pytest
from pydantic import SecretStr

from backend.core.config import ConfigurationError, Settings, get_settings
from backend.integrations import factory
from backend.integrations.mock_provider import MockProvider
from backend.integrations.openai_provider import OpenAIComposer, OpenAIProvider
from backend.integrations.rule_provider import RuleProvider
from backend.services.message_service import TemplateComposer


def settings(**overrides: object) -> Settings:
    return Settings(**{**get_settings().model_dump(), **overrides})


def test_por_defecto_mock_y_plantillas() -> None:
    assert isinstance(factory.get_classifier(settings(classifier_provider="mock")), MockProvider)
    assert isinstance(factory.get_classifier(settings(classifier_provider="rules")), RuleProvider)
    assert isinstance(
        factory.get_composer(settings(message_composer="templates")), TemplateComposer
    )


@pytest.mark.parametrize(
    "overrides",
    [
        {"openai_api_key": SecretStr(""), "openai_model": "gpt-falso"},
        {"openai_api_key": SecretStr("sk-prueba"), "openai_model": None},
        {"openai_api_key": None, "openai_model": None},
    ],
)
def test_openai_sin_credenciales_no_arranca(overrides: dict[str, object]) -> None:
    with pytest.raises(ConfigurationError, match="OPENAI_API_KEY"):
        factory.get_classifier(settings(classifier_provider="openai", **overrides))
    with pytest.raises(ConfigurationError):
        factory.get_composer(settings(message_composer="openai", **overrides))


def test_openai_con_credenciales_crea_los_adaptadores_sin_llamar_a_la_red() -> None:
    config = settings(
        classifier_provider="openai",
        message_composer="openai",
        openai_api_key=SecretStr("sk-prueba-no-real"),
        openai_model="gpt-falso",
        openai_timeout_seconds=7,
    )

    classifier = factory.get_classifier(config)
    composer = factory.get_composer(config)
    client = factory.openai_client(config)

    assert isinstance(classifier, OpenAIProvider)
    assert isinstance(composer, OpenAIComposer)
    assert client.max_retries == 0  # sin reintentos: si falla, respaldo local inmediato
    assert client.timeout == 7
