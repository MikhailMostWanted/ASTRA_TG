from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from astra_runtime.chat_identity import ChatIdentity, parse_runtime_only_chat_id
from astra_runtime.message_identity import MessageIdentity, parse_message_key
from astra_runtime.new_telegram.config import NewTelegramRuntimeConfig
from astra_runtime.new_telegram.transport import (
    NewTelegramChatSummary,
    NewTelegramRemoteMessage,
    NewTelegramSendClientFactory,
    build_new_telegram_send_client,
)
from astra_runtime.status import RuntimeUnavailableError
from services.message_normalizer import normalize_text
from storage.repositories import ChatRepository, MessageRepository


DEFAULT_SEND_FAILURE_COOLDOWN_SECONDS = 8


@dataclass(frozen=True, slots=True)
class ResolvedSendChat:
    requested_chat_id: int
    runtime_chat_id: int
    local_chat_id: int | None

    @property
    def identity(self) -> ChatIdentity:
        return ChatIdentity(
            runtime_chat_id=self.runtime_chat_id,
            local_chat_id=self.local_chat_id,
        )


@dataclass(slots=True)
class NewTelegramMessageSender:
    config: NewTelegramRuntimeConfig
    session_factory: async_sessionmaker[AsyncSession] | None = None
    client_factory: NewTelegramSendClientFactory = build_new_telegram_send_client
    history: Any | None = None
    roster: Any | None = None
    failure_cooldown_seconds: int = DEFAULT_SEND_FAILURE_COOLDOWN_SECONDS
    _last_error: str | None = field(default=None, init=False)
    _last_error_at: datetime | None = field(default=None, init=False)
    _last_success_at: datetime | None = field(default=None, init=False)
    _degraded_until: datetime | None = field(default=None, init=False)
    _last_trace: dict[str, Any] | None = field(default=None, init=False)

    def route_ready(self) -> bool:
        if self.session_factory is None:
            return False
        if self._degraded_until is None:
            return True
        return self._degraded_until <= datetime.now(UTC)

    def route_reason(self) -> str | None:
        if self.session_factory is None:
            return "New Telegram send path requires local storage runtime."
        if self._degraded_until is not None and self._degraded_until > datetime.now(UTC):
            return self._last_error or "New Telegram send path is temporarily degraded."
        return None

    def status_payload(self) -> dict[str, Any]:
        return {
            "lastSuccessAt": _serialize_datetime(self._last_success_at),
            "lastError": self._last_error,
            "lastErrorAt": _serialize_datetime(self._last_error_at),
            "degradedUntil": _serialize_datetime(self._degraded_until),
            "routeReady": self.route_ready(),
            "routeReason": self.route_reason(),
            "lastTrace": self._last_trace,
        }

    async def send_chat_message(
        self,
        chat_id: int,
        *,
        text: str,
        source_message_id: int | None = None,
        reply_to_source_message_id: int | None = None,
        source_message_key: str | None = None,
        reply_to_source_message_key: str | None = None,
        draft_scope_key: str | None = None,
        client_send_id: str | None = None,
    ) -> dict[str, Any]:
        if not self.route_ready():
            raise RuntimeUnavailableError(self.route_reason() or "New Telegram send path is not route-ready.")

        cleaned_text = text.strip()
        if not cleaned_text:
            raise ValueError("Нельзя отправить пустое сообщение.")

        started_at = datetime.now(UTC)
        trace: dict[str, Any] = {
            "backend": "new",
            "status": "started",
            "startedAt": _serialize_datetime(started_at),
            "completedAt": None,
            "requestedChatId": int(chat_id),
            "runtimeChatId": None,
            "localChatId": None,
            "replyToRuntimeMessageId": None,
            "replyToLocalMessageId": None,
            "draftScopeKey": draft_scope_key,
            "clientSendId": client_send_id,
            "localStoreUpdated": False,
            "error": None,
        }
        self._last_trace = trace

        try:
            if self.session_factory is None:
                raise RuntimeUnavailableError("New Telegram send path requires local storage runtime.")

            async with self.session_factory() as session:
                resolved = await self._resolve_chat(session, chat_id)
                trace["runtimeChatId"] = resolved.runtime_chat_id
                trace["localChatId"] = resolved.local_chat_id

                reply_to_runtime_message_id, reply_to_local_message_id = await self._resolve_reply_target(
                    session,
                    resolved=resolved,
                    source_message_id=source_message_id,
                    reply_to_source_message_id=reply_to_source_message_id,
                    source_message_key=source_message_key,
                    reply_to_source_message_key=reply_to_source_message_key,
                )
                trace["replyToRuntimeMessageId"] = reply_to_runtime_message_id
                trace["replyToLocalMessageId"] = reply_to_local_message_id

                remote_result = await self.client_factory(self.config).send_message(
                    resolved.runtime_chat_id,
                    text=cleaned_text,
                    reply_to_message_id=reply_to_runtime_message_id,
                )
                local_message = None
                if resolved.local_chat_id is not None:
                    upsert = await MessageRepository(session).create_or_update_message(
                        chat_id=resolved.local_chat_id,
                        telegram_message_id=remote_result.message.telegram_message_id,
                        sender_id=remote_result.message.sender_id,
                        sender_name=remote_result.message.sender_name,
                        direction=remote_result.message.direction,
                        source_adapter="new_runtime",
                        source_type=remote_result.message.source_type,
                        sent_at=remote_result.message.sent_at,
                        raw_text=remote_result.message.raw_text,
                        normalized_text=remote_result.message.normalized_text,
                        reply_to_message_id=reply_to_local_message_id,
                        forward_info=remote_result.message.forward_info,
                        has_media=remote_result.message.has_media,
                        media_type=remote_result.message.media_type,
                        entities_json=remote_result.message.entities_json,
                    )
                    local_message = upsert.message
                    trace["localStoreUpdated"] = True
                    await session.commit()

                self._note_success(
                    remote_result.chat,
                    remote_result.message,
                )
                completed_at = datetime.now(UTC)
                trace["status"] = "success"
                trace["completedAt"] = _serialize_datetime(completed_at)
                self._record_success(completed_at)

                sent_message = _serialize_sent_message(
                    remote_result.message,
                    runtime_chat_id=resolved.runtime_chat_id,
                    requested_chat_id=resolved.requested_chat_id,
                    local_message_id=local_message.id if local_message is not None else None,
                    reply_to_local_message_id=reply_to_local_message_id,
                )
                return {
                    "ok": True,
                    "status": "success",
                    "backend": "new",
                    "chat": {
                        **resolved.identity.to_payload(),
                        "requestedChatId": resolved.requested_chat_id,
                    },
                    "sentMessage": sent_message,
                    "sentMessageIdentity": {
                        "chatKey": sent_message["chatKey"],
                        "messageKey": sent_message["messageKey"],
                        "runtimeChatId": resolved.runtime_chat_id,
                        "runtimeMessageId": remote_result.message.telegram_message_id,
                        "localChatId": resolved.local_chat_id,
                        "localMessageId": local_message.id if local_message is not None else None,
                    },
                    "trace": trace,
                    "error": None,
                }
        except Exception as error:
            completed_at = datetime.now(UTC)
            trace["status"] = "failed"
            trace["completedAt"] = _serialize_datetime(completed_at)
            trace["error"] = str(error)
            self._record_error(str(error), at=completed_at)
            raise

    async def _resolve_chat(self, session, chat_id: int) -> ResolvedSendChat:
        chat_repository = ChatRepository(session)
        if int(chat_id) > 0:
            local_chat = await chat_repository.get_by_id(int(chat_id))
            if local_chat is None:
                raise LookupError("Чат не найден.")
            return ResolvedSendChat(
                requested_chat_id=int(chat_id),
                runtime_chat_id=int(local_chat.telegram_chat_id),
                local_chat_id=local_chat.id,
            )

        runtime_chat_id = parse_runtime_only_chat_id(int(chat_id))
        if runtime_chat_id is None:
            raise LookupError("Чат не найден.")

        local_chat = await chat_repository.get_by_telegram_chat_id(runtime_chat_id)
        return ResolvedSendChat(
            requested_chat_id=int(chat_id),
            runtime_chat_id=runtime_chat_id,
            local_chat_id=local_chat.id if local_chat is not None else None,
        )

    async def _resolve_reply_target(
        self,
        session,
        *,
        resolved: ResolvedSendChat,
        source_message_id: int | None,
        reply_to_source_message_id: int | None,
        source_message_key: str | None,
        reply_to_source_message_key: str | None,
    ) -> tuple[int | None, int | None]:
        runtime_from_key = _parse_matching_runtime_message_id(
            reply_to_source_message_key or source_message_key,
            runtime_chat_id=resolved.runtime_chat_id,
        )
        local_source_id = reply_to_source_message_id or source_message_id
        if resolved.local_chat_id is None:
            return runtime_from_key, None

        message_repository = MessageRepository(session)
        if local_source_id is not None:
            local_message = await message_repository.get_by_id(local_source_id)
            if local_message is not None and local_message.chat_id == resolved.local_chat_id:
                return local_message.telegram_message_id, local_message.id

        if runtime_from_key is not None:
            local_message = await message_repository.get_by_chat_and_telegram_message_id(
                chat_id=resolved.local_chat_id,
                telegram_message_id=runtime_from_key,
            )
            return runtime_from_key, local_message.id if local_message is not None else None

        return None, None

    def _note_success(
        self,
        chat: NewTelegramChatSummary,
        message: NewTelegramRemoteMessage,
    ) -> None:
        if self.history is not None and hasattr(self.history, "note_sent_message"):
            self.history.note_sent_message(chat=chat, message=message)
        if self.history is not None and hasattr(self.history, "note_manual_send"):
            self.history.note_manual_send(
                runtime_chat_id=chat.telegram_chat_id,
                runtime_message_id=message.telegram_message_id,
            )
        if self.roster is not None and hasattr(self.roster, "invalidate"):
            self.roster.invalidate()

    def _record_success(self, at: datetime) -> None:
        self._last_success_at = at
        self._last_error = None
        self._last_error_at = None
        self._degraded_until = None

    def _record_error(self, message: str, *, at: datetime) -> None:
        self._last_error = message
        self._last_error_at = at
        self._degraded_until = None


def _serialize_sent_message(
    message: NewTelegramRemoteMessage,
    *,
    runtime_chat_id: int,
    requested_chat_id: int,
    local_message_id: int | None,
    reply_to_local_message_id: int | None,
) -> dict[str, Any]:
    identity = MessageIdentity(
        runtime_chat_id=runtime_chat_id,
        runtime_message_id=message.telegram_message_id,
        local_message_id=local_message_id,
    )
    return {
        "id": local_message_id if local_message_id is not None else message.telegram_message_id,
        **identity.to_payload(),
        "telegramMessageId": message.telegram_message_id,
        "chatId": requested_chat_id,
        "direction": message.direction,
        "sourceAdapter": "new_runtime",
        "sourceType": message.source_type,
        "senderId": message.sender_id,
        "senderName": message.sender_name,
        "sentAt": _serialize_datetime(message.sent_at),
        "text": message.raw_text,
        "normalizedText": message.normalized_text or normalize_text(message.raw_text),
        "replyToMessageId": reply_to_local_message_id,
        "replyToLocalMessageId": reply_to_local_message_id,
        "replyToRuntimeMessageId": message.reply_to_telegram_message_id,
        "replyToMessageKey": (
            MessageIdentity(
                runtime_chat_id=runtime_chat_id,
                runtime_message_id=message.reply_to_telegram_message_id,
            ).message_key
            if message.reply_to_telegram_message_id is not None
            else None
        ),
        "hasMedia": message.has_media,
        "mediaType": message.media_type,
        "mediaPreviewUrl": None,
        "forwardInfo": message.forward_info if isinstance(message.forward_info, (dict, list)) else None,
        "entities": message.entities_json if isinstance(message.entities_json, (dict, list)) else None,
        "preview": _message_preview(message.raw_text),
    }


def _parse_matching_runtime_message_id(
    message_key: str | None,
    *,
    runtime_chat_id: int,
) -> int | None:
    parsed = parse_message_key(message_key)
    if parsed is None:
        return None
    parsed_chat_id, parsed_message_id = parsed
    if parsed_chat_id != runtime_chat_id:
        return None
    return parsed_message_id


def _message_preview(text: str | None) -> str:
    cleaned = " ".join((text or "").split()).strip()
    if not cleaned:
        return "Без текста"
    if len(cleaned) <= 140:
        return cleaned
    return f"{cleaned[:137].rstrip()}..."


def _serialize_datetime(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    else:
        value = value.astimezone(UTC)
    return value.isoformat()
