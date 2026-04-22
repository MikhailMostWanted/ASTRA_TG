from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, cast

from sqlalchemy import desc, func, or_, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from models import (
    Chat,
    ChatMemory,
    ChatStyleOverride,
    Digest,
    DigestItem,
    Message,
    PersonMemory,
    ReplyExample,
    Reminder,
    Setting,
    StyleProfile,
    Task,
)


class _Unset:
    pass


UNSET = _Unset()


@dataclass(frozen=True, slots=True)
class DigestMessageRecord:
    chat: Chat
    message: Message


@dataclass(frozen=True, slots=True)
class ChatMessageRecord:
    chat: Chat
    message: Message


@dataclass(frozen=True, slots=True)
class ReplyExampleSearchCandidate:
    id: int
    chat_id: int
    chat_title: str
    inbound_message_id: int | None
    outbound_message_id: int | None
    inbound_text: str
    outbound_text: str
    inbound_normalized: str
    outbound_normalized: str
    example_type: str
    source_person_key: str | None
    quality_score: float
    created_at: datetime
    fts_rank: float


@dataclass(slots=True)
class ChatRepository:
    session: AsyncSession

    async def get_by_id(self, chat_id: int) -> Chat | None:
        result = await self.session.execute(select(Chat).where(Chat.id == chat_id))
        return result.scalar_one_or_none()

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

    async def list_enabled_memory_chats(self) -> list[Chat]:
        result = await self.session.execute(
            select(Chat)
            .where(
                Chat.is_enabled.is_(True),
                Chat.exclude_from_memory.is_(False),
            )
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

    async def count_messages_by_source_adapter(self, source_adapter: str) -> int:
        result = await self.session.execute(
            select(func.count())
            .select_from(Message)
            .where(Message.source_adapter == source_adapter)
        )
        return int(result.scalar_one())

    async def count_distinct_chats_by_source_adapter(self, source_adapter: str) -> int:
        result = await self.session.execute(
            select(func.count(func.distinct(Message.chat_id)))
            .where(Message.source_adapter == source_adapter)
        )
        return int(result.scalar_one())

    async def count_messages_for_chat(self, *, chat_id: int) -> int:
        result = await self.session.execute(
            select(func.count()).select_from(Message).where(Message.chat_id == chat_id)
        )
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

    async def get_last_messages_by_chat(
        self,
        *,
        chat_ids: Sequence[int],
    ) -> dict[int, Message]:
        normalized_chat_ids = [int(chat_id) for chat_id in chat_ids]
        if not normalized_chat_ids:
            return {}

        ranked_messages = (
            select(
                Message.id.label("message_id"),
                Message.chat_id.label("chat_id"),
                func.row_number()
                .over(
                    partition_by=Message.chat_id,
                    order_by=(desc(Message.sent_at), desc(Message.id)),
                )
                .label("row_number"),
            )
            .where(Message.chat_id.in_(normalized_chat_ids))
            .subquery()
        )
        result = await self.session.execute(
            select(Message)
            .join(ranked_messages, ranked_messages.c.message_id == Message.id)
            .where(ranked_messages.c.row_number == 1)
        )
        messages = list(result.scalars().all())
        return {
            message.chat_id: message
            for message in messages
        }

    async def get_last_message_timestamp(self) -> datetime | None:
        result = await self.session.execute(select(func.max(Message.sent_at)))
        return result.scalar_one_or_none()

    async def get_latest_telegram_message_id(self, *, chat_id: int) -> int | None:
        result = await self.session.execute(
            select(Message.telegram_message_id)
            .where(Message.chat_id == chat_id)
            .order_by(desc(Message.telegram_message_id), desc(Message.id))
            .limit(1)
        )
        value = result.scalar_one_or_none()
        return int(value) if value is not None else None

    async def get_messages_for_chat(
        self,
        *,
        chat_id: int,
        limit: int | None = None,
        ascending: bool = True,
    ) -> list[Message]:
        statement = select(Message).where(Message.chat_id == chat_id)
        if ascending:
            statement = statement.order_by(Message.sent_at, Message.id)
        else:
            statement = statement.order_by(desc(Message.sent_at), desc(Message.id))
        if limit is not None:
            statement = statement.limit(limit)

        result = await self.session.execute(statement)
        return list(result.scalars().all())

    async def get_recent_messages(self, *, chat_id: int, limit: int = 20) -> list[Message]:
        result = await self.session.execute(
            select(Message)
            .where(Message.chat_id == chat_id)
            .order_by(desc(Message.sent_at), desc(Message.id))
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_top_senders_for_chat(
        self,
        *,
        chat_id: int,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        result = await self.session.execute(
            select(
                Message.sender_id,
                Message.sender_name,
                func.count(Message.id).label("message_count"),
            )
            .where(
                Message.chat_id == chat_id,
                or_(Message.sender_id.is_not(None), Message.sender_name.is_not(None)),
            )
            .group_by(Message.sender_id, Message.sender_name)
            .order_by(
                desc(func.count(Message.id)),
                func.lower(func.coalesce(Message.sender_name, "")),
                Message.sender_id,
            )
            .limit(limit)
        )
        return [
            {
                "sender_id": sender_id,
                "sender_name": sender_name,
                "message_count": int(message_count),
            }
            for sender_id, sender_name, message_count in result.all()
        ]

    async def count_messages_for_person(self, *, person_key: str) -> int:
        filter_expression = _build_person_message_filter(person_key)
        if filter_expression is None:
            return 0

        result = await self.session.execute(
            select(func.count()).select_from(Message).where(filter_expression)
        )
        return int(result.scalar_one())

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

    async def count_chats_ready_for_reply(self, *, min_messages: int = 3) -> int:
        eligible_chat_ids = (
            select(Message.chat_id)
            .join(Chat, Message.chat_id == Chat.id)
            .where(
                Chat.is_enabled.is_(True),
                Chat.type != "channel",
            )
            .group_by(Message.chat_id)
            .having(func.count(Message.id) >= min_messages)
            .subquery()
        )
        result = await self.session.execute(
            select(func.count()).select_from(eligible_chat_ids)
        )
        return int(result.scalar_one())

    async def list_reply_ready_chats(
        self,
        *,
        min_messages: int = 3,
        limit: int | None = None,
    ) -> list[Chat]:
        eligible_chats = (
            select(
                Message.chat_id.label("chat_id"),
                func.max(Message.sent_at).label("last_message_at"),
            )
            .join(Chat, Message.chat_id == Chat.id)
            .where(
                Chat.is_enabled.is_(True),
                Chat.type != "channel",
            )
            .group_by(Message.chat_id)
            .having(func.count(Message.id) >= min_messages)
            .subquery()
        )
        statement = (
            select(Chat)
            .join(eligible_chats, eligible_chats.c.chat_id == Chat.id)
            .order_by(
                desc(eligible_chats.c.last_message_at),
                func.lower(Chat.title),
                Chat.telegram_chat_id,
            )
        )
        if limit is not None:
            statement = statement.limit(limit)
        result = await self.session.execute(statement)
        return list(result.scalars().all())

    async def get_messages_for_reminder_scan(
        self,
        *,
        window_start: datetime,
        window_end: datetime,
        chat_id: int | None = None,
    ) -> list[ChatMessageRecord]:
        statement = (
            select(Message, Chat)
            .join(Chat, Message.chat_id == Chat.id)
            .where(
                Chat.is_enabled.is_(True),
                Chat.exclude_from_memory.is_(False),
                Message.sent_at >= window_start,
                Message.sent_at <= window_end,
            )
            .order_by(desc(Message.sent_at), desc(Message.id))
        )
        if chat_id is not None:
            statement = statement.where(Chat.id == chat_id)

        result = await self.session.execute(statement)
        return [
            ChatMessageRecord(chat=chat, message=message)
            for message, chat in result.all()
        ]


@dataclass(slots=True)
class ReplyExampleRepository:
    session: AsyncSession

    async def create_example(
        self,
        *,
        chat_id: int,
        inbound_message_id: int | None,
        outbound_message_id: int | None,
        inbound_text: str,
        outbound_text: str,
        inbound_normalized: str,
        outbound_normalized: str,
        context_before_json: dict[str, Any] | list[Any] | None,
        example_type: str,
        source_person_key: str | None,
        quality_score: float,
    ) -> ReplyExample:
        example = ReplyExample(
            chat_id=chat_id,
            inbound_message_id=inbound_message_id,
            outbound_message_id=outbound_message_id,
            inbound_text=inbound_text,
            outbound_text=outbound_text,
            inbound_normalized=inbound_normalized,
            outbound_normalized=outbound_normalized,
            context_before_json=context_before_json,
            example_type=example_type,
            source_person_key=source_person_key,
            quality_score=quality_score,
        )
        self.session.add(example)
        await self.session.flush()
        return example

    async def list_examples(self, *, limit: int | None = None) -> list[ReplyExample]:
        statement = (
            select(ReplyExample)
            .order_by(
                desc(ReplyExample.quality_score),
                desc(ReplyExample.created_at),
                desc(ReplyExample.id),
            )
        )
        if limit is not None:
            statement = statement.limit(limit)
        result = await self.session.execute(statement)
        return list(result.scalars().all())

    async def delete_all(self) -> int:
        result = await self.session.execute(select(ReplyExample))
        items = list(result.scalars().all())
        if not items:
            return 0
        for item in items:
            await self.session.delete(item)
        await self.session.flush()
        return len(items)

    async def delete_for_chat(self, *, chat_id: int) -> int:
        result = await self.session.execute(
            select(ReplyExample).where(ReplyExample.chat_id == chat_id)
        )
        items = list(result.scalars().all())
        for item in items:
            await self.session.delete(item)
        await self.session.flush()
        return len(items)

    async def delete_for_chats(self, chat_ids: Sequence[int]) -> int:
        normalized_ids = [chat_id for chat_id in dict.fromkeys(chat_ids) if chat_id]
        if not normalized_ids:
            return 0
        result = await self.session.execute(
            select(ReplyExample).where(ReplyExample.chat_id.in_(normalized_ids))
        )
        items = list(result.scalars().all())
        for item in items:
            await self.session.delete(item)
        await self.session.flush()
        return len(items)

    async def count_examples(self) -> int:
        result = await self.session.execute(select(func.count()).select_from(ReplyExample))
        return int(result.scalar_one())

    async def count_chats_with_examples(self) -> int:
        result = await self.session.execute(
            select(func.count(func.distinct(ReplyExample.chat_id)))
        )
        return int(result.scalar_one())

    async def search_similar(
        self,
        query: str,
        *,
        limit: int = 20,
        min_quality: float = 0.0,
    ) -> list[ReplyExampleSearchCandidate]:
        normalized = query.strip()
        if not normalized:
            return []

        result = await self.session.execute(
            text(
                """
                SELECT
                    reply_examples.id,
                    reply_examples.chat_id,
                    chats.title AS chat_title,
                    reply_examples.inbound_message_id,
                    reply_examples.outbound_message_id,
                    reply_examples.inbound_text,
                    reply_examples.outbound_text,
                    reply_examples.inbound_normalized,
                    reply_examples.outbound_normalized,
                    reply_examples.example_type,
                    reply_examples.source_person_key,
                    reply_examples.quality_score,
                    reply_examples.created_at,
                    bm25(reply_examples_fts) AS fts_rank
                FROM reply_examples
                JOIN reply_examples_fts ON reply_examples_fts.rowid = reply_examples.id
                JOIN chats ON chats.id = reply_examples.chat_id
                WHERE reply_examples_fts MATCH :query
                  AND reply_examples.quality_score >= :min_quality
                ORDER BY bm25(reply_examples_fts), reply_examples.quality_score DESC, reply_examples.created_at DESC
                LIMIT :limit
                """
            ),
            {
                "query": normalized,
                "min_quality": float(min_quality),
                "limit": int(limit),
            },
        )
        rows = result.mappings().all()
        return [
            ReplyExampleSearchCandidate(
                id=int(row["id"]),
                chat_id=int(row["chat_id"]),
                chat_title=str(row["chat_title"] or ""),
                inbound_message_id=_coerce_optional_int(row["inbound_message_id"]),
                outbound_message_id=_coerce_optional_int(row["outbound_message_id"]),
                inbound_text=str(row["inbound_text"] or ""),
                outbound_text=str(row["outbound_text"] or ""),
                inbound_normalized=str(row["inbound_normalized"] or ""),
                outbound_normalized=str(row["outbound_normalized"] or ""),
                example_type=str(row["example_type"] or "soft_reply"),
                source_person_key=str(row["source_person_key"]) if row["source_person_key"] else None,
                quality_score=float(row["quality_score"] or 0.0),
                created_at=_coerce_datetime(row["created_at"]),
                fts_rank=float(row["fts_rank"] or 0.0),
            )
            for row in rows
        ]


@dataclass(slots=True)
class DigestRepository:
    session: AsyncSession

    async def get_digest(self, digest_id: int) -> Digest | None:
        result = await self.session.execute(
            select(Digest)
            .options(
                selectinload(Digest.items).selectinload(DigestItem.source_chat),
                selectinload(Digest.items).selectinload(DigestItem.source_message),
            )
            .where(Digest.id == digest_id)
        )
        return result.scalar_one_or_none()

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

    async def get_last_digest_at_for_chat(self, chat_id: int) -> datetime | None:
        result = await self.session.execute(
            select(func.max(Digest.created_at))
            .join(DigestItem, DigestItem.digest_id == Digest.id)
            .where(DigestItem.source_chat_id == chat_id)
        )
        return result.scalar_one_or_none()

    async def get_last_digest(self) -> Digest | None:
        result = await self.session.execute(
            select(Digest)
            .options(
                selectinload(Digest.items).selectinload(DigestItem.source_chat),
                selectinload(Digest.items).selectinload(DigestItem.source_message),
            )
            .order_by(desc(Digest.created_at), desc(Digest.id))
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def list_recent(self, *, limit: int = 10) -> list[Digest]:
        result = await self.session.execute(
            select(Digest)
            .options(
                selectinload(Digest.items).selectinload(DigestItem.source_chat),
                selectinload(Digest.items).selectinload(DigestItem.source_message),
            )
            .order_by(desc(Digest.created_at), desc(Digest.id))
            .limit(limit)
        )
        return list(result.scalars().all())

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
class TaskRepository:
    session: AsyncSession

    async def create_task(
        self,
        *,
        source_chat_id: int | None,
        source_message_id: int | None,
        title: str,
        summary: str,
        due_at: datetime | None,
        suggested_remind_at: datetime | None,
        status: str,
        confidence: float,
        needs_user_confirmation: bool,
    ) -> Task:
        task = Task(
            source_chat_id=source_chat_id,
            source_message_id=source_message_id,
            title=title,
            summary=summary,
            due_at=due_at,
            suggested_remind_at=suggested_remind_at,
            status=status,
            confidence=confidence,
            needs_user_confirmation=needs_user_confirmation,
        )
        self.session.add(task)
        await self.session.flush()
        return task

    async def get_task(self, task_id: int) -> Task | None:
        result = await self.session.execute(
            select(Task)
            .options(
                selectinload(Task.source_chat),
                selectinload(Task.source_message),
                selectinload(Task.reminders),
            )
            .where(Task.id == task_id)
        )
        task = result.scalar_one_or_none()
        if task is None:
            return None
        return _normalize_task_instance(task)

    async def get_by_source_message_id(self, source_message_id: int) -> Task | None:
        result = await self.session.execute(
            select(Task)
            .options(
                selectinload(Task.source_chat),
                selectinload(Task.source_message),
                selectinload(Task.reminders),
            )
            .where(Task.source_message_id == source_message_id)
            .order_by(desc(Task.updated_at), desc(Task.id))
            .limit(1)
        )
        task = result.scalar_one_or_none()
        if task is None:
            return None
        return _normalize_task_instance(task)

    async def upsert_candidate(
        self,
        *,
        source_chat_id: int,
        source_message_id: int,
        title: str,
        summary: str,
        due_at: datetime | None,
        suggested_remind_at: datetime | None,
        confidence: float,
    ) -> tuple[Task, bool]:
        existing = await self.get_by_source_message_id(source_message_id)
        if existing is None:
            task = await self.create_task(
                source_chat_id=source_chat_id,
                source_message_id=source_message_id,
                title=title,
                summary=summary,
                due_at=due_at,
                suggested_remind_at=suggested_remind_at,
                status="candidate",
                confidence=confidence,
                needs_user_confirmation=True,
            )
            return task, True

        existing.source_chat_id = source_chat_id
        existing.title = title
        existing.summary = summary
        existing.due_at = due_at
        existing.suggested_remind_at = suggested_remind_at
        existing.confidence = confidence
        existing.status = "candidate"
        existing.needs_user_confirmation = True
        await self.session.flush()
        return existing, False

    async def set_status(
        self,
        task_id: int,
        *,
        status: str,
        needs_user_confirmation: bool,
    ) -> Task | None:
        task = await self.get_task(task_id)
        if task is None:
            return None
        task.status = status
        task.needs_user_confirmation = needs_user_confirmation
        await self.session.flush()
        return task

    async def list_candidates(self) -> list[Task]:
        result = await self.session.execute(
            select(Task)
            .options(
                selectinload(Task.source_chat),
                selectinload(Task.source_message),
                selectinload(Task.reminders),
            )
            .where(Task.status == "candidate")
            .order_by(Task.id)
        )
        return [_normalize_task_instance(task) for task in result.scalars().all() if task is not None]

    async def list_active_tasks(self) -> list[Task]:
        result = await self.session.execute(
            select(Task)
            .options(
                selectinload(Task.source_chat),
                selectinload(Task.source_message),
                selectinload(Task.reminders),
            )
            .where(Task.status == "active")
            .order_by(Task.due_at.is_(None), Task.due_at, Task.id)
        )
        return [_normalize_task_instance(task) for task in result.scalars().all() if task is not None]

    async def count_candidates(self) -> int:
        result = await self.session.execute(
            select(func.count()).select_from(Task).where(Task.status == "candidate")
        )
        return int(result.scalar_one())

    async def count_confirmed(self) -> int:
        result = await self.session.execute(
            select(func.count())
            .select_from(Task)
            .where(Task.needs_user_confirmation.is_(False))
        )
        return int(result.scalar_one())


@dataclass(slots=True)
class ReminderRepository:
    session: AsyncSession

    async def create_reminder(
        self,
        *,
        task_id: int | None,
        remind_at: datetime,
        status: str,
        payload_json: dict[str, Any] | list[Any] | None = None,
    ) -> Reminder:
        reminder = Reminder(
            task_id=task_id,
            remind_at=remind_at,
            status=status,
            payload_json=payload_json,
        )
        self.session.add(reminder)
        await self.session.flush()
        return reminder

    async def get_reminder(self, reminder_id: int) -> Reminder | None:
        result = await self.session.execute(
            select(Reminder)
            .options(
                selectinload(Reminder.task).selectinload(Task.source_chat),
                selectinload(Reminder.task).selectinload(Task.source_message),
            )
            .where(Reminder.id == reminder_id)
        )
        reminder = result.scalar_one_or_none()
        if reminder is None:
            return None
        return _normalize_reminder_instance(reminder)

    async def get_by_task_id(self, task_id: int) -> Reminder | None:
        result = await self.session.execute(
            select(Reminder)
            .options(
                selectinload(Reminder.task).selectinload(Task.source_chat),
                selectinload(Reminder.task).selectinload(Task.source_message),
            )
            .where(Reminder.task_id == task_id)
            .order_by(desc(Reminder.updated_at), desc(Reminder.id))
            .limit(1)
        )
        reminder = result.scalar_one_or_none()
        if reminder is None:
            return None
        return _normalize_reminder_instance(reminder)

    async def upsert_candidate_for_task(
        self,
        *,
        task_id: int,
        remind_at: datetime,
        payload_json: dict[str, Any] | list[Any] | None,
    ) -> Reminder:
        reminder = await self.get_by_task_id(task_id)
        if reminder is None:
            return await self.create_reminder(
                task_id=task_id,
                remind_at=remind_at,
                status="candidate",
                payload_json=payload_json,
            )

        reminder.remind_at = remind_at
        reminder.status = "candidate"
        reminder.payload_json = payload_json
        reminder.last_notification_at = None
        await self.session.flush()
        return reminder

    async def set_status(
        self,
        reminder_id: int,
        *,
        status: str,
        remind_at: datetime | _Unset = UNSET,
    ) -> Reminder | None:
        reminder = await self.get_reminder(reminder_id)
        if reminder is None:
            return None

        reminder.status = status
        if remind_at is not UNSET:
            reminder.remind_at = cast(datetime, remind_at)
        await self.session.flush()
        return reminder

    async def list_active_reminders(self) -> list[Reminder]:
        result = await self.session.execute(
            select(Reminder)
            .options(
                selectinload(Reminder.task).selectinload(Task.source_chat),
                selectinload(Reminder.task).selectinload(Task.source_message),
            )
            .where(Reminder.status == "active")
            .order_by(Reminder.remind_at, Reminder.id)
        )
        return [
            _normalize_reminder_instance(reminder)
            for reminder in result.scalars().all()
            if reminder is not None
        ]

    async def get_due_reminders(self, now: datetime) -> list[Reminder]:
        result = await self.session.execute(
            select(Reminder)
            .options(
                selectinload(Reminder.task).selectinload(Task.source_chat),
                selectinload(Reminder.task).selectinload(Task.source_message),
            )
            .where(
                Reminder.status == "active",
                Reminder.remind_at <= now,
            )
            .order_by(Reminder.remind_at, Reminder.id)
        )
        return [
            _normalize_reminder_instance(reminder)
            for reminder in result.scalars().all()
            if reminder is not None
        ]

    async def mark_delivered(
        self,
        reminder_id: int,
        *,
        delivered_at: datetime,
    ) -> Reminder | None:
        reminder = await self.get_reminder(reminder_id)
        if reminder is None:
            return None

        reminder.status = "delivered"
        reminder.last_notification_at = delivered_at
        await self.session.flush()
        return reminder

    async def list_all(self) -> list[Reminder]:
        result = await self.session.execute(
            select(Reminder)
            .options(
                selectinload(Reminder.task).selectinload(Task.source_chat),
                selectinload(Reminder.task).selectinload(Task.source_message),
            )
            .order_by(Reminder.id)
        )
        return [
            _normalize_reminder_instance(reminder)
            for reminder in result.scalars().all()
            if reminder is not None
        ]

    async def count_active_reminders(self) -> int:
        result = await self.session.execute(
            select(func.count()).select_from(Reminder).where(Reminder.status == "active")
        )
        return int(result.scalar_one())

    async def get_last_notification_at(self) -> datetime | None:
        result = await self.session.execute(select(func.max(Reminder.last_notification_at)))
        return result.scalar_one_or_none()


@dataclass(slots=True)
class ChatMemoryRepository:
    session: AsyncSession

    async def upsert_chat_memory(
        self,
        *,
        chat_id: int,
        chat_summary_short: str,
        chat_summary_long: str,
        current_state: str | None,
        dominant_topics_json: list[dict[str, Any]] | list[str] | None,
        recent_conflicts_json: list[str] | None,
        pending_tasks_json: list[str] | None,
        linked_people_json: list[dict[str, Any]] | None,
        last_digest_at: datetime | None,
    ) -> ChatMemory:
        memory = await self.get_chat_memory(chat_id)
        if memory is None:
            memory = ChatMemory(chat_id=chat_id)
            self.session.add(memory)

        memory.chat_summary_short = chat_summary_short
        memory.chat_summary_long = chat_summary_long
        memory.current_state = current_state
        memory.dominant_topics_json = dominant_topics_json
        memory.recent_conflicts_json = recent_conflicts_json
        memory.pending_tasks_json = pending_tasks_json
        memory.linked_people_json = linked_people_json
        memory.last_digest_at = last_digest_at
        await self.session.flush()
        return memory

    async def get_chat_memory(self, chat_id: int) -> ChatMemory | None:
        result = await self.session.execute(
            select(ChatMemory)
            .options(selectinload(ChatMemory.chat))
            .where(ChatMemory.chat_id == chat_id)
        )
        return result.scalar_one_or_none()

    async def list_chat_memory(self, *, limit: int | None = None) -> list[ChatMemory]:
        statement = (
            select(ChatMemory)
            .options(selectinload(ChatMemory.chat))
            .order_by(desc(ChatMemory.updated_at), ChatMemory.chat_id)
        )
        if limit is not None:
            statement = statement.limit(limit)
        result = await self.session.execute(statement)
        return list(result.scalars().all())

    async def count_chat_memory(self) -> int:
        result = await self.session.execute(select(func.count()).select_from(ChatMemory))
        return int(result.scalar_one())

    async def get_last_updated_at(self) -> datetime | None:
        result = await self.session.execute(select(func.max(ChatMemory.updated_at)))
        return result.scalar_one_or_none()


@dataclass(slots=True)
class PersonMemoryRepository:
    session: AsyncSession

    async def upsert_person_memory(
        self,
        *,
        person_key: str,
        display_name: str,
        relationship_label: str | None,
        importance_score: float,
        last_summary: str | None,
        known_facts_json: list[str] | None,
        sensitive_topics_json: list[str] | None,
        open_loops_json: list[str] | None,
        interaction_pattern: str | None,
    ) -> PersonMemory:
        memory = await self.get_person_memory(person_key)
        if memory is None:
            memory = PersonMemory(person_key=person_key, display_name=display_name)
            self.session.add(memory)

        memory.display_name = display_name
        memory.relationship_label = relationship_label
        memory.importance_score = importance_score
        memory.last_summary = last_summary
        memory.known_facts_json = known_facts_json
        memory.sensitive_topics_json = sensitive_topics_json
        memory.open_loops_json = open_loops_json
        memory.interaction_pattern = interaction_pattern
        await self.session.flush()
        return memory

    async def get_person_memory(self, person_key: str) -> PersonMemory | None:
        result = await self.session.execute(
            select(PersonMemory).where(PersonMemory.person_key == person_key)
        )
        return result.scalar_one_or_none()

    async def search_people_memory(
        self,
        query: str,
        *,
        limit: int = 5,
    ) -> list[PersonMemory]:
        normalized = query.strip()
        if not normalized:
            return []

        lowered = normalized.casefold()
        lowered_handle = lowered.lstrip("@")
        result = await self.session.execute(
            select(PersonMemory).order_by(
                desc(PersonMemory.importance_score),
                PersonMemory.display_name,
                PersonMemory.person_key,
            )
        )
        matches = [
            person
            for person in result.scalars().all()
            if _person_matches_query(person, lowered, lowered_handle)
        ]
        matches.sort(key=lambda item: _person_match_rank(item, lowered, lowered_handle))
        return matches[:limit]

    async def get_people_memory_by_keys(self, person_keys: Sequence[str]) -> list[PersonMemory]:
        normalized_keys = [key for key in dict.fromkeys(person_keys) if key]
        if not normalized_keys:
            return []

        result = await self.session.execute(
            select(PersonMemory)
            .where(PersonMemory.person_key.in_(normalized_keys))
            .order_by(
                desc(PersonMemory.importance_score),
                func.lower(PersonMemory.display_name),
                PersonMemory.person_key,
            )
        )
        return list(result.scalars().all())

    async def list_people_memory(self, *, limit: int | None = None) -> list[PersonMemory]:
        statement = select(PersonMemory).order_by(
            desc(PersonMemory.importance_score),
            func.lower(PersonMemory.display_name),
            PersonMemory.person_key,
        )
        if limit is not None:
            statement = statement.limit(limit)
        result = await self.session.execute(statement)
        return list(result.scalars().all())

    async def count_people_memory(self) -> int:
        result = await self.session.execute(select(func.count()).select_from(PersonMemory))
        return int(result.scalar_one())

    async def get_last_updated_at(self) -> datetime | None:
        result = await self.session.execute(select(func.max(PersonMemory.updated_at)))
        return result.scalar_one_or_none()


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
            setting.value_json = cast(dict[str, Any] | list[Any] | None, value_json)
        if value_text is not UNSET:
            setting.value_text = cast(str | None, value_text)

        await self.session.flush()
        return setting


@dataclass(slots=True)
class StyleProfileRepository:
    session: AsyncSession

    async def list_profiles(self) -> list[StyleProfile]:
        result = await self.session.execute(
            select(StyleProfile).order_by(StyleProfile.sort_order, StyleProfile.key)
        )
        return list(result.scalars().all())

    async def count_profiles(self) -> int:
        result = await self.session.execute(select(func.count()).select_from(StyleProfile))
        return int(result.scalar_one())

    async def get_by_key(self, key: str) -> StyleProfile | None:
        normalized = key.strip().lower()
        if not normalized:
            return None

        result = await self.session.execute(
            select(StyleProfile).where(func.lower(StyleProfile.key) == normalized)
        )
        return result.scalar_one_or_none()


@dataclass(slots=True)
class ChatStyleOverrideRepository:
    session: AsyncSession

    async def get_override_for_chat(self, chat_id: int) -> ChatStyleOverride | None:
        result = await self.session.execute(
            select(ChatStyleOverride)
            .options(selectinload(ChatStyleOverride.style_profile))
            .where(ChatStyleOverride.chat_id == chat_id)
        )
        return result.scalar_one_or_none()

    async def set_override(
        self,
        *,
        chat_id: int,
        style_profile_id: int,
    ) -> ChatStyleOverride:
        override = await self.get_override_for_chat(chat_id)
        if override is None:
            override = ChatStyleOverride(
                chat_id=chat_id,
                style_profile_id=style_profile_id,
            )
            self.session.add(override)
        else:
            override.style_profile_id = style_profile_id

        await self.session.flush()
        return override

    async def unset_override(self, *, chat_id: int) -> bool:
        override = await self.get_override_for_chat(chat_id)
        if override is None:
            return False

        await self.session.delete(override)
        await self.session.flush()
        return True

    async def count_overrides(self) -> int:
        result = await self.session.execute(
            select(func.count()).select_from(ChatStyleOverride)
        )
        return int(result.scalar_one())


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


def _build_person_message_filter(person_key: str):
    normalized = person_key.strip()
    if not normalized:
        return None

    if normalized.startswith("tg:"):
        try:
            sender_id = int(normalized.split(":", 1)[1])
        except ValueError:
            return None
        return Message.sender_id == sender_id

    if normalized.startswith("username:"):
        handle = normalized.split(":", 1)[1].strip().casefold()
        if not handle:
            return None
        return func.lower(Message.sender_name) == f"@{handle}"

    if normalized.startswith("name:"):
        name = normalized.split(":", 1)[1].strip().casefold()
        if not name:
            return None
        return func.lower(Message.sender_name) == name

    return func.lower(Message.sender_name) == normalized.casefold()


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


def _coerce_datetime(value: object) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return datetime.now(timezone.utc)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed
    return datetime.now(timezone.utc)


def _person_match_rank(person: PersonMemory, lowered_query: str, lowered_handle: str) -> tuple[int, float, str]:
    lowered_display_name = person.display_name.casefold()
    lowered_key = person.person_key.casefold()

    if lowered_key == lowered_query or lowered_display_name == lowered_query:
        priority = 0
    elif lowered_key == f"username:{lowered_handle}" or lowered_display_name == f"@{lowered_handle}":
        priority = 1
    elif lowered_display_name.startswith(lowered_query) or lowered_display_name.startswith(f"@{lowered_handle}"):
        priority = 2
    else:
        priority = 3

    return (
        priority,
        -float(person.importance_score),
        lowered_display_name,
    )


def _person_matches_query(person: PersonMemory, lowered_query: str, lowered_handle: str) -> bool:
    lowered_display_name = person.display_name.casefold()
    lowered_key = person.person_key.casefold()
    return (
        lowered_key == lowered_query
        or lowered_key == f"username:{lowered_handle}"
        or lowered_display_name == lowered_query
        or lowered_display_name == f"@{lowered_handle}"
        or lowered_display_name.startswith(lowered_query)
        or lowered_display_name.startswith(f"@{lowered_handle}")
    )


def _normalize_task_instance(task: Task) -> Task:
    task.due_at = _normalize_datetime(task.due_at)
    task.suggested_remind_at = _normalize_datetime(task.suggested_remind_at)
    task.created_at = _normalize_datetime(task.created_at) or task.created_at
    task.updated_at = _normalize_datetime(task.updated_at) or task.updated_at
    if "source_message" in task.__dict__ and task.source_message is not None:
        task.source_message.sent_at = _normalize_datetime(task.source_message.sent_at) or task.source_message.sent_at
        task.source_message.created_at = _normalize_datetime(task.source_message.created_at) or task.source_message.created_at
    return task


def _normalize_reminder_instance(reminder: Reminder) -> Reminder:
    reminder.remind_at = _normalize_datetime(reminder.remind_at) or reminder.remind_at
    reminder.last_notification_at = _normalize_datetime(reminder.last_notification_at)
    reminder.created_at = _normalize_datetime(reminder.created_at) or reminder.created_at
    reminder.updated_at = _normalize_datetime(reminder.updated_at) or reminder.updated_at
    return reminder


def _normalize_datetime(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
