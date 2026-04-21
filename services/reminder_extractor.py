from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
import re

from services.memory_common import truncate_text
from services.reminder_models import ReminderCandidate


EXPLICIT_REMINDER_RE = re.compile(r"\bнапомни(?:\s+мне)?\s+(?P<task>.+)", re.IGNORECASE)
FORGET_RE = re.compile(r"\bне забудь\s+(?P<task>.+)", re.IGNORECASE)
NEED_RE = re.compile(r"\b(?:надо|нужно)\s+(?P<task>.+)", re.IGNORECASE)
CALL_RE = re.compile(r"\bсозвонимся\b(?P<task>.*)", re.IGNORECASE)
PROMISE_RE = re.compile(r"\b(?:скину|отправлю)\b(?P<task>.*)", re.IGNORECASE)
TIME_RE = re.compile(r"\b(?P<hour>[01]?\d|2[0-3]):(?P<minute>[0-5]\d)\b")
RELATIVE_HOURS_RE = re.compile(r"\bчерез\s+(?:(?P<count>\d+)\s+)?час(?:а|ов)?\b", re.IGNORECASE)
SCHEDULE_KEYWORDS = {
    "встреча": "Встреча",
    "созвон": "Созвон",
    "дедлайн": "Дедлайн",
}
PERIOD_TIMES = {
    "утром": time(hour=9, minute=0),
    "днём": time(hour=14, minute=0),
    "днем": time(hour=14, minute=0),
    "вечером": time(hour=19, minute=0),
    "ночью": time(hour=21, minute=0),
}
DATE_MARKERS = (
    ("послезавтра", 2),
    ("завтра", 1),
    ("сегодня", 0),
)
TASK_CLEANUP_PATTERNS = (
    re.compile(r"\b(?:сегодня|завтра|послезавтра)\b", re.IGNORECASE),
    re.compile(r"\bчерез\s+\d+\s+час(?:а|ов)?\b", re.IGNORECASE),
    re.compile(r"\bчерез\s+час\b", re.IGNORECASE),
    re.compile(r"\b(?:утром|днём|днем|вечером|ночью)\b", re.IGNORECASE),
    re.compile(r"\bв\s+\d{1,2}:\d{2}\b", re.IGNORECASE),
    re.compile(r"\bпожалуйста\b", re.IGNORECASE),
    re.compile(r"\bмне\b", re.IGNORECASE),
)


@dataclass(frozen=True, slots=True)
class _MatchResult:
    kind: str
    raw_task_text: str
    reasons: tuple[str, ...]
    confidence: float


class ReminderExtractor:
    def extract(
        self,
        message: object,
        *,
        now: datetime | None = None,
    ) -> ReminderCandidate | None:
        sent_at = _ensure_utc(getattr(message, "sent_at", None) or now or datetime.now(timezone.utc))
        extraction_now = _ensure_utc(now or datetime.now(timezone.utc))
        raw_text = _normalize_space(getattr(message, "raw_text", None))
        normalized_text = _normalize_space(getattr(message, "normalized_text", None)) or raw_text
        if not normalized_text:
            return None

        match_result = self._match_text(normalized_text)
        if match_result is None:
            return None

        due_at = _extract_due_at(normalized_text, sent_at)
        title = _build_title(match_result.kind, match_result.raw_task_text, normalized_text)
        if not title:
            return None

        reasons = list(match_result.reasons)
        if due_at is not None:
            reasons.append(f"время/дата: {due_at.strftime('%Y-%m-%d %H:%M UTC')}")

        confidence = min(match_result.confidence + (0.06 if due_at is not None else 0.0), 0.98)
        suggested_remind_at = _suggest_remind_at(due_at=due_at, now=extraction_now)
        return ReminderCandidate(
            title=title,
            summary=truncate_text(raw_text or normalized_text, limit=220),
            due_at=due_at,
            suggested_remind_at=suggested_remind_at,
            confidence=confidence,
            reasons=tuple(reasons),
            source_message_preview=truncate_text(raw_text or normalized_text, limit=180),
            sender_name=getattr(message, "sender_name", None),
        )

    def _match_text(self, text: str) -> _MatchResult | None:
        for regex, kind, reason, confidence in (
            (EXPLICIT_REMINDER_RE, "explicit_reminder", "триггер: напомни", 0.9),
            (FORGET_RE, "forget", "триггер: не забудь", 0.84),
            (CALL_RE, "call", "триггер: созвонимся", 0.78),
            (PROMISE_RE, "promise", "триггер: обещание скинуть/отправить", 0.73),
            (NEED_RE, "need", "триггер: надо/нужно", 0.72),
        ):
            match = regex.search(text)
            if match is None:
                continue
            return _MatchResult(
                kind=kind,
                raw_task_text=match.group("task").strip(),
                reasons=(reason,),
                confidence=confidence,
            )

        lowered = text.casefold()
        for keyword, title in SCHEDULE_KEYWORDS.items():
            if keyword in lowered and _looks_scheduled(lowered):
                return _MatchResult(
                    kind=f"schedule:{title}",
                    raw_task_text=text,
                    reasons=(f"ключевое слово: {keyword}",),
                    confidence=0.7,
                )
        return None


def _build_title(kind: str, raw_task_text: str, full_text: str) -> str | None:
    cleaned_task = _cleanup_task_text(raw_task_text or full_text)
    if kind == "call":
        return _capitalize_first(f"Созвон {cleaned_task}".strip()) if cleaned_task else "Созвон"
    if kind == "promise":
        if cleaned_task:
            return _capitalize_first(f"Проверить обещанное: {cleaned_task}")
        return "Проверить обещанный материал"
    if kind.startswith("schedule:"):
        schedule_title = kind.split(":", 1)[1]
        extracted_tail = _extract_tail_after_schedule_keyword(full_text)
        if extracted_tail:
            return _capitalize_first(f"{schedule_title} {extracted_tail}".strip())
        return schedule_title

    if not cleaned_task:
        return None

    return _capitalize_first(cleaned_task)


def _extract_due_at(text: str, base_time: datetime) -> datetime | None:
    lowered = text.casefold()
    relative_match = RELATIVE_HOURS_RE.search(lowered)
    if relative_match is not None:
        hours = int(relative_match.group("count") or 1)
        return base_time + timedelta(hours=hours)

    day_offset = None
    for marker, offset in DATE_MARKERS:
        if marker in lowered:
            day_offset = offset
            break

    explicit_time = TIME_RE.search(lowered)
    if explicit_time is not None:
        candidate_time = time(
            hour=int(explicit_time.group("hour")),
            minute=int(explicit_time.group("minute")),
        )
        return _combine_date_and_time(
            base_time=base_time,
            candidate_time=candidate_time,
            day_offset=day_offset,
        )

    for marker, candidate_time in PERIOD_TIMES.items():
        if marker in lowered:
            return _combine_date_and_time(
                base_time=base_time,
                candidate_time=candidate_time,
                day_offset=day_offset,
            )

    return None


def _combine_date_and_time(
    *,
    base_time: datetime,
    candidate_time: time,
    day_offset: int | None,
) -> datetime:
    candidate_date = base_time.date()
    if day_offset is not None:
        candidate_date = candidate_date + timedelta(days=day_offset)

    candidate = datetime.combine(
        candidate_date,
        candidate_time,
        tzinfo=base_time.tzinfo or timezone.utc,
    )
    if day_offset is None and candidate <= base_time:
        candidate += timedelta(days=1)
    return candidate


def _suggest_remind_at(
    *,
    due_at: datetime | None,
    now: datetime,
) -> datetime:
    if due_at is None:
        return now + timedelta(hours=1)

    delta = due_at - now
    if delta <= timedelta(minutes=15):
        return now + timedelta(minutes=15)
    if delta <= timedelta(hours=1):
        return due_at - timedelta(minutes=15)
    if delta <= timedelta(hours=4):
        return due_at - timedelta(minutes=30)
    return due_at - timedelta(hours=1)


def _looks_scheduled(text: str) -> bool:
    if TIME_RE.search(text) is not None:
        return True
    if RELATIVE_HOURS_RE.search(text) is not None:
        return True
    return any(marker in text for marker, _ in DATE_MARKERS) or any(
        marker in text for marker in PERIOD_TIMES
    )


def _extract_tail_after_schedule_keyword(text: str) -> str:
    lowered = text.casefold()
    for keyword in SCHEDULE_KEYWORDS:
        if keyword not in lowered:
            continue
        _, tail = lowered.split(keyword, 1)
        cleaned = _cleanup_task_text(tail)
        return cleaned
    return ""


def _cleanup_task_text(value: str) -> str:
    cleaned = _normalize_space(value)
    if not cleaned:
        return ""

    for pattern in TASK_CLEANUP_PATTERNS:
        cleaned = pattern.sub(" ", cleaned)

    cleaned = re.sub(r"\b(?:прошу|просто|тогда)\b", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned)
    cleaned = cleaned.strip(" ,.;:-")
    cleaned = cleaned.strip()
    if cleaned.startswith("про "):
        cleaned = cleaned.removeprefix("про ").strip()
    return cleaned


def _capitalize_first(value: str) -> str:
    normalized = _normalize_space(value)
    if not normalized:
        return ""
    return normalized[0].upper() + normalized[1:]


def _normalize_space(value: str | None) -> str:
    if not value:
        return ""
    return " ".join(value.split()).strip()


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
