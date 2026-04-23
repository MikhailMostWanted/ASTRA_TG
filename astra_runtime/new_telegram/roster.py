from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from astra_runtime.chat_identity import ChatIdentity
from astra_runtime.new_telegram.config import NewTelegramRuntimeConfig
from astra_runtime.new_telegram.transport import (
    NewTelegramDialogMessage,
    NewTelegramDialogSummary,
    NewTelegramRosterClientFactory,
    build_new_telegram_roster_client,
)
from astra_runtime.status import RuntimeUnavailableError
from fullaccess.cache import avatar_base_path, find_cached_variant
from models import Chat, Message
from services.digest_target import DigestTargetService
from storage.repositories import ChatRepository, MessageRepository, SettingRepository


DEFAULT_DIALOG_LIMIT = 250
DEFAULT_SNAPSHOT_TTL_SECONDS = 6
DEFAULT_FAILURE_COOLDOWN_SECONDS = 20


@dataclass(frozen=True, slots=True)
class NewTelegramChatRosterSnapshot:
    items: tuple[dict[str, Any], ...]
    refreshed_at: datetime


@dataclass(slots=True)
class NewTelegramChatRoster:
    config: NewTelegramRuntimeConfig
    session_factory: async_sessionmaker[AsyncSession] | None = None
    client_factory: NewTelegramRosterClientFactory = build_new_telegram_roster_client
    dialog_limit: int = DEFAULT_DIALOG_LIMIT
    snapshot_ttl_seconds: int = DEFAULT_SNAPSHOT_TTL_SECONDS
    failure_cooldown_seconds: int = DEFAULT_FAILURE_COOLDOWN_SECONDS
    _snapshot: NewTelegramChatRosterSnapshot | None = field(default=None, init=False, repr=False)
    _refresh_lock: object = field(init=False, repr=False)
    _last_error: str | None = field(default=None, init=False)
    _last_error_at: datetime | None = field(default=None, init=False)
    _last_success_at: datetime | None = field(default=None, init=False)
    _degraded_until: datetime | None = field(default=None, init=False)

    def __post_init__(self) -> None:
        import asyncio

        self._refresh_lock = asyncio.Lock()

    def route_ready(self) -> bool:
        if self.session_factory is None:
            return False
        if self._degraded_until is None:
            return True
        return self._degraded_until <= datetime.now(UTC)

    def route_reason(self) -> str | None:
        if self.session_factory is None:
            return "New Telegram chat roster requires local storage runtime."
        if self._degraded_until is not None and self._degraded_until > datetime.now(UTC):
            return self._last_error or "New Telegram chat roster is temporarily degraded."
        return None

    def status_payload(self) -> dict[str, Any]:
        return {
            "lastSuccessAt": _serialize_datetime(self._last_success_at),
            "lastError": self._last_error,
            "lastErrorAt": _serialize_datetime(self._last_error_at),
            "degradedUntil": _serialize_datetime(self._degraded_until),
            "routeReady": self.route_ready(),
            "routeReason": self.route_reason(),
        }

    async def list_chats(
        self,
        *,
        search: str | None = None,
        filter_key: str = "all",
        sort_key: str = "activity",
    ) -> dict[str, Any]:
        snapshot = await self._load_snapshot()
        items = list(snapshot.items)
        items = _apply_search(items, search=search)
        items = _apply_filter(items, filter_key=filter_key)
        items = _apply_sort(items, sort_key=sort_key)
        return {
            "items": items,
            "count": len(items),
            "filters": {"active": filter_key, "sort": sort_key, "search": search or ""},
            "refreshedAt": _serialize_datetime(snapshot.refreshed_at),
            "runtimeMeta": self.status_payload(),
        }

    async def _load_snapshot(self) -> NewTelegramChatRosterSnapshot:
        if not self.route_ready():
            raise RuntimeUnavailableError(self.route_reason() or "New Telegram chat roster is not route-ready.")

        snapshot = self._snapshot
        if snapshot is not None and not _is_snapshot_stale(snapshot.refreshed_at, ttl_seconds=self.snapshot_ttl_seconds):
            return snapshot

        async with self._refresh_lock:
            snapshot = self._snapshot
            if snapshot is not None and not _is_snapshot_stale(
                snapshot.refreshed_at,
                ttl_seconds=self.snapshot_ttl_seconds,
            ):
                return snapshot
            return await self._refresh_snapshot()

    async def _refresh_snapshot(self) -> NewTelegramChatRosterSnapshot:
        if self.session_factory is None:
            raise RuntimeUnavailableError("New Telegram chat roster requires local storage runtime.")

        try:
            dialogs = await self.client_factory(self.config).list_dialogs(limit=self.dialog_limit)
            items = await self._build_items(dialogs)
        except Exception as error:
            now = datetime.now(UTC)
            self._last_error = str(error)
            self._last_error_at = now
            self._degraded_until = now + timedelta(seconds=self.failure_cooldown_seconds)
            raise RuntimeUnavailableError(
                f"New Telegram chat roster временно недоступен: {error}"
            ) from error

        refreshed_at = datetime.now(UTC)
        snapshot = NewTelegramChatRosterSnapshot(
            items=tuple(items),
            refreshed_at=refreshed_at,
        )
        self._snapshot = snapshot
        self._last_success_at = refreshed_at
        self._last_error = None
        self._last_error_at = None
        self._degraded_until = None
        return snapshot

    async def _build_items(
        self,
        dialogs: tuple[NewTelegramDialogSummary, ...],
    ) -> list[dict[str, Any]]:
        if self.session_factory is None:
            return []

        runtime_chat_ids = [dialog.telegram_chat_id for dialog in dialogs if dialog.telegram_chat_id != 0]
        async with self.session_factory() as session:
            chat_repository = ChatRepository(session)
            message_repository = MessageRepository(session)
            setting_repository = SettingRepository(session)
            existing_chats = await chat_repository.list_by_telegram_chat_ids(runtime_chat_ids)
            local_chat_ids = [chat.id for chat in existing_chats.values()]
            message_counts = await message_repository.count_messages_by_chat(chat_ids=local_chat_ids)
            last_messages = await message_repository.get_last_messages_by_chat(chat_ids=local_chat_ids)
            digest_target = await DigestTargetService(setting_repository).get_target()

        items: list[dict[str, Any]] = []
        for dialog in dialogs:
            local_chat = existing_chats.get(dialog.telegram_chat_id)
            local_last_message = (
                last_messages.get(local_chat.id)
                if local_chat is not None
                else None
            )
            local_message_count = (
                message_counts.get(local_chat.id, 0)
                if local_chat is not None
                else 0
            )
            items.append(
                _serialize_runtime_roster_item(
                    dialog,
                    local_chat=local_chat,
                    local_message_count=local_message_count,
                    local_last_message=local_last_message,
                    is_digest_target=digest_target.chat_id == dialog.telegram_chat_id,
                    asset_session_files=self.config.asset_session_files,
                )
            )
        return items


def _serialize_runtime_roster_item(
    dialog: NewTelegramDialogSummary,
    *,
    local_chat: Chat | None,
    local_message_count: int,
    local_last_message: Message | None,
    is_digest_target: bool,
    asset_session_files: tuple[Path, ...],
) -> dict[str, Any]:
    identity = ChatIdentity(
        runtime_chat_id=dialog.telegram_chat_id,
        local_chat_id=local_chat.id if local_chat is not None else None,
    )
    avatar_url = _build_avatar_url(
        asset_session_files,
        telegram_chat_id=dialog.telegram_chat_id,
    )
    runtime_preview = _runtime_message_preview(dialog.last_message)
    runtime_last_activity_at = _serialize_datetime(dialog.last_activity_at)
    local_last_message_at = _serialize_datetime(local_last_message.sent_at if local_last_message is not None else None)
    local_preview = _message_preview(
        local_last_message.raw_text if local_last_message is not None else None,
        fallback="Сообщений пока нет",
    )

    return {
        **identity.to_payload(),
        "identity": identity.to_payload(),
        "reference": _build_reference(dialog.username, dialog.telegram_chat_id),
        "title": local_chat.title if local_chat is not None else dialog.title,
        "handle": local_chat.handle if local_chat is not None else dialog.username,
        "type": local_chat.type if local_chat is not None else dialog.chat_type,
        "enabled": bool(local_chat.is_enabled) if local_chat is not None else False,
        "category": local_chat.category if local_chat is not None else "runtime_only",
        "summarySchedule": local_chat.summary_schedule if local_chat is not None else None,
        "replyAssistEnabled": bool(local_chat.reply_assist_enabled) if local_chat is not None else False,
        "autoReplyMode": local_chat.auto_reply_mode if local_chat is not None else None,
        "excludeFromMemory": bool(local_chat.exclude_from_memory) if local_chat is not None else False,
        "excludeFromDigest": bool(local_chat.exclude_from_digest) if local_chat is not None else False,
        "isDigestTarget": is_digest_target,
        "messageCount": local_message_count,
        "lastMessageAt": local_last_message_at,
        "lastMessageId": local_last_message.id if local_last_message is not None else None,
        "lastTelegramMessageId": (
            local_last_message.telegram_message_id if local_last_message is not None else None
        ),
        "lastMessagePreview": local_preview,
        "lastDirection": local_last_message.direction if local_last_message is not None else None,
        "lastSourceAdapter": local_last_message.source_adapter if local_last_message is not None else None,
        "lastSenderName": local_last_message.sender_name if local_last_message is not None else None,
        "avatarUrl": avatar_url,
        "syncStatus": _resolve_sync_status(
            local_message_count=local_message_count,
            local_last_message=local_last_message,
        ),
        "memory": None,
        "favorite": False,
        "rosterSource": "new",
        "rosterLastActivityAt": runtime_last_activity_at,
        "rosterLastMessagePreview": runtime_preview,
        "rosterLastDirection": dialog.last_message.direction if dialog.last_message is not None else None,
        "rosterLastSenderName": dialog.last_message.sender_name if dialog.last_message is not None else None,
        "rosterFreshness": _build_roster_freshness(dialog.last_activity_at),
        "unreadCount": dialog.unread_count,
        "unreadMentionCount": dialog.unread_mentions_count,
        "pinned": dialog.pinned,
        "muted": dialog.muted,
        "archived": dialog.archived,
        "assetHints": {
            "avatarCached": avatar_url is not None,
            "avatarSource": "cache" if avatar_url is not None else None,
        },
    }


def _apply_search(items: list[dict[str, Any]], *, search: str | None) -> list[dict[str, Any]]:
    normalized_query = (search or "").strip().casefold()
    if not normalized_query:
        return items

    filtered: list[dict[str, Any]] = []
    for item in items:
        candidates = (
            item.get("title"),
            item.get("handle"),
            item.get("reference"),
            item.get("chatKey"),
            item.get("runtimeChatId"),
            item.get("localChatId"),
            item.get("rosterLastMessagePreview"),
        )
        if any(normalized_query in str(candidate).casefold() for candidate in candidates if candidate is not None):
            filtered.append(item)
    return filtered


def _apply_filter(items: list[dict[str, Any]], *, filter_key: str) -> list[dict[str, Any]]:
    if filter_key == "enabled":
        return [item for item in items if item.get("enabled")]
    if filter_key == "reply":
        return [
            item
            for item in items
            if item.get("type") != "channel" and int(item.get("messageCount") or 0) >= 3
        ]
    if filter_key == "fullaccess":
        return [item for item in items if item.get("syncStatus") == "fullaccess"]
    return items


def _apply_sort(items: list[dict[str, Any]], *, sort_key: str) -> list[dict[str, Any]]:
    if sort_key == "title":
        items.sort(
            key=lambda item: (
                not bool(item.get("pinned")),
                item.get("title", "").casefold(),
                int(item.get("runtimeChatId") or 0),
            )
        )
        return items

    if sort_key == "messages":
        items.sort(
            key=lambda item: (
                not bool(item.get("pinned")),
                -(int(item.get("messageCount") or 0)),
                item.get("title", "").casefold(),
                int(item.get("runtimeChatId") or 0),
            )
        )
        return items

    items.sort(key=lambda item: item.get("title", "").casefold())
    items.sort(key=lambda item: item.get("rosterLastActivityAt") or "", reverse=True)
    items.sort(key=lambda item: item.get("rosterLastActivityAt") is None)
    items.sort(key=lambda item: bool(item.get("archived")))
    items.sort(key=lambda item: not bool(item.get("pinned")))
    return items


def _is_snapshot_stale(refreshed_at: datetime, *, ttl_seconds: int) -> bool:
    return datetime.now(UTC) - refreshed_at > timedelta(seconds=ttl_seconds)


def _build_reference(username: str | None, telegram_chat_id: int) -> str:
    if username:
        return f"@{username}"
    return str(telegram_chat_id)


def _runtime_message_preview(message: NewTelegramDialogMessage | None) -> str:
    if message is None:
        return "Активности пока нет"
    if message.text.strip():
        return _message_preview(message.text, fallback="Без текста")
    if message.has_media:
        media_type = message.media_type or "media"
        return f"Медиа: {media_type}"
    return "Без текста"


def _resolve_sync_status(
    *,
    local_message_count: int,
    local_last_message: Message | None,
) -> str:
    last_source_adapter = local_last_message.source_adapter if local_last_message is not None else None
    if last_source_adapter == "fullaccess":
        return "fullaccess"
    if local_message_count > 0:
        return "local"
    return "empty"


def _build_avatar_url(session_files: tuple[Path, ...], *, telegram_chat_id: int) -> str | None:
    if telegram_chat_id == 0:
        return None
    for session_file in session_files:
        cached = find_cached_variant(avatar_base_path(session_file, telegram_chat_id))
        if cached is None:
            continue
        version = int(cached.stat().st_mtime)
        return f"/api/media/avatars/{telegram_chat_id}?v={version}"
    return None


def _message_preview(text: str | None, *, fallback: str) -> str:
    cleaned = (text or "").strip()
    if not cleaned:
        return fallback
    compact = " ".join(cleaned.split())
    if len(compact) <= 140:
        return compact
    return f"{compact[:137].rstrip()}..."


def _build_roster_freshness(last_activity_at: datetime | None) -> dict[str, Any]:
    if last_activity_at is None:
        return {
            "mode": "empty",
            "label": "без активности",
            "lastActivityAt": None,
        }
    age = datetime.now(UTC) - last_activity_at
    if age <= timedelta(hours=12):
        mode = "fresh"
        label = "свежее"
    elif age <= timedelta(days=3):
        mode = "recent"
        label = "недавнее"
    else:
        mode = "stale"
        label = "давно без апдейта"
    return {
        "mode": mode,
        "label": label,
        "lastActivityAt": _serialize_datetime(last_activity_at),
    }


def _serialize_datetime(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC).isoformat()
    return value.astimezone(UTC).isoformat()
