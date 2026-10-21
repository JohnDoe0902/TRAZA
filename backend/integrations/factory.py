"""Elige los adaptadores según las variables de entorno (CLASSIFIER_PROVIDER, etc.).

Si se elige OpenAI sin credenciales, el proceso no arranca: un error de configuración debe
verse, no esconderse detrás del respaldo por reglas.
"""

import openai

from backend.core.config import ConfigurationError, Settings, get_settings
from backend.integrations.base import (
    ClassificationProvider,
    MessageComposer,
    NotificationProvider,
)
from backend.integrations.mock_provider import MockProvider
from backend.integrations.openai_provider import OpenAIComposer, OpenAIProvider
from backend.integrations.rule_provider import RuleProvider
from backend.integrations.simulated_whatsapp import SimulatedWhatsApp
from backend.services.message_service import TemplateComposer


def openai_client(settings: Settings) -> openai.OpenAI:
    """Cliente con timeout propio y sin reintentos: si falla, se usa el respaldo local."""
    api_key = settings.openai_api_key.get_secret_value() if settings.openai_api_key else ""
    if not api_key or not settings.openai_model:
        raise ConfigurationError(
            "Elegiste OpenAI, pero faltan OPENAI_API_KEY u OPENAI_MODEL en el .env. "
            "Complétalas o usa CLASSIFIER_PROVIDER=mock|rules y MESSAGE_COMPOSER=templates."
        )
    return openai.OpenAI(api_key=api_key, timeout=settings.openai_timeout_seconds, max_retries=0)


def get_classifier(settings: Settings | None = None) -> ClassificationProvider:
    settings = settings or get_settings()
    if settings.classifier_provider == "openai":
        return OpenAIProvider(openai_client(settings), settings.openai_model or "")
    if settings.classifier_provider == "rules":
        return RuleProvider()
    return MockProvider()


def get_fallback_classifier() -> ClassificationProvider:
    return RuleProvider()


def get_composer(settings: Settings | None = None) -> MessageComposer:
    settings = settings or get_settings()
    if settings.message_composer == "openai":
        return OpenAIComposer(openai_client(settings), settings.openai_model or "")
    return TemplateComposer()


def get_notification_provider() -> NotificationProvider:
    provider = get_settings().notification_provider
    if provider == "whatsapp":
        raise NotImplementedError("WhatsAppCloudProvider llega en la Fase 4; usa simulated.")
    return SimulatedWhatsApp()
