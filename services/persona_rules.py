from __future__ import annotations

from dataclasses import dataclass
from typing import Any


DEFAULT_PERSONA_VERSION = "owner-core-v1"
DEFAULT_PERSONA_ENABLED = {"enabled": True}

DEFAULT_OWNER_PERSONA_CORE: dict[str, Any] = {
    "core_speech_rules": [
        "серия коротких сообщений важнее длинного абзаца",
        "обычный ритм это 2-4 коротких сообщения подряд",
        "ритм быстрый, рваный и телеграмный",
        "для owner_style обычный формат это каскад 2-4 коротких реплик",
        "одна реплика часто 1-8 слов",
        "можно начинать с ну, да, не, не не, а, слушай, смотри, короче, типо, щас",
        "короткая реплика лучше вылизанного литературного блока",
        "mostly lowercase",
        "минимум пунктуации и почти без восклицаний",
        "без канцелярита и слишком правильной гладкости",
    ],
    "explanation_pattern": [
        "снять неправильное понимание",
        "сузить смысл",
        "упростить",
        "приземлить в человеческую формулировку",
        "коротко добить смысл",
    ],
    "warmth_rules": [
        "тепло короткое и встроенное",
        "без сахара и без приторности",
        "мягкость не должна ломать естественность",
    ],
    "directness_rules": [
        "если можно сказать прямо, говорим прямо",
        "жёсткость допускается только без хамства",
        "в жёстком дружеском режиме прямота выше",
    ],
    "profanity_rules": [
        "мат только как функциональный усилитель",
        "не сыпать мат в каждое сообщение",
        "в мягких режимах грубость опускаем",
        "в дружеских жёстких режимах допускается чуть выше прямота",
    ],
    "anti_pattern_rules": [
        "нельзя писать одним слишком длинным блоком то, что должно быть серией",
        "нельзя перегружать ответ словами брат, короче и !!!",
        "нельзя уходить в гопнический цирк",
        "нельзя звучать слишком умно и академично",
        "нельзя скатываться в слащавую мягкость",
        "нельзя писать я бы ответил, можно написать, вариант ответа",
        "нельзя использовать markdown внутри готового ответа",
    ],
    "opener_bank": ["ну", "а", "да", "не", "не не", "слушай", "смотри", "короче", "типо", "щас", "это", "я"],
    "closer_bank": [
        "если что добью дальше",
        "дальше уже по факту скажу",
        "если что я рядом",
    ],
    "rewrite_constraints": [
        "mostly_lower",
        "low_punctuation",
        "no_corporate_tone",
        "no_polished_literary_blocks",
        "prefer_human_chunking",
        "avoid_caricature",
    ],
}

DEFAULT_PERSONA_GUARDRAILS: dict[str, Any] = {
    "checks": [
        "message_count",
        "average_length",
        "single_message_length",
        "punctuation_noise",
        "literary_tone",
        "bot_phrases",
        "assistant_tone",
        "profanity_overuse",
        "repeated_openers",
        "anti_patterns",
    ],
    "max_messages": 4,
    "max_message_length": 86,
    "max_average_message_length": 58,
    "max_exclamation_count": 1,
    "max_periods_per_message": 1,
    "max_repeated_openers": 1,
    "max_strong_profane_tokens": 1,
    "literary_patterns": [
        "в данном случае",
        "благодарю",
        "максимально корректно",
        "обстоятельно обсудить",
        "однако",
        "без лишних эмоций",
    ],
    "bot_patterns": [
        "буду рад помочь",
        "обращайся если будут вопросы",
        "если у вас есть",
        "я всегда готов помочь",
        "я бы ответил",
        "можно написать",
        "предлагаю ответить",
        "с учётом контекста",
        "вариант ответа",
    ],
    "forbidden_patterns": [
        "!!!",
        "брат",
        "короче короче",
        "гопнический",
    ],
}

STRONG_PROFANITY_TOKENS = (
    "бляд",
    "пизд",
    "ебан",
    "нахуй",
    "хуй",
)


@dataclass(frozen=True, slots=True)
class OwnerPersonaCore:
    core_speech_rules: tuple[str, ...]
    explanation_pattern: tuple[str, ...]
    warmth_rules: tuple[str, ...]
    directness_rules: tuple[str, ...]
    profanity_rules: tuple[str, ...]
    anti_pattern_rules: tuple[str, ...]
    opener_bank: tuple[str, ...]
    closer_bank: tuple[str, ...]
    rewrite_constraints: tuple[str, ...]

    @classmethod
    def from_payload(cls, payload: Any) -> "OwnerPersonaCore":
        if not isinstance(payload, dict):
            raise ValueError("persona.core должен быть JSON-объектом.")

        return cls(
            core_speech_rules=_tuple_from_payload(payload.get("core_speech_rules")),
            explanation_pattern=_tuple_from_payload(payload.get("explanation_pattern")),
            warmth_rules=_tuple_from_payload(payload.get("warmth_rules")),
            directness_rules=_tuple_from_payload(payload.get("directness_rules")),
            profanity_rules=_tuple_from_payload(payload.get("profanity_rules")),
            anti_pattern_rules=_tuple_from_payload(payload.get("anti_pattern_rules")),
            opener_bank=_tuple_from_payload(payload.get("opener_bank")),
            closer_bank=_tuple_from_payload(payload.get("closer_bank")),
            rewrite_constraints=_tuple_from_payload(payload.get("rewrite_constraints")),
        )

    @property
    def active_rule_count(self) -> int:
        return sum(
            len(items)
            for items in (
                self.core_speech_rules,
                self.explanation_pattern,
                self.warmth_rules,
                self.directness_rules,
                self.profanity_rules,
                self.anti_pattern_rules,
                self.opener_bank,
                self.closer_bank,
                self.rewrite_constraints,
            )
        )


@dataclass(frozen=True, slots=True)
class PersonaGuardrailConfig:
    checks: tuple[str, ...]
    max_messages: int
    max_message_length: int
    max_average_message_length: int
    max_exclamation_count: int
    max_periods_per_message: int
    max_repeated_openers: int
    max_strong_profane_tokens: int
    literary_patterns: tuple[str, ...]
    bot_patterns: tuple[str, ...]
    forbidden_patterns: tuple[str, ...]

    @classmethod
    def from_payload(cls, payload: Any) -> "PersonaGuardrailConfig":
        if not isinstance(payload, dict):
            raise ValueError("persona.guardrails должен быть JSON-объектом.")

        return cls(
            checks=_tuple_from_payload(payload.get("checks")),
            max_messages=_int_from_payload(payload.get("max_messages"), default=4),
            max_message_length=_int_from_payload(payload.get("max_message_length"), default=86),
            max_average_message_length=_int_from_payload(
                payload.get("max_average_message_length"),
                default=58,
            ),
            max_exclamation_count=_int_from_payload(
                payload.get("max_exclamation_count"),
                default=1,
            ),
            max_periods_per_message=_int_from_payload(
                payload.get("max_periods_per_message"),
                default=1,
            ),
            max_repeated_openers=_int_from_payload(
                payload.get("max_repeated_openers"),
                default=1,
            ),
            max_strong_profane_tokens=_int_from_payload(
                payload.get("max_strong_profane_tokens"),
                default=1,
            ),
            literary_patterns=_tuple_from_payload(payload.get("literary_patterns")),
            bot_patterns=_tuple_from_payload(payload.get("bot_patterns")),
            forbidden_patterns=_tuple_from_payload(payload.get("forbidden_patterns")),
        )

    @property
    def active_checks_count(self) -> int:
        return len(self.checks)


def _tuple_from_payload(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(str(item).strip() for item in value if str(item).strip())


def _int_from_payload(value: Any, *, default: int) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return default
