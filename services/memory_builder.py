from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from services.chat_memory_builder import ChatMemoryBuilder
from services.memory_formatter import MemoryFormatter
from services.people_memory_builder import PeopleMemoryBuilder
from storage.repositories import (
    ChatMemoryRepository,
    ChatMessageRecord,
    ChatRepository,
    DigestRepository,
    MessageRepository,
    PersonMemoryRepository,
    SettingRepository,
)


@dataclass(frozen=True, slots=True)
class MemoryRebuildResult:
    updated_chat_count: int
    updated_people_count: int
    analyzed_message_count: int

    def to_user_message(self) -> str:
        return "\n".join(
            [
                "Пересборка памяти завершена.",
                f"Чатов обновлено: {self.updated_chat_count}",
                f"Карточек людей обновлено: {self.updated_people_count}",
                f"Проанализировано сообщений: {self.analyzed_message_count}",
            ]
        )


@dataclass(slots=True)
class MemoryService:
    chat_repository: ChatRepository
    message_repository: MessageRepository
    digest_repository: DigestRepository
    setting_repository: SettingRepository
    chat_memory_repository: ChatMemoryRepository
    person_memory_repository: PersonMemoryRepository
    chat_builder: ChatMemoryBuilder
    people_builder: PeopleMemoryBuilder
    formatter: MemoryFormatter

    async def rebuild(self, reference: str | None = None) -> MemoryRebuildResult:
        target_chats = await self._resolve_target_chats(reference)
        analyzed_message_count = 0
        updated_chat_count = 0
        collected_records: list[ChatMessageRecord] = []

        for chat in target_chats:
            chat_messages = await self.message_repository.get_messages_for_chat(chat_id=chat.id)
            if not chat_messages:
                continue

            analyzed_message_count += len(chat_messages)
            top_senders = await self.message_repository.get_top_senders_for_chat(chat_id=chat.id)
            last_digest_at = await self.digest_repository.get_last_digest_at_for_chat(chat.id)
            snapshot = self.chat_builder.build(
                chat=chat,
                messages=chat_messages,
                top_senders=top_senders,
                last_digest_at=last_digest_at,
            )
            await self.chat_memory_repository.upsert_chat_memory(
                chat_id=snapshot.chat_id,
                chat_summary_short=snapshot.chat_summary_short,
                chat_summary_long=snapshot.chat_summary_long,
                current_state=snapshot.current_state,
                dominant_topics_json=snapshot.dominant_topics_json,
                recent_conflicts_json=snapshot.recent_conflicts_json,
                pending_tasks_json=snapshot.pending_tasks_json,
                linked_people_json=snapshot.linked_people_json,
                last_digest_at=snapshot.last_digest_at,
            )
            updated_chat_count += 1
            collected_records.extend(
                ChatMessageRecord(chat=chat, message=message)
                for message in chat_messages
            )

        people_snapshots = self.people_builder.build(records=collected_records)
        for snapshot in people_snapshots:
            await self.person_memory_repository.upsert_person_memory(
                person_key=snapshot.person_key,
                display_name=snapshot.display_name,
                relationship_label=snapshot.relationship_label,
                importance_score=snapshot.importance_score,
                last_summary=snapshot.last_summary,
                known_facts_json=snapshot.known_facts_json,
                sensitive_topics_json=snapshot.sensitive_topics_json,
                open_loops_json=snapshot.open_loops_json,
                interaction_pattern=snapshot.interaction_pattern,
            )

        rebuilt_at = datetime.now(timezone.utc)
        await self.setting_repository.set_value(
            key="memory.last_rebuild_at",
            value_text=rebuilt_at.isoformat(),
        )
        await self.setting_repository.set_value(
            key="memory.last_rebuild_stats",
            value_json={
                "updated_chat_count": updated_chat_count,
                "updated_people_count": len(people_snapshots),
                "analyzed_message_count": analyzed_message_count,
                "reference": reference,
            },
        )

        return MemoryRebuildResult(
            updated_chat_count=updated_chat_count,
            updated_people_count=len(people_snapshots),
            analyzed_message_count=analyzed_message_count,
        )

    async def build_chat_memory_card(self, reference: str | None) -> str:
        if reference is None or not reference.strip():
            chats = await self.chat_repository.list_enabled_memory_chats()
            return self.formatter.format_chat_help(chats)

        chat = await self.chat_repository.find_chat_by_handle_or_telegram_id(reference)
        if chat is None:
            return "Источник не найден. Проверь chat_id или @username."

        memory = await self.chat_memory_repository.get_chat_memory(chat.id)
        if memory is None:
            return (
                f"Память по чату «{chat.title}» ещё не собрана. "
                "Сначала запусти /memory_rebuild."
            )

        message_count = await self.message_repository.count_messages_for_chat(chat_id=chat.id)
        return self.formatter.format_chat_card(
            chat=chat,
            memory=memory,
            message_count=message_count,
        )

    async def build_person_memory_card(self, query: str | None) -> str:
        if query is None or not query.strip():
            people = await self.person_memory_repository.list_people_memory(limit=8)
            return self.formatter.format_person_help(people)

        normalized_query = query.strip()
        person_memory = await self.person_memory_repository.get_person_memory(normalized_query)
        if person_memory is None:
            matches = await self.person_memory_repository.search_people_memory(normalized_query)
            if not matches:
                return f"Память по человеку «{normalized_query}» ещё не собрана."
            if len(matches) > 1 and not _is_direct_person_match(matches[0], normalized_query):
                return self.formatter.format_person_search_results(
                    query=normalized_query,
                    matches=matches,
                )
            person_memory = matches[0]

        message_count = await self.message_repository.count_messages_for_person(
            person_key=person_memory.person_key
        )
        return self.formatter.format_person_card(
            memory=person_memory,
            message_count=message_count,
        )

    async def _resolve_target_chats(self, reference: str | None):
        if reference is None or not reference.strip():
            return await self.chat_repository.list_enabled_memory_chats()

        chat = await self.chat_repository.find_chat_by_handle_or_telegram_id(reference.strip())
        if chat is None:
            raise ValueError("Источник не найден. Проверь chat_id или @username.")
        return [chat]


def _is_direct_person_match(person_memory, query: str) -> bool:
    lowered_query = query.casefold()
    lowered_handle = lowered_query.lstrip("@")
    return (
        person_memory.person_key.casefold() == lowered_query
        or person_memory.person_key.casefold() == f"username:{lowered_handle}"
        or person_memory.display_name.casefold() == lowered_query
        or person_memory.display_name.casefold() == f"@{lowered_handle}"
    )
