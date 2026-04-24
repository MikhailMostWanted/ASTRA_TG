from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol, cast

from astra_runtime.contracts import TelegramRuntime
from astra_runtime.status import RuntimeBackendStatus, RuntimeRouteStatus, RuntimeUnavailableError
from astra_runtime.switches import RuntimeBackend, RuntimeSwitches


RuntimeSurfaceName = str

SURFACE_TO_SWITCH: dict[RuntimeSurfaceName, str] = {
    "chatRoster": "chat_roster",
    "messageWorkspace": "message_workspace",
    "replyGeneration": "reply_generation",
    "sendPath": "send_path",
    "autopilotControl": "autopilot_control",
}

SURFACE_TO_COMPONENT: dict[RuntimeSurfaceName, str] = {
    "chatRoster": "chat_roster",
    "messageWorkspace": "message_history",
    "replyGeneration": "reply_workspace",
    "sendPath": "message_sender",
    "autopilotControl": "autopilot",
}


class RuntimeBackendHandle(Protocol):
    backend: RuntimeBackend
    runtime: TelegramRuntime
    route_available: bool

    async def start(self) -> RuntimeBackendStatus: ...

    async def stop(self) -> RuntimeBackendStatus: ...

    async def health(self) -> RuntimeBackendStatus: ...

    async def status(self) -> RuntimeBackendStatus: ...

    def route_available_for(self, surface: RuntimeSurfaceName) -> bool: ...

    def route_reason_for(self, surface: RuntimeSurfaceName) -> str | None: ...


@dataclass(slots=True)
class LegacyRuntimeBackend:
    runtime: TelegramRuntime
    backend: RuntimeBackend = "legacy"
    route_available: bool = True

    async def start(self) -> RuntimeBackendStatus:
        return await self.status()

    async def stop(self) -> RuntimeBackendStatus:
        return await self.status()

    async def health(self) -> RuntimeBackendStatus:
        return await self.status()

    async def status(self) -> RuntimeBackendStatus:
        return RuntimeBackendStatus(
            backend="legacy",
            name="legacy-runtime",
            registered=True,
            lifecycle="running",
            active=True,
            healthy=True,
            ready=True,
            route_available=True,
            started_at=None,
            capabilities=(
                "chat-roster",
                "message-history",
                "reply-workspace",
                "manual-send",
                "autopilot-control",
            ),
        )

    def route_available_for(self, _surface: RuntimeSurfaceName) -> bool:
        return self.route_available

    def route_reason_for(self, _surface: RuntimeSurfaceName) -> str | None:
        return None


@dataclass(slots=True)
class StaticRuntimeBackend:
    backend: RuntimeBackend
    runtime: TelegramRuntime
    name: str
    route_available: bool = True

    async def start(self) -> RuntimeBackendStatus:
        return await self.status()

    async def stop(self) -> RuntimeBackendStatus:
        return await self.status()

    async def health(self) -> RuntimeBackendStatus:
        return await self.status()

    async def status(self) -> RuntimeBackendStatus:
        return RuntimeBackendStatus(
            backend=self.backend,
            name=self.name,
            registered=True,
            lifecycle="running",
            active=True,
            healthy=True,
            ready=True,
            route_available=self.route_available,
            capabilities=("external-runtime",),
        )

    def route_available_for(self, _surface: RuntimeSurfaceName) -> bool:
        return self.route_available

    def route_reason_for(self, _surface: RuntimeSurfaceName) -> str | None:
        if self.route_available:
            return None
        return "External runtime backend is not route-ready."


@dataclass(slots=True)
class RuntimeManager:
    switches: RuntimeSwitches
    _registry: dict[RuntimeBackend, RuntimeBackendHandle] = field(default_factory=dict)

    def register_backend(self, backend: RuntimeBackendHandle) -> None:
        self._registry[backend.backend] = backend

    def registered_backends(self) -> tuple[RuntimeBackend, ...]:
        return tuple(self._registry)

    def get_backend(self, backend: RuntimeBackend) -> RuntimeBackendHandle | None:
        return self._registry.get(backend)

    def active_backend_for_surface(self, surface: RuntimeSurfaceName) -> RuntimeBackend:
        return self._route_status(surface).effective

    def surface(self, surface: RuntimeSurfaceName):
        status = self._route_status(surface)
        if status.status != "available":
            raise RuntimeUnavailableError(
                status.reason or f"Runtime surface is unavailable: {surface}",
                code=status.reason_code,
                action_hint=status.action_hint,
            )
        backend = self._registry[status.effective]
        component_name = SURFACE_TO_COMPONENT[surface]
        return getattr(backend.runtime, component_name)

    async def bootstrap(self) -> None:
        backend = self._registry.get("new")
        if backend is not None:
            await backend.start()

    async def shutdown(self) -> None:
        backend = self._registry.get("new")
        if backend is not None:
            await backend.stop()

    async def start_backend(self, backend: RuntimeBackend) -> RuntimeBackendStatus:
        handle = self._require_backend(backend)
        return await handle.start()

    async def stop_backend(self, backend: RuntimeBackend) -> RuntimeBackendStatus:
        handle = self._require_backend(backend)
        return await handle.stop()

    async def health(self, backend: RuntimeBackend | None = None) -> dict[str, Any]:
        if backend is not None:
            handle = self._require_backend(backend)
            return (await handle.health()).to_payload()
        return {
            name: (await handle.health()).to_payload()
            for name, handle in self._registry.items()
        }

    async def status(self) -> dict[str, Any]:
        statuses = {
            name: (await handle.status()).to_payload()
            for name, handle in self._registry.items()
        }
        return {
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "defaultBackend": "legacy",
            "registeredBackends": list(self._registry),
            "routes": self.describe_routes(),
            "backends": statuses,
            "legacy": statuses.get("legacy"),
            "newRuntime": statuses.get("new"),
        }

    def describe_routes(self) -> dict[str, Any]:
        return {
            "targetRegistered": "new" in self._registry,
            "routes": {
                surface: self._route_status(surface).to_payload()
                for surface in SURFACE_TO_SWITCH
            },
        }

    def route_status(self, surface: RuntimeSurfaceName) -> RuntimeRouteStatus:
        return self._route_status(surface)

    def _route_status(self, surface: RuntimeSurfaceName) -> RuntimeRouteStatus:
        if surface not in SURFACE_TO_SWITCH:
            raise ValueError(f"Unknown runtime surface: {surface}")

        requested = cast(
            RuntimeBackend,
            getattr(self.switches, SURFACE_TO_SWITCH[surface]),
        )
        target = self._registry.get("new")
        target_available = target is not None
        target_ready = bool(target and target.route_available_for(surface))
        effective: RuntimeBackend = requested
        reason: str | None = None
        status = "available"
        reason_code: str | None = None
        action_hint: str | None = None

        if requested == "new":
            if target_ready:
                effective = "new"
            elif not target_available:
                status = "unavailable"
                reason_code = "not_registered"
                reason = "New runtime is not registered."
                action_hint = "Проверь запуск нового Telegram runtime."
            else:
                status = "unavailable"
                reason = (
                    target.route_reason_for(surface)
                    or "New runtime is registered but not route-ready."
                )
                reason_code, action_hint = _classify_unavailable_reason(reason)
        elif "legacy" not in self._registry:
            status = "unavailable"
            reason_code = "legacy_not_registered"
            reason = "Legacy runtime is not registered."
            action_hint = "Выбери доступный backend или зарегистрируй legacy runtime."

        return RuntimeRouteStatus(
            surface=surface,
            requested=requested,
            effective=effective,
            target_available=target_available,
            target_ready=target_ready,
            reason=reason,
            status=status,
            reason_code=reason_code,
            action_hint=action_hint,
        )

    def _require_backend(self, backend: RuntimeBackend) -> RuntimeBackendHandle:
        handle = self._registry.get(backend)
        if handle is None:
            raise ValueError(f"Runtime backend is not registered: {backend}")
        return handle


def _classify_unavailable_reason(reason: str | None) -> tuple[str, str]:
    lowered = (reason or "").casefold()
    if "api_id" in lowered or "api_hash" in lowered or "disabled" in lowered or "выключ" in lowered:
        return "not_ready", "Проверь настройки нового Telegram runtime."
    if "not authorized" in lowered or "authorized" in lowered or "авториз" in lowered or "войти" in lowered:
        return "not_authorized", "Войди в Telegram runtime."
    if "degraded" in lowered or "temporarily" in lowered or "временно" in lowered:
        return "degraded", "Повтори позже или обнови runtime."
    if "chat" in lowered or "чат" in lowered:
        return "chat_not_available", "Обнови чат или дождись чтения новым runtime."
    if "not route-ready" in lowered or "route-ready" in lowered:
        return "not_ready", "Проверь готовность surface нового runtime."
    return "unavailable", "Проверь runtime и повтори действие."
