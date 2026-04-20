from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
import re
from typing import Any


WORD_PATTERN = re.compile(r"[0-9A-Za-zА-Яа-яЁё]{3,}")
STOP_WORDS = {
    "это",
    "как",
    "так",
    "что",
    "или",
    "для",
    "при",
    "над",
    "под",
    "если",
    "когда",
    "потом",
    "после",
    "сегодня",
    "завтра",
    "вчера",
    "просто",
    "очень",
    "снова",
    "опять",
    "ещё",
    "только",
    "нужно",
    "надо",
    "будет",
    "буду",
    "были",
    "было",
    "есть",
    "нет",
    "там",
    "тут",
    "тоже",
    "уже",
    "меня",
    "тебя",
    "него",
    "неё",
    "них",
    "всем",
    "нам",
    "вам",
    "его",
    "её",
    "the",
    "and",
    "for",
    "with",
    "that",
    "this",
    "from",
    "have",
    "will",
    "just",
    "into",
    "about",
    "after",
    "before",
    "your",
    "our",
    "или",
    "она",
    "они",
    "оно",
    "ему",
    "ей",
    "мой",
    "моя",
    "твой",
    "твоя",
    "вот",
    "еще",
}
OPEN_LOOP_MARKERS = (
    "завтра",
    "потом",
    "позже",
    "скину",
    "отправлю",
    "вернусь",
    "созвонимся",
    "обсудим",
    "напомни",
    "проверю",
    "сделаю",
    "посмотрю",
    "надо",
    "нужно",
)
CONFLICT_MARKERS = (
    "срочно",
    "почему",
    "проблем",
    "сломал",
    "сломалс",
    "сломался",
    "ошибка",
    "не работает",
    "непонятно",
    "опять",
    "жесть",
    "бесит",
)
SENSITIVE_TOPIC_MARKERS = {
    "здоровье и медицина": ("врач", "анализ", "болез", "лечен", "здоров", "страхов"),
    "деньги и бюджет": ("бюджет", "деньг", "оплат", "счёт", "счет", "долг", "зарплат"),
    "семья и личное": ("семь", "ребен", "ребён", "мама", "папа", "муж", "жена"),
    "срочные рабочие вопросы": ("дедлайн", "срочно", "релиз", "проблем", "сломал", "импорт"),
}


@dataclass(frozen=True, slots=True)
class PersonReference:
    person_key: str
    display_name: str


def build_person_reference(
    *,
    sender_id: int | None,
    sender_name: str | None,
    fallback_title: str | None = None,
    fallback_handle: str | None = None,
) -> PersonReference | None:
    display_name = normalize_display_name(sender_name)
    if display_name is None and fallback_handle:
        display_name = normalize_display_name(f"@{fallback_handle}")
    if display_name is None:
        display_name = normalize_display_name(fallback_title)

    if sender_id is not None:
        return PersonReference(
            person_key=f"tg:{int(sender_id)}",
            display_name=display_name or f"Пользователь {sender_id}",
        )

    if display_name is None:
        return None

    if display_name.startswith("@"):
        return PersonReference(
            person_key=f"username:{display_name.lstrip('@').casefold()}",
            display_name=display_name,
        )

    return PersonReference(
        person_key=f"name:{display_name.casefold()}",
        display_name=display_name,
    )


def normalize_display_name(value: str | None) -> str | None:
    if value is None:
        return None

    normalized = " ".join(value.split()).strip()
    if not normalized:
        return None

    return normalized


def truncate_text(value: str | None, *, limit: int = 160) -> str:
    normalized = " ".join((value or "").split()).strip()
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 3].rstrip() + "..."


def format_utc(value: datetime | str | None) -> str:
    if value is None:
        return "ещё нет"

    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return value
        value = parsed

    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    else:
        value = value.astimezone(timezone.utc)

    return value.strftime("%Y-%m-%d %H:%M UTC")


def tokenize_text(value: str | None) -> list[str]:
    if value is None:
        return []

    tokens: list[str] = []
    for match in WORD_PATTERN.finditer(value.casefold()):
        token = match.group(0)
        if token.isdigit():
            continue
        if token in STOP_WORDS:
            continue
        tokens.append(token)
    return tokens


def extract_dominant_topics(
    texts: Sequence[str],
    *,
    limit: int = 5,
) -> list[dict[str, Any]]:
    unigram_counts: Counter[str] = Counter()
    bigram_counts: Counter[str] = Counter()

    for text in texts:
        tokens = tokenize_text(text)
        if not tokens:
            continue

        unigram_counts.update(set(tokens))
        bigrams = {
            f"{left} {right}"
            for left, right in zip(tokens, tokens[1:], strict=False)
            if left != right
        }
        bigram_counts.update(bigrams)

    topics: list[dict[str, Any]] = []
    for topic, mentions in bigram_counts.most_common():
        if mentions < 2:
            continue
        topics.append({"topic": topic, "mentions": int(mentions)})
        if len(topics) >= limit:
            return topics

    minimum_mentions = 2 if unigram_counts else 1
    for topic, mentions in unigram_counts.most_common():
        if mentions < minimum_mentions:
            continue
        if any(topic in existing["topic"] for existing in topics):
            continue
        topics.append({"topic": topic, "mentions": int(mentions)})
        if len(topics) >= limit:
            break

    if topics:
        return topics

    fallback_counts = Counter(token for text in texts for token in tokenize_text(text))
    return [
        {"topic": topic, "mentions": int(mentions)}
        for topic, mentions in fallback_counts.most_common(limit)
    ]


def summarize_topics(topics: Iterable[dict[str, Any]] | None) -> str:
    if not topics:
        return "без явных повторяющихся тем"
    labels = [str(item.get("topic")) for item in topics if item.get("topic")]
    if not labels:
        return "без явных повторяющихся тем"
    return ", ".join(labels[:4])


def looks_like_open_loop(text: str | None) -> bool:
    normalized = (text or "").casefold()
    if not normalized.strip():
        return False
    if "?" in normalized and len(normalized.strip()) >= 10:
        return True
    return any(marker in normalized for marker in OPEN_LOOP_MARKERS)


def looks_like_conflict(text: str | None) -> bool:
    normalized = (text or "").casefold()
    if not normalized.strip():
        return False
    if normalized.count("!") >= 2 or normalized.isupper():
        return True
    return any(marker in normalized for marker in CONFLICT_MARKERS)


def detect_sensitive_topics(
    texts: Sequence[str],
    *,
    limit: int = 4,
) -> list[str]:
    category_counts: Counter[str] = Counter()
    category_markers: dict[str, set[str]] = {category: set() for category in SENSITIVE_TOPIC_MARKERS}

    for text in texts:
        lowered = text.casefold()
        for category, markers in SENSITIVE_TOPIC_MARKERS.items():
            matched_markers = {marker for marker in markers if marker in lowered}
            if matched_markers:
                category_counts[category] += 1
                category_markers[category].update(matched_markers)

    labels: list[str] = []
    for category, _ in category_counts.most_common(limit):
        matched = ", ".join(sorted(category_markers[category])[:3])
        if matched:
            labels.append(f"{category}: {matched}")
        else:
            labels.append(category)
    return labels
