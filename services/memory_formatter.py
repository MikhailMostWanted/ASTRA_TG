from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from models import Chat, ChatMemory, PersonMemory
from services.memory_common import format_utc


@dataclass(slots=True)
class MemoryFormatter:
    def format_chat_card(
        self,
        *,
        chat: Chat,
        memory: ChatMemory,
        message_count: int,
    ) -> str:
        lines = [
            f"🧠 Память по чату: {chat.title}",
            f"Коротко: {memory.chat_summary_short}",
            f"Сейчас: {memory.current_state or 'не определено'}",
            f"Сообщений в базе: {message_count}",
            f"Тип чата: {_human_chat_type(chat.type)}",
            _format_string_section(
                "Доминирующие темы",
                [
                    f"{item.get('topic')} ({item.get('mentions')})"
                    for item in (memory.dominant_topics_json or [])
                    if isinstance(item, dict) and item.get("topic")
                ],
                empty_text="темы пока не выделены",
            ),
            _format_string_section(
                "Незакрытые темы",
                [str(item) for item in (memory.pending_tasks_json or [])],
                empty_text="явных хвостов пока нет",
            ),
            _format_people_section(_coerce_people_items(memory.linked_people_json)),
            _format_string_section(
                "Напряжённые сигналы",
                [str(item) for item in (memory.recent_conflicts_json or [])],
                empty_text="не замечены",
            ),
            f"Последний дайджест: {format_utc(memory.last_digest_at)}",
            f"Память обновлена: {format_utc(memory.updated_at)}",
        ]
        return "\n".join(lines)

    def format_person_card(
        self,
        *,
        memory: PersonMemory,
        message_count: int,
    ) -> str:
        lines = [
            f"🧠 Память по человеку: {memory.display_name}",
            f"Ключ: {memory.person_key}",
            f"Статус: {memory.relationship_label or 'контакт'}",
            f"Связанных сообщений: {message_count}",
            f"Паттерн общения: {memory.interaction_pattern or 'пока не определён'}",
            f"Коротко: {memory.last_summary or 'сводка пока не собрана'}",
            _format_string_section(
                "Известные факты",
                [str(item) for item in (memory.known_facts_json or [])],
                empty_text="пока нет подтверждённых фактов",
            ),
            _format_string_section(
                "Чувствительные темы",
                [str(item) for item in (memory.sensitive_topics_json or [])],
                empty_text="не выделены",
            ),
            _format_string_section(
                "Открытые хвосты",
                [str(item) for item in (memory.open_loops_json or [])],
                empty_text="явных хвостов пока нет",
            ),
            f"Память обновлена: {format_utc(memory.updated_at)}",
        ]
        return "\n".join(lines)

    def format_chat_help(self, chats: Sequence[Chat]) -> str:
        lines = [
            "Использование: /chat_memory <chat_id|@username>",
            "",
            "Доступные источники:",
        ]
        if not chats:
            lines.append("• Пока нет активных memory-источников.")
            return "\n".join(lines)

        for chat in chats[:8]:
            reference = f"@{chat.handle}" if chat.handle else str(chat.telegram_chat_id)
            lines.append(f"• {chat.title} — {reference}")
        return "\n".join(lines)

    def format_person_help(self, people: Sequence[PersonMemory]) -> str:
        lines = [
            "Использование: /person_memory <person_key|имя|@username>",
            "",
            "Уже собранные карточки:",
        ]
        if not people:
            lines.append("• Пока нет собранной памяти по людям.")
            return "\n".join(lines)

        for person in people[:8]:
            lines.append(f"• {person.display_name} — {person.person_key}")
        return "\n".join(lines)

    def format_person_search_results(
        self,
        *,
        query: str,
        matches: Sequence[PersonMemory],
    ) -> str:
        lines = [
            f"Найдено несколько совпадений для «{query}». Уточни person_key:",
        ]
        for person in matches[:8]:
            lines.append(f"• {person.display_name} — {person.person_key}")
        return "\n".join(lines)


def _format_string_section(title: str, items: Sequence[str], *, empty_text: str) -> str:
    lines = [f"{title}:"]
    if not items:
        lines.append(f"• {empty_text}")
        return "\n".join(lines)

    for item in items[:5]:
        lines.append(f"• {item}")
    return "\n".join(lines)


def _format_people_section(items: Sequence[dict[str, Any]]) -> str:
    lines = ["Связанные люди:"]
    if not items:
        lines.append("• пока не выделены")
        return "\n".join(lines)

    for item in items[:5]:
        display_name = item.get("display_name") or item.get("person_key") or "без имени"
        message_count = item.get("message_count")
        if message_count is None:
            lines.append(f"• {display_name}")
            continue
        lines.append(f"• {display_name} — {message_count} сообщ.")
    return "\n".join(lines)


def _coerce_people_items(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _human_chat_type(chat_type: str) -> str:
    return {
        "private": "личный чат",
        "group": "группа",
        "supergroup": "супергруппа",
        "channel": "канал",
    }.get(chat_type, chat_type)
