import asyncio
from pathlib import Path

from astra_runtime.manager import LegacyRuntimeBackend, RuntimeManager, StaticRuntimeBackend
from astra_runtime.new_telegram import NewTelegramRuntimeConfig, NewTelegramRuntimeService
from astra_runtime.new_telegram.auth import default_auth_session_state
from astra_runtime.status import RuntimeAuthSessionState
from astra_runtime.switches import RuntimeSwitches


def test_runtime_manager_keeps_legacy_effective_when_new_runtime_is_not_route_ready(
    tmp_path: Path,
) -> None:
    async def run_assertions() -> None:
        config = NewTelegramRuntimeConfig(
            enabled=True,
            session_path=tmp_path / "new.session",
            device_name="test-device",
            product_surfaces_enabled=False,
        )
        new_runtime = NewTelegramRuntimeService(
            config=config,
            auth_store=_MemoryAuthStore(default_auth_session_state(config)),
        )
        manager = RuntimeManager(RuntimeSwitches(chat_roster="new"))
        manager.register_backend(LegacyRuntimeBackend(_FakeRuntime("legacy")))
        manager.register_backend(new_runtime)

        await manager.bootstrap()
        payload = await manager.surface("chatRoster").list_chats()
        status = await manager.status()
        route = status["routes"]["routes"]["chatRoster"]

        assert payload == {"runtime": "legacy"}
        assert route["requested"] == "new"
        assert route["effective"] == "legacy"
        assert route["targetAvailable"] is True
        assert route["targetReady"] is False
        assert route["reason"] == "Нужно задать RUNTIME_NEW_API_ID и RUNTIME_NEW_API_HASH."
        assert status["newRuntime"]["active"] is True
        assert status["newRuntime"]["ready"] is False

    asyncio.run(run_assertions())


def test_runtime_manager_can_route_to_registered_route_ready_target() -> None:
    async def run_assertions() -> None:
        manager = RuntimeManager(RuntimeSwitches(chat_roster="new"))
        manager.register_backend(LegacyRuntimeBackend(_FakeRuntime("legacy")))
        manager.register_backend(
            StaticRuntimeBackend(
                backend="new",
                runtime=_FakeRuntime("new"),
                name="test-target",
                route_available=True,
            )
        )

        payload = await manager.surface("chatRoster").list_chats()
        route = manager.describe_routes()["routes"]["chatRoster"]

        assert payload == {"runtime": "new"}
        assert manager.active_backend_for_surface("chatRoster") == "new"
        assert route["effective"] == "new"
        assert route["targetReady"] is True

    asyncio.run(run_assertions())


def test_runtime_manager_keeps_unimplemented_surfaces_on_legacy_even_when_chat_roster_is_ready() -> None:
    async def run_assertions() -> None:
        manager = RuntimeManager(
            RuntimeSwitches(
                chat_roster="new",
                send_path="new",
            )
        )
        manager.register_backend(LegacyRuntimeBackend(_FakeRuntime("legacy")))
        manager.register_backend(_SurfaceAwareBackend())

        assert manager.active_backend_for_surface("chatRoster") == "new"
        assert manager.active_backend_for_surface("sendPath") == "legacy"
        assert manager.describe_routes()["routes"]["sendPath"]["reason"] == (
            "New runtime пока не реализует этот surface; legacy remains effective."
        )

    asyncio.run(run_assertions())


def test_runtime_manager_routes_message_workspace_to_new_when_surface_is_ready() -> None:
    async def run_assertions() -> None:
        manager = RuntimeManager(RuntimeSwitches(message_workspace="new"))
        manager.register_backend(LegacyRuntimeBackend(_FakeRuntime("legacy")))
        manager.register_backend(_WorkspaceAwareBackend())

        route = manager.describe_routes()["routes"]["messageWorkspace"]

        assert manager.active_backend_for_surface("messageWorkspace") == "new"
        assert route["requested"] == "new"
        assert route["effective"] == "new"
        assert route["targetReady"] is True

    asyncio.run(run_assertions())


class _MemoryAuthStore:
    def __init__(self, state: RuntimeAuthSessionState) -> None:
        self.state = state

    async def load(self, _config: NewTelegramRuntimeConfig) -> RuntimeAuthSessionState:
        return self.state

    async def save(self, state: RuntimeAuthSessionState) -> None:
        self.state = state

    async def clear(self, config: NewTelegramRuntimeConfig) -> RuntimeAuthSessionState:
        self.state = default_auth_session_state(config)
        return self.state


class _FakeRuntime:
    def __init__(self, name: str) -> None:
        self.name = name

    @property
    def chat_roster(self):
        return self

    @property
    def message_history(self):
        return self

    @property
    def reply_workspace(self):
        return self

    @property
    def message_sender(self):
        return self

    @property
    def autopilot(self):
        return self

    async def list_chats(self, **_kwargs):
        return {"runtime": self.name}

    async def get_chat_messages(self, *_args, **_kwargs):
        return {"runtime": self.name, "surface": "messageWorkspace"}

    async def get_chat_workspace(self, *_args, **_kwargs):
        return {"runtime": self.name, "surface": "messageWorkspace"}


class _SurfaceAwareBackend:
    backend = "new"
    runtime = _FakeRuntime("new")
    route_available = True

    async def start(self):
        return await self.status()

    async def stop(self):
        return await self.status()

    async def health(self):
        return await self.status()

    async def status(self):
        from astra_runtime.status import RuntimeBackendStatus

        return RuntimeBackendStatus(
            backend="new",
            name="surface-aware-runtime",
            registered=True,
            lifecycle="running",
            active=True,
            healthy=True,
            ready=True,
            route_available=True,
            capabilities=("chat-roster",),
        )

    def route_available_for(self, surface: str) -> bool:
        return surface == "chatRoster"

    def route_reason_for(self, surface: str) -> str | None:
        if surface == "chatRoster":
            return None
        return "New runtime пока не реализует этот surface; legacy remains effective."


class _WorkspaceAwareBackend:
    backend = "new"
    runtime = _FakeRuntime("new")
    route_available = True

    async def start(self):
        return await self.status()

    async def stop(self):
        return await self.status()

    async def health(self):
        return await self.status()

    async def status(self):
        from astra_runtime.status import RuntimeBackendStatus

        return RuntimeBackendStatus(
            backend="new",
            name="workspace-aware-runtime",
            registered=True,
            lifecycle="running",
            active=True,
            healthy=True,
            ready=True,
            route_available=True,
            capabilities=("message-history",),
        )

    def route_available_for(self, surface: str) -> bool:
        return surface == "messageWorkspace"

    def route_reason_for(self, surface: str) -> str | None:
        if surface == "messageWorkspace":
            return None
        return "New runtime пока не реализует этот surface; legacy remains effective."
