from __future__ import annotations

import re
from dataclasses import dataclass

from services.reply_models import ReplyVariant


@dataclass(slots=True)
class ReplyVariantBuilder:
    def build(
        self,
        *,
        final_messages: tuple[str, ...],
        baseline_messages: tuple[str, ...] = (),
        provider_variants: tuple[ReplyVariant, ...] = (),
        few_shot_support=None,
    ) -> tuple[ReplyVariant, ...]:
        primary_text = _join_messages(final_messages)
        baseline_text = _join_messages(baseline_messages)
        provider_map = {item.id: item for item in provider_variants if item.text.strip()}

        variants: list[ReplyVariant] = []
        primary_variant = provider_map.get("primary") or ReplyVariant(
            id="primary",
            label="Основной",
            description="Главный вариант для отправки.",
            text=primary_text or baseline_text,
        )
        _append_variant(variants, primary_variant)

        short_variant = provider_map.get("short") or ReplyVariant(
            id="short",
            label="Короче",
            description="Более короткий и прямой ответ.",
            text=_build_short_text(primary_variant.text),
        )
        _append_variant(variants, short_variant)

        soft_variant = provider_map.get("soft") or ReplyVariant(
            id="soft",
            label="Мягче",
            description="Более мягкая и спокойная подача.",
            text=_build_soft_text(primary_variant.text),
        )
        _append_variant(variants, soft_variant)

        style_variant = provider_map.get("style") or ReplyVariant(
            id="style",
            label="В моём стиле",
            description="Более разговорный и каскадный ритм.",
            text=_build_style_text(
                primary_variant.text,
                prefer_series=bool(getattr(few_shot_support, "rhythm_hint", None) == "series"),
            ),
        )
        _append_variant(variants, style_variant)

        if len(variants) < 2 and baseline_text:
            _append_variant(
                variants,
                ReplyVariant(
                    id="fallback",
                    label="Базовый",
                    description="Спокойный fallback-вариант.",
                    text=baseline_text,
                ),
            )
        return tuple(variants[:4])


def _append_variant(variants: list[ReplyVariant], variant: ReplyVariant) -> None:
    cleaned = _compact_multiline(variant.text)
    if not cleaned:
        return
    if any(item.id == variant.id for item in variants):
        return
    if any(item.text == cleaned for item in variants):
        return
    variants.append(
        ReplyVariant(
            id=variant.id,
            label=variant.label,
            description=variant.description,
            text=cleaned,
        )
    )


def _join_messages(messages: tuple[str, ...]) -> str:
    return "\n".join(line.strip() for line in messages if line and line.strip()).strip()


def _compact_multiline(value: str | None) -> str:
    if not value:
        return ""
    return "\n".join(line.strip() for line in str(value).splitlines() if line.strip()).strip()


def _build_short_text(value: str) -> str:
    normalized = _compact_multiline(value)
    if not normalized:
        return ""
    lines = normalized.splitlines()
    if len(lines) >= 2:
        return lines[0]
    sentences = [
        part.strip()
        for part in re.split(r"(?<=[.!?])\s+", normalized)
        if part.strip()
    ]
    if len(sentences) >= 2:
        return sentences[0]
    words = normalized.split()
    if len(words) <= 9:
        return normalized
    return " ".join(words[:9]).rstrip(".,!?") + "."


def _build_soft_text(value: str) -> str:
    normalized = _compact_multiline(value)
    if not normalized:
        return ""
    softened = normalized
    replacements = (
        ("надо", "лучше"),
        ("нужно", "лучше"),
        ("сейчас", "сейчас аккуратно"),
        ("скину", "мягко скину"),
        ("вернусь", "чуть позже вернусь"),
    )
    for source, target in replacements:
        lowered = softened.casefold()
        if source in lowered:
            softened = re.sub(source, target, softened, flags=re.IGNORECASE, count=1)
            break
    if len(softened.splitlines()) == 1 and not softened.casefold().startswith(("понимаю", "да", "ок")):
        softened = f"Понимаю.\n{softened[0].lower() + softened[1:]}" if len(softened) > 1 else softened
    return softened


def _build_style_text(value: str, *, prefer_series: bool) -> str:
    normalized = _compact_multiline(value)
    if not normalized:
        return ""
    lowered = normalized[:1].lower() + normalized[1:] if len(normalized) > 1 else normalized.lower()
    if "\n" in lowered:
        return lowered
    if prefer_series:
        parts = re.split(r"(?<=[,!?.])\s+", lowered, maxsplit=1)
        if len(parts) == 2:
            return "\n".join(part.strip(" ") for part in parts if part.strip())
    words = lowered.split()
    if len(words) >= 8:
        pivot = min(5, max(3, len(words) // 2))
        return "\n".join(
            [
                " ".join(words[:pivot]).strip(),
                " ".join(words[pivot:]).strip(),
            ]
        ).strip()
    return lowered
