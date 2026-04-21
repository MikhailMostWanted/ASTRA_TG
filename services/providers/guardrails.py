from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from services.persona_core import PersonaState
from services.persona_guardrails import PersonaGuardrails
from services.providers.models import DigestImprovementCandidate, ReplyRefinementCandidate


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


@dataclass(frozen=True, slots=True)
class ReplyRefinementDecision:
    messages: tuple[str, ...]
    flags: tuple[str, ...]
    used_fallback: bool


@dataclass(frozen=True, slots=True)
class DigestImprovementDecision:
    summary_short: str
    overview_lines: tuple[str, ...]
    key_source_lines: tuple[str, ...]
    flags: tuple[str, ...]
    used_fallback: bool


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
            return ReplyRefinementDecision(
                messages=baseline,
                flags=("пустой_ответ",),
                used_fallback=True,
            )

        flags: list[str] = []
        if _has_forbidden_factual_novelty(normalized, allowed_context, baseline):
            flags.append("новые_факты")
        if _too_far_from_baseline(normalized, baseline):
            flags.append("сильное_отклонение_от_baseline")

        persona_decision = self.persona_guardrails.apply(
            proposed_messages=normalized,
            fallback_messages=baseline,
            profile=profile,
            persona_core=persona_state.core,
            guardrails=persona_state.guardrails,
        )
        combined_flags = tuple(dict.fromkeys([*flags, *persona_decision.flags]))
        hard_flags = {"новые_факты", "сильное_отклонение_от_baseline"}
        if persona_decision.used_fallback or any(flag in hard_flags for flag in combined_flags):
            return ReplyRefinementDecision(
                messages=baseline,
                flags=combined_flags,
                used_fallback=True,
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
            return DigestImprovementDecision(
                summary_short=fallback.summary_short,
                overview_lines=fallback.overview_lines,
                key_source_lines=fallback.key_source_lines,
                flags=("пустой_дайджест",),
                used_fallback=True,
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
            )
        return DigestImprovementDecision(
            summary_short=summary_short,
            overview_lines=overview_lines,
            key_source_lines=key_source_lines,
            flags=(),
            used_fallback=False,
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


def _too_far_from_baseline(
    candidate_messages: tuple[str, ...],
    baseline_messages: tuple[str, ...],
) -> bool:
    baseline_words = _meaningful_words("\n".join(baseline_messages))
    candidate_words = _meaningful_words("\n".join(candidate_messages))
    if not baseline_words or not candidate_words:
        return False
    overlap = len(baseline_words & candidate_words) / max(1, len(candidate_words))
    return overlap < 0.3


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


def _has_new_numeric_facts(candidate_blob: str, allowed_blob: str) -> bool:
    candidate_numbers = {token for token in candidate_blob.split() if any(symbol.isdigit() for symbol in token)}
    allowed_numbers = {token for token in allowed_blob.split() if any(symbol.isdigit() for symbol in token)}
    return not candidate_numbers.issubset(allowed_numbers)


def _meaningful_words(text: str) -> set[str]:
    words = {
        chunk.casefold().strip(".,!?;:-()[]{}\"'")
        for chunk in text.split()
    }
    return {word for word in words if len(word) >= 4}
