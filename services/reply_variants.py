from __future__ import annotations

import re
from dataclasses import dataclass

from services.reply_models import ReplyVariant
from services.reply_postprocessor import (
    normalize_variant_id,
    postprocess_variant_text,
)


@dataclass(slots=True)
class ReplyVariantBuilder:
    def build(
        self,
        *,
        final_messages: tuple[str, ...],
        baseline_messages: tuple[str, ...] = (),
        provider_variants: tuple[ReplyVariant, ...] = (),
        few_shot_support=None,
        profile=None,
    ) -> tuple[ReplyVariant, ...]:
        opener_hint = getattr(few_shot_support, "opener_hint", None)
        primary_text = postprocess_variant_text(
            final_messages,
            variant_id="primary",
            opener_hint=opener_hint,
        )
        baseline_text = postprocess_variant_text(
            baseline_messages,
            variant_id="primary",
            opener_hint=opener_hint,
        )
        provider_map = {
            normalize_variant_id(item.id): ReplyVariant(
                id=normalize_variant_id(item.id),
                label=item.label,
                description=item.description,
                text=postprocess_variant_text(
                    item.text,
                    variant_id=normalize_variant_id(item.id),
                    opener_hint=opener_hint,
                ),
            )
            for item in provider_variants
            if item.text.strip()
        }

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
            description="Одна-две короткие реплики без лишнего.",
            text=_build_short_text(primary_variant.text, opener_hint=opener_hint),
        )
        _append_variant(variants, short_variant)

        soft_variant = provider_map.get("soft") or ReplyVariant(
            id="soft",
            label="Мягче",
            description="Теплее и аккуратнее, без лишней резкости.",
            text=_build_soft_text(primary_variant.text, opener_hint=opener_hint),
        )
        _append_variant(variants, soft_variant)

        style_variant = provider_map.get("owner_style") or ReplyVariant(
            id="owner_style",
            label="В моём стиле",
            description="Каскад коротких живых реплик в манере владельца.",
            text=_build_owner_style_text(
                primary_variant.text,
                prefer_series=bool(getattr(few_shot_support, "rhythm_hint", None) == "series"),
                opener_hint=opener_hint,
            ),
        )
        _append_variant(variants, style_variant)

        if len(variants) < 4:
            variants = _fill_missing_variants(
                variants,
                primary_text=primary_variant.text or baseline_text,
                opener_hint=opener_hint,
            )

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
        return tuple(_sort_variants(variants)[:4])


def _append_variant(variants: list[ReplyVariant], variant: ReplyVariant) -> None:
    variant_id = normalize_variant_id(variant.id)
    cleaned = postprocess_variant_text(variant.text, variant_id=variant_id)
    if not cleaned:
        return
    if any(item.id == variant_id for item in variants):
        return
    variants.append(
        ReplyVariant(
            id=variant_id,
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


def _build_short_text(value: str, *, opener_hint: str | None) -> str:
    normalized = _compact_multiline(value)
    if not normalized:
        return ""
    return postprocess_variant_text(
        normalized,
        variant_id="short",
        opener_hint=opener_hint,
        max_lines=2,
    )


def _build_soft_text(value: str, *, opener_hint: str | None) -> str:
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
    return postprocess_variant_text(
        softened,
        variant_id="soft",
        opener_hint=opener_hint,
        max_lines=3,
    )


def _build_owner_style_text(value: str, *, prefer_series: bool, opener_hint: str | None) -> str:
    normalized = _compact_multiline(value)
    if not normalized:
        return ""
    lowered = normalized[:1].lower() + normalized[1:] if len(normalized) > 1 else normalized.lower()
    if "\n" in lowered and prefer_series:
        return postprocess_variant_text(lowered, variant_id="owner_style", opener_hint=opener_hint)
    if prefer_series:
        parts = re.split(r"(?<=[,!?.])\s+", lowered, maxsplit=1)
        if len(parts) == 2:
            lowered = "\n".join(part.strip(" ") for part in parts if part.strip())
    return postprocess_variant_text(
        lowered,
        variant_id="owner_style",
        opener_hint=opener_hint,
        max_lines=4,
    )


def _fill_missing_variants(
    variants: list[ReplyVariant],
    *,
    primary_text: str,
    opener_hint: str | None,
) -> list[ReplyVariant]:
    existing = {variant.id for variant in variants}
    filled = list(variants)
    if "primary" not in existing and primary_text:
        _append_variant(
            filled,
            ReplyVariant("primary", "Основной", "Главный вариант для отправки.", primary_text),
        )
    if "short" not in existing:
        _append_variant(
            filled,
            ReplyVariant("short", "Короче", "Одна-две короткие реплики без лишнего.", _build_short_text(primary_text, opener_hint=opener_hint)),
        )
    if "soft" not in existing:
        _append_variant(
            filled,
            ReplyVariant("soft", "Мягче", "Теплее и аккуратнее, без лишней резкости.", _build_soft_text(primary_text, opener_hint=opener_hint)),
        )
    if "owner_style" not in existing:
        _append_variant(
            filled,
            ReplyVariant(
                "owner_style",
                "В моём стиле",
                "Каскад коротких живых реплик в манере владельца.",
                _build_owner_style_text(primary_text, prefer_series=True, opener_hint=opener_hint),
            ),
        )
    return filled


def _sort_variants(variants: list[ReplyVariant]) -> list[ReplyVariant]:
    order = {"primary": 0, "short": 1, "soft": 2, "owner_style": 3}
    return sorted(variants, key=lambda item: order.get(item.id, 99))
