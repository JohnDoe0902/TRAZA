"""Configuración de la aplicación, leída solo de variables de entorno (y `.env`)."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: Literal["development", "test", "production"] = "development"
    secret_key: SecretStr = Field(min_length=16)
    database_url: str
    test_database_url: str | None = None
    timezone: str = "America/Lima"
    seed_password: SecretStr | None = None

    classifier_provider: Literal["mock", "rules", "openai"] = "mock"
    message_composer: Literal["templates", "openai"] = "templates"
    notification_provider: Literal["simulated", "whatsapp"] = "simulated"

    openai_api_key: SecretStr | None = None
    openai_model: str | None = None
    openai_timeout_seconds: float = 10

    whatsapp_token: SecretStr | None = None
    whatsapp_phone_number_id: str | None = None
    whatsapp_app_secret: SecretStr | None = None
    whatsapp_verify_token: SecretStr | None = None

    outbox_poll_seconds: int = 5
    outbox_max_attempts: int = 5
    reminder_after_minutes: int = 120
    sla_critica_minutes: int = 15
    sla_alta_minutes: int = 30
    sla_media_minutes: int = 120
    sla_baja_minutes: int = 1440

    session_max_age_seconds: int = 8 * 60 * 60

    @property
    def is_development(self) -> bool:
        return self.app_env in ("development", "test")


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
