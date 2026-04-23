from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol, cast

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from astra_runtime.new_telegram.config import NewTelegramRuntimeConfig
from astra_runtime.new_telegram.transport import (
    NewTelegramAccount,
    NewTelegramAuthClientError,
    NewTelegramAuthClientProtocol,
    NewTelegramPasswordRequiredError,
    build_new_telegram_auth_client,
    delete_session_file,
    telethon_is_available,
)
from astra_runtime.status import (
    RuntimeAuthMachineState,
    RuntimeAuthSessionState,
    RuntimeAuthState,
    RuntimeSessionState,
)
from storage.repositories import SettingRepository


NEW_TELEGRAM_AUTH_SESSION_KEY = "runtime.new_telegram.auth_session"
AUTH_STATUS_REFRESH_TTL = timedelta(seconds=15)


class _Unset:
    pass


_UNSET = _Unset()


class NewTelegramAuthSessionStore(Protocol):
    async def load(self, config: NewTelegramRuntimeConfig) -> RuntimeAuthSessionState: ...

    async def save(self, state: RuntimeAuthSessionState) -> None: ...

    async def clear(self, config: NewTelegramRuntimeConfig) -> RuntimeAuthSessionState: ...


NewTelegramAuthClientFactory = Callable[
    [NewTelegramRuntimeConfig],
    NewTelegramAuthClientProtocol,
]


class NewTelegramAuthActionError(ValueError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        status: RuntimeAuthSessionState | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


@dataclass(frozen=True, slots=True)
class NewTelegramAuthActionResult:
    kind: str
    message: str
    status: RuntimeAuthSessionState

    def to_payload(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "message": self.message,
            "status": self.status.to_payload(),
        }


class DatabaseNewTelegramAuthSessionStore:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def load(self, config: NewTelegramRuntimeConfig) -> RuntimeAuthSessionState:
        async with self._session_factory() as session:
            value = await SettingRepository(session).get_value(NEW_TELEGRAM_AUTH_SESSION_KEY)
        return build_auth_session_state(value, config=config)

    async def save(self, state: RuntimeAuthSessionState) -> None:
        async with self._session_factory() as session:
            await SettingRepository(session).set_value(
                key=NEW_TELEGRAM_AUTH_SESSION_KEY,
                value_json=_state_to_storage_payload(state),
                value_text=None,
            )
            await session.commit()

    async def clear(self, config: NewTelegramRuntimeConfig) -> RuntimeAuthSessionState:
        state = default_auth_session_state(config)
        await self.save(state)
        return state


@dataclass(slots=True)
class NewTelegramAuthController:
    config: NewTelegramRuntimeConfig
    store: NewTelegramAuthSessionStore
    client_factory: NewTelegramAuthClientFactory = build_new_telegram_auth_client
    _lock: asyncio.Lock = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._lock = asyncio.Lock()

    async def status(self, *, force_refresh: bool = False) -> RuntimeAuthSessionState:
        async with self._lock:
            current = await self.store.load(self.config)
            refreshed = await self._refresh_state(current, force_refresh=force_refresh)
            if refreshed != current:
                await self.store.save(refreshed)
            return refreshed

    async def request_code(self) -> NewTelegramAuthActionResult:
        async with self._lock:
            current = await self.store.load(self.config)
            self._ensure_code_request_allowed(current)

            phone = self._require_phone(current)
            now = _now_utc()
            request_state = _set_state(
                current,
                state="code_requested",
                session_state=_resolve_session_state(self.config),
                phone_hint=_mask_phone(phone),
                pending_phone=phone,
                reason_code="requesting_code",
                reason="Запрашиваю код Telegram для нового runtime.",
                error_code=None,
                error_message=None,
                error_at=None,
                updated_at=now,
                state_changed_at=now,
            )
            await self.store.save(request_state)

            try:
                phone_code_hash = await self.client_factory(self.config).request_login_code(phone)
            except NewTelegramAuthClientError as error:
                failed = _set_state(
                    request_state,
                    state="error",
                    session_state=_resolve_session_state(self.config),
                    reason_code=error.code,
                    reason=error.message,
                    error_code=error.code,
                    error_message=error.message,
                    error_at=_now_utc(),
                    updated_at=_now_utc(),
                    state_changed_at=_now_utc(),
                )
                await self.store.save(failed)
                raise NewTelegramAuthActionError(error.code, error.message, status=failed) from error

            requested_at = _now_utc()
            awaiting = _set_state(
                request_state,
                state="awaiting_code",
                session_state=_resolve_session_state(self.config),
                phone_code_hash=phone_code_hash,
                code_requested_at=requested_at,
                reason_code="awaiting_code",
                reason="Код отправлен. Введи его в Desktop или CLI.",
                updated_at=requested_at,
                state_changed_at=requested_at,
            )
            await self.store.save(awaiting)
            return NewTelegramAuthActionResult(
                kind="code_requested",
                message="Код Telegram отправлен. Теперь введи его для нового runtime.",
                status=awaiting,
            )

    async def submit_code(self, code: str) -> NewTelegramAuthActionResult:
        normalized_code = "".join(ch for ch in code.strip() if not ch.isspace())
        if not normalized_code:
            current = await self.status()
            raise NewTelegramAuthActionError(
                "code_required",
                "Код Telegram пустой. Сначала запроси код, затем введи его.",
                status=current,
            )

        async with self._lock:
            current = await self.store.load(self.config)
            self._ensure_code_submission_allowed(current)

            phone = self._require_phone(current)
            phone_code_hash = current.phone_code_hash
            assert phone_code_hash is not None

            try:
                account = await self.client_factory(self.config).submit_code(
                    phone=phone,
                    code=normalized_code,
                    phone_code_hash=phone_code_hash,
                )
            except NewTelegramPasswordRequiredError:
                waiting_password = _set_state(
                    current,
                    state="awaiting_password",
                    session_state=_resolve_session_state(self.config, fallback="available"),
                    reason_code="awaiting_password",
                    reason="Telegram требует пароль 2FA.",
                    error_code=None,
                    error_message=None,
                    error_at=None,
                    updated_at=_now_utc(),
                    state_changed_at=_now_utc(),
                )
                await self.store.save(waiting_password)
                return NewTelegramAuthActionResult(
                    kind="password_required",
                    message="Telegram запросил пароль 2FA. Введи пароль для завершения входа.",
                    status=waiting_password,
                )
            except NewTelegramAuthClientError as error:
                failed = self._handle_submit_code_error(current, error)
                await self.store.save(failed)
                raise NewTelegramAuthActionError(error.code, error.message, status=failed) from error

            authorized = _build_authorized_state(
                current,
                account=account,
                config=self.config,
                now=_now_utc(),
            )
            await self.store.save(authorized)
            return NewTelegramAuthActionResult(
                kind="authorized",
                message="Новый runtime успешно авторизован в Telegram.",
                status=authorized,
            )

    async def submit_password(self, password: str) -> NewTelegramAuthActionResult:
        normalized_password = password.strip()
        if not normalized_password:
            current = await self.status()
            raise NewTelegramAuthActionError(
                "password_required",
                "Пароль 2FA пустой. Введи пароль, который запросил Telegram.",
                status=current,
            )

        async with self._lock:
            current = await self.store.load(self.config)
            self._ensure_password_submission_allowed(current)

            try:
                account = await self.client_factory(self.config).submit_password(normalized_password)
            except NewTelegramAuthClientError as error:
                if error.code == "password_invalid":
                    failed = _set_state(
                        current,
                        state="awaiting_password",
                        session_state=_resolve_session_state(self.config, fallback="available"),
                        reason_code="awaiting_password",
                        reason="Telegram ждёт корректный пароль 2FA.",
                        error_code=error.code,
                        error_message=error.message,
                        error_at=_now_utc(),
                        updated_at=_now_utc(),
                    )
                else:
                    failed = _set_state(
                        current,
                        state="error",
                        session_state=_resolve_session_state(self.config),
                        reason_code=error.code,
                        reason=error.message,
                        error_code=error.code,
                        error_message=error.message,
                        error_at=_now_utc(),
                        updated_at=_now_utc(),
                        state_changed_at=_now_utc(),
                    )
                await self.store.save(failed)
                raise NewTelegramAuthActionError(error.code, error.message, status=failed) from error

            authorized = _build_authorized_state(
                current,
                account=account,
                config=self.config,
                now=_now_utc(),
            )
            await self.store.save(authorized)
            return NewTelegramAuthActionResult(
                kind="authorized",
                message="Пароль 2FA подтверждён. Новый runtime авторизован.",
                status=authorized,
            )

    async def logout(self) -> NewTelegramAuthActionResult:
        async with self._lock:
            current = await self.store.load(self.config)
            started = _set_state(
                current,
                state="logout_in_progress",
                session_state=_resolve_session_state(self.config),
                reason_code="logout_in_progress",
                reason="Завершаю сессию нового runtime.",
                error_code=None,
                error_message=None,
                error_at=None,
                logout_started_at=_now_utc(),
                updated_at=_now_utc(),
                state_changed_at=_now_utc(),
            )
            await self.store.save(started)

            warning: str | None = None
            if self.config.api_credentials_configured and telethon_is_available() and self.config.session_path.exists():
                try:
                    await self.client_factory(self.config).logout()
                except NewTelegramAuthClientError as error:
                    warning = error.message

            delete_session_file(self.config.session_path)
            cleared = default_auth_session_state(self.config)
            cleared = _set_state(
                cleared,
                state="idle" if self.config.enabled else "disabled",
                session_state="missing",
                reason_code="logged_out",
                reason=warning or "Сессия нового runtime очищена.",
                updated_at=_now_utc(),
                state_changed_at=_now_utc(),
            )
            await self.store.save(cleared)
            return NewTelegramAuthActionResult(
                kind="logged_out",
                message=warning or "Новый runtime вышел из Telegram и локальная session очищена.",
                status=cleared,
            )

    async def reset(self) -> NewTelegramAuthActionResult:
        async with self._lock:
            delete_session_file(self.config.session_path)
            cleared = default_auth_session_state(self.config)
            cleared = _set_state(
                cleared,
                state="idle" if self.config.enabled else "disabled",
                session_state="missing",
                reason_code="session_reset",
                reason="Состояние auth/session нового runtime сброшено.",
                updated_at=_now_utc(),
                state_changed_at=_now_utc(),
            )
            await self.store.save(cleared)
            return NewTelegramAuthActionResult(
                kind="session_reset",
                message="Auth/session состояние нового runtime сброшено.",
                status=cleared,
            )

    async def _refresh_state(
        self,
        current: RuntimeAuthSessionState,
        *,
        force_refresh: bool,
    ) -> RuntimeAuthSessionState:
        if not self.config.enabled:
            return _build_disabled_state(self.config, template=current)

        if current.state in {"awaiting_code", "awaiting_password", "logout_in_progress", "code_requested"}:
            return _set_state(
                current,
                session_state=_resolve_session_state(self.config),
                updated_at=current.updated_at or _now_utc(),
            )

        session_exists = self.config.session_path.exists()
        if current.state == "error" and not session_exists:
            return current

        if not self.config.api_credentials_configured:
            return _set_state(
                current,
                state="idle",
                session_state=_resolve_session_state(self.config),
                reason_code="api_credentials_missing",
                reason="Нужно задать RUNTIME_NEW_API_ID и RUNTIME_NEW_API_HASH.",
                updated_at=current.updated_at or _now_utc(),
            )

        if not telethon_is_available():
            return _set_state(
                current,
                state="idle",
                session_state=_resolve_session_state(self.config),
                reason_code="telethon_unavailable",
                reason="Telethon не установлен. Установи optional dependency: pip install -e '.[fullaccess]'.",
                updated_at=current.updated_at or _now_utc(),
            )

        if not session_exists:
            return _set_state(
                current,
                state="idle",
                session_state="missing",
                reason_code="login_required",
                reason="Новый runtime ждёт авторизацию в Telegram.",
                user_id=None,
                username=None,
                phone_hint=current.phone_hint or _mask_phone(self.config.phone),
                last_checked_at=_now_utc(),
                updated_at=_now_utc(),
            )

        if not force_refresh and not _is_status_refresh_stale(current.last_checked_at):
            return current

        try:
            client = self.client_factory(self.config)
            if not await client.is_authorized():
                return _set_state(
                    current,
                    state="idle",
                    session_state="available",
                    user_id=None,
                    username=None,
                    phone_hint=current.phone_hint or _mask_phone(self.config.phone),
                    reason_code="login_required",
                    reason="Локальная session найдена, но новый runtime не авторизован.",
                    last_checked_at=_now_utc(),
                    updated_at=_now_utc(),
                )
            account = await client.current_account()
        except NewTelegramAuthClientError as error:
            return _set_state(
                current,
                state="error",
                session_state="invalid",
                reason_code=error.code,
                reason=error.message,
                error_code=error.code,
                error_message=error.message,
                error_at=_now_utc(),
                last_checked_at=_now_utc(),
                updated_at=_now_utc(),
                state_changed_at=_now_utc(),
            )
        except Exception as error:
            message = f"Не удалось проверить авторизацию нового runtime: {error}"
            return _set_state(
                current,
                state="error",
                session_state="invalid",
                reason_code="authorization_check_failed",
                reason=message,
                error_code="authorization_check_failed",
                error_message=message,
                error_at=_now_utc(),
                last_checked_at=_now_utc(),
                updated_at=_now_utc(),
                state_changed_at=_now_utc(),
            )

        return _build_authorized_state(
            current,
            account=account,
            config=self.config,
            now=_now_utc(),
        )

    def _ensure_code_request_allowed(self, current: RuntimeAuthSessionState) -> None:
        if not self.config.enabled:
            raise NewTelegramAuthActionError(
                "runtime_disabled",
                "Новый runtime выключен. Включи RUNTIME_NEW_ENABLED=true.",
                status=_build_disabled_state(self.config, template=current),
            )
        if current.state == "authorized":
            raise NewTelegramAuthActionError(
                "already_authorized",
                "Новый runtime уже авторизован. Сначала выполни logout или reset, если нужен другой вход.",
                status=current,
            )
        if current.state in {"code_requested", "awaiting_code"}:
            raise NewTelegramAuthActionError(
                "code_already_requested",
                "Код уже запрошен. Введи его или сбрось auth/session состояние.",
                status=current,
            )
        if current.state == "awaiting_password":
            raise NewTelegramAuthActionError(
                "password_required",
                "Telegram уже ждёт пароль 2FA. Введи пароль или сбрось auth/session состояние.",
                status=current,
            )
        self._ensure_runtime_prerequisites(current)

    def _ensure_code_submission_allowed(self, current: RuntimeAuthSessionState) -> None:
        if current.state not in {"awaiting_code"} or not current.phone_code_hash:
            raise NewTelegramAuthActionError(
                "awaiting_code_required",
                "Сейчас новый runtime не ждёт код. Сначала запроси новый код.",
                status=current,
            )

    def _ensure_password_submission_allowed(self, current: RuntimeAuthSessionState) -> None:
        if current.state != "awaiting_password":
            raise NewTelegramAuthActionError(
                "awaiting_password_required",
                "Сейчас новый runtime не ждёт пароль 2FA.",
                status=current,
            )

    def _ensure_runtime_prerequisites(self, current: RuntimeAuthSessionState) -> None:
        if not self.config.api_credentials_configured:
            raise NewTelegramAuthActionError(
                "api_credentials_missing",
                "Сначала задай RUNTIME_NEW_API_ID и RUNTIME_NEW_API_HASH.",
                status=current,
            )
        if not telethon_is_available():
            raise NewTelegramAuthActionError(
                "telethon_unavailable",
                "Telethon не установлен. Установи optional dependency: pip install -e '.[fullaccess]'.",
                status=current,
            )
        if not self.config.phone_configured:
            raise NewTelegramAuthActionError(
                "phone_missing",
                "Сначала задай RUNTIME_NEW_PHONE для запроса кода.",
                status=current,
            )

    def _require_phone(self, current: RuntimeAuthSessionState) -> str:
        self._ensure_runtime_prerequisites(current)
        phone = (self.config.phone or "").strip()
        if not phone:
            raise NewTelegramAuthActionError(
                "phone_missing",
                "Сначала задай RUNTIME_NEW_PHONE для запроса кода.",
                status=current,
            )
        return phone

    def _handle_submit_code_error(
        self,
        current: RuntimeAuthSessionState,
        error: NewTelegramAuthClientError,
    ) -> RuntimeAuthSessionState:
        if error.code == "phone_code_invalid":
            return _set_state(
                current,
                state="awaiting_code",
                session_state=_resolve_session_state(self.config),
                reason_code="awaiting_code",
                reason="Telegram ждёт корректный код.",
                error_code=error.code,
                error_message=error.message,
                error_at=_now_utc(),
                updated_at=_now_utc(),
            )
        if error.code == "phone_code_expired":
            return _set_state(
                current,
                state="error",
                session_state=_resolve_session_state(self.config),
                phone_code_hash=None,
                reason_code=error.code,
                reason=error.message,
                error_code=error.code,
                error_message=error.message,
                error_at=_now_utc(),
                updated_at=_now_utc(),
                state_changed_at=_now_utc(),
            )
        return _set_state(
            current,
            state="error",
            session_state=_resolve_session_state(self.config),
            reason_code=error.code,
            reason=error.message,
            error_code=error.code,
            error_message=error.message,
            error_at=_now_utc(),
            updated_at=_now_utc(),
            state_changed_at=_now_utc(),
        )


def default_auth_session_state(config: NewTelegramRuntimeConfig) -> RuntimeAuthSessionState:
    session_exists = config.session_path.exists()
    session_state: RuntimeSessionState = "available" if session_exists else "missing"
    if not config.enabled:
        return RuntimeAuthSessionState(
            state="disabled",
            auth_state="unauthorized",
            session_state=session_state,
            phone_hint=_mask_phone(config.phone),
            device_name=config.device_name,
            session_path=str(config.session_path),
            updated_at=_now_utc(),
            state_changed_at=_now_utc(),
            reason_code="runtime_disabled",
            reason="New Telegram runtime is disabled by RUNTIME_NEW_ENABLED.",
        )

    return RuntimeAuthSessionState(
        state="idle",
        auth_state="unauthorized",
        session_state=session_state,
        phone_hint=_mask_phone(config.phone),
        device_name=config.device_name,
        session_path=str(config.session_path),
        updated_at=_now_utc(),
        state_changed_at=_now_utc(),
        reason_code="login_required" if not session_exists else "session_present",
        reason=(
            "Новый runtime ждёт авторизацию в Telegram."
            if not session_exists
            else "Локальная session найдена. Новый runtime проверит авторизацию при следующем auth-check."
        ),
    )


def build_auth_session_state(
    value: object,
    *,
    config: NewTelegramRuntimeConfig,
) -> RuntimeAuthSessionState:
    if not isinstance(value, Mapping):
        return default_auth_session_state(config)

    default_state = default_auth_session_state(config)
    session_exists = config.session_path.exists()
    raw_auth_state = _read_literal(
        value.get("auth_state"),
        allowed={"unknown", "unauthorized", "authorizing", "authorized", "error"},
        fallback=default_state.auth_state,
    )
    raw_state = _read_literal(
        value.get("state"),
        allowed={
            "disabled",
            "idle",
            "code_requested",
            "awaiting_code",
            "awaiting_password",
            "authorized",
            "logout_in_progress",
            "error",
        },
        fallback=_state_from_legacy_auth_state(raw_auth_state),
    )
    if not config.enabled:
        raw_state = "disabled"
    elif raw_state == "disabled":
        raw_state = "authorized" if raw_auth_state == "authorized" else "idle"

    session_state = _read_literal(
        value.get("session_state"),
        allowed={"unknown", "missing", "available", "invalid"},
        fallback="available" if session_exists else "missing",
    )
    updated_at = _parse_datetime(value.get("updated_at"))
    state_changed_at = _parse_datetime(value.get("state_changed_at"))
    code_requested_at = _parse_datetime(value.get("code_requested_at"))
    authorized_at = _parse_datetime(value.get("authorized_at"))
    logout_started_at = _parse_datetime(value.get("logout_started_at"))
    last_checked_at = _parse_datetime(value.get("last_checked_at"))
    error_at = _parse_datetime(value.get("error_at"))

    return RuntimeAuthSessionState(
        state=cast(RuntimeAuthMachineState, raw_state),
        auth_state=cast(RuntimeAuthState, _auth_state_from_machine_state(raw_state)),
        session_state=cast(RuntimeSessionState, session_state),
        user_id=_read_int(value.get("user_id")),
        username=_read_string(value.get("username")),
        phone_hint=_read_string(value.get("phone_hint")) or _mask_phone(config.phone),
        pending_phone=_read_string(value.get("pending_phone")),
        phone_code_hash=_read_string(value.get("phone_code_hash")),
        device_id=_read_string(value.get("device_id")),
        device_name=_read_string(value.get("device_name")) or config.device_name,
        session_path=_read_string(value.get("session_path")) or str(config.session_path),
        updated_at=updated_at,
        state_changed_at=state_changed_at or updated_at,
        code_requested_at=code_requested_at,
        authorized_at=authorized_at,
        logout_started_at=logout_started_at,
        last_checked_at=last_checked_at,
        reason_code=_read_string(value.get("reason_code")),
        reason=_read_string(value.get("reason")) or default_state.reason,
        error_code=_read_string(value.get("error_code")),
        error_message=_read_string(value.get("error_message")),
        error_at=error_at,
    )


def _state_to_storage_payload(state: RuntimeAuthSessionState) -> dict[str, Any]:
    return {
        "state": state.state,
        "auth_state": state.auth_state,
        "session_state": state.session_state,
        "user_id": state.user_id,
        "username": state.username,
        "phone_hint": state.phone_hint,
        "pending_phone": state.pending_phone,
        "phone_code_hash": state.phone_code_hash,
        "device_id": state.device_id,
        "device_name": state.device_name,
        "session_path": state.session_path,
        "updated_at": (state.updated_at or _now_utc()).isoformat(),
        "state_changed_at": _serialize_datetime(state.state_changed_at),
        "code_requested_at": _serialize_datetime(state.code_requested_at),
        "authorized_at": _serialize_datetime(state.authorized_at),
        "logout_started_at": _serialize_datetime(state.logout_started_at),
        "last_checked_at": _serialize_datetime(state.last_checked_at),
        "reason_code": state.reason_code,
        "reason": state.reason,
        "error_code": state.error_code,
        "error_message": state.error_message,
        "error_at": _serialize_datetime(state.error_at),
    }


def _build_authorized_state(
    current: RuntimeAuthSessionState,
    *,
    account: NewTelegramAccount | None,
    config: NewTelegramRuntimeConfig,
    now: datetime,
) -> RuntimeAuthSessionState:
    phone_hint = (
        account.phone_hint
        if account is not None and account.phone_hint is not None
        else current.phone_hint or _mask_phone(config.phone)
    )
    return _set_state(
        current,
        state="authorized",
        session_state="available",
        user_id=account.user_id if account is not None else current.user_id,
        username=account.username if account is not None else current.username,
        phone_hint=phone_hint,
        pending_phone=None,
        phone_code_hash=None,
        reason_code="authorized",
        reason="Новый runtime авторизован в Telegram.",
        error_code=None,
        error_message=None,
        error_at=None,
        authorized_at=current.authorized_at or now,
        last_checked_at=now,
        updated_at=now,
        state_changed_at=now,
    )


def _build_disabled_state(
    config: NewTelegramRuntimeConfig,
    *,
    template: RuntimeAuthSessionState | None = None,
) -> RuntimeAuthSessionState:
    base = template or default_auth_session_state(config)
    now = _now_utc()
    updated_at = base.updated_at if base.state == "disabled" and base.updated_at is not None else now
    state_changed_at = (
        base.state_changed_at
        if base.state == "disabled" and base.state_changed_at is not None
        else now
    )
    return _set_state(
        base,
        state="disabled",
        session_state=_resolve_session_state(config),
        reason_code="runtime_disabled",
        reason="New Telegram runtime is disabled by RUNTIME_NEW_ENABLED.",
        updated_at=updated_at,
        state_changed_at=state_changed_at,
    )


def _set_state(
    current: RuntimeAuthSessionState,
    *,
    state: RuntimeAuthMachineState | None = None,
    session_state: RuntimeSessionState | None = None,
    user_id: int | None | object = _UNSET,
    username: str | None | object = _UNSET,
    phone_hint: str | None | object = _UNSET,
    pending_phone: str | None | object = _UNSET,
    phone_code_hash: str | None | object = _UNSET,
    device_id: str | None | object = _UNSET,
    device_name: str | None | object = _UNSET,
    session_path: str | None | object = _UNSET,
    updated_at: datetime | None | object = _UNSET,
    state_changed_at: datetime | None | object = _UNSET,
    code_requested_at: datetime | None | object = _UNSET,
    authorized_at: datetime | None | object = _UNSET,
    logout_started_at: datetime | None | object = _UNSET,
    last_checked_at: datetime | None | object = _UNSET,
    reason_code: str | None | object = _UNSET,
    reason: str | None | object = _UNSET,
    error_code: str | None | object = _UNSET,
    error_message: str | None | object = _UNSET,
    error_at: datetime | None | object = _UNSET,
) -> RuntimeAuthSessionState:
    next_state = current.state if state is None else state
    return RuntimeAuthSessionState(
        state=next_state,
        auth_state=cast(RuntimeAuthState, _auth_state_from_machine_state(next_state)),
        session_state=current.session_state if session_state is None else session_state,
        user_id=current.user_id if user_id is _UNSET else cast(int | None, user_id),
        username=current.username if username is _UNSET else cast(str | None, username),
        phone_hint=current.phone_hint if phone_hint is _UNSET else cast(str | None, phone_hint),
        pending_phone=(
            current.pending_phone if pending_phone is _UNSET else cast(str | None, pending_phone)
        ),
        phone_code_hash=(
            current.phone_code_hash if phone_code_hash is _UNSET else cast(str | None, phone_code_hash)
        ),
        device_id=current.device_id if device_id is _UNSET else cast(str | None, device_id),
        device_name=current.device_name if device_name is _UNSET else cast(str | None, device_name),
        session_path=current.session_path if session_path is _UNSET else cast(str | None, session_path),
        updated_at=current.updated_at if updated_at is _UNSET else cast(datetime | None, updated_at),
        state_changed_at=(
            current.state_changed_at if state_changed_at is _UNSET else cast(datetime | None, state_changed_at)
        ),
        code_requested_at=(
            current.code_requested_at if code_requested_at is _UNSET else cast(datetime | None, code_requested_at)
        ),
        authorized_at=(
            current.authorized_at if authorized_at is _UNSET else cast(datetime | None, authorized_at)
        ),
        logout_started_at=(
            current.logout_started_at if logout_started_at is _UNSET else cast(datetime | None, logout_started_at)
        ),
        last_checked_at=(
            current.last_checked_at if last_checked_at is _UNSET else cast(datetime | None, last_checked_at)
        ),
        reason_code=current.reason_code if reason_code is _UNSET else cast(str | None, reason_code),
        reason=current.reason if reason is _UNSET else cast(str | None, reason),
        error_code=current.error_code if error_code is _UNSET else cast(str | None, error_code),
        error_message=(
            current.error_message if error_message is _UNSET else cast(str | None, error_message)
        ),
        error_at=current.error_at if error_at is _UNSET else cast(datetime | None, error_at),
    )


def _resolve_session_state(
    config: NewTelegramRuntimeConfig,
    *,
    fallback: RuntimeSessionState | None = None,
) -> RuntimeSessionState:
    if config.session_path.exists():
        return "available"
    return fallback or "missing"


def _state_from_legacy_auth_state(raw_auth_state: str) -> RuntimeAuthMachineState:
    mapping: dict[str, RuntimeAuthMachineState] = {
        "authorized": "authorized",
        "authorizing": "awaiting_code",
        "error": "error",
        "unknown": "idle",
        "unauthorized": "idle",
    }
    return mapping.get(raw_auth_state, "idle")


def _auth_state_from_machine_state(state: str) -> str:
    if state == "authorized":
        return "authorized"
    if state == "error":
        return "error"
    if state in {"code_requested", "awaiting_code", "awaiting_password", "logout_in_progress"}:
        return "authorizing"
    if state == "disabled":
        return "unauthorized"
    return "unauthorized"


def _serialize_datetime(value: datetime | None) -> str | None:
    if value is None:
        return None
    return _ensure_utc(value).isoformat()


def _read_literal(value: object, *, allowed: set[str], fallback: str) -> str:
    if isinstance(value, str) and value in allowed:
        return value
    return fallback


def _read_string(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _read_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return None


def _parse_datetime(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return _ensure_utc(parsed)


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _mask_phone(value: str | None) -> str | None:
    if value is None:
        return None
    digits = "".join(ch for ch in value if ch.isdigit())
    if len(digits) < 4:
        return None
    return f"+***{digits[-4:]}"


def _is_status_refresh_stale(last_checked_at: datetime | None) -> bool:
    if last_checked_at is None:
        return True
    return (_now_utc() - _ensure_utc(last_checked_at)) >= AUTH_STATUS_REFRESH_TTL


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)
