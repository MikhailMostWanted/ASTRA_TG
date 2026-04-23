from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, cast

from astra_runtime.new_telegram.config import NewTelegramRuntimeConfig


@dataclass(frozen=True, slots=True)
class NewTelegramAccount:
    user_id: int | None
    username: str | None
    phone_hint: str | None


class NewTelegramAuthClientError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class NewTelegramPasswordRequiredError(NewTelegramAuthClientError):
    def __init__(self) -> None:
        super().__init__(
            "password_required",
            "Telegram требует пароль 2FA для завершения входа.",
        )


class NewTelegramAuthClientProtocol(Protocol):
    async def is_authorized(self) -> bool: ...

    async def request_login_code(self, phone: str) -> str: ...

    async def submit_code(
        self,
        *,
        phone: str,
        code: str,
        phone_code_hash: str,
    ) -> NewTelegramAccount: ...

    async def submit_password(self, password: str) -> NewTelegramAccount: ...

    async def current_account(self) -> NewTelegramAccount | None: ...

    async def logout(self) -> bool: ...


NewTelegramAuthClientFactory = Callable[
    [NewTelegramRuntimeConfig],
    NewTelegramAuthClientProtocol,
]


def telethon_is_available() -> bool:
    try:
        import telethon  # noqa: F401
    except ImportError:
        return False
    return True


@dataclass(slots=True)
class TelethonNewTelegramAuthClient:
    config: NewTelegramRuntimeConfig

    async def is_authorized(self) -> bool:
        async with _connected_client(self.config) as client:
            return bool(await client.is_user_authorized())

    async def request_login_code(self, phone: str) -> str:
        async with _connected_client(self.config) as client:
            try:
                sent = await client.send_code_request(phone)
            except Exception as error:
                raise _map_send_code_error(error) from error
            return str(sent.phone_code_hash)

    async def submit_code(
        self,
        *,
        phone: str,
        code: str,
        phone_code_hash: str,
    ) -> NewTelegramAccount:
        try:
            from telethon.errors import SessionPasswordNeededError
        except ImportError as error:  # pragma: no cover - defensive
            raise RuntimeError("Telethon не установлен.") from error

        async with _connected_client(self.config) as client:
            try:
                account = await client.sign_in(
                    phone=phone,
                    code=code,
                    phone_code_hash=phone_code_hash,
                )
            except SessionPasswordNeededError as error:
                raise NewTelegramPasswordRequiredError() from error
            except Exception as error:
                raise _map_submit_code_error(error) from error
            return _build_account(account)

    async def submit_password(self, password: str) -> NewTelegramAccount:
        async with _connected_client(self.config) as client:
            try:
                account = await client.sign_in(password=password)
            except Exception as error:
                raise _map_submit_password_error(error) from error
            return _build_account(account)

    async def current_account(self) -> NewTelegramAccount | None:
        async with _connected_client(self.config) as client:
            account = await client.get_me()
            if account is None:
                return None
            return _build_account(account)

    async def logout(self) -> bool:
        async with _connected_client(self.config) as client:
            try:
                return bool(await client.log_out())
            except Exception as error:
                raise NewTelegramAuthClientError(
                    "logout_failed",
                    f"Не удалось выполнить logout нового runtime: {error}",
                ) from error


def build_new_telegram_auth_client(
    config: NewTelegramRuntimeConfig,
) -> NewTelegramAuthClientProtocol:
    return TelethonNewTelegramAuthClient(config=config)


class _TelethonSentCodeProtocol(Protocol):
    phone_code_hash: object


class _TelethonClientProtocol(Protocol):
    def is_connected(self) -> bool: ...

    async def connect(self) -> object: ...

    async def disconnect(self) -> object: ...

    async def is_user_authorized(self) -> bool: ...

    async def send_code_request(self, phone: str) -> _TelethonSentCodeProtocol: ...

    async def sign_in(
        self,
        phone: str | None = None,
        code: str | None = None,
        *,
        password: str | None = None,
        phone_code_hash: str | None = None,
    ) -> object: ...

    async def get_me(self) -> object | None: ...

    async def log_out(self) -> bool: ...


@asynccontextmanager
async def _connected_client(
    config: NewTelegramRuntimeConfig,
) -> AsyncIterator[_TelethonClientProtocol]:
    client = _build_telethon_client(config)
    try:
        if not client.is_connected():
            await client.connect()
        yield client
    finally:
        if client.is_connected():
            await client.disconnect()


def _build_telethon_client(config: NewTelegramRuntimeConfig) -> _TelethonClientProtocol:
    if not telethon_is_available():
        raise RuntimeError(
            "Telethon не установлен. Установи optional dependency: pip install -e '.[fullaccess]'"
        )

    from telethon import TelegramClient

    api_id = config.api_id
    api_hash = config.api_hash
    if api_id is None or not api_hash:
        raise RuntimeError("RUNTIME_NEW_API_ID и RUNTIME_NEW_API_HASH не настроены.")

    config.session_path.parent.mkdir(parents=True, exist_ok=True)
    return cast(
        _TelethonClientProtocol,
        TelegramClient(
            str(config.session_path),
            api_id,
            api_hash,
            device_model=config.device_name,
            app_version="ASTRA_TG new runtime",
            lang_code="ru",
            system_lang_code="ru",
            receive_updates=False,
        ),
    )


def delete_session_file(session_path: Path) -> bool:
    removed = False
    for candidate in (
        session_path,
        session_path.with_name(f"{session_path.name}-journal"),
        session_path.with_name(f"{session_path.name}-shm"),
        session_path.with_name(f"{session_path.name}-wal"),
    ):
        if not candidate.exists():
            continue
        candidate.unlink()
        removed = True
    return removed


def _build_account(account: object) -> NewTelegramAccount:
    return NewTelegramAccount(
        user_id=_coerce_int(getattr(account, "id", None)),
        username=_coerce_string(getattr(account, "username", None)),
        phone_hint=_mask_phone(getattr(account, "phone", None)),
    )


def _map_send_code_error(error: Exception) -> NewTelegramAuthClientError:
    try:
        from telethon.errors import ApiIdInvalidError, FloodWaitError, PhoneNumberInvalidError
    except ImportError as import_error:  # pragma: no cover - defensive
        raise RuntimeError("Telethon не установлен.") from import_error

    if isinstance(error, ApiIdInvalidError):
        return NewTelegramAuthClientError(
            "api_credentials_invalid",
            "Telegram отклонил RUNTIME_NEW_API_ID/RUNTIME_NEW_API_HASH.",
        )
    if isinstance(error, PhoneNumberInvalidError):
        return NewTelegramAuthClientError(
            "phone_invalid",
            "Telegram не принял RUNTIME_NEW_PHONE.",
        )
    if isinstance(error, FloodWaitError):
        return NewTelegramAuthClientError(
            "flood_wait",
            f"Telegram временно ограничил запросы кода. Подожди {error.seconds} сек.",
        )
    return NewTelegramAuthClientError(
        "request_code_failed",
        f"Не удалось запросить код Telegram: {error}",
    )


def _map_submit_code_error(error: Exception) -> NewTelegramAuthClientError:
    try:
        from telethon.errors import (
            ApiIdInvalidError,
            PhoneCodeEmptyError,
            PhoneCodeExpiredError,
            PhoneCodeHashEmptyError,
            PhoneCodeInvalidError,
        )
    except ImportError as import_error:  # pragma: no cover - defensive
        raise RuntimeError("Telethon не установлен.") from import_error

    if isinstance(error, ApiIdInvalidError):
        return NewTelegramAuthClientError(
            "api_credentials_invalid",
            "Telegram отклонил RUNTIME_NEW_API_ID/RUNTIME_NEW_API_HASH.",
        )
    if isinstance(error, PhoneCodeInvalidError):
        return NewTelegramAuthClientError(
            "phone_code_invalid",
            "Код Telegram не подошёл. Проверь код и попробуй ещё раз.",
        )
    if isinstance(error, PhoneCodeExpiredError):
        return NewTelegramAuthClientError(
            "phone_code_expired",
            "Код Telegram уже истёк. Запроси новый код.",
        )
    if isinstance(error, (PhoneCodeEmptyError, PhoneCodeHashEmptyError)):
        return NewTelegramAuthClientError(
            "missing_code_context",
            "Контекст кода утрачен. Запроси код заново.",
        )
    return NewTelegramAuthClientError(
        "submit_code_failed",
        f"Не удалось подтвердить код Telegram: {error}",
    )


def _map_submit_password_error(error: Exception) -> NewTelegramAuthClientError:
    try:
        from telethon.errors import PasswordHashInvalidError
    except ImportError as import_error:  # pragma: no cover - defensive
        raise RuntimeError("Telethon не установлен.") from import_error

    if isinstance(error, PasswordHashInvalidError):
        return NewTelegramAuthClientError(
            "password_invalid",
            "Пароль 2FA не подошёл. Попробуй ещё раз.",
        )
    return NewTelegramAuthClientError(
        "submit_password_failed",
        f"Не удалось подтвердить пароль 2FA: {error}",
    )


def _coerce_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return None


def _coerce_string(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _mask_phone(value: object) -> str | None:
    phone = _coerce_string(value)
    if phone is None:
        return None
    digits = "".join(ch for ch in phone if ch.isdigit())
    if len(digits) < 4:
        return None
    return f"+***{digits[-4:]}"
