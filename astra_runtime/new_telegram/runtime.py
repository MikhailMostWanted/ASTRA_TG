from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from astra_runtime.new_telegram.auth import (
    NewTelegramAuthActionResult,
    NewTelegramAuthActionError,
    NewTelegramAuthController,
    NewTelegramAuthSessionStore,
)
from astra_runtime.new_telegram.config import NewTelegramRuntimeConfig
from astra_runtime.new_telegram.transport import (
    NewTelegramAuthClientFactory,
    build_new_telegram_auth_client,
)
from astra_runtime.status import (
    RuntimeAuthSessionState,
    RuntimeBackendStatus,
    RuntimeLifecycle,
    RuntimeUnavailableError,
)
from core.logging import get_logger, log_event, log_exception
from services.operational_state import OperationalStateService
from storage.repositories import SettingRepository


LOGGER = get_logger(__name__)


@dataclass(slots=True)
class NewTelegramRuntimeService:
    """Lifecycle shell for the future Telegram runtime.

    It is deliberately not a chat/message/send source yet. The service owns
    runtime startup, shutdown, auth/session visibility and readiness reasons so
    the rest of the product can observe it without switching product traffic.
    """

    config: NewTelegramRuntimeConfig
    auth_store: NewTelegramAuthSessionStore
    session_factory: async_sessionmaker[AsyncSession] | None = None
    client_factory: NewTelegramAuthClientFactory = build_new_telegram_auth_client
    _lifecycle: RuntimeLifecycle = "stopped"
    _started_at: datetime | None = None
    _stopped_at: datetime | None = None
    _last_error: str | None = None
    _auth_session: RuntimeAuthSessionState | None = None
    _auth_controller: NewTelegramAuthController = field(init=False, repr=False)
    _surface: "_NewTelegramRuntimeSurface" = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._auth_controller = NewTelegramAuthController(
            config=self.config,
            store=self.auth_store,
            client_factory=self.client_factory,
        )
        self._surface = _NewTelegramRuntimeSurface(self)

    @property
    def backend(self) -> str:
        return "new"

    @property
    def runtime(self) -> "_NewTelegramRuntimeSurface":
        return self._surface

    @property
    def route_available(self) -> bool:
        if not self.config.product_surfaces_enabled:
            return False
        status = self._build_status(self._auth_session)
        return status.ready and status.healthy

    async def bootstrap(self) -> RuntimeBackendStatus:
        return await self.start()

    async def start(self) -> RuntimeBackendStatus:
        if self._lifecycle == "running":
            return await self.status()

        self._lifecycle = "starting"
        self._last_error = None
        self._started_at = datetime.now(timezone.utc)
        self._stopped_at = None
        log_event(
            LOGGER,
            logging.INFO,
            "runtime.new_telegram.starting",
            "New Telegram runtime lifecycle стартует.",
            enabled=self.config.enabled,
            session_path=str(self.config.session_path),
        )

        try:
            self.config.session_path.parent.mkdir(parents=True, exist_ok=True)
            self._auth_session = await self._auth_controller.status(force_refresh=True)
            self._lifecycle = "running"
            status = self._build_status(self._auth_session)
            await self._record_status(status)
            log_event(
                LOGGER,
                logging.INFO,
                "runtime.new_telegram.started",
                "New Telegram runtime lifecycle запущен.",
                active=status.active,
                ready=status.ready,
                healthy=status.healthy,
                degraded_reason=status.degraded_reason,
            )
            return status
        except Exception as error:
            self._lifecycle = "failed"
            self._last_error = str(error)
            status = self._build_status(self._auth_session)
            await self._record_status(status)
            await self._record_error(str(error))
            log_exception(
                LOGGER,
                "runtime.new_telegram.start_failed",
                error,
                message="New Telegram runtime не смог стартовать.",
            )
            return status

    async def stop(self) -> RuntimeBackendStatus:
        if self._lifecycle == "stopped":
            return await self.status()

        self._lifecycle = "stopping"
        log_event(
            LOGGER,
            logging.INFO,
            "runtime.new_telegram.stopping",
            "New Telegram runtime lifecycle останавливается.",
        )
        self._stopped_at = datetime.now(timezone.utc)
        self._lifecycle = "stopped"
        status = self._build_status(self._auth_session)
        await self._record_status(status)
        log_event(
            LOGGER,
            logging.INFO,
            "runtime.new_telegram.stopped",
            "New Telegram runtime lifecycle остановлен.",
        )
        return status

    async def health(self) -> RuntimeBackendStatus:
        return await self.status()

    async def status(self) -> RuntimeBackendStatus:
        try:
            self._auth_session = await self._auth_controller.status(
                force_refresh=self._lifecycle == "running",
            )
        except Exception as error:
            self._last_error = str(error)
            self._lifecycle = "failed"
            await self._record_error(str(error))
        return self._build_status(self._auth_session)

    async def readiness(self) -> RuntimeBackendStatus:
        return await self.status()

    async def auth_status(self) -> RuntimeAuthSessionState:
        self._auth_session = await self._auth_controller.status(force_refresh=True)
        await self._record_status(self._build_status(self._auth_session))
        return self._auth_session

    async def request_code(self) -> NewTelegramAuthActionResult:
        try:
            result = await self._auth_controller.request_code()
        except NewTelegramAuthActionError as error:
            if error.status is not None:
                self._auth_session = error.status
                await self._record_status(self._build_status(self._auth_session))
            raise
        self._auth_session = result.status
        await self._record_status(self._build_status(self._auth_session))
        return result

    async def submit_code(self, code: str) -> NewTelegramAuthActionResult:
        try:
            result = await self._auth_controller.submit_code(code)
        except NewTelegramAuthActionError as error:
            if error.status is not None:
                self._auth_session = error.status
                await self._record_status(self._build_status(self._auth_session))
            raise
        self._auth_session = result.status
        await self._record_status(self._build_status(self._auth_session))
        return result

    async def submit_password(self, password: str) -> NewTelegramAuthActionResult:
        try:
            result = await self._auth_controller.submit_password(password)
        except NewTelegramAuthActionError as error:
            if error.status is not None:
                self._auth_session = error.status
                await self._record_status(self._build_status(self._auth_session))
            raise
        self._auth_session = result.status
        await self._record_status(self._build_status(self._auth_session))
        return result

    async def logout(self) -> NewTelegramAuthActionResult:
        try:
            result = await self._auth_controller.logout()
        except NewTelegramAuthActionError as error:
            if error.status is not None:
                self._auth_session = error.status
                await self._record_status(self._build_status(self._auth_session))
            raise
        self._auth_session = result.status
        await self._record_status(self._build_status(self._auth_session))
        return result

    async def reset(self) -> NewTelegramAuthActionResult:
        try:
            result = await self._auth_controller.reset()
        except NewTelegramAuthActionError as error:
            if error.status is not None:
                self._auth_session = error.status
                await self._record_status(self._build_status(self._auth_session))
            raise
        self._auth_session = result.status
        await self._record_status(self._build_status(self._auth_session))
        return result

    def _build_status(
        self,
        auth_session: RuntimeAuthSessionState | None,
    ) -> RuntimeBackendStatus:
        active = self.config.enabled and self._lifecycle == "running"
        healthy = self._lifecycle in {"running", "stopped"} and self._last_error is None
        auth_ready = bool(auth_session and auth_session.authorized)
        surface_routing_ready = False
        ready = active and healthy and auth_ready and surface_routing_ready

        unavailable_reason: str | None = None
        degraded_reason: str | None = None
        if self._last_error:
            unavailable_reason = self._last_error
        elif not self.config.enabled:
            unavailable_reason = "New Telegram runtime is disabled by RUNTIME_NEW_ENABLED."
        elif self._lifecycle != "running":
            unavailable_reason = "New Telegram runtime lifecycle is not running."
        elif not auth_ready:
            degraded_reason = (
                auth_session.reason
                if auth_session and auth_session.reason
                else "New Telegram runtime is not authorized yet."
            )
        elif not surface_routing_ready:
            degraded_reason = (
                "Auth/session слой готов, но product surfaces пока намеренно остаются на legacy."
            )

        return RuntimeBackendStatus(
            backend="new",
            name="new-telegram-runtime",
            registered=True,
            lifecycle=self._lifecycle,
            active=active,
            healthy=healthy,
            ready=ready,
            route_available=ready and self.config.product_surfaces_enabled,
            started_at=self._started_at,
            stopped_at=self._stopped_at,
            last_error=self._last_error,
            degraded_reason=degraded_reason,
            unavailable_reason=unavailable_reason,
            auth_session=auth_session,
            capabilities=(
                "lifecycle",
                "health",
                "readiness",
                "auth-session-status",
                "auth-request-code",
                "auth-submit-code",
                "auth-submit-password",
                "auth-logout",
                "auth-reset",
            ),
        )

    async def _record_status(self, status: RuntimeBackendStatus) -> None:
        if self.session_factory is None:
            return
        async with self.session_factory() as session:
            await OperationalStateService(SettingRepository(session)).record_runtime_status(
                backend="new",
                status=status.to_payload(),
            )
            await session.commit()

    async def _record_error(self, message: str) -> None:
        if self.session_factory is None:
            return
        async with self.session_factory() as session:
            await OperationalStateService(SettingRepository(session)).record_error(
                "new_runtime",
                message=message,
            )
            await session.commit()


@dataclass(slots=True)
class _NewTelegramRuntimeSurface:
    service: NewTelegramRuntimeService

    @property
    def chat_roster(self) -> "_NewTelegramRuntimeSurface":
        return self

    @property
    def message_history(self) -> "_NewTelegramRuntimeSurface":
        return self

    @property
    def reply_workspace(self) -> "_NewTelegramRuntimeSurface":
        return self

    @property
    def message_sender(self) -> "_NewTelegramRuntimeSurface":
        return self

    @property
    def autopilot(self) -> "_NewTelegramRuntimeSurface":
        return self

    async def list_chats(self, **_kwargs) -> dict[str, Any]:
        raise RuntimeUnavailableError(_surface_unavailable_message())

    async def get_chat_messages(self, *_args, **_kwargs) -> dict[str, Any]:
        raise RuntimeUnavailableError(_surface_unavailable_message())

    async def get_chat_workspace(self, *_args, **_kwargs) -> dict[str, Any]:
        raise RuntimeUnavailableError(_surface_unavailable_message())

    async def build_reply_result(self, *_args, **_kwargs):
        raise RuntimeUnavailableError(_surface_unavailable_message())

    async def get_reply_preview(self, *_args, **_kwargs) -> dict[str, Any]:
        raise RuntimeUnavailableError(_surface_unavailable_message())

    async def send_chat_message(self, *_args, **_kwargs) -> dict[str, Any]:
        raise RuntimeUnavailableError(_surface_unavailable_message())

    async def update_autopilot_global(self, **_kwargs) -> dict[str, Any]:
        raise RuntimeUnavailableError(_surface_unavailable_message())

    async def update_chat_autopilot(self, *_args, **_kwargs) -> dict[str, Any]:
        raise RuntimeUnavailableError(_surface_unavailable_message())


def _surface_unavailable_message() -> str:
    return (
        "New Telegram runtime product surfaces are not enabled yet. "
        "Legacy remains the effective backend."
    )
