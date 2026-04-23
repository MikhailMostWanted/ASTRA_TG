from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from astra_runtime.new_telegram.auth import (
    NewTelegramAuthActionError,
    NewTelegramAuthActionResult,
    NewTelegramAuthController,
    NewTelegramAuthSessionStore,
)
from astra_runtime.new_telegram.config import NewTelegramRuntimeConfig
from astra_runtime.new_telegram.history import NewTelegramMessageHistory
from astra_runtime.new_telegram.reply import NewTelegramReplyWorkspace
from astra_runtime.new_telegram.roster import NewTelegramChatRoster
from astra_runtime.new_telegram.transport import (
    NewTelegramAuthClientFactory,
    NewTelegramHistoryClientFactory,
    NewTelegramRosterClientFactory,
    build_new_telegram_auth_client,
    build_new_telegram_history_client,
    build_new_telegram_roster_client,
    close_managed_new_telegram_clients,
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
CHAT_ROSTER_SURFACE = "chatRoster"
MESSAGE_WORKSPACE_SURFACE = "messageWorkspace"
REPLY_GENERATION_SURFACE = "replyGeneration"


@dataclass(slots=True)
class NewTelegramRuntimeService:
    """Managed new Telegram runtime with auth/session and chat roster routing."""

    config: NewTelegramRuntimeConfig
    auth_store: NewTelegramAuthSessionStore
    session_factory: async_sessionmaker[AsyncSession] | None = None
    client_factory: NewTelegramAuthClientFactory = build_new_telegram_auth_client
    roster_client_factory: NewTelegramRosterClientFactory = build_new_telegram_roster_client
    history_client_factory: NewTelegramHistoryClientFactory = build_new_telegram_history_client
    settings: Any | None = None
    _lifecycle: RuntimeLifecycle = "stopped"
    _started_at: datetime | None = None
    _stopped_at: datetime | None = None
    _last_error: str | None = None
    _auth_session: RuntimeAuthSessionState | None = None
    _auth_controller: NewTelegramAuthController = field(init=False, repr=False)
    _surface: "_NewTelegramRuntimeSurface" = field(init=False, repr=False)
    _chat_roster: NewTelegramChatRoster = field(init=False, repr=False)
    _message_history: NewTelegramMessageHistory = field(init=False, repr=False)
    _reply_workspace: NewTelegramReplyWorkspace = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._auth_controller = NewTelegramAuthController(
            config=self.config,
            store=self.auth_store,
            client_factory=self.client_factory,
        )
        self._chat_roster = NewTelegramChatRoster(
            config=self.config,
            session_factory=self.session_factory,
            client_factory=self.roster_client_factory,
        )
        self._message_history = NewTelegramMessageHistory(
            config=self.config,
            session_factory=self.session_factory,
            client_factory=self.history_client_factory,
        )
        self._reply_workspace = NewTelegramReplyWorkspace(
            settings=self.settings,
            session_factory=self.session_factory,
            history=self._message_history,
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
        return self.route_available_for(CHAT_ROSTER_SURFACE)

    def route_available_for(self, surface: str) -> bool:
        if self._surface_prerequisites_reason(self._auth_session) is not None:
            return False
        if surface == CHAT_ROSTER_SURFACE:
            return self._chat_roster.route_ready()
        if surface == MESSAGE_WORKSPACE_SURFACE:
            return self._message_history.route_ready()
        if surface == REPLY_GENERATION_SURFACE:
            return self._reply_workspace.route_ready()
        return False

    def route_reason_for(self, surface: str) -> str | None:
        prerequisite_reason = self._surface_prerequisites_reason(self._auth_session)
        if prerequisite_reason is not None:
            return prerequisite_reason
        if surface == CHAT_ROSTER_SURFACE:
            return self._chat_roster.route_reason()
        if surface == MESSAGE_WORKSPACE_SURFACE:
            return self._message_history.route_reason()
        if surface == REPLY_GENERATION_SURFACE:
            return self._reply_workspace.route_reason()
        return (
            "New Telegram runtime пока не реализует этот surface; "
            "legacy remains effective."
        )

    def chat_roster_status_payload(self) -> dict[str, Any]:
        return self._chat_roster.status_payload()

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
        await close_managed_new_telegram_clients()
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
        await close_managed_new_telegram_clients()
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
        await close_managed_new_telegram_clients()
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
        surface_routing_ready = self.route_available_for(CHAT_ROSTER_SURFACE)
        ready = active and healthy and auth_ready and surface_routing_ready

        unavailable_reason: str | None = None
        degraded_reason: str | None = None
        if self._last_error:
            unavailable_reason = self._last_error
        elif not self.config.enabled:
            unavailable_reason = "New Telegram runtime is disabled by RUNTIME_NEW_ENABLED."
        elif self._lifecycle != "running":
            unavailable_reason = "New Telegram runtime lifecycle is not running."
        else:
            route_reason = self.route_reason_for(CHAT_ROSTER_SURFACE)
            if route_reason is not None:
                degraded_reason = route_reason

        return RuntimeBackendStatus(
            backend="new",
            name="new-telegram-runtime",
            registered=True,
            lifecycle=self._lifecycle,
            active=active,
            healthy=healthy,
            ready=ready,
            route_available=surface_routing_ready,
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
                "chat-roster",
                "message-history",
                "reply-workspace",
            ),
        )

    def _surface_prerequisites_reason(
        self,
        auth_session: RuntimeAuthSessionState | None,
    ) -> str | None:
        if self._last_error:
            return self._last_error
        if not self.config.enabled:
            return "New Telegram runtime is disabled by RUNTIME_NEW_ENABLED."
        if self._lifecycle != "running":
            return "New Telegram runtime lifecycle is not running."
        if not auth_session or not auth_session.authorized:
            if auth_session and auth_session.reason:
                return auth_session.reason
            return "New Telegram runtime is not authorized yet."
        if not self.config.product_surfaces_enabled:
            return (
                "Auth/session слой готов, но product surfaces нового runtime выключены "
                "через RUNTIME_NEW_PRODUCT_SURFACES_ENABLED."
            )
        return None

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

    async def list_chats(self, **kwargs) -> dict[str, Any]:
        self._ensure_surface_available(CHAT_ROSTER_SURFACE)
        return await self.service._chat_roster.list_chats(**kwargs)

    async def get_chat_messages(self, *_args, **_kwargs) -> dict[str, Any]:
        self._ensure_surface_available(MESSAGE_WORKSPACE_SURFACE)
        return await self.service._message_history.get_chat_messages(*_args, **_kwargs)

    async def get_chat_workspace(self, *_args, **_kwargs) -> dict[str, Any]:
        self._ensure_surface_available(MESSAGE_WORKSPACE_SURFACE)
        payload = await self.service._message_history.get_chat_workspace(*_args, **_kwargs)
        if self.service.route_available_for(REPLY_GENERATION_SURFACE):
            payload = await self.service._reply_workspace.enrich_workspace_payload(payload)
        return payload

    async def build_reply_result(self, *_args, **_kwargs):
        self._ensure_surface_available(REPLY_GENERATION_SURFACE)
        return await self.service._reply_workspace.build_reply_result(*_args, **_kwargs)

    async def get_reply_preview(self, *_args, **_kwargs) -> dict[str, Any]:
        self._ensure_surface_available(REPLY_GENERATION_SURFACE)
        return await self.service._reply_workspace.get_reply_preview(*_args, **_kwargs)

    async def send_chat_message(self, *_args, **_kwargs) -> dict[str, Any]:
        raise RuntimeUnavailableError(self._surface_unavailable_message("sendPath"))

    async def update_autopilot_global(self, **_kwargs) -> dict[str, Any]:
        raise RuntimeUnavailableError(self._surface_unavailable_message("autopilotControl"))

    async def update_chat_autopilot(self, *_args, **_kwargs) -> dict[str, Any]:
        raise RuntimeUnavailableError(self._surface_unavailable_message("autopilotControl"))

    def _ensure_surface_available(self, surface: str) -> None:
        if self.service.route_available_for(surface):
            return
        raise RuntimeUnavailableError(
            self.service.route_reason_for(surface)
            or self._surface_unavailable_message(surface)
        )

    def _surface_unavailable_message(self, surface: str) -> str:
        labels = {
            "chatRoster": "chat roster",
            "messageWorkspace": "message workspace",
            "replyGeneration": "reply generation",
            "sendPath": "send path",
            "autopilotControl": "autopilot",
        }
        return (
            f"New Telegram runtime {labels.get(surface, surface)} surface is not enabled yet. "
            "Legacy remains the effective backend."
        )
