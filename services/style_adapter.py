from __future__ import annotations

import re
from dataclasses import dataclass

from services.style_profiles import StyleProfileSnapshot


SHORT_REPLACEMENTS = {
    "с конкретным апдейтом": "с апдейтом",
    "чуть позже": "позже",
    "это сейчас": "сейчас",
    "пожалуйста": "",
    "конкретным": "",
}


@dataclass(frozen=True, slots=True)
class StyledReply:
    messages: tuple[str, ...]
    notes: tuple[str, ...]


@dataclass(slots=True)
class StyleAdapter:
    def adapt(
        self,
        *,
        draft_text: str,
        profile: StyleProfileSnapshot,
        strategy: str,
        few_shot_support=None,
    ) -> StyledReply:
        original = _normalize_spaces(draft_text)
        if not original:
            return StyledReply(messages=(), notes=("Базовый черновик пустой.",))

        compact = self._compact_text(
            original,
            profile,
            prefer_short=bool(getattr(few_shot_support, "length_hint", None) == "short"),
        )
        punctuation_changed = compact != original
        segments = self._split_into_messages(
            compact,
            profile,
            prefer_series=bool(getattr(few_shot_support, "rhythm_hint", None) == "series"),
        )
        target_count = getattr(few_shot_support, "message_count_hint", None)
        if isinstance(target_count, int) and target_count >= 2 and len(segments) == 1:
            segments = self._split_long_part(segments[0], profile, aggressive=True)
        opener_added = False
        if segments:
            updated_first = self._ensure_opener(
                segments[0],
                profile,
                opener_hint=getattr(few_shot_support, "opener_hint", None),
            )
            opener_added = updated_first != segments[0]
            segments[0] = updated_first

        segments = [self._finalize_segment(segment, profile) for segment in segments if segment]
        if strategy == "не отвечать" and len(segments) > 1:
            segments = [" ".join(segments[:2])]
        segments = self._trim_segment_count(segments, profile)
        if not segments:
            segments = [self._finalize_segment(compact, profile)]

        notes: list[str] = []
        if len(segments) > 1:
            notes.append(f"Разбил на {len(segments)} коротких сообщения.")
        if punctuation_changed:
            notes.append("Снизил пунктуацию и убрал лишнюю литературность.")
        if opener_added:
            notes.append("Добавил разговорный старт.")
        if not notes:
            notes.append("Оставил draft близко к базовому варианту.")

        return StyledReply(messages=tuple(segments), notes=tuple(notes))

    def _compact_text(
        self,
        text: str,
        profile: StyleProfileSnapshot,
        *,
        prefer_short: bool,
    ) -> str:
        compact = text
        for source, target in SHORT_REPLACEMENTS.items():
            compact = compact.replace(source, target)
            compact = compact.replace(source.capitalize(), target)
        if prefer_short:
            compact = compact.replace(" и вернусь с ответом", " и вернусь")
            compact = compact.replace(" и вернусь коротко", " и вернусь")

        compact = re.sub(r"\.{2,}", ".", compact)
        if profile.punctuation_level == "low":
            compact = compact.replace("!", "")
            compact = compact.replace(";", ",")
        else:
            compact = re.sub(r"!{2,}", "!", compact)
        compact = re.sub(r"\s*,\s*", ", ", compact)
        compact = _normalize_spaces(compact)
        return compact

    def _split_into_messages(
        self,
        text: str,
        profile: StyleProfileSnapshot,
        *,
        prefer_series: bool,
    ) -> list[str]:
        if profile.message_mode == "one":
            return [text]

        parts = [
            _strip_edge_punctuation(part)
            for part in re.split(r"(?<=[.!?])\s+", text)
            if _strip_edge_punctuation(part)
        ]
        if not parts:
            parts = [text]

        expanded: list[str] = []
        for part in parts:
            expanded.extend(self._split_long_part(part, profile))

        if len(expanded) == 1 and (profile.target_message_count > 1 or prefer_series):
            expanded = self._split_long_part(expanded[0], profile, aggressive=True)
        return [part for part in expanded if part]

    def _split_long_part(
        self,
        part: str,
        profile: StyleProfileSnapshot,
        *,
        aggressive: bool = False,
    ) -> list[str]:
        target_length = 52 if profile.avg_length_hint == "short" else 80
        if len(part) <= target_length and not aggressive:
            return [part]

        chunks = re.split(
            r",\s+| и | но | а | потом | затем | чтобы ",
            part,
        )
        cleaned = [_strip_edge_punctuation(chunk) for chunk in chunks if _strip_edge_punctuation(chunk)]
        if len(cleaned) <= 1:
            return [part]
        return cleaned

    def _ensure_opener(
        self,
        message: str,
        profile: StyleProfileSnapshot,
        *,
        opener_hint: str | None,
    ) -> str:
        lowered = message.casefold()
        opener_bank = tuple(
            dict.fromkeys(
                [
                    *((opener_hint,) if opener_hint else ()),
                    *(profile.preferred_openers or ()),
                ]
            )
        )
        if not opener_bank:
            return message
        if any(lowered.startswith(f"{opener} ") or lowered == opener for opener in opener_bank):
            return message

        if len(message) < 10 and opener_hint is None:
            return message
        return f"{opener_bank[0]} {message}"

    def _finalize_segment(self, segment: str, profile: StyleProfileSnapshot) -> str:
        finalized = _strip_edge_punctuation(_normalize_spaces(segment))
        if profile.casing_mode == "mostly_lower":
            finalized = _mostly_lower_preserving_names(finalized)
        finalized = finalized.replace("  ", " ")
        return finalized.strip()

    def _trim_segment_count(
        self,
        segments: list[str],
        profile: StyleProfileSnapshot,
    ) -> list[str]:
        if len(segments) <= profile.max_message_count:
            return segments

        trimmed = segments[: profile.max_message_count - 1]
        tail = " ".join(segments[profile.max_message_count - 1 :]).strip()
        trimmed.append(tail)
        return trimmed


def _normalize_spaces(value: str) -> str:
    return " ".join(value.split()).strip()


def _strip_edge_punctuation(value: str) -> str:
    return value.strip(" \n\t,.!?;:-")


def _mostly_lower_preserving_names(value: str) -> str:
    words = value.split()
    lowered: list[str] = []
    opener_tokens = {"ну", "да", "не", "а", "слушай", "смотри", "короче", "типо", "ща", "щас"}
    for index, word in enumerate(words):
        stripped = word.strip(".,!?;:-")
        previous = words[index - 1].strip(".,!?;:-").casefold() if index > 0 else ""
        if (
            index > 0
            and previous not in opener_tokens
            and len(stripped) > 2
            and stripped[:1].isupper()
            and stripped[1:].islower()
        ):
            lowered.append(word)
            continue
        lowered.append(word.lower())
    return " ".join(lowered)
