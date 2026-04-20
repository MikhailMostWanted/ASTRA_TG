from __future__ import annotations

from dataclasses import dataclass

from models import Chat, Message
from services.message_normalizer import normalize_telegram_message
from storage.repositories import ChatRepository, MessageRepository


@dataclass(frozen=True, slots=True)
class MessageIngestResult:
    action: str
    reason: str
    chat: Chat | None = None
    message: Message | None = None


@dataclass(slots=True)
class MessageIngestService:
    chat_repository: ChatRepository
    message_repository: MessageRepository

    async def ingest_message(
        self,
        telegram_message: object,
        *,
        for_digest: bool = True,
    ) -> MessageIngestResult:
        source_chat = getattr(telegram_message, "chat", None)
        telegram_chat_id = getattr(source_chat, "id", None)
        if telegram_chat_id is None:
            return MessageIngestResult(action="ignored", reason="missing_chat")

        if getattr(source_chat, "type", None) == "private":
            return MessageIngestResult(action="ignored", reason="private_chat")

        message_id = getattr(telegram_message, "message_id", None)
        if message_id is None:
            return MessageIngestResult(action="ignored", reason="missing_message_id")

        chat = await self.chat_repository.get_by_telegram_chat_id(int(telegram_chat_id))
        if chat is None:
            return MessageIngestResult(action="ignored", reason="chat_not_allowlisted")
        if not chat.is_enabled:
            return MessageIngestResult(action="ignored", reason="chat_disabled", chat=chat)
        if for_digest and chat.exclude_from_digest:
            return MessageIngestResult(
                action="ignored",
                reason="chat_excluded_from_digest",
                chat=chat,
            )

        normalized = normalize_telegram_message(telegram_message)
        if not normalized.raw_text and not normalized.has_media:
            return MessageIngestResult(
                action="ignored",
                reason="unsupported_message",
                chat=chat,
            )
        reply_to_message_id = await self._resolve_reply_to_message_id(
            chat_id=chat.id,
            reply_to_telegram_message_id=normalized.reply_to_telegram_message_id,
        )
        upsert_result = await self.message_repository.create_or_update_message(
            chat_id=chat.id,
            telegram_message_id=normalized.telegram_message_id,
            sender_id=normalized.sender_id,
            sender_name=normalized.sender_name,
            direction="inbound",
            source_adapter=normalized.source_adapter,
            source_type=normalized.source_type,
            sent_at=normalized.sent_at,
            raw_text=normalized.raw_text,
            normalized_text=normalized.normalized_text,
            reply_to_message_id=reply_to_message_id,
            forward_info=normalized.forward_info,
            has_media=normalized.has_media,
            media_type=normalized.media_type,
            entities_json=normalized.entities_json,
        )
        return MessageIngestResult(
            action="created" if upsert_result.created else "updated",
            reason="stored",
            chat=chat,
            message=upsert_result.message,
        )

    async def _resolve_reply_to_message_id(
        self,
        *,
        chat_id: int,
        reply_to_telegram_message_id: int | None,
    ) -> int | None:
        if reply_to_telegram_message_id is None:
            return None

        reply_to_message = await self.message_repository.get_by_chat_and_telegram_message_id(
            chat_id=chat_id,
            telegram_message_id=reply_to_telegram_message_id,
        )
        if reply_to_message is None:
            return None
        return reply_to_message.id
