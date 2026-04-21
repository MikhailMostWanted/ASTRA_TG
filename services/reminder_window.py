from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone


DEFAULT_REMINDER_WINDOW = "24h"
WINDOW_RE = re.compile(r"^(?P<value>\d+)(?P<unit>[hd])$")


@dataclass(frozen=True, slots=True)
class ReminderScanWindow:
    original_text: str
    label: str
    duration: timedelta
    start: datetime
    end: datetime


def parse_reminder_scan_window(
    value: str | None,
    *,
    now: datetime | None = None,
) -> ReminderScanWindow:
    raw_value = (value or DEFAULT_REMINDER_WINDOW).strip().lower()
    if not raw_value:
        raw_value = DEFAULT_REMINDER_WINDOW

    match = WINDOW_RE.fullmatch(raw_value)
    if match is None:
        raise ValueError(
            "Для /reminders_scan поддержаны окна вида 12h, 24h или 3d. "
            "Пример: /reminders_scan 24h"
        )

    amount = int(match.group("value"))
    if amount <= 0:
        raise ValueError("Окно reminders_scan должно быть больше нуля.")

    duration = timedelta(hours=amount) if match.group("unit") == "h" else timedelta(days=amount)
    end = _ensure_utc(now or datetime.now(timezone.utc))
    start = end - duration
    return ReminderScanWindow(
        original_text=raw_value,
        label=raw_value,
        duration=duration,
        start=start,
        end=end,
    )


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
