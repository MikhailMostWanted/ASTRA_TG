from __future__ import annotations

from dataclasses import dataclass, field, replace
import re
from typing import Iterable

from services.persona_core import PersonaState
from services.persona_guardrails import PersonaGuardrails
from services.providers.models import (
    DigestImprovementCandidate,
    LLMDecisionReason,
    ReplyRefinementCandidate,
)


LITERARY_PATTERNS = (
    "в данном случае",
    "благодарю",
    "максимально корректно",
    "обстоятельно обсудить",
    "без лишних эмоций",
)
BOT_PATTERNS = (
    "буду рад помочь",
    "обращайся если будут вопросы",
    "я всегда готов помочь",
)
GENERIC_REPLY_WORDS = {
    "давай",
    "если",
    "потом",
    "сейчас",
    "просто",
    "тогда",
    "отдельно",
}


@dataclass(frozen=True, slots=True)
class ReplyRefinementDecision:
    messages: tuple[str, ...]
    flags: tuple[str, ...]
    used_fallback: bool
    rejection: LLMDecisionReason | None = None


@dataclass(frozen=True, slots=True)
class DigestImprovementDecision:
    summary_short: str
    overview_lines: tuple[str, ...]
    key_source_lines: tuple[str, ...]
    flags: tuple[str, ...]
    used_fallback: bool
    rejection: LLMDecisionReason | None = None


@dataclass(slots=True)
class ReplyRefinementGuardrails:
    persona_guardrails: PersonaGuardrails = field(default_factory=PersonaGuardrails)

    def apply(
        self,
        *,
        candidate: ReplyRefinementCandidate,
        baseline_messages: tuple[str, ...],
        allowed_context: tuple[str, ...],
        profile,
        persona_state: PersonaState,
    ) -> ReplyRefinementDecision:
        normalized = tuple(_normalize_lines(candidate.messages))
        baseline = tuple(_normalize_lines(baseline_messages))
        if not normalized:
            flags = ("пустой_ответ",)
            return ReplyRefinementDecision(
                messages=baseline,
                flags=flags,
                used_fallback=True,
                rejection=_build_guardrail_rejection(
                    code="empty_candidate",
                    summary="LLM-кандидат для reply пустой.",
                    detail=(
                        "После нормализации у кандидата не осталось текста, "
                        "поэтому сохранена детерминированная база."
                    ),
                    flags=flags,
                ),
            )

        flags: list[str] = []
        if _has_forbidden_factual_novelty(normalized, allowed_context, baseline):
            flags.append("новые_факты")
        if _has_obvious_topic_drift(normalized, allowed_context, baseline):
            flags.append("явный_оффтопик")

        guardrails = persona_state.guardrails
        if guardrails is not None:
            guardrails = _build_reply_guardrail_config(
                guardrails,
                baseline_messages=baseline,
                allowed_context=allowed_context,
            )
        persona_decision = self.persona_guardrails.apply(
            proposed_messages=normalized,
            fallback_messages=baseline,
            profile=profile,
            persona_core=persona_state.core,
            guardrails=guardrails,
        )
        combined_flags = tuple(dict.fromkeys([*flags, *persona_decision.flags]))
        hard_flags = {
            "новые_факты",
            "слишком_литературно",
            "слишком_ботски",
            "слишком_грубо",
            "анти_паттерн",
            "слишком_длинно",
            "явный_оффтопик",
        }
        if persona_decision.used_fallback or any(flag in hard_flags for flag in combined_flags):
            return ReplyRefinementDecision(
                messages=baseline,
                flags=combined_flags,
                used_fallback=True,
                rejection=_build_guardrail_rejection(
                    code="guardrails_rejected",
                    summary="LLM-кандидат для reply отклонён guardrails.",
                    detail=_format_guardrail_detail(
                        combined_flags,
                        fallback_label="детерминированная база",
                    ),
                    flags=combined_flags,
                ),
            )
        return ReplyRefinementDecision(
            messages=persona_decision.messages,
            flags=combined_flags,
            used_fallback=False,
        )


@dataclass(slots=True)
class DigestImprovementGuardrails:
    def apply(
        self,
        *,
        candidate: DigestImprovementCandidate,
        baseline_summary_short: str,
        baseline_overview_lines: tuple[str, ...],
        baseline_key_source_lines: tuple[str, ...],
        source_titles: tuple[str, ...],
    ) -> DigestImprovementDecision:
        summary_short = _normalize_text(candidate.summary_short)
        overview_lines = tuple(_normalize_bullets(candidate.overview_lines))
        key_source_lines = tuple(_normalize_bullets(candidate.key_source_lines))

        fallback = DigestImprovementDecision(
            summary_short=baseline_summary_short,
            overview_lines=baseline_overview_lines,
            key_source_lines=baseline_key_source_lines,
            flags=(),
            used_fallback=False,
        )
        if not summary_short or not overview_lines or not key_source_lines:
            flags = ("пустой_дайджест",)
            return DigestImprovementDecision(
                summary_short=fallback.summary_short,
                overview_lines=fallback.overview_lines,
                key_source_lines=fallback.key_source_lines,
                flags=flags,
                used_fallback=True,
                rejection=_build_guardrail_rejection(
                    code="empty_candidate",
                    summary="LLM-кандидат для digest пустой.",
                    detail=(
                        "LLM не вернул полный digest-кандидат, поэтому сохранён "
                        "детерминированный вариант."
                    ),
                    flags=flags,
                ),
            )

        flags: list[str] = []
        baseline_blob = "\n".join(
            (
                baseline_summary_short,
                *baseline_overview_lines,
                *baseline_key_source_lines,
                *source_titles,
            )
        )
        candidate_blob = "\n".join((summary_short, *overview_lines, *key_source_lines)).casefold()
        if _has_new_numeric_facts(candidate_blob, baseline_blob.casefold()):
            flags.append("новые_факты")
        if any(pattern in candidate_blob for pattern in (*LITERARY_PATTERNS, *BOT_PATTERNS)):
            flags.append("слишком_литературно")
        if len(summary_short) > max(220, int(len(baseline_summary_short) * 1.5)):
            flags.append("слишком_длинно")
        if len(overview_lines) > max(len(baseline_overview_lines) + 1, 5):
            flags.append("слишком_много_overview")
        if len(key_source_lines) > max(len(baseline_key_source_lines) + 1, len(source_titles) + 1):
            flags.append("слишком_много_секций")
        for source_title in source_titles:
            if source_title and source_title.casefold() not in candidate_blob:
                flags.append("потеряны_источники")
                break

        if flags:
            return DigestImprovementDecision(
                summary_short=fallback.summary_short,
                overview_lines=fallback.overview_lines,
                key_source_lines=fallback.key_source_lines,
                flags=tuple(dict.fromkeys(flags)),
                used_fallback=True,
                rejection=_build_guardrail_rejection(
                    code="guardrails_rejected",
                    summary="LLM-кандидат для digest отклонён guardrails.",
                    detail=_format_guardrail_detail(
                        tuple(dict.fromkeys(flags)),
                        fallback_label="детерминированный дайджест",
                    ),
                    flags=tuple(dict.fromkeys(flags)),
                ),
            )
        return DigestImprovementDecision(
            summary_short=summary_short,
            overview_lines=overview_lines,
            key_source_lines=key_source_lines,
            flags=(),
            used_fallback=False,
        )


def _build_guardrail_rejection(
    *,
    code: str,
    summary: str,
    detail: str,
    flags: tuple[str, ...],
) -> LLMDecisionReason:
    return LLMDecisionReason(
        source="guardrails",
        code=code,
        summary=summary,
        detail=detail,
        flags=flags,
    )


def _format_guardrail_detail(
    flags: tuple[str, ...],
    *,
    fallback_label: str,
) -> str:
    saved_label = _format_saved_label(fallback_label)
    if not flags:
        return f"Сработали guardrails, поэтому {saved_label}."
    saved_sentence = saved_label[:1].upper() + saved_label[1:]
    return (
        f"Сработали guardrails: {', '.join(flags)}. "
        f"{saved_sentence}."
    )


def _normalize_lines(lines: Iterable[str]) -> tuple[str, ...]:
    return tuple(line for line in (_normalize_text(item) for item in lines) if line)


def _normalize_bullets(lines: Iterable[str]) -> tuple[str, ...]:
    normalized: list[str] = []
    for line in lines:
        cleaned = _normalize_text(line)
        if not cleaned:
            continue
        if not cleaned.startswith("- "):
            cleaned = f"- {cleaned.lstrip('- ').strip()}"
        normalized.append(cleaned)
    return tuple(normalized)


def _normalize_text(value: object) -> str:
    return " ".join(str(value).split()).strip()


def _has_forbidden_factual_novelty(
    candidate_messages: tuple[str, ...],
    allowed_context: tuple[str, ...],
    baseline_messages: tuple[str, ...],
) -> bool:
    allowed_blob = "\n".join((*allowed_context, *baseline_messages)).casefold()
    candidate_blob = "\n".join(candidate_messages).casefold()
    if _has_new_numeric_facts(candidate_blob, allowed_blob):
        return True
    for token in ("http://", "https://", "@"):
        if token in candidate_blob and token not in allowed_blob:
            return True
    return False


def _has_obvious_topic_drift(
    candidate_messages: tuple[str, ...],
    allowed_context: tuple[str, ...],
    baseline_messages: tuple[str, ...],
) -> bool:
    allowed_tokens = _salient_tokens((*allowed_context, *baseline_messages))
    candidate_tokens = _salient_tokens(candidate_messages)
    if len(candidate_tokens) < 4 or not allowed_tokens:
        return False
    overlap = candidate_tokens & allowed_tokens
    novel_tokens = candidate_tokens - allowed_tokens
    overlap_ratio = len(overlap) / max(1, len(candidate_tokens))
    return len(novel_tokens) >= 3 and overlap_ratio < 0.25


def _has_new_numeric_facts(candidate_blob: str, allowed_blob: str) -> bool:
    candidate_numbers = {token for token in candidate_blob.split() if any(symbol.isdigit() for symbol in token)}
    allowed_numbers = {token for token in allowed_blob.split() if any(symbol.isdigit() for symbol in token)}
    return not candidate_numbers.issubset(allowed_numbers)


def _salient_tokens(lines: Iterable[str]) -> set[str]:
    ignored = {
        *GENERIC_REPLY_WORDS,
        "понял",
        "поняла",
        "гляну",
        "будет",
        "буду",
        "можно",
        "нужно",
        "пока",
        "там",
        "тут",
        "этот",
        "этим",
        "этой",
        "этого",
        "через",
        "после",
        "перед",
        "очень",
        "тоже",
        "уже",
        "еще",
        "ещё",
        "привет",
    }
    tokens: set[str] = set()
    for line in lines:
        for token in re.findall(r"[0-9a-zа-яё@._-]+", line.casefold()):
            if len(token) < 4 or token in ignored or any(symbol.isdigit() for symbol in token):
                continue
            tokens.add(token)
    return tokens


def _format_saved_label(fallback_label: str) -> str:
    if fallback_label.endswith("ая база"):
        return f"сохранена {fallback_label}"
    return f"сохранён {fallback_label}"


def _build_reply_guardrail_config(
    guardrails,
    *,
    baseline_messages: tuple[str, ...],
    allowed_context: tuple[str, ...],
):
    baseline_lengths = [len(message) for message in baseline_messages if message]
    context_lengths = [len(item) for item in allowed_context if item]
    max_context_length = max(context_lengths, default=0)
    average_baseline_length = (
        sum(baseline_lengths) / len(baseline_lengths)
        if baseline_lengths
        else 0
    )
    max_baseline_length = max(baseline_lengths, default=0)

    return replace(
        guardrails,
        max_messages=max(guardrails.max_messages, len(baseline_messages) + 1),
        max_message_length=max(
            guardrails.max_message_length + 28,
            max_baseline_length + 32,
            min(180, max_context_length + 20),
        ),
        max_average_message_length=max(
            guardrails.max_average_message_length + 14,
            int(average_baseline_length + 24),
            min(120, int(max_context_length * 0.7)),
        ),
    )
