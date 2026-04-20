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
    ) -> StyledReply:
        original = _normalize_spaces(draft_text)
        if not original:
            return StyledReply(messages=(), notes=("Базовый черновик пустой.",))

        compact = self._compact_text(original, profile)
        punctuation_changed = compact != original
        segments = self._split_into_messages(compact, profile)
        opener_added = False
        if segments:
            updated_first = self._ensure_opener(segments[0], profile)
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

    def _compact_text(self, text: str, profile: StyleProfileSnapshot) -> str:
        compact = text
        for source, target in SHORT_REPLACEMENTS.items():
            compact = compact.replace(source, target)
            compact = compact.replace(source.capitalize(), target)

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

        if len(expanded) == 1 and profile.target_message_count > 1:
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

    def _ensure_opener(self, message: str, profile: StyleProfileSnapshot) -> str:
        if not profile.preferred_openers:
            return message

        lowered = message.casefold()
        if any(lowered.startswith(f"{opener} ") or lowered == opener for opener in profile.preferred_openers):
            return message

        if len(message) < 10:
            return message
        return f"{profile.preferred_openers[0]} {message}"

    def _finalize_segment(self, segment: str, profile: StyleProfileSnapshot) -> str:
        finalized = _strip_edge_punctuation(_normalize_spaces(segment))
        if profile.casing_mode == "mostly_lower":
            finalized = finalized.lower()
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
