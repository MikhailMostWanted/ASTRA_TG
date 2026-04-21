from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from aiogram.types import InlineKeyboardMarkup

from models import Reminder, Task


@dataclass(frozen=True, slots=True)
class ReminderCandidate:
    title: str
    summary: str
    due_at: datetime | None
    suggested_remind_at: datetime | None
    confidence: float
    reasons: tuple[str, ...]
    source_message_preview: str
    sender_name: str | None


@dataclass(frozen=True, slots=True)
class RenderedReminderCard:
    task_id: int
    text: str
    reply_markup: InlineKeyboardMarkup | None


@dataclass(frozen=True, slots=True)
class ReminderScanResult:
    summary_text: str
    cards: list[RenderedReminderCard]
    created_count: int
    skipped_existing_count: int


@dataclass(frozen=True, slots=True)
class ReminderActionResult:
    action: str
    task: Task
    reminder: Reminder
    text: str
    original_remind_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class ReminderDeliveryResult:
    sent_count: int
    blocked_count: int
    due_count: int
    last_notification_at: datetime | None
    failed_count: int = 0
    skipped_count: int = 0
