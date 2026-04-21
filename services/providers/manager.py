from __future__ import annotations

from dataclasses import dataclass

from config.settings import Settings
from core.logging import get_logger, log_event
from services.operational_state import OperationalStateService
from services.providers.base import BaseProvider
from services.providers.errors import ProviderError
from services.providers.factory import create_provider, is_supported_provider
from services.providers.models import (
    DigestImproveRequest,
    ProviderExecutionResult,
    ProviderStatus,
    RewriteReplyRequest,
)
from storage.repositories import SettingRepository


LOGGER = get_logger(__name__)


@dataclass(slots=True)
class ProviderManager:
    settings: Settings
    provider: BaseProvider | None = None
    setting_repository: SettingRepository | None = None

    @classmethod
    def from_settings(
        cls,
        settings: Settings,
        *,
        setting_repository: SettingRepository | None = None,
    ) -> "ProviderManager":
        return cls(
            settings=settings,
            provider=create_provider(settings),
            setting_repository=setting_repository,
        )

    async def get_status(self, *, check_api: bool = False) -> ProviderStatus:
        enabled = bool(self.settings.llm_enabled)
        provider_name = _normalize(self.settings.llm_provider)
        model_fast = _normalize(self.settings.llm_model_fast)
        model_deep = _normalize(self.settings.llm_model_deep)

        configured, reason = self._configuration_state()
        available = False
        if configured and self.provider is not None:
            if check_api:
                try:
                    available, health_reason = await self.provider.check_health()
                    reason = health_reason
                except ProviderError as error:
                    available = False
                    reason = str(error)
                    await self._record_provider_error(reason, stage="healthcheck")
                except Exception as error:  # pragma: no cover - страховка на непредвиденный transport error
                    available = False
                    reason = f"API-проверка завершилась ошибкой: {error}"
                    await self._record_provider_error(reason, stage="healthcheck")
            else:
                available = True
                reason = "Провайдер сконфигурирован, deterministic fallback остаётся активным."

        reply_refine_enabled = bool(self.settings.llm_refine_reply_enabled)
        digest_refine_enabled = bool(self.settings.llm_refine_digest_enabled)
        reply_refine_available = enabled and configured and available and reply_refine_enabled
        digest_refine_available = enabled and configured and available and digest_refine_enabled

        return ProviderStatus(
            enabled=enabled,
            configured=configured,
            provider_name=provider_name,
            model_fast=model_fast,
            model_deep=model_deep,
            timeout_seconds=float(self.settings.llm_timeout),
            available=available,
            reason=reason,
            reply_refine_enabled=reply_refine_enabled,
            digest_refine_enabled=digest_refine_enabled,
            reply_refine_available=reply_refine_available,
            digest_refine_available=digest_refine_available,
            api_checked=check_api,
        )

    async def rewrite_reply(
        self,
        request: RewriteReplyRequest,
    ) -> ProviderExecutionResult:
        status = await self.get_status()
        if not self.settings.llm_refine_reply_enabled:
            return ProviderExecutionResult.failure(
                "LLM refine для reply выключен.",
                provider_name=status.provider_name,
            )
        if not status.enabled or not status.configured or self.provider is None:
            return ProviderExecutionResult.failure(
                status.reason,
                provider_name=status.provider_name,
            )
        try:
            candidate = await self.provider.rewrite_reply(request)
        except Exception as error:
            reason = _format_runtime_error(error)
            await self._record_provider_error(reason, stage="rewrite_reply")
            log_event(
                LOGGER,
                30,
                "provider.reply.failure",
                "Provider rewrite_reply завершился с fallback.",
                provider_name=status.provider_name,
                reason=reason,
            )
            return ProviderExecutionResult.failure(
                reason,
                provider_name=status.provider_name,
            )
        return ProviderExecutionResult.success(
            candidate,
            provider_name=status.provider_name,
        )

    async def improve_digest(
        self,
        request: DigestImproveRequest,
    ) -> ProviderExecutionResult:
        status = await self.get_status()
        if not self.settings.llm_refine_digest_enabled:
            return ProviderExecutionResult.failure(
                "LLM refine для digest выключен.",
                provider_name=status.provider_name,
            )
        if not status.enabled or not status.configured or self.provider is None:
            return ProviderExecutionResult.failure(
                status.reason,
                provider_name=status.provider_name,
            )
        try:
            candidate = await self.provider.improve_digest(request)
        except Exception as error:
            reason = _format_runtime_error(error)
            await self._record_provider_error(reason, stage="improve_digest")
            log_event(
                LOGGER,
                30,
                "provider.digest.failure",
                "Provider improve_digest завершился с fallback.",
                provider_name=status.provider_name,
                reason=reason,
            )
            return ProviderExecutionResult.failure(
                reason,
                provider_name=status.provider_name,
            )
        return ProviderExecutionResult.success(
            candidate,
            provider_name=status.provider_name,
        )

    def _configuration_state(self) -> tuple[bool, str]:
        if not self.settings.llm_enabled:
            return False, "Provider layer выключен через LLM_ENABLED=false."
        provider_name = _normalize(self.settings.llm_provider)
        if provider_name is None:
            return False, "LLM_PROVIDER не задан."
        if not is_supported_provider(provider_name):
            return False, f"Провайдер {provider_name} пока не поддержан."
        if not _normalize(self.settings.llm_base_url):
            return False, "LLM_BASE_URL не задан."
        if not _normalize(self.settings.llm_api_key):
            return False, "LLM_API_KEY не задан."
        if not _normalize(self.settings.llm_model_fast):
            return False, "LLM_MODEL_FAST не задан."
        if not _normalize(self.settings.llm_model_deep):
            return False, "LLM_MODEL_DEEP не задан."
        if self.provider is None:
            return False, "Provider factory не смог собрать runtime-клиент."
        return True, "Провайдер сконфигурирован."

    async def _record_provider_error(self, message: str, *, stage: str) -> None:
        if self.setting_repository is None:
            return
        await OperationalStateService(self.setting_repository).record_error(
            "provider",
            message=message,
            details={"stage": stage},
        )


def _normalize(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _format_runtime_error(error: Exception) -> str:
    if isinstance(error, ProviderError):
        return str(error)
    return f"Provider runtime завершился ошибкой: {error}"
