from __future__ import annotations

from dataclasses import dataclass

from services.persona_rules import (
    OwnerPersonaCore,
    PersonaGuardrailConfig,
    STRONG_PROFANITY_TOKENS,
)


@dataclass(frozen=True, slots=True)
class PersonaGuardrailDecision:
    messages: tuple[str, ...]
    flags: tuple[str, ...]
    used_fallback: bool


@dataclass(slots=True)
class PersonaGuardrails:
    def apply(
        self,
        *,
        proposed_messages: tuple[str, ...],
        fallback_messages: tuple[str, ...],
        profile,
        persona_core: OwnerPersonaCore | None,
        guardrails: PersonaGuardrailConfig | None,
    ) -> PersonaGuardrailDecision:
        normalized = tuple(_normalize(message) for message in proposed_messages if _normalize(message))
        safe_fallback = tuple(_normalize(message) for message in fallback_messages if _normalize(message))
        if not normalized or persona_core is None or guardrails is None:
            return PersonaGuardrailDecision(
                messages=safe_fallback or normalized,
                flags=(),
                used_fallback=False,
            )

        flags: list[str] = []
        repaired = list(normalized)

        if sum(message.count("!") for message in repaired) > guardrails.max_exclamation_count:
            repaired = [message.replace("!", "") for message in repaired]
            flags.append("пунктуационный_шум")

        repaired, repeated_openers_changed = _reduce_repeated_openers(
            repaired,
            opener_bank=persona_core.opener_bank,
            max_repeated_openers=guardrails.max_repeated_openers,
        )
        if repeated_openers_changed:
            flags.append("повтор_открывашек")

        if _contains_patterns(repaired, guardrails.literary_patterns):
            flags.append("слишком_литературно")
        if _contains_patterns(repaired, guardrails.bot_patterns):
            flags.append("слишком_ботски")
        if _contains_patterns(repaired, (*guardrails.forbidden_patterns, *persona_core.anti_pattern_rules)):
            flags.append("анти_паттерн")

        allowed_strong_profane_tokens = (
            min(1, guardrails.max_strong_profane_tokens)
            if getattr(profile, "profanity_level", "none") == "functional"
            else 0
        )
        if _count_strong_profanity(repaired) > allowed_strong_profane_tokens:
            flags.append("слишком_грубо")

        average_length = (
            sum(len(message) for message in repaired) / len(repaired)
            if repaired
            else 0
        )
        if (
            len(repaired) > guardrails.max_messages
            or average_length > guardrails.max_average_message_length
            or max(len(message) for message in repaired) > guardrails.max_message_length
        ):
            flags.append("слишком_длинно")

        hard_flags = {
            "слишком_литературно",
            "слишком_ботски",
            "слишком_грубо",
            "слишком_длинно",
            "анти_паттерн",
        }
        unique_flags = tuple(dict.fromkeys(flags))
        if any(flag in hard_flags for flag in unique_flags):
            return PersonaGuardrailDecision(
                messages=safe_fallback or tuple(repaired),
                flags=unique_flags,
                used_fallback=True,
            )

        return PersonaGuardrailDecision(
            messages=tuple(repaired),
            flags=unique_flags,
            used_fallback=False,
        )


def _normalize(value: str) -> str:
    return " ".join(str(value).split()).strip()


def _contains_patterns(messages: list[str] | tuple[str, ...], patterns: tuple[str, ...]) -> bool:
    text = "\n".join(message.casefold() for message in messages)
    return any(pattern.casefold() in text for pattern in patterns if pattern)


def _count_strong_profanity(messages: list[str] | tuple[str, ...]) -> int:
    text = "\n".join(message.casefold() for message in messages)
    return sum(text.count(token) for token in STRONG_PROFANITY_TOKENS)


def _reduce_repeated_openers(
    messages: list[str],
    *,
    opener_bank: tuple[str, ...],
    max_repeated_openers: int,
) -> tuple[list[str], bool]:
    counts: dict[str, int] = {}
    updated = list(messages)
    changed = False
    for index, message in enumerate(messages):
        lowered = message.casefold()
        opener = next(
            (
                item
                for item in opener_bank
                if lowered == item or lowered.startswith(f"{item} ")
            ),
            None,
        )
        if opener is None:
            continue
        counts[opener] = counts.get(opener, 0) + 1
        if counts[opener] <= max_repeated_openers:
            continue
        stripped = message[len(opener) :].strip()
        if stripped:
            updated[index] = stripped
            changed = True
    return updated, changed
