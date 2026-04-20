from __future__ import annotations

from dataclasses import dataclass

from models import Chat, Message
from services.memory_common import build_person_reference, extract_dominant_topics, truncate_text
from services.reply_models import ReplyContext, ReplyContextIssue
from storage.repositories import ChatMemoryRepository, MessageRepository, PersonMemoryRepository


@dataclass(slots=True)
class ReplyContextBuilder:
    message_repository: MessageRepository
    chat_memory_repository: ChatMemoryRepository
    person_memory_repository: PersonMemoryRepository
    context_limit: int = 40
    min_messages: int = 3

    async def build(self, chat: Chat) -> ReplyContext | ReplyContextIssue:
        recent_desc = await self.message_repository.get_recent_messages(
            chat_id=chat.id,
            limit=self.context_limit,
        )
        if not recent_desc:
            return ReplyContextIssue(
                code="not_enough_data",
                message=(
                    "Подсказку пока не собрать: в этом чате ещё нет накопленного локального контекста."
                ),
            )

        recent_messages = tuple(reversed(recent_desc))
        latest_message = recent_messages[-1]
        if latest_message.direction == "outbound":
            return ReplyContextIssue(
                code="latest_is_self",
                message=(
                    "Подсказку не строю: последнее сохранённое сообщение уже от тебя. "
                    "Лучше дождаться новой входящей реплики."
                ),
            )

        text_messages = [message for message in recent_messages if _pick_message_text(message)]
        if len(text_messages) < self.min_messages:
            return ReplyContextIssue(
                code="not_enough_data",
                message=(
                    "Подсказку пока не собрать: локальных сообщений маловато для внятного контекста. "
                    "Накопи ещё несколько реплик и повтори /reply."
                ),
            )

        target_message = next(
            (
                message
                for message in reversed(recent_messages)
                if message.direction == "inbound" and _pick_message_text(message)
            ),
            None,
        )
        if target_message is None:
            return ReplyContextIssue(
                code="not_enough_data",
                message=(
                    "Подсказку пока не собрать: не вижу последнего входящего сообщения, "
                    "на которое логично отвечать."
                ),
            )

        chat_memory = await self.chat_memory_repository.get_chat_memory(chat.id)
        person_memory = await self._resolve_person_memory(chat, target_message)
        linked_people = await self._resolve_linked_people(chat_memory, person_memory)
        pending_loops = tuple(
            str(item)
            for item in (
                getattr(chat_memory, "pending_tasks_json", None) or []
            )
            if str(item).strip()
        )[:4]
        recent_conflicts = tuple(
            str(item)
            for item in (
                getattr(chat_memory, "recent_conflicts_json", None) or []
            )
            if str(item).strip()
        )[:3]
        topic_hints = self._collect_topic_hints(
            target_message=target_message,
            chat_memory=chat_memory,
            recent_messages=recent_messages,
        )

        return ReplyContext(
            chat=chat,
            recent_messages=recent_messages,
            latest_message=latest_message,
            target_message=target_message,
            chat_memory=chat_memory,
            person_memory=person_memory,
            linked_people=linked_people,
            topic_hints=topic_hints,
            pending_loops=pending_loops,
            recent_conflicts=recent_conflicts,
        )

    async def _resolve_person_memory(self, chat: Chat, message: Message):
        fallback_title = chat.title if chat.type == "private" else None
        fallback_handle = chat.handle if chat.type == "private" else None
        person_reference = build_person_reference(
            sender_id=message.sender_id,
            sender_name=message.sender_name,
            fallback_title=fallback_title,
            fallback_handle=fallback_handle,
        )
        if person_reference is None:
            return None
        person_memory = await self.person_memory_repository.get_person_memory(
            person_reference.person_key
        )
        if person_memory is not None:
            return person_memory

        matches = await self.person_memory_repository.search_people_memory(
            person_reference.display_name,
            limit=1,
        )
        return matches[0] if matches else None

    async def _resolve_linked_people(self, chat_memory, person_memory):
        person_keys = [
            str(item.get("person_key"))
            for item in ((getattr(chat_memory, "linked_people_json", None) or []))
            if isinstance(item, dict) and item.get("person_key")
        ]
        linked_people = await self.person_memory_repository.get_people_memory_by_keys(person_keys)
        if person_memory is not None and all(
            item.person_key != person_memory.person_key for item in linked_people
        ):
            linked_people = [person_memory, *linked_people]
        return tuple(linked_people[:4])

    def _collect_topic_hints(
        self,
        *,
        target_message: Message,
        chat_memory,
        recent_messages: tuple[Message, ...],
    ) -> tuple[str, ...]:
        hints: list[str] = []
        for item in (getattr(chat_memory, "dominant_topics_json", None) or []):
            if isinstance(item, dict) and item.get("topic"):
                hints.append(str(item["topic"]).strip())

        recent_texts = [_pick_message_text(target_message)]
        recent_texts.extend(
            _pick_message_text(message)
            for message in recent_messages[-6:]
            if message.id != target_message.id
        )
        extracted_topics = extract_dominant_topics(
            [text for text in recent_texts if text],
            limit=3,
        )
        for topic in extracted_topics:
            label = str(topic.get("topic") or "").strip()
            if label:
                hints.append(label)

        unique_hints: list[str] = []
        seen: set[str] = set()
        for hint in hints:
            lowered = hint.casefold()
            if lowered in seen:
                continue
            seen.add(lowered)
            unique_hints.append(truncate_text(hint, limit=40))
        return tuple(unique_hints[:3])


def _pick_message_text(message: Message) -> str:
    return " ".join((message.normalized_text or message.raw_text or "").split()).strip()
