from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from services.memory_common import (
    PersonReference,
    build_person_reference,
    detect_sensitive_topics,
    extract_dominant_topics,
    format_utc,
    looks_like_open_loop,
    summarize_topics,
    truncate_text,
)
from storage.repositories import ChatMessageRecord


@dataclass(frozen=True, slots=True)
class PersonMemorySnapshot:
    person_key: str
    display_name: str
    relationship_label: str
    importance_score: float
    last_summary: str
    known_facts_json: list[str]
    sensitive_topics_json: list[str]
    open_loops_json: list[str]
    interaction_pattern: str


@dataclass(slots=True)
class PeopleMemoryBuilder:
    max_topics: int = 4
    max_open_loops: int = 4

    def build(self, *, records: Sequence[ChatMessageRecord]) -> list[PersonMemorySnapshot]:
        if not records:
            return []

        latest_seen_at = max(record.message.sent_at for record in records)
        grouped_records: dict[str, list[tuple[PersonReference, ChatMessageRecord]]] = defaultdict(list)
        for record in records:
            fallback_title = record.chat.title if record.chat.type == "private" else None
            fallback_handle = record.chat.handle if record.chat.type == "private" else None
            person = build_person_reference(
                sender_id=record.message.sender_id,
                sender_name=record.message.sender_name,
                fallback_title=fallback_title,
                fallback_handle=fallback_handle,
            )
            if person is None:
                continue
            grouped_records[person.person_key].append((person, record))

        snapshots = [
            self._build_person_snapshot(
                person_key=person_key,
                person_records=person_records,
                latest_seen_at=latest_seen_at,
            )
            for person_key, person_records in grouped_records.items()
        ]
        snapshots.sort(key=lambda item: (-item.importance_score, item.display_name.casefold()))
        return snapshots

    def _build_person_snapshot(
        self,
        *,
        person_key: str,
        person_records: Sequence[tuple[PersonReference, ChatMessageRecord]],
        latest_seen_at: datetime,
    ) -> PersonMemorySnapshot:
        ordered_records = sorted(
            person_records,
            key=lambda item: (item[1].message.sent_at, item[1].message.id),
        )
        display_name = ordered_records[-1][0].display_name
        message_count = len(ordered_records)
        texts = [text for _, record in ordered_records if (text := _pick_message_text(record))]
        topics = extract_dominant_topics(texts, limit=self.max_topics)
        topic_summary = summarize_topics(topics)
        chat_counter = Counter(record.chat.title for _, record in ordered_records)
        chat_titles = list(chat_counter.keys())
        private_count = sum(1 for _, record in ordered_records if record.chat.type == "private")
        unique_days = {record.message.sent_at.date() for _, record in ordered_records}
        avg_length = (
            sum(len(text) for text in texts) / len(texts)
            if texts
            else 0.0
        )
        question_count = sum(1 for text in texts if "?" in text)
        open_loops = self._collect_open_loops(ordered_records)
        sensitive_topics = detect_sensitive_topics(texts)
        importance_score = _calculate_importance(
            message_count=message_count,
            chat_count=len(chat_titles),
            last_seen_at=ordered_records[-1][1].message.sent_at,
            latest_seen_at=latest_seen_at,
        )
        interaction_pattern = _build_interaction_pattern(
            message_count=message_count,
            unique_day_count=len(unique_days),
            private_count=private_count,
            total_count=message_count,
            average_length=avg_length,
            question_count=question_count,
        )
        known_facts = [
            f"Замечен в чатах: {', '.join(chat_titles[:4])}.",
            f"Чаще всего пишет в чате «{chat_counter.most_common(1)[0][0]}».",
            (
                f"Повторяющиеся темы: {topic_summary}."
                if topics
                else "Повторяющиеся темы пока не выделены."
            ),
            f"Последняя активность: {format_utc(ordered_records[-1][1].message.sent_at)}.",
        ]
        last_summary = truncate_text(
            (
                f"{display_name}: {message_count} сообщений, чаты — {', '.join(chat_titles[:3])}. "
                f"Темы: {topic_summary}. "
                f"{'Есть открытые хвосты.' if open_loops else 'Явных открытых хвостов не видно.'}"
            ),
            limit=320,
        )

        return PersonMemorySnapshot(
            person_key=person_key,
            display_name=display_name,
            relationship_label="контакт",
            importance_score=importance_score,
            last_summary=last_summary,
            known_facts_json=known_facts,
            sensitive_topics_json=sensitive_topics,
            open_loops_json=open_loops,
            interaction_pattern=interaction_pattern,
        )

    def _collect_open_loops(
        self,
        person_records: Sequence[tuple[PersonReference, ChatMessageRecord]],
    ) -> list[str]:
        loops: list[str] = []
        for _, record in reversed(person_records[-20:]):
            text = _pick_message_text(record)
            if not looks_like_open_loop(text):
                continue
            line = _format_person_message_line(record)
            if line not in loops:
                loops.append(line)
            if len(loops) >= self.max_open_loops:
                break
        return loops


def _pick_message_text(record: ChatMessageRecord) -> str:
    return " ".join((record.message.normalized_text or record.message.raw_text or "").split()).strip()


def _format_person_message_line(record: ChatMessageRecord) -> str:
    return (
        f"{record.message.sent_at.strftime('%H:%M')} "
        f"{truncate_text(_pick_message_text(record), limit=120)}"
    ).strip()


def _calculate_importance(
    *,
    message_count: int,
    chat_count: int,
    last_seen_at: datetime,
    latest_seen_at: datetime,
) -> float:
    message_score = min(message_count * 12, 60)
    chat_score = min(chat_count * 10, 20)
    recency_hours = max((latest_seen_at - last_seen_at).total_seconds() / 3600, 0.0)
    if recency_hours <= 24:
        recency_score = 20
    elif recency_hours <= 72:
        recency_score = 15
    elif recency_hours <= 168:
        recency_score = 10
    else:
        recency_score = 5
    return round(message_score + chat_score + recency_score, 1)


def _build_interaction_pattern(
    *,
    message_count: int,
    unique_day_count: int,
    private_count: int,
    total_count: int,
    average_length: float,
    question_count: int,
) -> str:
    if message_count >= 5 or unique_day_count >= 3:
        frequency = "регулярно выходит на связь"
    elif message_count >= 3:
        frequency = "периодически выходит на связь"
    else:
        frequency = "редко появляется"

    private_ratio = private_count / total_count if total_count else 0.0
    if private_ratio >= 0.5:
        context = "чаще общение один на один"
    else:
        context = "чаще встречается в группах"

    if average_length >= 40:
        style = "обычно пишет развёрнуто"
    else:
        style = "обычно пишет коротко"

    if question_count >= max(2, message_count // 2):
        style += ", часто задаёт вопросы"

    return f"{frequency}; {context}; {style}."
