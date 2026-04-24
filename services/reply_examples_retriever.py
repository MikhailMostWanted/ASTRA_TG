from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone

from services.memory_common import build_person_reference, extract_dominant_topics, tokenize_text
from services.reply_classifier import ReplyClassifier
from services.reply_examples_models import ReplyExampleMatch, ReplyExamplesRetrievalResult
from storage.repositories import ReplyExampleRepository


PROMISE_UPDATE_MARKERS = (
    "вернусь",
    "скину",
    "пришлю",
    "напишу",
    "отпишу",
    "проверю",
    "смотрю",
    "посмотрю",
    "гляну",
    "апдейт",
)
CLARIFY_MARKERS = (
    "уточни",
    "что именно",
    "какой вариант",
    "какой из",
)
SOFTEN_MARKERS = (
    "спокойно",
    "без лишних эмоций",
    "без резкости",
    "давай",
)
STYLE_MARKERS = (
    "ну",
    "да",
    "не",
    "не не",
    "а",
    "че",
    "щас",
    "ща",
    "типо",
    "бля",
    "блять",
    "пиздец",
    "хуйня",
    "заебись",
    "окей",
    "давай",
)
PROFANITY_MARKERS = ("бля", "блять", "пиздец", "хуйня", "заебись", "нахуй", "хуй")


@dataclass(slots=True)
class ReplyExamplesRetriever:
    reply_example_repository: ReplyExampleRepository
    classifier: ReplyClassifier = field(default_factory=ReplyClassifier)
    min_quality_score: float = 0.45
    min_match_score: float = 0.34

    async def retrieve_for_context(
        self,
        context,
        *,
        limit: int = 3,
    ) -> ReplyExamplesRetrievalResult:
        retrieval_context_text = _build_retrieval_context_text(context)
        target_text = _pick_context_text(context)
        query = _build_fts_query(retrieval_context_text)
        if not query:
            return _empty_result()

        target_tokens = set(tokenize_text(retrieval_context_text))
        if not target_tokens:
            return _empty_result()

        source_person_key = _resolve_person_key(context)
        current_type = self.classifier.classify(context).situation
        target_context_tokens = set(
            tokenize_text(
                " ".join(
                    [
                        *(message.get("text", "") for message in _build_working_context_messages(context)),
                        *context.unanswered_questions,
                        *context.pending_promises,
                        *context.emotional_signals,
                        *context.pending_loops,
                        *context.topic_hints,
                    ]
                )
            )
        )
        candidates = await self.reply_example_repository.search_similar(
            query,
            limit=max(limit * 8, 12),
            min_quality=self.min_quality_score,
        )

        matches: list[ReplyExampleMatch] = []
        for index, candidate in enumerate(candidates):
            score, reasons = _score_candidate(
                candidate=candidate,
                index=index,
                target_tokens=target_tokens,
                target_context_tokens=target_context_tokens,
                current_chat_id=context.chat.id,
                current_person_key=source_person_key,
                current_type=current_type,
                current_sent_at=context.target_message.sent_at,
            )
            if score < self.min_match_score:
                continue
            matches.append(
                ReplyExampleMatch(
                    id=candidate.id,
                    chat_id=candidate.chat_id,
                    chat_title=candidate.chat_title,
                    inbound_text=candidate.inbound_text,
                    outbound_text=candidate.outbound_text,
                    example_type=candidate.example_type,
                    source_person_key=candidate.source_person_key,
                    quality_score=candidate.quality_score,
                    score=score,
                    created_at=candidate.created_at,
                    reasons=tuple(reasons),
                )
            )

        matches.sort(
            key=lambda item: (
                -item.score,
                -item.quality_score,
                item.chat_title.casefold(),
                item.id,
            )
        )
        top_matches = tuple(matches[:limit])
        if not top_matches:
            return _empty_result()

        strategy_bias = _derive_strategy_bias(top_matches)
        length_hint = _derive_length_hint(top_matches)
        rhythm_hint = _derive_rhythm_hint(top_matches)
        opener_hint = _derive_opener_hint(top_matches)
        message_count_hint = _derive_message_count_hint(top_matches)
        softness_hint = _derive_softness_hint(top_matches)
        profanity_hint = _derive_profanity_hint(top_matches)
        style_markers = _derive_style_markers(top_matches)
        dominant_topic_hint = _derive_topic_hint(target_text, top_matches)
        confidence_delta = min(
            0.12,
            round(0.03 + (sum(match.score for match in top_matches) / len(top_matches)) * 0.08, 2),
        )
        notes = _build_notes(
            matches=top_matches,
            strategy_bias=strategy_bias,
            length_hint=length_hint,
            rhythm_hint=rhythm_hint,
        )

        return ReplyExamplesRetrievalResult(
            matches=top_matches,
            support_used=True,
            match_count=len(top_matches),
            confidence_delta=confidence_delta,
            strategy_bias=strategy_bias,
            length_hint=length_hint,
            rhythm_hint=rhythm_hint,
            opener_hint=opener_hint,
            dominant_topic_hint=dominant_topic_hint,
            notes=notes,
            message_count_hint=message_count_hint,
            softness_hint=softness_hint,
            profanity_hint=profanity_hint,
            style_markers=style_markers,
        )


def _score_candidate(
    *,
    candidate,
    index: int,
    target_tokens: set[str],
    target_context_tokens: set[str],
    current_chat_id: int,
    current_person_key: str | None,
    current_type: str,
    current_sent_at,
) -> tuple[float, list[str]]:
    candidate_tokens = set(tokenize_text(candidate.inbound_normalized or candidate.inbound_text))
    overlap = len(target_tokens & candidate_tokens) / max(len(target_tokens), 1)
    score = overlap * 0.56
    reasons: list[str] = []

    context_tokens = set(tokenize_text(_context_before_blob(candidate.context_before_json)))
    if context_tokens:
        context_overlap = len(target_context_tokens & context_tokens) / max(1, len(target_context_tokens))
        if context_overlap:
            score += context_overlap * 0.16
            reasons.append("похожий живой контекст")

    fts_bonus = max(0.04, 0.18 - index * 0.012)
    score += fts_bonus
    reasons.append("lexical match")

    if candidate.chat_id == current_chat_id:
        score += 0.18
        reasons.append("тот же чат")
    if current_person_key and candidate.source_person_key == current_person_key:
        score += 0.12
        reasons.append("тот же человек")
    if candidate.example_type == current_type:
        score += 0.07
        reasons.append(f"тот же тип: {current_type}")

    freshness_bonus = 0.0
    candidate_created_at = _as_utc(candidate.created_at)
    current_sent_at = _as_utc(current_sent_at)
    if candidate_created_at is not None and current_sent_at is not None:
        age_seconds = abs((current_sent_at - candidate_created_at).total_seconds())
        if age_seconds <= 14 * 24 * 60 * 60:
            freshness_bonus = 0.06
        elif age_seconds <= 60 * 24 * 60 * 60:
            freshness_bonus = 0.03
    score += freshness_bonus
    if freshness_bonus:
        reasons.append("свежий пример")

    quality_bonus = candidate.quality_score * 0.12
    score += quality_bonus
    reasons.append(f"quality {candidate.quality_score:.2f}")

    outbound_rhythm_bonus = _score_outbound_rhythm(candidate.outbound_text)
    if outbound_rhythm_bonus:
        score += outbound_rhythm_bonus
        reasons.append("ритм ответа похож")

    if overlap == 0 and candidate.chat_id != current_chat_id and candidate.source_person_key != current_person_key:
        score -= 0.25

    return round(max(score, 0.0), 2), reasons


def _derive_strategy_bias(matches: tuple[ReplyExampleMatch, ...]) -> str | None:
    counter: Counter[str] = Counter()
    for match in matches:
        lowered = match.outbound_text.casefold()
        matched = False
        if any(marker in lowered for marker in PROMISE_UPDATE_MARKERS):
            counter["promise_update"] += 1
            matched = True
        if any(marker in lowered for marker in CLARIFY_MARKERS) or "?" in match.outbound_text:
            counter["clarify"] += 1
            matched = True
        if any(marker in lowered for marker in SOFTEN_MARKERS) or match.example_type in {
            "soft_reply",
            "tension",
        }:
            counter["soften"] += 1
            matched = True
        if not matched:
            counter["practical"] += 1
    if not counter:
        return None
    return counter.most_common(1)[0][0]


def _derive_length_hint(matches: tuple[ReplyExampleMatch, ...]) -> str | None:
    average = sum(len(tokenize_text(match.outbound_text)) for match in matches) / len(matches)
    return "short" if average <= 10 else "medium"


def _derive_rhythm_hint(matches: tuple[ReplyExampleMatch, ...]) -> str | None:
    average = sum(_reply_message_count(match.outbound_text) for match in matches) / len(matches)
    return "single" if average <= 1.3 else "series"


def _derive_opener_hint(matches: tuple[ReplyExampleMatch, ...]) -> str | None:
    opener_counter: Counter[str] = Counter()
    for match in matches:
        opener = _first_opener(match.outbound_text)
        if opener is not None:
            opener_counter[opener] += 1
    if not opener_counter:
        return None
    return opener_counter.most_common(1)[0][0]


def _derive_message_count_hint(matches: tuple[ReplyExampleMatch, ...]) -> int | None:
    if not matches:
        return None
    average = sum(_reply_message_count(match.outbound_text) for match in matches) / len(matches)
    return max(1, min(4, round(average)))


def _derive_softness_hint(matches: tuple[ReplyExampleMatch, ...]) -> str | None:
    soft = 0
    direct = 0
    for match in matches:
        lowered = match.outbound_text.casefold()
        if match.example_type in {"soft_reply", "tension"} or any(marker in lowered for marker in SOFTEN_MARKERS):
            soft += 1
        if any(marker in lowered for marker in ("бля", "хуйня", "не не", "давай")):
            direct += 1
    if soft > direct:
        return "soft"
    if direct > soft:
        return "direct"
    return None


def _derive_profanity_hint(matches: tuple[ReplyExampleMatch, ...]) -> str | None:
    count = sum(_count_profanity(match.outbound_text) for match in matches)
    if count <= 0:
        return "none"
    average = count / len(matches)
    return "strong" if average >= 1 else "light"


def _derive_style_markers(matches: tuple[ReplyExampleMatch, ...]) -> tuple[str, ...]:
    counter: Counter[str] = Counter()
    for match in matches:
        lowered = f" {match.outbound_text.casefold()} "
        for marker in STYLE_MARKERS:
            if f" {marker} " in lowered or lowered.strip().startswith(f"{marker} "):
                counter[marker] += 1
    return tuple(marker for marker, _count in counter.most_common(6))


def _derive_topic_hint(
    target_text: str,
    matches: tuple[ReplyExampleMatch, ...],
) -> str | None:
    topics = extract_dominant_topics(
        [target_text, *(match.inbound_text for match in matches)],
        limit=1,
    )
    if not topics:
        return None
    topic = topics[0].get("topic")
    return str(topic).strip() if topic else None


def _build_notes(
    *,
    matches: tuple[ReplyExampleMatch, ...],
    strategy_bias: str | None,
    length_hint: str | None,
    rhythm_hint: str | None,
) -> tuple[str, ...]:
    notes = [f"Нашёл похожие реальные ответы: {len(matches)}."]
    if strategy_bias == "promise_update":
        notes.append("Паттерн: коротко подтвердить и вернуться с апдейтом.")
    elif strategy_bias == "clarify":
        notes.append("Паттерн: сначала уточнить, потом уже закрывать тему.")
    elif strategy_bias == "soften":
        notes.append("Паттерн: держать тон мягким и не разгонять напряжение.")
    else:
        notes.append("Паттерн: короткий практичный ответ без воды.")
    if length_hint == "short":
        notes.append("По длине лучше держаться короткого ответа.")
    if rhythm_hint == "series":
        notes.append("Ритм лучше телеграмной серией, а не длинным полотном.")
    return tuple(notes)


def _resolve_person_key(context) -> str | None:
    fallback_title = context.chat.title if context.chat.type == "private" else None
    fallback_handle = context.chat.handle if context.chat.type == "private" else None
    reference = build_person_reference(
        sender_id=context.target_message.sender_id,
        sender_name=context.target_message.sender_name,
        fallback_title=fallback_title,
        fallback_handle=fallback_handle,
    )
    if reference is None:
        return None
    return reference.person_key


def _build_fts_query(text: str) -> str:
    tokens = list(dict.fromkeys(tokenize_text(text)))[:12]
    if not tokens:
        return ""
    return " OR ".join(f"{token}*" for token in tokens)


def _pick_context_text(context) -> str:
    return " ".join(
        (context.target_message.normalized_text or context.target_message.raw_text or "").split()
    ).strip()


def _build_retrieval_context_text(context) -> str:
    parts = [
        _pick_context_text(context),
        *(message.get("text", "") for message in _build_working_context_messages(context)),
        *context.unanswered_questions[:2],
        *context.pending_promises[:2],
        *context.emotional_signals[:1],
        *context.pending_loops[:2],
        *context.topic_hints[:2],
    ]
    return " ".join(part for part in parts if part).strip()


def _build_working_context_messages(context) -> tuple[dict[str, str], ...]:
    rendered: list[dict[str, str]] = []
    for message in context.working_messages[-6:]:
        text = " ".join((message.normalized_text or message.raw_text or "").split()).strip()
        if not text:
            continue
        rendered.append(
            {
                "direction": message.direction,
                "text": text,
            }
        )
    return tuple(rendered)


def _context_before_blob(value) -> str:
    if not isinstance(value, list):
        return ""
    parts: list[str] = []
    for item in value:
        if isinstance(item, dict) and isinstance(item.get("text"), str):
            parts.append(item["text"])
    return " ".join(parts)


def _score_outbound_rhythm(text: str) -> float:
    normalized = " ".join(text.split()).strip()
    if not normalized:
        return 0.0
    punctuation = normalized.count("!") + normalized.count("?")
    line_like = max(1, len([line for line in text.splitlines() if line.strip()]) + normalized.count(".") + punctuation)
    if len(tokenize_text(normalized)) <= 12:
        return 0.05
    if line_like >= 2:
        return 0.04
    return 0.0


def _empty_result() -> ReplyExamplesRetrievalResult:
    return ReplyExamplesRetrievalResult(
        matches=(),
        support_used=False,
        match_count=0,
        confidence_delta=0.0,
        strategy_bias=None,
        length_hint=None,
        rhythm_hint=None,
        opener_hint=None,
        dominant_topic_hint=None,
        notes=("Похожих реальных ответов не нашёл.",),
    )


def _reply_message_count(text: str) -> int:
    if not text.strip():
        return 0
    newline_count = len([line for line in text.splitlines() if line.strip()])
    if newline_count > 1:
        return min(4, newline_count)
    sentence_count = text.count(".") + text.count("!") + text.count("?")
    if sentence_count > 1:
        return min(4, sentence_count)
    if len(tokenize_text(text)) > 12:
        return 2
    return 1


def _first_opener(text: str) -> str | None:
    normalized = " ".join(text.casefold().split()).strip(" ,.!?;:-")
    if not normalized:
        return None
    if normalized.startswith("не не "):
        return "не не"
    tokens = tokenize_text(normalized)
    if not tokens:
        return None
    opener = tokens[0]
    allowed = {
        "ну",
        "да",
        "ага",
        "ок",
        "окей",
        "понял",
        "поняла",
        "вижу",
        "гляну",
        "смотрю",
        "не",
        "а",
        "слушай",
        "смотри",
        "короче",
        "типо",
        "ща",
        "щас",
        "давай",
    }
    return opener if opener in allowed else None


def _count_profanity(text: str) -> int:
    lowered = text.casefold()
    return sum(lowered.count(marker) for marker in PROFANITY_MARKERS)


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
