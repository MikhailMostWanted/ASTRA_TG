from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import desc, func, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from models import Chat, Digest, DigestItem, Message, Setting


class _Unset:
    pass


UNSET = _Unset()


@dataclass(frozen=True, slots=True)
class DigestMessageRecord:
    chat: Chat
    message: Message


@dataclass(slots=True)
class ChatRepository:
    session: AsyncSession

    async def upsert_chat(
        self,
        *,
        telegram_chat_id: int,
        title: str | _Unset = UNSET,
        handle: str | None | _Unset = UNSET,
        chat_type: str | _Unset = UNSET,
        is_enabled: bool | _Unset = UNSET,
        category: str | None | _Unset = UNSET,
        summary_schedule: str | None | _Unset = UNSET,
        reply_assist_enabled: bool | _Unset = UNSET,
        auto_reply_mode: str | None | _Unset = UNSET,
        exclude_from_memory: bool | _Unset = UNSET,
        exclude_from_digest: bool | _Unset = UNSET,
    ) -> Chat:
        chat = await self.get_by_telegram_chat_id(telegram_chat_id)
        if chat is None:
            chat = Chat(
                telegram_chat_id=telegram_chat_id,
                title="" if title is UNSET else title,
                type="private" if chat_type is UNSET else chat_type,
            )
            self.session.add(chat)

        updates = {
            "title": title,
            "handle": handle,
            "type": chat_type,
            "is_enabled": is_enabled,
            "category": category,
            "summary_schedule": summary_schedule,
            "reply_assist_enabled": reply_assist_enabled,
            "auto_reply_mode": auto_reply_mode,
            "exclude_from_memory": exclude_from_memory,
            "exclude_from_digest": exclude_from_digest,
        }
        for field_name, value in updates.items():
            if value is not UNSET:
                setattr(chat, field_name, value)

        await self.session.flush()
        return chat

    async def get_by_telegram_chat_id(self, telegram_chat_id: int) -> Chat | None:
        result = await self.session.execute(
            select(Chat).where(Chat.telegram_chat_id == telegram_chat_id)
        )
        return result.scalar_one_or_none()

    async def list_chats(self) -> list[Chat]:
        result = await self.session.execute(
            select(Chat).order_by(
                desc(Chat.is_enabled),
                func.lower(Chat.title),
                Chat.telegram_chat_id,
            )
        )
        return list(result.scalars().all())

    async def list_enabled_chats(self) -> list[Chat]:
        result = await self.session.execute(
            select(Chat)
            .where(Chat.is_enabled.is_(True))
            .order_by(func.lower(Chat.title), Chat.telegram_chat_id)
        )
        return list(result.scalars().all())

    async def count_chats(self) -> int:
        result = await self.session.execute(select(func.count()).select_from(Chat))
        return int(result.scalar_one())

    async def count_enabled_chats(self) -> int:
        result = await self.session.execute(
            select(func.count()).select_from(Chat).where(Chat.is_enabled.is_(True))
        )
        return int(result.scalar_one())

    async def count_digest_enabled_chats(self) -> int:
        result = await self.session.execute(
            select(func.count())
            .select_from(Chat)
            .where(Chat.is_enabled.is_(True), Chat.exclude_from_digest.is_(False))
        )
        return int(result.scalar_one())

    async def find_chat_by_handle_or_telegram_id(self, reference: str | int) -> Chat | None:
        telegram_chat_id = _parse_telegram_chat_id(reference)
        if telegram_chat_id is not None:
            return await self.get_by_telegram_chat_id(telegram_chat_id)

        normalized_handle = _normalize_handle(reference)
        if normalized_handle is None:
            return None

        result = await self.session.execute(
            select(Chat).where(func.lower(Chat.handle) == normalized_handle)
        )
        return result.scalar_one_or_none()

    async def set_chat_enabled(self, reference: str | int, *, is_enabled: bool) -> Chat | None:
        chat = await self.find_chat_by_handle_or_telegram_id(reference)
        if chat is None:
            return None

        chat.is_enabled = is_enabled
        await self.session.flush()
        return chat


@dataclass(slots=True)
class MessageRepository:
    session: AsyncSession

    @dataclass(frozen=True, slots=True)
    class UpsertResult:
        message: Message
        created: bool

    async def create_message(
        self,
        *,
        chat_id: int,
        telegram_message_id: int,
        sender_id: int | None = None,
        sender_name: str | None = None,
        direction: str,
        source_adapter: str,
        source_type: str,
        sent_at: datetime | None = None,
        raw_text: str = "",
        normalized_text: str | None = None,
        reply_to_message_id: int | None = None,
        forward_info: dict[str, Any] | list[Any] | None = None,
        has_media: bool = False,
        media_type: str | None = None,
        entities_json: dict[str, Any] | list[Any] | None = None,
    ) -> Message:
        message = Message(
            chat_id=chat_id,
            telegram_message_id=telegram_message_id,
            sender_id=sender_id,
            sender_name=sender_name,
            direction=direction,
            source_adapter=source_adapter,
            source_type=source_type,
            sent_at=sent_at or datetime.now(timezone.utc),
            raw_text=raw_text,
            normalized_text=raw_text if normalized_text is None else normalized_text,
            reply_to_message_id=reply_to_message_id,
            forward_info=forward_info,
            has_media=has_media,
            media_type=media_type,
            entities_json=entities_json,
        )
        self.session.add(message)
        await self.session.flush()
        return message

    async def get_by_chat_and_telegram_message_id(
        self,
        *,
        chat_id: int,
        telegram_message_id: int,
    ) -> Message | None:
        result = await self.session.execute(
            select(Message).where(
                Message.chat_id == chat_id,
                Message.telegram_message_id == telegram_message_id,
            )
        )
        return result.scalar_one_or_none()

    async def create_or_update_message(
        self,
        *,
        chat_id: int,
        telegram_message_id: int,
        sender_id: int | None = None,
        sender_name: str | None = None,
        direction: str,
        source_adapter: str,
        source_type: str,
        sent_at: datetime | None = None,
        raw_text: str = "",
        normalized_text: str | None = None,
        reply_to_message_id: int | None = None,
        forward_info: dict[str, Any] | list[Any] | None = None,
        has_media: bool = False,
        media_type: str | None = None,
        entities_json: dict[str, Any] | list[Any] | None = None,
    ) -> UpsertResult:
        message = await self.get_by_chat_and_telegram_message_id(
            chat_id=chat_id,
            telegram_message_id=telegram_message_id,
        )
        if message is None:
            created_message = await self.create_message(
                chat_id=chat_id,
                telegram_message_id=telegram_message_id,
                sender_id=sender_id,
                sender_name=sender_name,
                direction=direction,
                source_adapter=source_adapter,
                source_type=source_type,
                sent_at=sent_at,
                raw_text=raw_text,
                normalized_text=normalized_text,
                reply_to_message_id=reply_to_message_id,
                forward_info=forward_info,
                has_media=has_media,
                media_type=media_type,
                entities_json=entities_json,
            )
            return self.UpsertResult(message=created_message, created=True)

        if sender_id is not None:
            message.sender_id = sender_id
        if sender_name is not None:
            message.sender_name = sender_name
        message.direction = direction
        message.source_adapter = source_adapter
        message.source_type = source_type
        message.sent_at = sent_at or datetime.now(timezone.utc)
        message.raw_text = raw_text
        message.normalized_text = raw_text if normalized_text is None else normalized_text
        if reply_to_message_id is not None:
            message.reply_to_message_id = reply_to_message_id
        if forward_info is not None:
            message.forward_info = forward_info
        message.has_media = has_media
        message.media_type = media_type
        if entities_json is not None:
            message.entities_json = entities_json
        await self.session.flush()
        return self.UpsertResult(message=message, created=False)

    async def count_messages(self) -> int:
        result = await self.session.execute(select(func.count()).select_from(Message))
        return int(result.scalar_one())

    async def count_messages_by_chat(self) -> dict[int, int]:
        result = await self.session.execute(
            select(Message.chat_id, func.count(Message.id))
            .group_by(Message.chat_id)
            .order_by(Message.chat_id)
        )
        return {
            int(chat_id): int(message_count)
            for chat_id, message_count in result.all()
        }

    async def get_last_message_timestamp(self) -> datetime | None:
        result = await self.session.execute(select(func.max(Message.sent_at)))
        return result.scalar_one_or_none()

    async def get_recent_messages(self, *, chat_id: int, limit: int = 20) -> list[Message]:
        result = await self.session.execute(
            select(Message)
            .where(Message.chat_id == chat_id)
            .order_by(desc(Message.sent_at), desc(Message.id))
            .limit(limit)
        )
        return list(result.scalars().all())

    async def search_full_text(self, query: str, *, limit: int = 20) -> list[Message]:
        result = await self.session.execute(
            select(Message).from_statement(
                text(
                    """
                    SELECT messages.*
                    FROM messages
                    JOIN messages_fts ON messages_fts.rowid = messages.id
                    WHERE messages_fts MATCH :query
                    ORDER BY messages.sent_at DESC, messages.id DESC
                    LIMIT :limit
                    """
                )
            ),
            {"query": query, "limit": limit},
        )
        return list(result.scalars().all())

    async def get_messages_for_digest(
        self,
        *,
        window_start: datetime,
        window_end: datetime,
    ) -> list[DigestMessageRecord]:
        result = await self.session.execute(
            select(Message, Chat)
            .join(Chat, Message.chat_id == Chat.id)
            .where(
                Chat.is_enabled.is_(True),
                Chat.exclude_from_digest.is_(False),
                Chat.type != "private",
                Message.direction == "inbound",
                Message.sent_at >= window_start,
                Message.sent_at <= window_end,
            )
            .order_by(func.lower(Chat.title), Message.sent_at, Message.id)
        )
        return [
            DigestMessageRecord(chat=chat, message=message)
            for message, chat in result.all()
        ]

    async def count_messages_by_digest_chat(
        self,
        *,
        window_start: datetime,
        window_end: datetime,
    ) -> dict[int, int]:
        result = await self.session.execute(
            select(Message.chat_id, func.count(Message.id))
            .join(Chat, Message.chat_id == Chat.id)
            .where(
                Chat.is_enabled.is_(True),
                Chat.exclude_from_digest.is_(False),
                Chat.type != "private",
                Message.direction == "inbound",
                Message.sent_at >= window_start,
                Message.sent_at <= window_end,
            )
            .group_by(Message.chat_id)
            .order_by(Message.chat_id)
        )
        return {
            int(chat_id): int(message_count)
            for chat_id, message_count in result.all()
        }


@dataclass(slots=True)
class DigestRepository:
    session: AsyncSession

    async def create_digest(
        self,
        *,
        chat_id: int | None,
        window_start: datetime,
        window_end: datetime,
        summary_short: str,
        summary_long: str,
        delivered_to_chat_id: int | None = None,
        delivered_message_id: int | None = None,
        items: Sequence[dict[str, Any]] = (),
    ) -> Digest:
        digest = Digest(
            chat_id=chat_id,
            window_start=window_start,
            window_end=window_end,
            summary_short=summary_short,
            summary_long=summary_long,
            delivered_to_chat_id=delivered_to_chat_id,
            delivered_message_id=delivered_message_id,
        )
        for item in items:
            digest.items.append(
                DigestItem(
                    source_chat_id=item["source_chat_id"],
                    source_message_id=item.get("source_message_id"),
                    title=item["title"],
                    summary=item["summary"],
                    link=item.get("link"),
                    sort_order=item.get("sort_order", 0),
                )
            )

        self.session.add(digest)
        await self.session.flush()
        return digest

    async def count_digests(self) -> int:
        result = await self.session.execute(select(func.count()).select_from(Digest))
        return int(result.scalar_one())

    async def get_last_digest(self) -> Digest | None:
        result = await self.session.execute(
            select(Digest)
            .options(selectinload(Digest.items))
            .order_by(desc(Digest.created_at), desc(Digest.id))
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def mark_delivered(
        self,
        digest_id: int,
        *,
        delivered_to_chat_id: int,
        delivered_message_id: int,
    ) -> Digest | None:
        result = await self.session.execute(select(Digest).where(Digest.id == digest_id))
        digest = result.scalar_one_or_none()
        if digest is None:
            return None

        digest.delivered_to_chat_id = delivered_to_chat_id
        digest.delivered_message_id = delivered_message_id
        await self.session.flush()
        return digest


@dataclass(slots=True)
class SettingRepository:
    session: AsyncSession

    async def get_by_key(self, key: str) -> Setting | None:
        result = await self.session.execute(select(Setting).where(Setting.key == key))
        return result.scalar_one_or_none()

    async def get_value(self, key: str) -> Any:
        setting = await self.get_by_key(key)
        if setting is None:
            return None
        if setting.value_json is not None:
            return setting.value_json
        return setting.value_text

    async def set_value(
        self,
        *,
        key: str,
        value_json: dict[str, Any] | list[Any] | None | _Unset = UNSET,
        value_text: str | None | _Unset = UNSET,
    ) -> Setting:
        setting = await self.get_by_key(key)
        if setting is None:
            setting = Setting(key=key)
            self.session.add(setting)

        if value_json is not UNSET:
            setting.value_json = value_json
        if value_text is not UNSET:
            setting.value_text = value_text

        await self.session.flush()
        return setting


@dataclass(slots=True)
class SystemRepository:
    session: AsyncSession

    async def get_schema_revision(self) -> str | None:
        try:
            result = await self.session.execute(
                text("SELECT version_num FROM alembic_version LIMIT 1")
            )
        except OperationalError:
            return None

        return result.scalar_one_or_none()


def _normalize_handle(reference: str | int) -> str | None:
    if not isinstance(reference, str):
        return None

    normalized = reference.strip().lower()
    if not normalized:
        return None

    return normalized.lstrip("@")


def _parse_telegram_chat_id(reference: str | int) -> int | None:
    if isinstance(reference, int):
        return reference

    if not isinstance(reference, str):
        return None

    normalized = reference.strip()
    if not normalized:
        return None

    if normalized.startswith("@"):
        return None

    try:
        return int(normalized)
    except ValueError:
        return None
