from __future__ import annotations

# LEGACY_RUNTIME: Telethon transport for the temporary full-access contour.
# New Telegram runtime work should implement `astra_runtime.contracts.TelegramRuntime`
# instead of expanding this module.

import asyncio
import hashlib
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from threading import Lock
from typing import Any, Protocol, cast

from fullaccess.cache import (
    avatar_base_path,
    clear_cached_variants,
    find_cached_variant,
    media_preview_base_path,
)
from fullaccess.copy import LOCAL_LOGIN_COMMAND
from fullaccess.models import (
    FullAccessChatSummary,
    FullAccessConfig,
    FullAccessRemoteMessage,
    FullAccessSendResult,
)
from services.message_normalizer import normalize_text


class FullAccessClientError(RuntimeError):
    """Base transport error for the experimental full-access layer."""


class FullAccessPasswordRequiredError(FullAccessClientError):
    """Raised when Telegram requires 2FA password after the login code."""


def telethon_is_available() -> bool:
    try:
        import telethon  # noqa: F401
    except ImportError:
        return False
    return True


class FullAccessClientProtocol(Protocol):
    async def is_authorized(self) -> bool: ...

    async def request_login_code(self, phone: str) -> str: ...

    async def complete_login(
        self,
        *,
        phone: str,
        code: str,
        phone_code_hash: str,
        password: str | None = None,
    ) -> bool: ...

    async def logout(self) -> bool: ...

    async def list_chats(self, *, limit: int) -> list[FullAccessChatSummary]: ...

    async def fetch_history(
        self,
        reference: str,
        *,
        limit: int,
        min_message_id: int | None = None,
    ) -> tuple[FullAccessChatSummary, list[FullAccessRemoteMessage]]: ...

    async def send_message(
        self,
        reference: str,
        *,
        text: str,
        reply_to_message_id: int | None = None,
    ) -> FullAccessSendResult: ...


FullAccessClientFactory = Callable[[FullAccessConfig], FullAccessClientProtocol]


class _TelethonSentCodeProtocol(Protocol):
    phone_code_hash: object


class _TelethonDialogProtocol(Protocol):
    entity: object


class _TelethonClientProtocol(Protocol):
    def is_connected(self) -> bool: ...

    async def is_user_authorized(self) -> bool: ...

    async def send_code_request(self, phone: str) -> _TelethonSentCodeProtocol: ...

    async def sign_in(
        self,
        *,
        phone: str | None = None,
        code: str | None = None,
        phone_code_hash: str | None = None,
        password: str | None = None,
    ) -> object: ...

    async def log_out(self) -> bool: ...

    def iter_dialogs(self, *, limit: int) -> AsyncIterator[_TelethonDialogProtocol]: ...

    def iter_messages(
        self,
        entity: object,
        *,
        limit: int,
        min_id: int | None = None,
    ) -> AsyncIterator[object]: ...

    async def get_entity(self, target: int | str) -> object: ...
    async def send_message(
        self,
        entity: object,
        message: str,
        *,
        reply_to: int | None = None,
    ) -> object: ...
    async def download_profile_photo(self, entity: object, file: str | None = None) -> object: ...
    async def download_media(self, message: object, file: str | None = None) -> object: ...

    async def connect(self) -> object: ...

    async def disconnect(self) -> object: ...


def build_fullaccess_client(config: FullAccessConfig) -> FullAccessClientProtocol:
    return RuntimeBackedFullAccessClient(
        config=config,
        runtime=_get_managed_runtime(config),
    )


_MANAGED_RUNTIMES: dict[str, "ManagedTelethonRuntime"] = {}
_MANAGED_RUNTIMES_GUARD = Lock()


@dataclass(slots=True)
class ManagedTelethonRuntime:
    config: FullAccessConfig
    _client: _TelethonClientProtocol | None = field(default=None, init=False, repr=False)
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

    async def _ensure_client(self) -> _TelethonClientProtocol:
        if not telethon_is_available():
            raise RuntimeError(
                "Telethon не установлен. Установи optional dependency: pip install -e '.[fullaccess]'"
            )

        api_id = self.config.api_id
        api_hash = self.config.api_hash
        if api_id is None or api_hash is None:
            raise RuntimeError("FULLACCESS_API_ID/FULLACCESS_API_HASH не настроены.")

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
class RuntimeBackedFullAccessClient:
    config: FullAccessConfig
    runtime: ManagedTelethonRuntime

    async def is_authorized(self) -> bool:
        return await self.runtime.run(_is_user_authorized)

    async def request_login_code(self, phone: str) -> str:
        async def _request(client: _TelethonClientProtocol) -> str:
            try:
                sent_code = await client.send_code_request(phone)
            except Exception as error:  # pragma: no cover - depends on Telethon runtime
                raise ValueError(f"Не удалось запросить код Telegram: {error}") from error
            return str(sent_code.phone_code_hash)

        return await self.runtime.run(_request)

    async def complete_login(
        self,
        *,
        phone: str,
        code: str,
        phone_code_hash: str,
        password: str | None = None,
    ) -> bool:
        try:
            from telethon.errors import (
                ApiIdInvalidError,
                PhoneCodeExpiredError,
                PhoneCodeInvalidError,
                SessionPasswordNeededError,
            )
        except ImportError as error:  # pragma: no cover - defensive
            raise RuntimeError("Telethon не установлен.") from error

        async def _complete(client: _TelethonClientProtocol) -> bool:
            try:
                await client.sign_in(
                    phone=phone,
                    code=code,
                    phone_code_hash=phone_code_hash,
                )
            except SessionPasswordNeededError as error:
                if password is None:
                    raise FullAccessPasswordRequiredError from error
                await client.sign_in(password=password)
            except PhoneCodeInvalidError as error:
                raise ValueError(
                    "Код Telegram не подошёл. Проверь код и попробуй ещё раз."
                ) from error
            except PhoneCodeExpiredError as error:
                raise ValueError(
                    f"Код Telegram уже истёк. Запусти {LOCAL_LOGIN_COMMAND} ещё раз и запроси новый код."
                ) from error
            except ApiIdInvalidError as error:
                raise ValueError(
                    "Telegram отклонил FULLACCESS_API_ID/FULLACCESS_API_HASH."
                ) from error
            except Exception as error:  # pragma: no cover - depends on Telethon runtime
                raise ValueError(f"Не удалось завершить авторизацию: {error}") from error

            return bool(await client.is_user_authorized())

        return await self.runtime.run(_complete)

    async def logout(self) -> bool:
        async def _logout(client: _TelethonClientProtocol) -> bool:
            try:
                return bool(await client.log_out())
            except Exception as error:  # pragma: no cover - depends on Telethon runtime
                raise ValueError(f"Не удалось завершить logout: {error}") from error

        try:
            return await self.runtime.run(_logout)
        finally:
            await self.runtime.close()

    async def list_chats(self, *, limit: int) -> list[FullAccessChatSummary]:
        async def _list(client: _TelethonClientProtocol) -> list[FullAccessChatSummary]:
            dialogs: list[FullAccessChatSummary] = []
            async for dialog in client.iter_dialogs(limit=limit):
                summary = _build_chat_summary(dialog.entity)
                await _cache_profile_photo(
                    client,
                    entity=dialog.entity,
                    config=self.config,
                    telegram_chat_id=summary.telegram_chat_id,
                )
                dialogs.append(summary)
            return dialogs

        return await self.runtime.run(_list)

    async def fetch_history(
        self,
        reference: str,
        *,
        limit: int,
        min_message_id: int | None = None,
    ) -> tuple[FullAccessChatSummary, list[FullAccessRemoteMessage]]:
        async def _fetch(client: _TelethonClientProtocol) -> tuple[FullAccessChatSummary, list[FullAccessRemoteMessage]]:
            entity = await _resolve_entity(client, reference)
            chat = _build_chat_summary(entity)
            await _cache_profile_photo(
                client,
                entity=entity,
                config=self.config,
                telegram_chat_id=chat.telegram_chat_id,
            )
            messages: list[FullAccessRemoteMessage] = []
            iter_kwargs: dict[str, int] = {"limit": limit}
            if min_message_id is not None:
                iter_kwargs["min_id"] = min_message_id
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
            return chat, messages

        return await self.runtime.run(_fetch)

    async def send_message(
        self,
        reference: str,
        *,
        text: str,
        reply_to_message_id: int | None = None,
    ) -> FullAccessSendResult:
        async def _send(client: _TelethonClientProtocol) -> FullAccessSendResult:
            entity = await _resolve_entity(client, reference)
            chat = _build_chat_summary(entity)
            await _cache_profile_photo(
                client,
                entity=entity,
                config=self.config,
                telegram_chat_id=chat.telegram_chat_id,
            )
            try:
                message = await client.send_message(
                    entity,
                    text,
                    reply_to=reply_to_message_id,
                )
            except Exception as error:  # pragma: no cover - depends on Telethon runtime
                raise ValueError(f"Не удалось отправить сообщение через full-access: {error}") from error
            return FullAccessSendResult(
                chat=chat,
                message=_build_remote_message(message),
            )

        return await self.runtime.run(_send)


@dataclass(slots=True)
class TelethonFullAccessClient:
    config: FullAccessConfig

    async def is_authorized(self) -> bool:
        async with self._open_client() as client:
            return bool(await client.is_user_authorized())

    async def request_login_code(self, phone: str) -> str:
        async with self._open_client() as client:
            try:
                sent_code = await client.send_code_request(phone)
            except Exception as error:  # pragma: no cover - depends on Telethon runtime
                raise ValueError(f"Не удалось запросить код Telegram: {error}") from error
            return str(sent_code.phone_code_hash)

    async def complete_login(
        self,
        *,
        phone: str,
        code: str,
        phone_code_hash: str,
        password: str | None = None,
    ) -> bool:
        try:
            from telethon.errors import (
                ApiIdInvalidError,
                PhoneCodeExpiredError,
                PhoneCodeInvalidError,
                SessionPasswordNeededError,
            )
        except ImportError as error:  # pragma: no cover - defensive
            raise RuntimeError("Telethon не установлен.") from error

        async with self._open_client() as client:
            try:
                await client.sign_in(
                    phone=phone,
                    code=code,
                    phone_code_hash=phone_code_hash,
                )
            except SessionPasswordNeededError as error:
                if password is None:
                    raise FullAccessPasswordRequiredError from error
                await client.sign_in(password=password)
            except PhoneCodeInvalidError as error:
                raise ValueError(
                    "Код Telegram не подошёл. Проверь код и попробуй ещё раз."
                ) from error
            except PhoneCodeExpiredError as error:
                raise ValueError(
                    f"Код Telegram уже истёк. Запусти {LOCAL_LOGIN_COMMAND} ещё раз и запроси новый код."
                ) from error
            except ApiIdInvalidError as error:
                raise ValueError(
                    "Telegram отклонил FULLACCESS_API_ID/FULLACCESS_API_HASH."
                ) from error
            except Exception as error:  # pragma: no cover - depends on Telethon runtime
                raise ValueError(f"Не удалось завершить авторизацию: {error}") from error

            return bool(await client.is_user_authorized())

    async def logout(self) -> bool:
        async with self._open_client() as client:
            try:
                return bool(await client.log_out())
            except Exception as error:  # pragma: no cover - depends on Telethon runtime
                raise ValueError(f"Не удалось завершить logout: {error}") from error

    async def list_chats(self, *, limit: int) -> list[FullAccessChatSummary]:
        async with self._open_client() as client:
            dialogs: list[FullAccessChatSummary] = []
            async for dialog in client.iter_dialogs(limit=limit):
                summary = _build_chat_summary(dialog.entity)
                await _cache_profile_photo(
                    client,
                    entity=dialog.entity,
                    config=self.config,
                    telegram_chat_id=summary.telegram_chat_id,
                )
                dialogs.append(summary)
            return dialogs

    async def fetch_history(
        self,
        reference: str,
        *,
        limit: int,
        min_message_id: int | None = None,
    ) -> tuple[FullAccessChatSummary, list[FullAccessRemoteMessage]]:
        async with self._open_client() as client:
            entity = await _resolve_entity(client, reference)
            chat = _build_chat_summary(entity)
            await _cache_profile_photo(
                client,
                entity=entity,
                config=self.config,
                telegram_chat_id=chat.telegram_chat_id,
            )
            messages: list[FullAccessRemoteMessage] = []
            iter_kwargs: dict[str, int] = {"limit": limit}
            if min_message_id is not None:
                iter_kwargs["min_id"] = min_message_id
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
            return chat, messages

    async def send_message(
        self,
        reference: str,
        *,
        text: str,
        reply_to_message_id: int | None = None,
    ) -> FullAccessSendResult:
        async with self._open_client() as client:
            entity = await _resolve_entity(client, reference)
            chat = _build_chat_summary(entity)
            await _cache_profile_photo(
                client,
                entity=entity,
                config=self.config,
                telegram_chat_id=chat.telegram_chat_id,
            )
            try:
                message = await client.send_message(
                    entity,
                    text,
                    reply_to=reply_to_message_id,
                )
            except Exception as error:  # pragma: no cover - depends on Telethon runtime
                raise ValueError(f"Не удалось отправить сообщение через full-access: {error}") from error
            return FullAccessSendResult(
                chat=chat,
                message=_build_remote_message(message),
            )

    @asynccontextmanager
    async def _open_client(self) -> AsyncIterator[_TelethonClientProtocol]:
        if not telethon_is_available():
            raise RuntimeError(
                "Telethon не установлен. Установи optional dependency: pip install -e '.[fullaccess]'"
            )

        api_id = self.config.api_id
        api_hash = self.config.api_hash
        if api_id is None or api_hash is None:
            raise RuntimeError("FULLACCESS_API_ID/FULLACCESS_API_HASH не настроены.")
        client = _build_telethon_client(self.config)
        await client.connect()
        try:
            yield client
        finally:
            await client.disconnect()


def _get_managed_runtime(config: FullAccessConfig) -> ManagedTelethonRuntime:
    key = _build_runtime_key(config)
    with _MANAGED_RUNTIMES_GUARD:
        runtime = _MANAGED_RUNTIMES.get(key)
        if runtime is None:
            runtime = ManagedTelethonRuntime(config=config)
            _MANAGED_RUNTIMES[key] = runtime
        return runtime


async def close_managed_fullaccess_clients() -> None:
    with _MANAGED_RUNTIMES_GUARD:
        runtimes = list(_MANAGED_RUNTIMES.values())
        _MANAGED_RUNTIMES.clear()

    for runtime in runtimes:
        await runtime.close()


async def _is_user_authorized(client: _TelethonClientProtocol) -> bool:
    return bool(await client.is_user_authorized())


def _build_runtime_key(config: FullAccessConfig) -> str:
    if config.uses_session_string:
        digest = hashlib.sha256((config.session_string or "").encode("utf-8")).hexdigest()[:12]
        session_key = f"string:{digest}"
    else:
        session_key = f"file:{config.session_path.expanduser().resolve()}"
    return f"{config.api_id}:{session_key}"


def _build_telethon_client(config: FullAccessConfig) -> _TelethonClientProtocol:
    from telethon import TelegramClient
    from telethon.sessions import StringSession

    api_id = config.api_id
    api_hash = config.api_hash
    if api_id is None or api_hash is None:
        raise RuntimeError("FULLACCESS_API_ID/FULLACCESS_API_HASH не настроены.")

    if config.uses_session_string:
        session = StringSession(config.session_string)
        return cast(
            _TelethonClientProtocol,
            TelegramClient(session, api_id, api_hash),
        )

    config.session_path.parent.mkdir(parents=True, exist_ok=True)
    return cast(
        _TelethonClientProtocol,
        TelegramClient(str(config.session_path), api_id, api_hash),
    )


async def _resolve_entity(client: _TelethonClientProtocol, reference: str) -> object:
    candidate = reference.strip()
    if not candidate:
        raise ValueError("Укажи chat_id или @username для full-access операции.")

    target: int | str
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
        raise ValueError("Не удалось найти чат по этому reference.") from error


def _build_chat_summary(entity: object) -> FullAccessChatSummary:
    from telethon import utils

    peer_id = _coerce_optional_int(utils.get_peer_id(entity))
    return FullAccessChatSummary(
        telegram_chat_id=peer_id or 0,
        title=_resolve_entity_title(entity),
        chat_type=_resolve_entity_type(entity),
        username=_resolve_entity_username(entity),
    )


def _build_remote_message(message: object) -> FullAccessRemoteMessage:
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
    if entities_payload is not None and not isinstance(entities_payload, list):
        entities_payload = None

    return FullAccessRemoteMessage(
        telegram_message_id=int(getattr(message, "id")),
        sender_id=_coerce_optional_int(getattr(message, "sender_id", None)),
        sender_name=sender_name,
        direction="outbound" if bool(getattr(message, "out", False)) else "inbound",
        sent_at=_normalize_datetime(getattr(message, "date", None)),
        raw_text=str(raw_text or ""),
        normalized_text=normalize_text(str(raw_text or "")),
        reply_to_telegram_message_id=_coerce_optional_int(reply_to),
        forward_info=_to_json_compatible(getattr(message, "fwd_from", None)),
        has_media=media is not None,
        media_type=media_type,
        entities_json=entities_payload,
        source_type="channel_post" if bool(getattr(message, "post", False)) else "message",
    )


async def _cache_profile_photo(
    client: _TelethonClientProtocol,
    *,
    entity: object,
    config: FullAccessConfig,
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
    config: FullAccessConfig,
    telegram_chat_id: int,
    remote_message: FullAccessRemoteMessage,
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


def _normalize_datetime(value: object) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
    return datetime.now(UTC)


def _coerce_optional_int(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


def _to_json_compatible(value: object) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC).isoformat()
        return value.astimezone(UTC).isoformat()
    if isinstance(value, dict):
        return {
            str(key): _to_json_compatible(item)
            for key, item in value.items()
            if item is not None
        }
    if isinstance(value, (list, tuple, set)):
        return [_to_json_compatible(item) for item in value]
    if hasattr(value, "__dict__"):
        return _to_json_compatible(
            {
                key: item
                for key, item in vars(value).items()
                if not key.startswith("_") and item is not None
            }
        )
    return str(value)
