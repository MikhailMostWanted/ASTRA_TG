from __future__ import annotations

from config.settings import Settings
from services.providers.base import BaseProvider
from services.providers.openai_compatible import OpenAICompatibleProvider


SUPPORTED_PROVIDER_NAMES = {
    "openai_compatible",
    "openai-compatible",
    "openai",
}


def create_provider(settings: Settings) -> BaseProvider | None:
    provider_name = _normalize(settings.llm_provider)
    if provider_name is None:
        return None
    if provider_name not in SUPPORTED_PROVIDER_NAMES:
        return None
    if not settings.llm_base_url or not settings.llm_api_key:
        return None
    if not settings.llm_model_fast or not settings.llm_model_deep:
        return None

    return OpenAICompatibleProvider(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        model_fast=settings.llm_model_fast,
        model_deep=settings.llm_model_deep,
        timeout_seconds=settings.llm_timeout,
    )


def is_supported_provider(provider_name: str | None) -> bool:
    normalized = _normalize(provider_name)
    return normalized in SUPPORTED_PROVIDER_NAMES


def _normalize(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip().lower()
    return cleaned or None
