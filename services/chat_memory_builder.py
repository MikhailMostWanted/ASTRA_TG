from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from models import Chat, Message
from services.memory_common import (
    build_person_reference,
    extract_dominant_topics,
    looks_like_conflict,
    looks_like_open_loop,
    summarize_topics,
    truncate_text,
)


@dataclass(frozen=True, slots=True)
class ChatMemorySnapshot:
    chat_id: int
    chat_summary_short: str
    chat_summary_long: str
    current_state: str | None
    dominant_topics_json: list[dict[str, Any]]
    recent_conflicts_json: list[str]
    pending_tasks_json: list[str]
    linked_people_json: list[dict[str, Any]]
    last_digest_at: datetime | None


@dataclass(slots=True)
class ChatMemoryBuilder:
    max_topics: int = 5
    max_pending: int = 4
    max_conflicts: int = 3
    max_people: int = 6

    def build(
        self,
        *,
        chat: Chat,
        messages: Sequence[Message],
        top_senders: Sequence[dict[str, Any]],
        last_digest_at: datetime | None,
    ) -> ChatMemorySnapshot:
        texts = [text for message in messages if (text := _pick_message_text(message))]
        dominant_topics = extract_dominant_topics(texts, limit=self.max_topics)
        pending_tasks = self._collect_pending_tasks(messages)
        recent_conflicts = self._collect_recent_conflicts(messages)
        linked_people = self._build_linked_people(top_senders)
        current_state = self._build_current_state(messages, pending_tasks, recent_conflicts)
        topics_text = summarize_topics(dominant_topics)
        people_text = ", ".join(
            person["display_name"] for person in linked_people[:3] if person.get("display_name")
        ) or "состав участников пока не выделен"

        summary_short = truncate_text(
            (
                f"{_human_chat_type(chat.type).capitalize()}: {len(messages)} сообщ. "
                f"Темы: {topics_text}. Состояние: {current_state}."
            ),
            limit=240,
        )
        summary_long = truncate_text(
            (
                f"В чате «{chat.title}» сохранено {len(messages)} сообщений. "
                f"Основные участники: {people_text}. "
                f"Повторяющиеся темы: {topics_text}. "
                f"{'Есть незакрытые темы: ' + '; '.join(pending_tasks[:2]) + '. ' if pending_tasks else ''}"
                f"{'Есть конфликтные сигналы: ' + '; '.join(recent_conflicts[:1]) + '. ' if recent_conflicts else ''}"
            ),
            limit=700,
        )

        return ChatMemorySnapshot(
            chat_id=chat.id,
            chat_summary_short=summary_short,
            chat_summary_long=summary_long,
            current_state=current_state,
            dominant_topics_json=dominant_topics,
            recent_conflicts_json=recent_conflicts,
            pending_tasks_json=pending_tasks,
            linked_people_json=linked_people,
            last_digest_at=last_digest_at,
        )

    def _collect_pending_tasks(self, messages: Sequence[Message]) -> list[str]:
        pending: list[str] = []
        for message in reversed(messages[-20:]):
            text = _pick_message_text(message)
            if not looks_like_open_loop(text):
                continue
            line = _format_message_line(message)
            if line not in pending:
                pending.append(line)
            if len(pending) >= self.max_pending:
                break
        return pending

    def _collect_recent_conflicts(self, messages: Sequence[Message]) -> list[str]:
        conflicts: list[str] = []
        for message in reversed(messages[-20:]):
            text = _pick_message_text(message)
            if not looks_like_conflict(text):
                continue
            line = _format_message_line(message)
            if line not in conflicts:
                conflicts.append(line)
            if len(conflicts) >= self.max_conflicts:
                break
        return conflicts

    def _build_linked_people(self, top_senders: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
        linked_people: list[dict[str, Any]] = []
        for sender in top_senders[: self.max_people]:
            person = build_person_reference(
                sender_id=sender.get("sender_id"),
                sender_name=sender.get("sender_name"),
            )
            if person is None:
                continue
            linked_people.append(
                {
                    "person_key": person.person_key,
                    "display_name": person.display_name,
                    "message_count": int(sender.get("message_count", 0)),
                }
            )
        return linked_people

    def _build_current_state(
        self,
        messages: Sequence[Message],
        pending_tasks: Sequence[str],
        recent_conflicts: Sequence[str],
    ) -> str:
        span_hours = _calculate_span_hours(messages)
        average_length = _average_text_length(messages)

        if len(messages) >= 6 and span_hours <= 24:
            state = "активное обсуждение"
        elif average_length <= 28 and len(messages) >= 3:
            state = "много коротких реплик"
        elif len(messages) <= 2:
            state = "пока мало накопленных сообщений"
        else:
            state = "спокойное рабочее обсуждение"

        if recent_conflicts:
            state += ", есть напряжённые сигналы"
        elif pending_tasks:
            state += ", есть открытые хвосты"

        return state


def _pick_message_text(message: Message) -> str:
    return " ".join((message.normalized_text or message.raw_text or "").split()).strip()


def _format_message_line(message: Message) -> str:
    sender_prefix = f"{message.sender_name}: " if message.sender_name else ""
    time_label = message.sent_at.strftime("%H:%M")
    return f"{time_label} {sender_prefix}{truncate_text(_pick_message_text(message), limit=120)}".strip()


def _calculate_span_hours(messages: Sequence[Message]) -> float:
    if len(messages) < 2:
        return 0.0
    start = messages[0].sent_at
    finish = messages[-1].sent_at
    return max((finish - start).total_seconds() / 3600, 0.0)


def _average_text_length(messages: Sequence[Message]) -> float:
    lengths = [len(_pick_message_text(message)) for message in messages if _pick_message_text(message)]
    if not lengths:
        return 0.0
    return sum(lengths) / len(lengths)


def _human_chat_type(chat_type: str) -> str:
    return {
        "private": "личный чат",
        "group": "группа",
        "supergroup": "супергруппа",
        "channel": "канал",
    }.get(chat_type, chat_type)
