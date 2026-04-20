from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone


DEFAULT_DIGEST_WINDOW = "24h"
WINDOW_RE = re.compile(r"^(?P<value>\d+)(?P<unit>[hd])$")


@dataclass(frozen=True, slots=True)
class DigestWindow:
    original_text: str
    label: str
    duration: timedelta
    start: datetime
    end: datetime


def parse_digest_window(
    value: str | None,
    *,
    now: datetime | None = None,
) -> DigestWindow:
    raw_value = (value or DEFAULT_DIGEST_WINDOW).strip().lower()
    if not raw_value:
        raw_value = DEFAULT_DIGEST_WINDOW

    match = WINDOW_RE.fullmatch(raw_value)
    if match is None:
        raise ValueError(
            "Для /digest_now поддержаны окна вида 12h, 24h или 3d. "
            "Пример: /digest_now 24h"
        )

    amount = int(match.group("value"))
    unit = match.group("unit")
    if amount <= 0:
        raise ValueError("Окно digest должно быть больше нуля.")

    duration = timedelta(hours=amount) if unit == "h" else timedelta(days=amount)
    end = _ensure_utc(now or datetime.now(timezone.utc))
    start = end - duration

    return DigestWindow(
        original_text=raw_value,
        label=raw_value,
        duration=duration,
        start=start,
        end=end,
    )


def format_window_range(window: DigestWindow) -> str:
    return (
        f"{format_timestamp(window.start)} - {format_timestamp(window.end)} "
        f"({window.label})"
    )


def format_timestamp(value: datetime) -> str:
    normalized = _ensure_utc(value)
    return normalized.strftime("%Y-%m-%d %H:%M UTC")


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
