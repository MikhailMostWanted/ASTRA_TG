import asyncio
from pathlib import Path

from astra_runtime.new_telegram import (
    DatabaseNewTelegramAuthSessionStore,
    NewTelegramRuntimeConfig,
    NewTelegramRuntimeService,
)
from astra_runtime.new_telegram.auth import default_auth_session_state
from astra_runtime.status import RuntimeAuthSessionState
from config.settings import Settings
from storage.database import bootstrap_database, build_database_runtime


def test_new_telegram_runtime_reports_disabled_state(tmp_path: Path) -> None:
    async def run_assertions() -> None:
        config = NewTelegramRuntimeConfig(
            enabled=False,
            session_path=tmp_path / "new.session",
            device_name="test-device",
        )
        service = NewTelegramRuntimeService(
            config=config,
            auth_store=_MemoryAuthStore(default_auth_session_state(config)),
        )

        status = await service.start()

        assert status.lifecycle == "running"
        assert status.active is False
        assert status.healthy is True
        assert status.ready is False
        assert status.route_available is False
        assert status.unavailable_reason == "New Telegram runtime is disabled by RUNTIME_NEW_ENABLED."
        assert status.auth_session is not None
        assert status.auth_session.auth_state == "unauthorized"

        stopped = await service.stop()
        assert stopped.lifecycle == "stopped"

    asyncio.run(run_assertions())


def test_new_telegram_runtime_reports_auth_degraded_state(tmp_path: Path) -> None:
    async def run_assertions() -> None:
        config = NewTelegramRuntimeConfig(
            enabled=True,
            session_path=tmp_path / "new.session",
            device_name="test-device",
        )
        service = NewTelegramRuntimeService(
            config=config,
            auth_store=_MemoryAuthStore(
                RuntimeAuthSessionState(
                    auth_state="unauthorized",
                    session_state="missing",
                    device_name="test-device",
                    session_path=str(config.session_path),
                    reason="auth required",
                )
            ),
        )

        status = await service.start()

        assert status.lifecycle == "running"
        assert status.active is True
        assert status.healthy is True
        assert status.ready is False
        assert status.degraded_reason == "auth required"

    asyncio.run(run_assertions())


def test_new_telegram_auth_session_store_persists_state(tmp_path: Path) -> None:
    async def run_assertions() -> None:
        settings = Settings(
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'astra.db'}",
            runtime_new_session_path=str(tmp_path / "new.session"),
        )
        runtime = build_database_runtime(settings)
        await bootstrap_database(runtime)
        config = NewTelegramRuntimeConfig.from_settings(settings)
        store = DatabaseNewTelegramAuthSessionStore(runtime.session_factory)

        default_state = await store.load(config)
        assert default_state.session_state == "missing"
        assert default_state.auth_state == "unauthorized"

        await store.save(
            RuntimeAuthSessionState(
                auth_state="authorized",
                session_state="available",
                user_id=42,
                username="astra_user",
                device_name="desktop",
                session_path=str(config.session_path),
                reason="stored by test",
            )
        )
        loaded = await store.load(config)

        assert loaded.authorized is True
        assert loaded.user_id == 42
        assert loaded.username == "astra_user"
        assert loaded.reason == "stored by test"
        await runtime.dispose()

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
