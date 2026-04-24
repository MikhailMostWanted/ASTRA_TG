from __future__ import annotations

import re
from dataclasses import dataclass

from services.persona_rules import OwnerPersonaCore
from services.style_profiles import StyleProfileSnapshot


COMMON_REWRITES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bв данном случае\b", re.IGNORECASE), "тут"),
    (re.compile(r"\bя посмотрю это сейчас\b", re.IGNORECASE), "я гляну это сейчас"),
    (re.compile(r"\bсмотрю это сейчас\b", re.IGNORECASE), "смотрю это сейчас"),
    (re.compile(r"\bконкретным апдейтом\b", re.IGNORECASE), "нормальным обновлением"),
    (re.compile(r"\bапдейтом\b", re.IGNORECASE), "обновлением"),
    (re.compile(r"\bчуть позже\b", re.IGNORECASE), "позже"),
    (re.compile(r"\bбез лишних эмоций\b", re.IGNORECASE), "без лишнего"),
    (re.compile(r"\bпроверю детали\b", re.IGNORECASE), "гляну детали"),
    (re.compile(r"\bя отвечу точнее\b", re.IGNORECASE), "я тогда точнее отвечу"),
    (re.compile(r"\bпожалуйста\b", re.IGNORECASE), ""),
    (re.compile(r"\bбуду рад\b", re.IGNORECASE), "я"),
)
DIRECT_REWRITES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bвижу вопрос\b", re.IGNORECASE), "тут вопрос"),
    (re.compile(r"\bвижу запрос\b", re.IGNORECASE), "тут запрос"),
    (re.compile(r"\bя это посмотрю\b", re.IGNORECASE), "я гляну это"),
    (re.compile(r"\bя на связи, если нужно, продолжим отсюда\b", re.IGNORECASE), "если что дальше добьём отсюда"),
)
WARM_REWRITES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bя на связи\b", re.IGNORECASE), "я на связи"),
    (re.compile(r"\bдавай без резкости\b", re.IGNORECASE), "давай спокойно"),
)
SPLIT_DELIMITERS = (
    r"(?<=[.!?])\s+",
    r",\s+",
    r"\s+потому что\s+",
    r"\s+но\s+",
    r"\s+и\s+",
    r"\s+чтобы\s+",
)


@dataclass(frozen=True, slots=True)
class PersonaAdaptation:
    messages: tuple[str, ...]
    notes: tuple[str, ...]
    applied: bool


@dataclass(slots=True)
class PersonaAdapter:
    split_target_length: int = 44

    def adapt(
        self,
        *,
        messages: tuple[str, ...],
        profile: StyleProfileSnapshot,
        persona_core: OwnerPersonaCore | None,
        strategy: str,
    ) -> PersonaAdaptation:
        original = tuple(_normalize_message(message) for message in messages if _normalize_message(message))
        if not original:
            return PersonaAdaptation(messages=(), notes=("Style-aware серия пустая.",), applied=False)
        if persona_core is None:
            return PersonaAdaptation(
                messages=original,
                notes=("Persona core недоступен, оставил style-aware серию.",),
                applied=False,
            )

        notes: list[str] = []
        transformed: list[str] = []
        for message in original:
            rewritten = self._rewrite_message(message, profile)
            if rewritten != message and "Сделал формулировку разговорнее." not in notes:
                notes.append("Сделал формулировку разговорнее.")
            chunks = self._split_message(
                rewritten,
                force=(
                    profile.message_mode == "series"
                    and len(original) == 1
                ),
            )
            if len(chunks) > 1 and "Разбил длинную фразу на короткую серию." not in notes:
                notes.append("Разбил длинную фразу на короткую серию.")
            transformed.extend(chunks)

        if transformed:
            updated_first = self._ensure_opener(
                transformed[0],
                profile=profile,
                persona_core=persona_core,
                strategy=strategy,
            )
            if updated_first != transformed[0]:
                notes.append("Добавил owner-like старт.")
                transformed[0] = updated_first

        transformed = [self._finalize(message, profile) for message in transformed]

        closer_added = False
        if self._should_add_closer(transformed, profile, strategy):
            closer = self._pick_closer(profile, persona_core)
            if closer is not None:
                transformed.append(self._finalize(closer, profile))
                closer_added = True
        if closer_added:
            notes.append("Добавил короткое тёплое завершение.")

        transformed = _trim_message_count(transformed, profile.max_message_count)
        applied = tuple(transformed) != original
        if not notes and not applied:
            notes.append("Оставил style-aware серию почти без изменений.")

        return PersonaAdaptation(
            messages=tuple(transformed),
            notes=tuple(notes),
            applied=applied,
        )

    def _rewrite_message(
        self,
        message: str,
        profile: StyleProfileSnapshot,
    ) -> str:
        rewritten = message
        for pattern, replacement in COMMON_REWRITES:
            rewritten = pattern.sub(replacement, rewritten)
        if profile.directness_level in {"medium", "high"}:
            for pattern, replacement in DIRECT_REWRITES:
                rewritten = pattern.sub(replacement, rewritten)
        if profile.warmth_level == "high":
            for pattern, replacement in WARM_REWRITES:
                rewritten = pattern.sub(replacement, rewritten)
        return _normalize_message(rewritten)

    def _split_message(self, message: str, *, force: bool) -> list[str]:
        if len(message) <= self.split_target_length and not force:
            return [message]

        parts = [message]
        for delimiter in SPLIT_DELIMITERS:
            next_parts: list[str] = []
            changed = False
            for part in parts:
                if len(part) <= self.split_target_length and not force:
                    next_parts.append(part)
                    continue
                split_parts = [
                    _normalize_message(chunk)
                    for chunk in re.split(delimiter, part)
                    if _normalize_message(chunk)
                ]
                if len(split_parts) > 1:
                    next_parts.extend(split_parts)
                    changed = True
                else:
                    next_parts.append(part)
            parts = next_parts
            if changed:
                force = False
        return _merge_tiny_chunks(parts)

    def _ensure_opener(
        self,
        message: str,
        *,
        profile: StyleProfileSnapshot,
        persona_core: OwnerPersonaCore,
        strategy: str,
    ) -> str:
        lowered = message.casefold()
        allowed_openers = tuple(
            dict.fromkeys(
                [
                    *profile.preferred_openers,
                    *persona_core.opener_bank,
                ]
            )
        )
        if any(lowered == opener or lowered.startswith(f"{opener} ") for opener in allowed_openers):
            return message

        opener = "ну"
        if profile.directness_level == "high":
            opener = "да"
        if strategy == "снять напряжение":
            opener = "я"
        if opener not in allowed_openers and allowed_openers:
            opener = allowed_openers[0]
        return f"{opener} {message}"

    def _finalize(
        self,
        message: str,
        profile: StyleProfileSnapshot,
    ) -> str:
        finalized = _normalize_message(message)
        finalized = finalized.strip(" \n\t,.!?;:-")
        if profile.casing_mode == "mostly_lower":
            finalized = _mostly_lower_preserving_names(finalized)
        finalized = re.sub(r"\s+", " ", finalized).strip()
        finalized = finalized.replace("  ", " ")
        return finalized

    def _should_add_closer(
        self,
        messages: list[str],
        profile: StyleProfileSnapshot,
        strategy: str,
    ) -> bool:
        if not messages:
            return False
        if len(messages) >= profile.max_message_count:
            return False
        if strategy not in {"поддержать", "мягко ответить", "снять напряжение"}:
            return False
        return profile.warmth_level == "high"

    def _pick_closer(
        self,
        profile: StyleProfileSnapshot,
        persona_core: OwnerPersonaCore,
    ) -> str | None:
        if profile.preferred_closers:
            return profile.preferred_closers[0]
        if persona_core.closer_bank:
            return persona_core.closer_bank[-1]
        return None


def _normalize_message(value: str) -> str:
    return " ".join(str(value).split()).strip()


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


def _merge_tiny_chunks(messages: list[str]) -> list[str]:
    merged: list[str] = []
    for chunk in messages:
        normalized = _normalize_message(chunk)
        if not normalized:
            continue
        if merged and len(normalized) < 12:
            merged[-1] = f"{merged[-1]} {normalized}".strip()
            continue
        merged.append(normalized)
    return merged


def _trim_message_count(messages: list[str], max_count: int) -> list[str]:
    if len(messages) <= max_count:
        return messages
    head = messages[: max_count - 1]
    tail = " ".join(messages[max_count - 1 :]).strip()
    return [*head, tail]
