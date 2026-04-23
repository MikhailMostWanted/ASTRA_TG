from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from astra_runtime.chat_identity import ChatIdentity, parse_runtime_only_chat_id
from astra_runtime.message_identity import MessageIdentity, build_message_key
from astra_runtime.new_telegram.config import NewTelegramRuntimeConfig
from astra_runtime.new_telegram.roster import (
    _build_avatar_url,
    _build_reference,
    _build_roster_freshness,
    _message_preview,
    _serialize_datetime,
)
from astra_runtime.new_telegram.transport import (
    NewTelegramChatSummary,
    NewTelegramHistoryClientFactory,
    NewTelegramRemoteMessage,
    build_new_telegram_history_client,
)
from astra_runtime.status import RuntimeUnavailableError
from fullaccess.cache import find_cached_variant, media_preview_base_path
from services.reply_signal import (
    has_emotional_signal,
    has_follow_up_commitment_signal,
    has_open_loop_signal,
    has_question_signal,
    has_request_signal,
    is_weak_reply_signal,
    pick_focus_label,
)
from storage.repositories import ChatRepository, MessageRepository


DEFAULT_HISTORY_TAIL_LIMIT = 80
DEFAULT_HISTORY_SNAPSHOT_TTL_SECONDS = 4
DEFAULT_HISTORY_FAILURE_COOLDOWN_SECONDS = 20
DEFAULT_INCREMENTAL_FETCH_LIMIT = 24
MAX_HISTORY_CACHE_MESSAGES = 240


@dataclass(frozen=True, slots=True)
class ResolvedRuntimeChat:
    requested_chat_id: int
    runtime_chat_id: int
    local_chat_id: int | None


@dataclass(slots=True)
class CachedHistorySnapshot:
    chat: NewTelegramChatSummary
    messages: tuple[NewTelegramRemoteMessage, ...]
    refreshed_at: datetime

    @property
    def newest_runtime_message_id(self) -> int | None:
        if not self.messages:
            return None
        return self.messages[-1].telegram_message_id

    @property
    def oldest_runtime_message_id(self) -> int | None:
        if not self.messages:
            return None
        return self.messages[0].telegram_message_id


@dataclass(slots=True)
class LocalHistoryContext:
    local_chat: Any | None
    local_message_count: int
    local_messages_by_runtime_id: dict[int, Any]


@dataclass(slots=True)
class NewTelegramMessageHistory:
    config: NewTelegramRuntimeConfig
    session_factory: async_sessionmaker[AsyncSession] | None = None
    client_factory: NewTelegramHistoryClientFactory = build_new_telegram_history_client
    tail_limit: int = DEFAULT_HISTORY_TAIL_LIMIT
    snapshot_ttl_seconds: int = DEFAULT_HISTORY_SNAPSHOT_TTL_SECONDS
    failure_cooldown_seconds: int = DEFAULT_HISTORY_FAILURE_COOLDOWN_SECONDS
    incremental_fetch_limit: int = DEFAULT_INCREMENTAL_FETCH_LIMIT
    _snapshot_by_chat: dict[int, CachedHistorySnapshot] = field(default_factory=dict, init=False, repr=False)
    _refresh_locks: dict[int, object] = field(default_factory=dict, init=False, repr=False)
    _lock_factory: Any = field(init=False, repr=False)
    _last_error: str | None = field(default=None, init=False)
    _last_error_at: datetime | None = field(default=None, init=False)
    _last_success_at: datetime | None = field(default=None, init=False)
    _degraded_until: datetime | None = field(default=None, init=False)

    def __post_init__(self) -> None:
        import asyncio

        self._lock_factory = asyncio.Lock

    def route_ready(self) -> bool:
        if self.session_factory is None:
            return False
        if self._degraded_until is None:
            return True
        return self._degraded_until <= datetime.now(UTC)

    def route_reason(self) -> str | None:
        if self.session_factory is None:
            return "New Telegram message history requires local storage runtime."
        if self._degraded_until is not None and self._degraded_until > datetime.now(UTC):
            return self._last_error or "New Telegram message history is temporarily degraded."
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

    async def get_chat_messages(
        self,
        chat_id: int,
        *,
        limit: int = 80,
        before_runtime_message_id: int | None = None,
    ) -> dict[str, Any]:
        resolved = await self._resolve_chat(chat_id)
        if before_runtime_message_id is None:
            snapshot, updated_now, sync_trigger, sync_error = await self._load_snapshot(
                runtime_chat_id=resolved.runtime_chat_id,
                limit=max(1, limit),
            )
            chat = snapshot.chat
            remote_messages = snapshot.messages[-max(1, limit) :]
            refreshed_at = snapshot.refreshed_at
        else:
            chat, remote_messages = await self._fetch_history(
                resolved.runtime_chat_id,
                limit=max(1, limit),
                max_message_id=before_runtime_message_id,
            )
            refreshed_at = datetime.now(UTC)
            updated_now = True
            sync_trigger = "runtime_history_page"
            sync_error = None

        local_context = await self._load_local_context(
            runtime_chat_id=resolved.runtime_chat_id,
            remote_messages=remote_messages,
        )
        message_payloads = self._serialize_messages(
            remote_messages=remote_messages,
            runtime_chat_id=resolved.runtime_chat_id,
            local_context=local_context,
            requested_chat_id=chat_id,
        )
        return {
            "chat": self._serialize_chat(
                chat=chat,
                local_context=local_context,
                remote_messages=remote_messages,
            ),
            "messages": message_payloads,
            "history": self._build_history_payload(message_payloads, limit=limit),
            "status": self._build_status_payload(
                source_backend="new",
                local_context=local_context,
                runtime_chat_id=resolved.runtime_chat_id,
                message_payloads=message_payloads,
                refreshed_at=refreshed_at,
                updated_now=updated_now,
                sync_trigger=sync_trigger,
                sync_error=sync_error,
                reply_context_available=False,
                has_more_before=bool(message_payloads and message_payloads[0]["runtimeMessageId"] > 1),
            ),
            "refreshedAt": _serialize_datetime(refreshed_at),
        }

    async def get_chat_workspace(
        self,
        chat_id: int,
        *,
        limit: int = 80,
    ) -> dict[str, Any]:
        resolved = await self._resolve_chat(chat_id)
        snapshot, updated_now, sync_trigger, sync_error = await self._load_snapshot(
            runtime_chat_id=resolved.runtime_chat_id,
            limit=max(1, limit),
        )
        local_context = await self._load_local_context(
            runtime_chat_id=resolved.runtime_chat_id,
            remote_messages=snapshot.messages,
        )
        visible_messages = snapshot.messages[-max(1, limit) :]
        message_payloads = self._serialize_messages(
            remote_messages=visible_messages,
            runtime_chat_id=resolved.runtime_chat_id,
            local_context=local_context,
            requested_chat_id=chat_id,
        )
        reply_context = self._build_reply_context(
            message_payloads=message_payloads,
            source_backend="new",
        )
        refreshed_at = snapshot.refreshed_at
        return {
            "chat": self._serialize_chat(
                chat=snapshot.chat,
                local_context=local_context,
                remote_messages=visible_messages,
            ),
            "messages": message_payloads,
            "history": self._build_history_payload(message_payloads, limit=limit),
            "replyContext": reply_context,
            "reply": self._build_placeholder_reply(
                chat=snapshot.chat,
                local_context=local_context,
                reply_context=reply_context,
            ),
            "autopilot": None,
            "freshness": self._build_freshness_payload(
                chat=snapshot.chat,
                refreshed_at=refreshed_at,
                updated_now=updated_now,
                sync_trigger=sync_trigger,
                sync_error=sync_error,
            ),
            "status": self._build_status_payload(
                source_backend="new",
                local_context=local_context,
                runtime_chat_id=resolved.runtime_chat_id,
                message_payloads=message_payloads,
                refreshed_at=refreshed_at,
                updated_now=updated_now,
                sync_trigger=sync_trigger,
                sync_error=sync_error,
                reply_context_available=bool(reply_context.get("available")),
                has_more_before=bool(message_payloads and message_payloads[0]["runtimeMessageId"] > 1),
            ),
            "refreshedAt": _serialize_datetime(refreshed_at),
        }

    async def _resolve_chat(self, chat_id: int) -> ResolvedRuntimeChat:
        if self.session_factory is None:
            raise RuntimeUnavailableError("New Telegram message history requires local storage runtime.")

        async with self.session_factory() as session:
            chat_repository = ChatRepository(session)
            if chat_id > 0:
                local_chat = await chat_repository.get_by_id(chat_id)
                if local_chat is None:
                    raise LookupError("Чат не найден.")
                return ResolvedRuntimeChat(
                    requested_chat_id=chat_id,
                    runtime_chat_id=int(local_chat.telegram_chat_id),
                    local_chat_id=local_chat.id,
                )

            runtime_chat_id = parse_runtime_only_chat_id(chat_id)
            if runtime_chat_id is None:
                raise LookupError("Чат не найден.")

            local_chat = await chat_repository.get_by_telegram_chat_id(runtime_chat_id)
            return ResolvedRuntimeChat(
                requested_chat_id=chat_id,
                runtime_chat_id=runtime_chat_id,
                local_chat_id=local_chat.id if local_chat is not None else None,
            )

    async def _load_snapshot(
        self,
        *,
        runtime_chat_id: int,
        limit: int,
    ) -> tuple[CachedHistorySnapshot, bool, str, str | None]:
        if not self.route_ready():
            raise RuntimeUnavailableError(self.route_reason() or "New Telegram message history is not route-ready.")

        snapshot = self._snapshot_by_chat.get(runtime_chat_id)
        if (
            snapshot is not None
            and not _is_snapshot_stale(snapshot.refreshed_at, ttl_seconds=self.snapshot_ttl_seconds)
            and len(snapshot.messages) >= limit
        ):
            return snapshot, False, "runtime_cache", None

        lock = self._refresh_locks.setdefault(runtime_chat_id, self._lock_factory())
        async with lock:
            snapshot = self._snapshot_by_chat.get(runtime_chat_id)
            if (
                snapshot is not None
                and not _is_snapshot_stale(snapshot.refreshed_at, ttl_seconds=self.snapshot_ttl_seconds)
                and len(snapshot.messages) >= limit
            ):
                return snapshot, False, "runtime_cache", None

            try:
                refreshed = await self._refresh_snapshot(
                    runtime_chat_id=runtime_chat_id,
                    existing=snapshot,
                    limit=limit,
                )
            except Exception as error:
                self._record_error(str(error))
                cached = self._snapshot_by_chat.get(runtime_chat_id)
                if cached is None:
                    raise RuntimeUnavailableError(
                        f"New Telegram message history временно недоступен: {error}"
                    ) from error
                return cached, False, "runtime_cache_fallback", str(error)

            self._snapshot_by_chat[runtime_chat_id] = refreshed
            self._record_success(refreshed.refreshed_at)
            return refreshed, True, "runtime_poll", None

    async def _refresh_snapshot(
        self,
        *,
        runtime_chat_id: int,
        existing: CachedHistorySnapshot | None,
        limit: int,
    ) -> CachedHistorySnapshot:
        if existing is None or len(existing.messages) < limit:
            chat, remote_messages = await self._fetch_history(
                runtime_chat_id,
                limit=max(limit, self.tail_limit),
            )
            return CachedHistorySnapshot(
                chat=chat,
                messages=_trim_messages(remote_messages),
                refreshed_at=datetime.now(UTC),
            )

        newest_runtime_message_id = existing.newest_runtime_message_id
        if newest_runtime_message_id is None:
            chat, remote_messages = await self._fetch_history(
                runtime_chat_id,
                limit=max(limit, self.tail_limit),
            )
            return CachedHistorySnapshot(
                chat=chat,
                messages=_trim_messages(remote_messages),
                refreshed_at=datetime.now(UTC),
            )

        chat, incremental = await self._fetch_history(
            runtime_chat_id,
            limit=max(limit, self.incremental_fetch_limit),
            min_message_id=newest_runtime_message_id,
        )
        merged_messages = _merge_messages(existing.messages, incremental)
        return CachedHistorySnapshot(
            chat=chat,
            messages=_trim_messages(merged_messages),
            refreshed_at=datetime.now(UTC),
        )

    async def _fetch_history(
        self,
        reference: int | str,
        *,
        limit: int,
        min_message_id: int | None = None,
        max_message_id: int | None = None,
    ) -> tuple[NewTelegramChatSummary, tuple[NewTelegramRemoteMessage, ...]]:
        return await self.client_factory(self.config).fetch_history(
            reference,
            limit=max(1, limit),
            min_message_id=min_message_id,
            max_message_id=max_message_id,
        )

    async def _load_local_context(
        self,
        *,
        runtime_chat_id: int,
        remote_messages: tuple[NewTelegramRemoteMessage, ...],
    ) -> LocalHistoryContext:
        if self.session_factory is None:
            return LocalHistoryContext(
                local_chat=None,
                local_message_count=0,
                local_messages_by_runtime_id={},
            )

        async with self.session_factory() as session:
            chat_repository = ChatRepository(session)
            local_chat = await chat_repository.get_by_telegram_chat_id(runtime_chat_id)
            if local_chat is None:
                return LocalHistoryContext(
                    local_chat=None,
                    local_message_count=0,
                    local_messages_by_runtime_id={},
                )

            message_repository = MessageRepository(session)
            runtime_message_ids = {
                message.telegram_message_id
                for message in remote_messages
            }
            runtime_message_ids.update(
                message.reply_to_telegram_message_id
                for message in remote_messages
                if message.reply_to_telegram_message_id is not None
            )
            local_messages = await message_repository.list_by_chat_and_telegram_message_ids(
                chat_id=local_chat.id,
                telegram_message_ids=tuple(runtime_message_ids),
            )
            return LocalHistoryContext(
                local_chat=local_chat,
                local_message_count=await message_repository.count_messages_for_chat(chat_id=local_chat.id),
                local_messages_by_runtime_id=local_messages,
            )

    def _serialize_chat(
        self,
        *,
        chat: NewTelegramChatSummary,
        local_context: LocalHistoryContext,
        remote_messages: tuple[NewTelegramRemoteMessage, ...],
    ) -> dict[str, Any]:
        identity = ChatIdentity(
            runtime_chat_id=chat.telegram_chat_id,
            local_chat_id=local_context.local_chat.id if local_context.local_chat is not None else None,
        )
        last_remote_message = remote_messages[-1] if remote_messages else None
        last_local_message = (
            local_context.local_messages_by_runtime_id.get(last_remote_message.telegram_message_id)
            if last_remote_message is not None
            else None
        )
        avatar_url = _build_avatar_url(
            self.config.asset_session_files,
            telegram_chat_id=chat.telegram_chat_id,
        )
        remote_preview = _remote_message_preview(last_remote_message)
        message_count = max(local_context.local_message_count, len(remote_messages))

        return {
            **identity.to_payload(),
            "identity": identity.to_payload(),
            "telegramChatId": chat.telegram_chat_id,
            "reference": _build_reference(chat.username, chat.telegram_chat_id),
            "title": local_context.local_chat.title if local_context.local_chat is not None else chat.title,
            "handle": local_context.local_chat.handle if local_context.local_chat is not None else chat.username,
            "type": local_context.local_chat.type if local_context.local_chat is not None else chat.chat_type,
            "enabled": bool(local_context.local_chat.is_enabled) if local_context.local_chat is not None else False,
            "category": local_context.local_chat.category if local_context.local_chat is not None else "runtime_only",
            "summarySchedule": local_context.local_chat.summary_schedule if local_context.local_chat is not None else None,
            "replyAssistEnabled": (
                bool(local_context.local_chat.reply_assist_enabled)
                if local_context.local_chat is not None
                else False
            ),
            "autoReplyMode": local_context.local_chat.auto_reply_mode if local_context.local_chat is not None else None,
            "excludeFromMemory": (
                bool(local_context.local_chat.exclude_from_memory)
                if local_context.local_chat is not None
                else False
            ),
            "excludeFromDigest": (
                bool(local_context.local_chat.exclude_from_digest)
                if local_context.local_chat is not None
                else False
            ),
            "isDigestTarget": False,
            "messageCount": message_count,
            "lastMessageAt": _serialize_datetime(last_remote_message.sent_at if last_remote_message is not None else None),
            "lastMessageId": last_local_message.id if last_local_message is not None else None,
            "lastMessageKey": (
                build_message_key(chat.telegram_chat_id, last_remote_message.telegram_message_id)
                if last_remote_message is not None
                else None
            ),
            "lastTelegramMessageId": (
                last_remote_message.telegram_message_id if last_remote_message is not None else None
            ),
            "lastMessagePreview": remote_preview,
            "lastDirection": last_remote_message.direction if last_remote_message is not None else None,
            "lastSourceAdapter": "new_runtime" if last_remote_message is not None else None,
            "lastSenderName": last_remote_message.sender_name if last_remote_message is not None else None,
            "avatarUrl": avatar_url,
            "syncStatus": "runtime" if last_remote_message is not None else "empty",
            "memory": None,
            "favorite": False,
            "rosterSource": "new",
            "rosterLastActivityAt": _serialize_datetime(last_remote_message.sent_at if last_remote_message is not None else None),
            "rosterLastMessageKey": (
                build_message_key(chat.telegram_chat_id, last_remote_message.telegram_message_id)
                if last_remote_message is not None
                else None
            ),
            "rosterLastMessagePreview": remote_preview,
            "rosterLastDirection": last_remote_message.direction if last_remote_message is not None else None,
            "rosterLastSenderName": last_remote_message.sender_name if last_remote_message is not None else None,
            "rosterFreshness": _build_roster_freshness(last_remote_message.sent_at if last_remote_message is not None else None),
            "unreadCount": 0,
            "unreadMentionCount": 0,
            "pinned": False,
            "muted": False,
            "archived": False,
            "assetHints": {
                "avatarCached": avatar_url is not None or chat.avatar_cached,
                "avatarSource": "cache" if avatar_url is not None or chat.avatar_cached else None,
            },
        }

    def _serialize_messages(
        self,
        *,
        remote_messages: tuple[NewTelegramRemoteMessage, ...],
        runtime_chat_id: int,
        local_context: LocalHistoryContext,
        requested_chat_id: int,
    ) -> list[dict[str, Any]]:
        payloads: list[dict[str, Any]] = []
        resolved_chat_id = (
            local_context.local_chat.id
            if local_context.local_chat is not None
            else requested_chat_id
        )
        for remote_message in remote_messages:
            local_message = local_context.local_messages_by_runtime_id.get(remote_message.telegram_message_id)
            identity = MessageIdentity(
                runtime_chat_id=runtime_chat_id,
                runtime_message_id=remote_message.telegram_message_id,
                local_message_id=local_message.id if local_message is not None else None,
            )
            reply_to_local_message = (
                local_context.local_messages_by_runtime_id.get(remote_message.reply_to_telegram_message_id)
                if remote_message.reply_to_telegram_message_id is not None
                else None
            )
            payloads.append(
                {
                    "id": local_message.id if local_message is not None else remote_message.telegram_message_id,
                    **identity.to_payload(),
                    "telegramMessageId": remote_message.telegram_message_id,
                    "chatId": resolved_chat_id,
                    "direction": remote_message.direction,
                    "sourceAdapter": "new_runtime",
                    "sourceType": remote_message.source_type,
                    "senderId": remote_message.sender_id,
                    "senderName": remote_message.sender_name,
                    "sentAt": _serialize_datetime(remote_message.sent_at),
                    "text": remote_message.raw_text,
                    "normalizedText": remote_message.normalized_text,
                    "replyToMessageId": reply_to_local_message.id if reply_to_local_message is not None else None,
                    "replyToLocalMessageId": reply_to_local_message.id if reply_to_local_message is not None else None,
                    "replyToRuntimeMessageId": remote_message.reply_to_telegram_message_id,
                    "replyToMessageKey": (
                        build_message_key(runtime_chat_id, remote_message.reply_to_telegram_message_id)
                        if remote_message.reply_to_telegram_message_id is not None
                        else None
                    ),
                    "hasMedia": remote_message.has_media,
                    "mediaType": remote_message.media_type,
                    "mediaPreviewUrl": _build_media_preview_url(
                        self.config.asset_session_files,
                        telegram_chat_id=runtime_chat_id,
                        telegram_message_id=remote_message.telegram_message_id,
                    ),
                    "forwardInfo": (
                        remote_message.forward_info
                        if isinstance(remote_message.forward_info, (dict, list))
                        else None
                    ),
                    "entities": (
                        remote_message.entities_json
                        if isinstance(remote_message.entities_json, (dict, list))
                        else None
                    ),
                    "preview": _remote_message_preview(remote_message),
                }
            )
        return payloads

    def _build_history_payload(
        self,
        message_payloads: list[dict[str, Any]],
        *,
        limit: int,
    ) -> dict[str, Any]:
        oldest = message_payloads[0] if message_payloads else None
        newest = message_payloads[-1] if message_payloads else None
        oldest_runtime_message_id = oldest.get("runtimeMessageId") if oldest is not None else None
        return {
            "limit": max(1, limit),
            "returnedCount": len(message_payloads),
            "hasMoreBefore": bool(
                oldest_runtime_message_id is not None and int(oldest_runtime_message_id) > 1
            ),
            "beforeRuntimeMessageId": int(oldest_runtime_message_id) if oldest_runtime_message_id is not None else None,
            "oldestMessageKey": oldest.get("messageKey") if oldest is not None else None,
            "newestMessageKey": newest.get("messageKey") if newest is not None else None,
            "oldestRuntimeMessageId": int(oldest_runtime_message_id) if oldest_runtime_message_id is not None else None,
            "newestRuntimeMessageId": (
                int(newest["runtimeMessageId"]) if newest is not None and newest.get("runtimeMessageId") is not None else None
            ),
        }

    def _build_reply_context(
        self,
        *,
        message_payloads: list[dict[str, Any]],
        source_backend: str,
    ) -> dict[str, Any]:
        target_message = _pick_focus_message(message_payloads)
        if target_message is None:
            return {
                "available": False,
                "sourceBackend": source_backend,
                "focusLabel": None,
                "focusReason": "Не вижу входящего сигнала, на который стоит опираться.",
                "replyOpportunityMode": None,
                "replyOpportunityReason": None,
                "sourceMessageKey": None,
                "sourceRuntimeMessageId": None,
                "sourceLocalMessageId": None,
                "sourceSenderName": None,
                "sourceMessagePreview": None,
                "sourceSentAt": None,
                "draftScopeBasis": None,
                "draftScopeKey": None,
            }

        latest_message = message_payloads[-1] if message_payloads else None
        latest_runtime_message_id = latest_message.get("runtimeMessageId") if latest_message is not None else None
        target_runtime_message_id = target_message.get("runtimeMessageId")
        later_messages = [
            message
            for message in message_payloads
            if (
                message.get("runtimeMessageId") is not None
                and target_runtime_message_id is not None
                and int(message["runtimeMessageId"]) > int(target_runtime_message_id)
            )
        ]
        later_outbound = [
            message
            for message in later_messages
            if message.get("direction") == "outbound"
        ]

        if latest_runtime_message_id == target_runtime_message_id:
            reply_opportunity_mode = "direct_reply"
            reply_opportunity_reason = "Последний входящий сигнал ещё без ответа в текущем хвосте."
        elif any(
            has_follow_up_commitment_signal(message.get("text"))
            for message in later_outbound
        ):
            reply_opportunity_mode = "follow_up_after_self"
            reply_opportunity_reason = (
                "После этого входящего уже был исходящий ответ, но по хвосту тема всё ещё выглядит незакрытой."
            )
        elif later_outbound:
            reply_opportunity_mode = "pending_context"
            reply_opportunity_reason = (
                "После фокусного входящего уже были исходящие сообщения, но лучше держать его как рабочий контекст."
            )
        else:
            reply_opportunity_mode = "direct_reply"
            reply_opportunity_reason = "Последний значимый входящий фрагмент остаётся лучшей опорой для ответа."

        focus_reason = _build_focus_reason(target_message, reply_opportunity_reason=reply_opportunity_reason)
        draft_scope_basis = {
            "sourceMessageKey": target_message.get("messageKey"),
            "sourceMessageId": target_message.get("localMessageId"),
            "runtimeMessageId": target_message.get("runtimeMessageId"),
            "focusLabel": pick_focus_label(target_message.get("text")),
            "sourceMessagePreview": target_message.get("preview"),
            "replyOpportunityMode": reply_opportunity_mode,
        }
        return {
            "available": True,
            "sourceBackend": source_backend,
            "focusLabel": draft_scope_basis["focusLabel"],
            "focusReason": focus_reason,
            "replyOpportunityMode": reply_opportunity_mode,
            "replyOpportunityReason": reply_opportunity_reason,
            "sourceMessageKey": target_message.get("messageKey"),
            "sourceRuntimeMessageId": target_message.get("runtimeMessageId"),
            "sourceLocalMessageId": target_message.get("localMessageId"),
            "sourceSenderName": target_message.get("senderName"),
            "sourceMessagePreview": target_message.get("preview"),
            "sourceSentAt": target_message.get("sentAt"),
            "draftScopeBasis": draft_scope_basis,
            "draftScopeKey": _build_draft_scope_key(draft_scope_basis),
        }

    def _build_placeholder_reply(
        self,
        *,
        chat: NewTelegramChatSummary,
        local_context: LocalHistoryContext,
        reply_context: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "kind": "workspace_context_only",
            "chatId": local_context.local_chat.id if local_context.local_chat is not None else None,
            "chatTitle": local_context.local_chat.title if local_context.local_chat is not None else chat.title,
            "chatReference": _build_reference(chat.username, chat.telegram_chat_id),
            "errorMessage": "Reply generation на новом workspace пока не включена. Сейчас доступен только read-only контекст.",
            "sourceSenderName": reply_context.get("sourceSenderName"),
            "sourceMessagePreview": reply_context.get("sourceMessagePreview"),
            "suggestion": None,
            "actions": {
                "copy": False,
                "refresh": True,
                "pasteToTelegram": False,
                "send": False,
                "markSent": False,
                "variants": {},
                "disabledReason": (
                    "Reply generation и send-path пока остаются на legacy. "
                    "Этот workspace обслуживает только чтение и focus context."
                ),
            },
        }

    def _build_freshness_payload(
        self,
        *,
        chat: NewTelegramChatSummary,
        refreshed_at: datetime,
        updated_now: bool,
        sync_trigger: str,
        sync_error: str | None,
    ) -> dict[str, Any]:
        if sync_error:
            return {
                "mode": "attention",
                "label": "New runtime деградировал",
                "detail": (
                    f"Во время чтения хвоста новый runtime вернул ошибку: {sync_error}. "
                    "Показан последний доступный snapshot."
                ),
                "isStale": True,
                "fullaccessReady": False,
                "canManualSync": False,
                "lastSyncAt": _serialize_datetime(refreshed_at),
                "reference": _build_reference(chat.username, chat.telegram_chat_id),
                "createdCount": 0,
                "updatedCount": 0,
                "skippedCount": 0,
                "syncTrigger": sync_trigger,
                "updatedNow": False,
                "syncError": sync_error,
            }

        return {
            "mode": "fresh",
            "label": "Контекст из new runtime",
            "detail": (
                "Активный чат читается напрямую из нового Telegram runtime. "
                "Reply generation и send-path пока не включены."
            ),
            "isStale": False,
            "fullaccessReady": False,
            "canManualSync": False,
            "lastSyncAt": _serialize_datetime(refreshed_at),
            "reference": _build_reference(chat.username, chat.telegram_chat_id),
            "createdCount": 0,
            "updatedCount": 0,
            "skippedCount": 0,
            "syncTrigger": sync_trigger,
            "updatedNow": updated_now,
            "syncError": None,
        }

    def _build_status_payload(
        self,
        *,
        source_backend: str,
        local_context: LocalHistoryContext,
        runtime_chat_id: int,
        message_payloads: list[dict[str, Any]],
        refreshed_at: datetime,
        updated_now: bool,
        sync_trigger: str,
        sync_error: str | None,
        reply_context_available: bool,
        has_more_before: bool,
    ) -> dict[str, Any]:
        chat_key = ChatIdentity(
            runtime_chat_id=runtime_chat_id,
            local_chat_id=local_context.local_chat.id if local_context.local_chat is not None else None,
        ).chat_key
        oldest = message_payloads[0] if message_payloads else None
        newest = message_payloads[-1] if message_payloads else None
        return {
            "source": source_backend,
            "effectiveBackend": source_backend,
            "degraded": sync_error is not None,
            "degradedReason": sync_error,
            "syncTrigger": sync_trigger,
            "updatedNow": updated_now,
            "syncError": sync_error,
            "lastUpdatedAt": _serialize_datetime(refreshed_at),
            "lastSuccessAt": _serialize_datetime(self._last_success_at),
            "lastError": sync_error or self._last_error,
            "lastErrorAt": _serialize_datetime(self._last_error_at),
            "availability": {
                "workspaceAvailable": True,
                "historyReadable": True,
                "runtimeReadable": True,
                "legacyWorkspaceAvailable": local_context.local_chat is not None,
                "replyContextAvailable": reply_context_available,
                "sendAvailable": False,
                "autopilotAvailable": False,
                "canLoadOlder": has_more_before,
            },
            "messageSource": {
                "backend": "new_runtime",
                "chatKey": chat_key,
                "runtimeChatId": runtime_chat_id,
                "localChatId": local_context.local_chat.id if local_context.local_chat is not None else None,
                "oldestMessageKey": oldest.get("messageKey") if oldest is not None else None,
                "newestMessageKey": newest.get("messageKey") if newest is not None else None,
                "oldestRuntimeMessageId": oldest.get("runtimeMessageId") if oldest is not None else None,
                "newestRuntimeMessageId": newest.get("runtimeMessageId") if newest is not None else None,
            },
            "runtimeMeta": self.status_payload(),
        }

    def _record_error(self, message: str) -> None:
        now = datetime.now(UTC)
        self._last_error = message
        self._last_error_at = now
        self._degraded_until = now + timedelta(seconds=self.failure_cooldown_seconds)

    def _record_success(self, refreshed_at: datetime) -> None:
        self._last_success_at = refreshed_at
        self._last_error = None
        self._last_error_at = None
        self._degraded_until = None


def _remote_message_preview(message: NewTelegramRemoteMessage | None) -> str:
    if message is None:
        return "Сообщений пока нет"
    if message.raw_text.strip():
        return _message_preview(message.raw_text, fallback="Без текста")
    if message.has_media:
        return f"Медиа: {message.media_type or 'media'}"
    return "Без текста"


def _build_media_preview_url(
    session_files: tuple[Any, ...],
    *,
    telegram_chat_id: int,
    telegram_message_id: int,
) -> str | None:
    for session_file in session_files:
        cached = find_cached_variant(
            media_preview_base_path(
                session_file,
                telegram_chat_id=telegram_chat_id,
                telegram_message_id=telegram_message_id,
            )
        )
        if cached is None:
            continue
        version = int(cached.stat().st_mtime)
        return f"/api/media/messages/{telegram_chat_id}/{telegram_message_id}?v={version}"
    return None


def _merge_messages(
    existing: tuple[NewTelegramRemoteMessage, ...],
    incremental: tuple[NewTelegramRemoteMessage, ...],
) -> tuple[NewTelegramRemoteMessage, ...]:
    by_message_id: dict[int, NewTelegramRemoteMessage] = {
        message.telegram_message_id: message
        for message in existing
    }
    for message in incremental:
        by_message_id[message.telegram_message_id] = message
    merged = sorted(by_message_id.values(), key=lambda message: message.telegram_message_id)
    return tuple(merged)


def _trim_messages(
    messages: tuple[NewTelegramRemoteMessage, ...],
    *,
    max_messages: int = MAX_HISTORY_CACHE_MESSAGES,
) -> tuple[NewTelegramRemoteMessage, ...]:
    if len(messages) <= max_messages:
        return messages
    return messages[-max_messages:]


def _is_snapshot_stale(refreshed_at: datetime, *, ttl_seconds: int) -> bool:
    return datetime.now(UTC) - refreshed_at > timedelta(seconds=ttl_seconds)


def _pick_focus_message(message_payloads: list[dict[str, Any]]) -> dict[str, Any] | None:
    inbound_candidates = [
        message
        for message in message_payloads[-20:]
        if message.get("direction") == "inbound"
        and (
            (isinstance(message.get("text"), str) and message["text"].strip())
            or bool(message.get("hasMedia"))
        )
    ]
    if not inbound_candidates:
        return None

    def score(message: dict[str, Any]) -> tuple[float, int]:
        text = message.get("text")
        value = 0.15
        if has_question_signal(text):
            value += 2.2
        if has_request_signal(text):
            value += 1.8
        if has_open_loop_signal(text):
            value += 1.1
        if has_emotional_signal(text):
            value += 1.4
        if not is_weak_reply_signal(text):
            value += 0.3
        if message.get("replyToRuntimeMessageId") is not None:
            value += 0.1
        runtime_message_id = int(message.get("runtimeMessageId") or 0)
        value += max(0.0, runtime_message_id / 1_000_000_000)
        return value, runtime_message_id

    return max(inbound_candidates, key=score)


def _build_focus_reason(
    message: dict[str, Any],
    *,
    reply_opportunity_reason: str,
) -> str:
    text = message.get("text")
    if has_question_signal(text):
        prefix = "Выбран последний вопрос, который всё ещё задаёт направление ответа."
    elif has_request_signal(text):
        prefix = "Выбрана свежая просьба, требующая конкретной реакции."
    elif has_open_loop_signal(text):
        prefix = "Выбрана незакрытая тема, которая ещё держит хвост разговора."
    elif has_emotional_signal(text):
        prefix = "Выбран эмоциональный сигнал, потому что он задаёт тон продолжения."
    else:
        prefix = "Выбран последний значимый входящий фрагмент из активного хвоста."
    return f"{prefix} {reply_opportunity_reason}"


def _build_draft_scope_key(draft_scope_basis: dict[str, Any] | None) -> str | None:
    if not isinstance(draft_scope_basis, dict):
        return None

    source_message_key = draft_scope_basis.get("sourceMessageKey")
    if not isinstance(source_message_key, str) and not draft_scope_basis.get("focusLabel") and not draft_scope_basis.get("sourceMessagePreview"):
        return None

    return "::".join(
        [
            str(source_message_key or draft_scope_basis.get("sourceMessageId") or "none"),
            str(draft_scope_basis.get("focusLabel") or "none"),
            str(draft_scope_basis.get("replyOpportunityMode") or "none"),
            str(draft_scope_basis.get("sourceMessagePreview") or "none"),
        ]
    )
