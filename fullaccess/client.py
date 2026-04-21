from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol, cast

from fullaccess.models import FullAccessChatSummary, FullAccessConfig, FullAccessRemoteMessage
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
    ) -> tuple[FullAccessChatSummary, list[FullAccessRemoteMessage]]: ...


FullAccessClientFactory = Callable[[FullAccessConfig], FullAccessClientProtocol]


class _TelethonSentCodeProtocol(Protocol):
    phone_code_hash: object


class _TelethonDialogProtocol(Protocol):
    entity: object


class _TelethonClientProtocol(Protocol):
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
        reverse: bool = False,
    ) -> AsyncIterator[object]: ...

    async def get_entity(self, target: int | str) -> object: ...

    async def connect(self) -> object: ...

    async def disconnect(self) -> object: ...


def build_fullaccess_client(config: FullAccessConfig) -> FullAccessClientProtocol:
    return TelethonFullAccessClient(config)


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
                    "Код Telegram уже истёк. Сначала заново вызови /fullaccess_login без аргументов."
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
                dialogs.append(_build_chat_summary(dialog.entity))
            return dialogs

    async def fetch_history(
        self,
        reference: str,
        *,
        limit: int,
    ) -> tuple[FullAccessChatSummary, list[FullAccessRemoteMessage]]:
        async with self._open_client() as client:
            entity = await _resolve_entity(client, reference)
            chat = _build_chat_summary(entity)
            messages: list[FullAccessRemoteMessage] = []
            async for message in client.iter_messages(entity, limit=limit, reverse=True):
                messages.append(_build_remote_message(message))
            return chat, messages

    @asynccontextmanager
    async def _open_client(self) -> AsyncIterator[_TelethonClientProtocol]:
        if not telethon_is_available():
            raise RuntimeError(
                "Telethon не установлен. Установи optional dependency: pip install -e '.[fullaccess]'"
            )

        from telethon import TelegramClient

        api_id = self.config.api_id
        api_hash = self.config.api_hash
        if api_id is None or api_hash is None:
            raise RuntimeError("FULLACCESS_API_ID/FULLACCESS_API_HASH не настроены.")

        self.config.session_path.parent.mkdir(parents=True, exist_ok=True)
        client = cast(
            _TelethonClientProtocol,
            TelegramClient(
                str(self.config.session_path),
                api_id,
                api_hash,
            ),
        )
        await client.connect()
        try:
            yield client
        finally:
            await client.disconnect()


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
