from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol

from services.bot_owner import BotOwnerService
from services.reminder_formatter import ReminderFormatter
from services.reminder_models import ReminderDeliveryResult
from storage.repositories import ReminderRepository, SettingRepository


class ReminderSenderProtocol(Protocol):
    async def send_message(self, chat_id: int, text: str):
        """Отправляет reminder packet в Telegram."""


@dataclass(slots=True)
class ReminderDeliveryService:
    setting_repository: SettingRepository
    reminder_repository: ReminderRepository
    formatter: ReminderFormatter

    async def deliver_due_reminders(
        self,
        *,
        sender: ReminderSenderProtocol | None,
        now: datetime | None = None,
    ) -> ReminderDeliveryResult:
        execution_time = _ensure_utc(now or datetime.now(timezone.utc))
        due_reminders = await self.reminder_repository.get_due_reminders(execution_time)
        if not due_reminders:
            return ReminderDeliveryResult(
                sent_count=0,
                blocked_count=0,
                due_count=0,
                last_notification_at=None,
            )

        owner_chat_id = await BotOwnerService(self.setting_repository).get_owner_chat_id()
        if owner_chat_id is None or sender is None:
            return ReminderDeliveryResult(
                sent_count=0,
                blocked_count=len(due_reminders),
                due_count=len(due_reminders),
                last_notification_at=None,
            )

        sent_count = 0
        for reminder in due_reminders:
            await sender.send_message(
                owner_chat_id,
                self.formatter.format_delivery_packet(reminder),
            )
            await self.reminder_repository.mark_delivered(
                reminder.id,
                delivered_at=execution_time,
            )
            sent_count += 1

        return ReminderDeliveryResult(
            sent_count=sent_count,
            blocked_count=0,
            due_count=len(due_reminders),
            last_notification_at=execution_time if sent_count else None,
        )


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
