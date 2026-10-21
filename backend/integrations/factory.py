"""Elige los adaptadores según las variables de entorno (CLASSIFIER_PROVIDER, etc.)."""

from backend.core.config import get_settings
from backend.integrations.base import ClassificationProvider, NotificationProvider
from backend.integrations.mock_provider import MockProvider
from backend.integrations.rule_provider import RuleProvider
from backend.integrations.simulated_whatsapp import SimulatedWhatsApp


def get_classifier() -> ClassificationProvider:
    provider = get_settings().classifier_provider
    if provider == "rules":
        return RuleProvider()
    if provider == "openai":
        raise NotImplementedError("OpenAIProvider llega en la Fase 3; usa mock o rules.")
    return MockProvider()


def get_fallback_classifier() -> ClassificationProvider:
    return RuleProvider()


def get_notification_provider() -> NotificationProvider:
    provider = get_settings().notification_provider
    if provider == "whatsapp":
        raise NotImplementedError("WhatsAppCloudProvider llega en la Fase 4; usa simulated.")
    return SimulatedWhatsApp()
