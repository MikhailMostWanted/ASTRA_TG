import asyncio
from pathlib import Path

from astra_runtime.new_telegram import (
    DatabaseNewTelegramAuthSessionStore,
    NewTelegramAccount,
    NewTelegramAuthActionError,
    NewTelegramAuthClientError,
    NewTelegramAuthController,
    NewTelegramPasswordRequiredError,
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
        assert status.auth_session.state == "disabled"
        assert status.auth_session.auth_state == "unauthorized"

        stopped = await service.stop()
        assert stopped.lifecycle == "stopped"

    asyncio.run(run_assertions())


def test_new_telegram_runtime_reports_auth_degraded_state(tmp_path: Path) -> None:
    async def run_assertions() -> None:
        config = NewTelegramRuntimeConfig(
            enabled=True,
            api_id=1,
            api_hash="hash",
            phone="+79990001122",
            session_path=tmp_path / "new.session",
            device_name="test-device",
        )
        service = NewTelegramRuntimeService(
            config=config,
            auth_store=_MemoryAuthStore(default_auth_session_state(config)),
            client_factory=lambda _config: _FakeAuthClient(config),
        )

        status = await service.start()

        assert status.lifecycle == "running"
        assert status.active is True
        assert status.healthy is True
        assert status.ready is False
        assert status.degraded_reason == "Новый runtime ждёт авторизацию в Telegram."
        assert status.auth_session is not None
        assert status.auth_session.state == "idle"
        assert status.auth_session.reason_code == "login_required"

    asyncio.run(run_assertions())


def test_new_telegram_auth_session_store_persists_state(tmp_path: Path) -> None:
    async def run_assertions() -> None:
        settings = Settings(
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'astra.db'}",
            runtime_new_enabled=True,
            runtime_new_api_id=1,
            runtime_new_api_hash="hash",
            runtime_new_phone="+79990001122",
            runtime_new_session_path=str(tmp_path / "new.session"),
        )
        runtime = build_database_runtime(settings)
        await bootstrap_database(runtime)
        config = NewTelegramRuntimeConfig.from_settings(settings)
        store = DatabaseNewTelegramAuthSessionStore(runtime.session_factory)

        default_state = await store.load(config)
        assert default_state.session_state == "missing"
        assert default_state.auth_state == "unauthorized"
        assert default_state.state == "idle"

        await store.save(
            RuntimeAuthSessionState(
                state="authorized",
                auth_state="authorized",
                session_state="available",
                user_id=42,
                username="astra_user",
                phone_hint="+***1122",
                device_name="desktop",
                session_path=str(config.session_path),
                reason_code="authorized",
                reason="stored by test",
            )
        )
        loaded = await store.load(config)

        assert loaded.authorized is True
        assert loaded.user_id == 42
        assert loaded.username == "astra_user"
        assert loaded.phone_hint == "+***1122"
        assert loaded.reason == "stored by test"
        await runtime.dispose()

    asyncio.run(run_assertions())


def test_new_telegram_auth_controller_handles_login_password_logout_and_reset(
    tmp_path: Path,
) -> None:
    async def run_assertions() -> None:
        config = NewTelegramRuntimeConfig(
            enabled=True,
            api_id=1,
            api_hash="hash",
            phone="+79990001122",
            session_path=tmp_path / "new.session",
            device_name="test-device",
        )
        client = _FakeAuthClient(config, require_password=True)
        controller = NewTelegramAuthController(
            config=config,
            store=_MemoryAuthStore(default_auth_session_state(config)),
            client_factory=lambda _config: client,
        )

        requested = await controller.request_code()
        assert requested.kind == "code_requested"
        assert requested.status.state == "awaiting_code"
        assert requested.status.awaiting_code is True
        assert requested.status.code_requested_at is not None

        password_required = await controller.submit_code("24680")
        assert password_required.kind == "password_required"
        assert password_required.status.state == "awaiting_password"
        assert password_required.status.awaiting_password is True

        authorized = await controller.submit_password("secret-2fa")
        assert authorized.kind == "authorized"
        assert authorized.status.state == "authorized"
        assert authorized.status.authorized is True
        assert authorized.status.user_id == 42
        assert authorized.status.username == "astra_runtime"
        assert authorized.status.phone_hint == "+***1122"

        verified = await controller.status(force_refresh=True)
        assert verified.state == "authorized"
        assert verified.authorized is True

        logged_out = await controller.logout()
        assert logged_out.kind == "logged_out"
        assert logged_out.status.state == "idle"
        assert logged_out.status.session_state == "missing"

        reset = await controller.reset()
        assert reset.kind == "session_reset"
        assert reset.status.state == "idle"
        assert reset.status.session_state == "missing"

    asyncio.run(run_assertions())


def test_new_telegram_auth_controller_protects_invalid_repeats_and_keeps_retryable_errors(
    tmp_path: Path,
) -> None:
    async def run_assertions() -> None:
        config = NewTelegramRuntimeConfig(
            enabled=True,
            api_id=1,
            api_hash="hash",
            phone="+79990001122",
            session_path=tmp_path / "new.session",
            device_name="test-device",
        )
        client = _FakeAuthClient(config)
        store = _MemoryAuthStore(default_auth_session_state(config))
        controller = NewTelegramAuthController(
            config=config,
            store=store,
            client_factory=lambda _config: client,
        )

        await controller.request_code()

        try:
            await controller.request_code()
        except NewTelegramAuthActionError as error:
            assert error.code == "code_already_requested"
            assert error.status is not None
            assert error.status.state == "awaiting_code"
        else:  # pragma: no cover - defensive
            raise AssertionError("Expected repeated request_code to be rejected.")

        try:
            await controller.submit_code("00000")
        except NewTelegramAuthActionError as error:
            assert error.code == "phone_code_invalid"
            assert error.status is not None
            assert error.status.state == "awaiting_code"
            assert error.status.error_message is not None
        else:  # pragma: no cover - defensive
            raise AssertionError("Expected invalid code to keep awaiting_code state.")

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


class _FakeAuthClient:
    def __init__(
        self,
        config: NewTelegramRuntimeConfig,
        *,
        require_password: bool = False,
    ) -> None:
        self.config = config
        self.require_password = require_password
        self.password_pending = False
        self.authorized = False

    async def is_authorized(self) -> bool:
        return self.authorized

    async def request_login_code(self, phone: str) -> str:
        self.config.session_path.parent.mkdir(parents=True, exist_ok=True)
        self.config.session_path.write_text("pending", encoding="utf-8")
        return f"hash:{phone}"

    async def submit_code(
        self,
        *,
        phone: str,
        code: str,
        phone_code_hash: str,
    ) -> NewTelegramAccount:
        if code != "24680":
            raise NewTelegramAuthClientError(
                "phone_code_invalid",
                "Код Telegram не подошёл. Проверь код и попробуй ещё раз.",
            )
        if not phone_code_hash.startswith("hash:") or phone not in phone_code_hash:
            raise NewTelegramAuthClientError(
                "missing_code_context",
                "Контекст кода утрачен. Запроси код заново.",
            )
        if self.require_password:
            self.password_pending = True
            raise NewTelegramPasswordRequiredError()
        self.authorized = True
        self.config.session_path.write_text("authorized", encoding="utf-8")
        return NewTelegramAccount(
            user_id=42,
            username="astra_runtime",
            phone_hint="+***1122",
        )

    async def submit_password(self, password: str) -> NewTelegramAccount:
        if not self.password_pending:
            raise NewTelegramAuthClientError(
                "submit_password_failed",
                "Нечего подтверждать паролем 2FA.",
            )
        if password != "secret-2fa":
            raise NewTelegramAuthClientError(
                "password_invalid",
                "Пароль 2FA не подошёл. Попробуй ещё раз.",
            )
        self.password_pending = False
        self.authorized = True
        self.config.session_path.write_text("authorized", encoding="utf-8")
        return NewTelegramAccount(
            user_id=42,
            username="astra_runtime",
            phone_hint="+***1122",
        )

    async def current_account(self) -> NewTelegramAccount | None:
        if not self.authorized:
            return None
        return NewTelegramAccount(
            user_id=42,
            username="astra_runtime",
            phone_hint="+***1122",
        )

    async def logout(self) -> bool:
        self.authorized = False
        self.password_pending = False
        return True
