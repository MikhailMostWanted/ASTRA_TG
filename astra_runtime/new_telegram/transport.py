from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import Any, Protocol, cast

from fullaccess.cache import (
    avatar_base_path,
    clear_cached_variants,
    find_cached_variant,
    media_preview_base_path,
)

from astra_runtime.new_telegram.config import NewTelegramRuntimeConfig
from services.message_normalizer import normalize_text


@dataclass(frozen=True, slots=True)
class NewTelegramAccount:
    user_id: int | None
    username: str | None
    phone_hint: str | None


@dataclass(frozen=True, slots=True)
class NewTelegramDialogMessage:
    telegram_message_id: int | None
    sender_id: int | None
    sender_name: str | None
    direction: str | None
    sent_at: datetime | None
    text: str
    has_media: bool
    media_type: str | None
    source_type: str | None


@dataclass(frozen=True, slots=True)
class NewTelegramDialogSummary:
    telegram_chat_id: int
    title: str
    chat_type: str
    username: str | None
    unread_count: int
    unread_mentions_count: int
    pinned: bool
    muted: bool
    archived: bool
    last_activity_at: datetime | None
    last_message: NewTelegramDialogMessage | None = None
    avatar_cached: bool = False


@dataclass(frozen=True, slots=True)
class NewTelegramChatSummary:
    telegram_chat_id: int
    title: str
    chat_type: str
    username: str | None
    avatar_cached: bool = False


@dataclass(frozen=True, slots=True)
class NewTelegramRemoteMessage:
    telegram_message_id: int
    sender_id: int | None
    sender_name: str | None
    direction: str
    sent_at: datetime
    raw_text: str
    normalized_text: str
    reply_to_telegram_message_id: int | None
    forward_info: dict[str, Any] | list[Any] | None
    has_media: bool
    media_type: str | None
    entities_json: list[dict[str, Any]] | dict[str, Any] | None
    source_type: str


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


class NewTelegramRosterClientProtocol(Protocol):
    async def list_dialogs(self, *, limit: int) -> tuple[NewTelegramDialogSummary, ...]: ...


class NewTelegramHistoryClientProtocol(Protocol):
    async def fetch_history(
        self,
        reference: int | str,
        *,
        limit: int,
        min_message_id: int | None = None,
        max_message_id: int | None = None,
    ) -> tuple[NewTelegramChatSummary, tuple[NewTelegramRemoteMessage, ...]]: ...


NewTelegramAuthClientFactory = Callable[
    [NewTelegramRuntimeConfig],
    NewTelegramAuthClientProtocol,
]
NewTelegramRosterClientFactory = Callable[
    [NewTelegramRuntimeConfig],
    NewTelegramRosterClientProtocol,
]
NewTelegramHistoryClientFactory = Callable[
    [NewTelegramRuntimeConfig],
    NewTelegramHistoryClientProtocol,
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


@dataclass(slots=True)
class ManagedNewTelegramRuntime:
    config: NewTelegramRuntimeConfig
    _client: "_TelethonClientProtocol | None" = field(default=None, init=False, repr=False)
    _lock: asyncio.Lock = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._lock = asyncio.Lock()

    async def run(self, operation):
        async with self._lock:
            client = await self._ensure_client()
            try:
                return await operation(client)
            except Exception:
                await self._disconnect_client()
                raise

    async def close(self) -> None:
        async with self._lock:
            await self._disconnect_client()

    async def _ensure_client(self) -> "_TelethonClientProtocol":
        if self._client is None:
            self._client = _build_telethon_client(self.config)
        if not self._client.is_connected():
            await self._client.connect()
        return self._client

    async def _disconnect_client(self) -> None:
        if self._client is None:
            return
        try:
            if self._client.is_connected():
                await self._client.disconnect()
        finally:
            self._client = None


@dataclass(slots=True)
class RuntimeBackedNewTelegramRosterClient:
    config: NewTelegramRuntimeConfig
    runtime: ManagedNewTelegramRuntime

    async def list_dialogs(self, *, limit: int) -> tuple[NewTelegramDialogSummary, ...]:
        async def _list(client: _TelethonClientProtocol) -> tuple[NewTelegramDialogSummary, ...]:
            dialogs: list[NewTelegramDialogSummary] = []
            async for dialog in client.iter_dialogs(limit=limit):
                dialogs.append(_build_dialog_summary(dialog, config=self.config))
            return tuple(dialogs)

        return await self.runtime.run(_list)


@dataclass(slots=True)
class RuntimeBackedNewTelegramHistoryClient:
    config: NewTelegramRuntimeConfig
    runtime: ManagedNewTelegramRuntime

    async def fetch_history(
        self,
        reference: int | str,
        *,
        limit: int,
        min_message_id: int | None = None,
        max_message_id: int | None = None,
    ) -> tuple[NewTelegramChatSummary, tuple[NewTelegramRemoteMessage, ...]]:
        async def _fetch(
            client: _TelethonClientProtocol,
        ) -> tuple[NewTelegramChatSummary, tuple[NewTelegramRemoteMessage, ...]]:
            entity = await _resolve_entity(client, reference)
            chat = _build_chat_summary(entity, config=self.config)
            await _cache_profile_photo(
                client,
                entity=entity,
                config=self.config,
                telegram_chat_id=chat.telegram_chat_id,
            )

            messages: list[NewTelegramRemoteMessage] = []
            iter_kwargs: dict[str, int] = {"limit": limit}
            if min_message_id is not None:
                iter_kwargs["min_id"] = min_message_id
            if max_message_id is not None:
                iter_kwargs["max_id"] = max_message_id

            async for message in client.iter_messages(entity, **iter_kwargs):
                remote_message = _build_remote_message(message)
                await _cache_message_preview(
                    client,
                    message=message,
                    config=self.config,
                    telegram_chat_id=chat.telegram_chat_id,
                    remote_message=remote_message,
                )
                messages.append(remote_message)

            messages.reverse()
            return chat, tuple(messages)

        return await self.runtime.run(_fetch)


def build_new_telegram_auth_client(
    config: NewTelegramRuntimeConfig,
) -> NewTelegramAuthClientProtocol:
    return TelethonNewTelegramAuthClient(config=config)


def build_new_telegram_roster_client(
    config: NewTelegramRuntimeConfig,
) -> NewTelegramRosterClientProtocol:
    return RuntimeBackedNewTelegramRosterClient(
        config=config,
        runtime=_get_managed_runtime(config),
    )


def build_new_telegram_history_client(
    config: NewTelegramRuntimeConfig,
) -> NewTelegramHistoryClientProtocol:
    return RuntimeBackedNewTelegramHistoryClient(
        config=config,
        runtime=_get_managed_runtime(config),
    )


_MANAGED_RUNTIMES: dict[str, ManagedNewTelegramRuntime] = {}
_MANAGED_RUNTIMES_GUARD = Lock()


async def close_managed_new_telegram_clients() -> None:
    with _MANAGED_RUNTIMES_GUARD:
        runtimes = list(_MANAGED_RUNTIMES.values())
        _MANAGED_RUNTIMES.clear()

    for runtime in runtimes:
        await runtime.close()


class _TelethonSentCodeProtocol(Protocol):
    phone_code_hash: object


class _TelethonDialogProtocol(Protocol):
    entity: object
    message: object | None
    unread_count: object
    unread_mentions_count: object
    pinned: object
    archived: object
    folder_id: object
    dialog: object | None
    date: object | None


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

    def iter_dialogs(self, *, limit: int) -> AsyncIterator[_TelethonDialogProtocol]: ...
    def iter_messages(
        self,
        entity: object,
        *,
        limit: int,
        min_id: int | None = None,
        max_id: int | None = None,
    ) -> AsyncIterator[object]: ...
    async def get_entity(self, target: int | str) -> object: ...
    async def download_profile_photo(self, entity: object, file: str | None = None) -> object: ...
    async def download_media(self, message: object, file: str | None = None) -> object: ...


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


def _get_managed_runtime(config: NewTelegramRuntimeConfig) -> ManagedNewTelegramRuntime:
    key = _build_runtime_key(config)
    with _MANAGED_RUNTIMES_GUARD:
        runtime = _MANAGED_RUNTIMES.get(key)
        if runtime is None:
            runtime = ManagedNewTelegramRuntime(config=config)
            _MANAGED_RUNTIMES[key] = runtime
        return runtime


def _build_runtime_key(config: NewTelegramRuntimeConfig) -> str:
    session_key = f"file:{config.session_path.expanduser().resolve()}"
    return f"{config.api_id}:{session_key}"


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


def _build_dialog_summary(
    dialog: _TelethonDialogProtocol,
    *,
    config: NewTelegramRuntimeConfig,
) -> NewTelegramDialogSummary:
    from telethon import utils

    entity = dialog.entity
    telegram_chat_id = _coerce_optional_int(utils.get_peer_id(entity)) or 0
    last_message = _build_dialog_message(getattr(dialog, "message", None))
    return NewTelegramDialogSummary(
        telegram_chat_id=telegram_chat_id,
        title=_resolve_entity_title(entity),
        chat_type=_resolve_entity_type(entity),
        username=_resolve_entity_username(entity),
        unread_count=_coerce_non_negative_int(getattr(dialog, "unread_count", None)),
        unread_mentions_count=_coerce_non_negative_int(
            getattr(dialog, "unread_mentions_count", None)
        ),
        pinned=bool(getattr(dialog, "pinned", False)),
        muted=_dialog_is_muted(dialog),
        archived=bool(getattr(dialog, "archived", False))
        or getattr(dialog, "folder_id", None) not in (None, 0),
        last_activity_at=(
            last_message.sent_at
            if last_message is not None and last_message.sent_at is not None
            else _normalize_datetime(getattr(dialog, "date", None))
        ),
        last_message=last_message,
        avatar_cached=telegram_chat_id != 0
        and find_cached_variant(avatar_base_path(config.session_path, telegram_chat_id)) is not None,
    )


def _build_dialog_message(message: object | None) -> NewTelegramDialogMessage | None:
    if message is None:
        return None

    raw_text = getattr(message, "text", None) or getattr(message, "message", None) or ""
    media = getattr(message, "media", None)
    media_type = type(media).__name__.lower() if media is not None else None
    return NewTelegramDialogMessage(
        telegram_message_id=_coerce_optional_int(getattr(message, "id", None)),
        sender_id=_coerce_optional_int(getattr(message, "sender_id", None)),
        sender_name=_resolve_sender_name(message),
        direction="outbound" if bool(getattr(message, "out", False)) else "inbound",
        sent_at=_normalize_datetime(getattr(message, "date", None)),
        text=str(raw_text or ""),
        has_media=media is not None,
        media_type=media_type,
        source_type="channel_post" if bool(getattr(message, "post", False)) else "message",
    )


async def _resolve_entity(
    client: _TelethonClientProtocol,
    reference: int | str,
) -> object:
    target: int | str
    if isinstance(reference, int):
        target = reference
    else:
        candidate = reference.strip()
        if not candidate:
            raise ValueError("Укажи runtime chat_id или @username для чтения истории.")
        if candidate.startswith("@"):
            target = candidate
        else:
            try:
                target = int(candidate)
            except ValueError:
                target = f"@{candidate.lstrip('@')}"

    try:
        return await client.get_entity(target)
    except Exception as error:  # pragma: no cover - depends on Telethon runtime
        raise ValueError("Не удалось найти чат в новом runtime.") from error


def _build_chat_summary(
    entity: object,
    *,
    config: NewTelegramRuntimeConfig,
) -> NewTelegramChatSummary:
    from telethon import utils

    telegram_chat_id = _coerce_optional_int(utils.get_peer_id(entity)) or 0
    return NewTelegramChatSummary(
        telegram_chat_id=telegram_chat_id,
        title=_resolve_entity_title(entity),
        chat_type=_resolve_entity_type(entity),
        username=_resolve_entity_username(entity),
        avatar_cached=telegram_chat_id != 0
        and find_cached_variant(avatar_base_path(config.session_path, telegram_chat_id)) is not None,
    )


def _build_remote_message(message: object) -> NewTelegramRemoteMessage:
    raw_text = getattr(message, "text", None) or getattr(message, "message", None) or ""
    media = getattr(message, "media", None)
    media_type = type(media).__name__.lower() if media is not None else None
    reply_to = getattr(getattr(message, "reply_to", None), "reply_to_msg_id", None)
    sender = getattr(message, "sender", None)
    sender_name = _resolve_entity_title(sender) if sender is not None else None
    if sender_name is None:
        post_author = getattr(message, "post_author", None)
        if isinstance(post_author, str) and post_author.strip():
            sender_name = post_author.strip()

    entities_payload = _to_json_compatible(getattr(message, "entities", None))
    if entities_payload is not None and not isinstance(entities_payload, (list, dict)):
        entities_payload = None

    return NewTelegramRemoteMessage(
        telegram_message_id=int(getattr(message, "id")),
        sender_id=_coerce_optional_int(getattr(message, "sender_id", None)),
        sender_name=sender_name,
        direction="outbound" if bool(getattr(message, "out", False)) else "inbound",
        sent_at=_normalize_datetime(getattr(message, "date", None)) or datetime.now(UTC),
        raw_text=str(raw_text or ""),
        normalized_text=normalize_text(str(raw_text or "")),
        reply_to_telegram_message_id=_coerce_optional_int(reply_to),
        forward_info=_to_json_compatible(getattr(message, "fwd_from", None)),
        has_media=media is not None,
        media_type=media_type,
        entities_json=entities_payload if isinstance(entities_payload, (list, dict)) else None,
        source_type="channel_post" if bool(getattr(message, "post", False)) else "message",
    )


async def _cache_profile_photo(
    client: _TelethonClientProtocol,
    *,
    entity: object,
    config: NewTelegramRuntimeConfig,
    telegram_chat_id: int,
) -> None:
    if telegram_chat_id == 0:
        return

    base_path = avatar_base_path(config.session_path, telegram_chat_id)
    if find_cached_variant(base_path) is not None:
        return

    base_path.parent.mkdir(parents=True, exist_ok=True)
    clear_cached_variants(base_path)
    try:
        await client.download_profile_photo(entity, file=str(base_path))
    except Exception:  # pragma: no cover - depends on Telethon runtime
        clear_cached_variants(base_path)


async def _cache_message_preview(
    client: _TelethonClientProtocol,
    *,
    message: object,
    config: NewTelegramRuntimeConfig,
    telegram_chat_id: int,
    remote_message: NewTelegramRemoteMessage,
) -> None:
    if remote_message.telegram_message_id <= 0:
        return
    if remote_message.media_type not in {"photo", "messagemediaphoto", "sticker", "messagemediadocument"}:
        return

    base_path = media_preview_base_path(
        config.session_path,
        telegram_chat_id=telegram_chat_id,
        telegram_message_id=remote_message.telegram_message_id,
    )
    if find_cached_variant(base_path) is not None:
        return

    base_path.parent.mkdir(parents=True, exist_ok=True)
    clear_cached_variants(base_path)
    try:
        await client.download_media(message, file=str(base_path))
    except Exception:  # pragma: no cover - depends on Telethon runtime
        clear_cached_variants(base_path)


def _dialog_is_muted(dialog: _TelethonDialogProtocol) -> bool:
    if bool(getattr(dialog, "muted", False)):
        return True

    raw_dialog = getattr(dialog, "dialog", None)
    notify_settings = getattr(raw_dialog, "notify_settings", None)
    mute_until = getattr(notify_settings, "mute_until", None)
    if isinstance(mute_until, datetime):
        return _normalize_datetime(mute_until) > datetime.now(UTC)
    if isinstance(mute_until, int):
        return mute_until > 0
    return False


def _resolve_sender_name(message: object) -> str | None:
    sender = getattr(message, "sender", None)
    if sender is not None:
        sender_name = _resolve_entity_title(sender)
        if sender_name and not sender_name.startswith("Источник "):
            return sender_name

    post_author = getattr(message, "post_author", None)
    if isinstance(post_author, str) and post_author.strip():
        return post_author.strip()
    return None


def _resolve_entity_title(entity: object | None) -> str:
    if entity is None:
        return "Неизвестный чат"

    title = getattr(entity, "title", None)
    if isinstance(title, str) and title.strip():
        return title.strip()

    first_name = getattr(entity, "first_name", None)
    last_name = getattr(entity, "last_name", None)
    name_parts = [
        part.strip()
        for part in (first_name, last_name)
        if isinstance(part, str) and part.strip()
    ]
    if name_parts:
        return " ".join(name_parts)

    username = _resolve_entity_username(entity)
    if username:
        return f"@{username}"

    entity_id = getattr(entity, "id", None)
    return f"Источник {entity_id}"


def _resolve_entity_username(entity: object | None) -> str | None:
    username = getattr(entity, "username", None)
    if not isinstance(username, str):
        return None
    cleaned = username.strip().lstrip("@")
    return cleaned or None


def _resolve_entity_type(entity: object) -> str:
    if bool(getattr(entity, "broadcast", False)):
        return "channel"
    if bool(getattr(entity, "megagroup", False)):
        return "supergroup"
    if getattr(entity, "first_name", None) is not None or getattr(entity, "bot", False):
        return "private"
    if getattr(entity, "title", None) is not None:
        return "group"
    return "unknown"


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


def _to_json_compatible(value: object) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value

    if isinstance(value, datetime):
        normalized = _normalize_datetime(value)
        return normalized.isoformat() if normalized is not None else None

    if isinstance(value, dict):
        return {
            str(key): _to_json_compatible(item)
            for key, item in value.items()
            if item is not None
        }

    if isinstance(value, (list, tuple, set)):
        return [_to_json_compatible(item) for item in value]

    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return _to_json_compatible(model_dump())

    dataclass_fields = getattr(value, "__dataclass_fields__", None)
    if dataclass_fields:
        return {
            field_name: _to_json_compatible(getattr(value, field_name))
            for field_name in dataclass_fields
        }

    return str(value)


def _normalize_datetime(value: object) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
    return None


def _coerce_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return None


def _coerce_optional_int(value: object) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    return None


def _coerce_non_negative_int(value: object) -> int:
    coerced = _coerce_optional_int(value)
    if coerced is None:
        return 0
    return max(0, coerced)


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
