from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from difflib import SequenceMatcher
from services.digest_window import DigestWindow
from storage.repositories import DigestMessageRecord


MAX_POINTS_PER_SOURCE = 5
MAX_POINT_TEXT_LENGTH = 220
SHORT_NOISE_MESSAGES = {
    "+",
    "++",
    "ага",
    "да",
    "ок",
    "окей",
    "понял",
    "принято",
    "спасибо",
    "ясно",
}


@dataclass(frozen=True, slots=True)
class DigestSourcePoint:
    source_message_id: int | None
    text: str
    score: float


@dataclass(frozen=True, slots=True)
class DigestSourceSummary:
    chat_id: int
    telegram_chat_id: int
    title: str
    handle: str | None
    message_count: int
    points: list[DigestSourcePoint]
    representative_message_id: int | None

    @property
    def display_title(self) -> str:
        if self.handle:
            return f"{self.title} (@{self.handle})"
        return self.title

    @property
    def top_score(self) -> float:
        if not self.points:
            return 0.0
        return self.points[0].score


@dataclass(frozen=True, slots=True)
class DigestBuildResult:
    window: DigestWindow
    total_messages: int
    source_count: int
    summary_short: str
    overview_lines: list[str]
    key_source_lines: list[str]
    source_summaries: list[DigestSourceSummary]

    def to_digest_items(self) -> list[dict[str, object]]:
        items: list[dict[str, object]] = []
        for index, source in enumerate(self.source_summaries, start=1):
            items.append(
                {
                    "source_chat_id": source.chat_id,
                    "source_message_id": source.representative_message_id,
                    "title": source.title,
                    "summary": "\n".join(f"- {point.text}" for point in source.points),
                    "sort_order": index,
                }
            )
        return items


@dataclass(slots=True)
class DigestBuilder:
    max_points_per_source: int = MAX_POINTS_PER_SOURCE

    def build(
        self,
        *,
        window: DigestWindow,
        records: list[DigestMessageRecord],
        message_counts: dict[int, int],
    ) -> DigestBuildResult:
        grouped_records: dict[int, list[DigestMessageRecord]] = defaultdict(list)
        for record in records:
            grouped_records[record.chat.id].append(record)

        source_summaries: list[DigestSourceSummary] = []
        for chat_id, source_records in grouped_records.items():
            summary = self._build_source_summary(
                source_records,
                message_count=message_counts.get(chat_id, len(source_records)),
            )
            if summary is not None:
                source_summaries.append(summary)

        source_summaries.sort(
            key=lambda item: (-item.message_count, -item.top_score, item.display_title.casefold())
        )

        total_messages = len(records)
        source_count = len(message_counts)
        top_sources = source_summaries[:3]
        top_source_labels = [
            f"{source.title} ({source.message_count})"
            for source in top_sources
        ]

        overview_lines = [
            f"- Всего сообщений в окне: {total_messages}.",
            f"- Источников с активностью: {source_count}.",
        ]
        if top_source_labels:
            overview_lines.append(
                "- Самые активные источники: " + ", ".join(top_source_labels) + "."
            )
        else:
            overview_lines.append("- Содержательных источников в окне не найдено.")

        key_source_lines = [
            f"- {source.display_title}: {source.message_count} сообщ., {len(source.points)} ключевых пункта."
            for source in source_summaries
        ]

        if top_source_labels:
            summary_short = (
                f"За {window.label}: {total_messages} сообщений из {source_count} источников. "
                f"Самые активные: {', '.join(top_source_labels)}."
            )
        else:
            summary_short = (
                f"За {window.label}: {total_messages} сообщений из {source_count} источников. "
                "Содержательных пунктов для digest не выделено."
            )

        return DigestBuildResult(
            window=window,
            total_messages=total_messages,
            source_count=source_count,
            summary_short=summary_short,
            overview_lines=overview_lines,
            key_source_lines=key_source_lines,
            source_summaries=source_summaries,
        )

    def _build_source_summary(
        self,
        records: list[DigestMessageRecord],
        *,
        message_count: int,
    ) -> DigestSourceSummary | None:
        ordered_records = sorted(
            records,
            key=lambda item: (item.message.sent_at, item.message.id),
            reverse=True,
        )
        seen_texts: list[str] = []
        points: list[DigestSourcePoint] = []
        media_only_count = 0

        for record in ordered_records:
            text = _pick_message_text(record)
            if not text:
                if record.message.has_media:
                    media_only_count += 1
                continue

            canonical = _canonicalize_text(text)
            if _is_noise(canonical):
                continue
            if any(_is_near_duplicate(canonical, existing) for existing in seen_texts):
                continue

            seen_texts.append(canonical)
            point_text = _format_point_text(record, text)
            points.append(
                DigestSourcePoint(
                    source_message_id=record.message.id,
                    text=point_text,
                    score=_score_record(record, canonical),
                )
            )

        points.sort(key=lambda item: item.score, reverse=True)
        points = points[: self.max_points_per_source]

        if not points and media_only_count:
            points.append(
                DigestSourcePoint(
                    source_message_id=ordered_records[0].message.id,
                    text=f"В окне были {media_only_count} медиа-сообщений без текста.",
                    score=0.1,
                )
            )
        if not points and ordered_records:
            points.append(
                DigestSourcePoint(
                    source_message_id=ordered_records[0].message.id,
                    text="В окне были только короткие служебные реплики без явных деталей.",
                    score=0.1,
                )
            )

        if not points:
            return None

        first_record = ordered_records[0]
        return DigestSourceSummary(
            chat_id=first_record.chat.id,
            telegram_chat_id=first_record.chat.telegram_chat_id,
            title=first_record.chat.title,
            handle=first_record.chat.handle,
            message_count=message_count,
            points=points,
            representative_message_id=points[0].source_message_id,
        )


def _pick_message_text(record: DigestMessageRecord) -> str:
    text = record.message.normalized_text or record.message.raw_text
    return " ".join(text.split()).strip()


def _format_point_text(record: DigestMessageRecord, text: str) -> str:
    time_label = record.message.sent_at.strftime("%H:%M")
    sender_prefix = f"{record.message.sender_name}: " if record.message.sender_name else ""
    media_suffix = (
        f" [media: {record.message.media_type}]"
        if record.message.has_media and record.message.media_type and text
        else ""
    )
    return f"{time_label} {sender_prefix}{_truncate_text(text)}{media_suffix}".strip()


def _truncate_text(text: str, *, limit: int = MAX_POINT_TEXT_LENGTH) -> str:
    normalized = " ".join(text.split()).strip()
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 3].rstrip() + "..."


def _score_record(record: DigestMessageRecord, canonical_text: str) -> float:
    length_score = min(len(canonical_text), 280) / 40
    media_bonus = 0.5 if record.message.has_media and canonical_text else 0.0
    numeric_bonus = 0.4 if any(symbol.isdigit() for symbol in canonical_text) else 0.0
    punctuation_bonus = 0.25 if any(symbol in canonical_text for symbol in ".:;!?") else 0.0
    sender_bonus = 0.15 if record.message.sender_name else 0.0
    short_penalty = 1.5 if len(canonical_text) < 18 else 0.0
    return length_score + media_bonus + numeric_bonus + punctuation_bonus + sender_bonus - short_penalty


def _canonicalize_text(text: str) -> str:
    normalized = []
    previous_space = False
    for symbol in text.casefold():
        if symbol.isalnum():
            normalized.append(symbol)
            previous_space = False
            continue
        if symbol.isspace() and not previous_space:
            normalized.append(" ")
            previous_space = True
    return "".join(normalized).strip()


def _is_noise(text: str) -> bool:
    if not text:
        return True
    if text in SHORT_NOISE_MESSAGES:
        return True
    return len(text) < 6


def _is_near_duplicate(left: str, right: str) -> bool:
    if left == right:
        return True
    if len(left) >= 24 and len(right) >= 24 and (left in right or right in left):
        return True
    return SequenceMatcher(a=left, b=right).ratio() >= 0.92
