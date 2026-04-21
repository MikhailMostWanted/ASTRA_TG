from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol

from core.logging import get_logger, log_event
from services.bot_owner import BotOwnerService
from services.operational_state import OperationalStateService
from services.reminder_formatter import ReminderFormatter
from services.reminder_models import ReminderDeliveryResult
from storage.repositories import ReminderRepository, SettingRepository


LOGGER = get_logger(__name__)


class ReminderSenderProtocol(Protocol):
    async def send_message(self, chat_id: int, text: str) -> object:
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
            log_event(
                LOGGER,
                20,
                "worker.reminders.empty",
                "Активных reminders для доставки не найдено.",
            )
            return ReminderDeliveryResult(
                sent_count=0,
                blocked_count=0,
                due_count=0,
                last_notification_at=None,
            )

        owner_chat_id = await BotOwnerService(self.setting_repository).get_owner_chat_id()
        if owner_chat_id is None or sender is None:
            log_event(
                LOGGER,
                30,
                "worker.reminders.blocked",
                "Доставка reminders заблокирована настройками worker.",
                due_count=len(due_reminders),
                owner_chat_known=owner_chat_id is not None,
                sender_ready=sender is not None,
            )
            return ReminderDeliveryResult(
                sent_count=0,
                blocked_count=len(due_reminders),
                due_count=len(due_reminders),
                last_notification_at=None,
            )

        sent_count = 0
        failed_count = 0
        skipped_count = 0
        seen_reminder_ids: set[int] = set()
        for reminder in due_reminders:
            if reminder.id in seen_reminder_ids:
                skipped_count += 1
                log_event(
                    LOGGER,
                    20,
                    "worker.reminders.duplicate_skip",
                    "Reminder пропущен как дубликат в пределах одного run.",
                    reminder_id=reminder.id,
                )
                continue

            seen_reminder_ids.add(reminder.id)
            try:
                await sender.send_message(
                    owner_chat_id,
                    self.formatter.format_delivery_packet(reminder),
                )
                await self.reminder_repository.mark_delivered(
                    reminder.id,
                    delivered_at=execution_time,
                )
            except Exception as error:
                failed_count += 1
                if hasattr(self.setting_repository, "set_value"):
                    await OperationalStateService(self.setting_repository).record_error(
                        "worker",
                        message=f"Reminder delivery failed: {error}",
                        details={"reminder_id": reminder.id},
                    )
                log_event(
                    LOGGER,
                    40,
                    "worker.reminders.failed",
                    "Reminder не был доставлен.",
                    reminder_id=reminder.id,
                    error_type=type(error).__name__,
                )
                continue

            sent_count += 1
            log_event(
                LOGGER,
                20,
                "worker.reminders.delivered",
                "Reminder доставлен.",
                reminder_id=reminder.id,
                owner_chat_id=owner_chat_id,
            )

        log_event(
            LOGGER,
            20,
            "worker.reminders.summary",
            "Reminder run завершён.",
            due_count=len(due_reminders),
            sent_count=sent_count,
            failed_count=failed_count,
            skipped_count=skipped_count,
        )
        return ReminderDeliveryResult(
            sent_count=sent_count,
            blocked_count=0,
            due_count=len(due_reminders),
            last_notification_at=execution_time if sent_count else None,
            failed_count=failed_count,
            skipped_count=skipped_count,
        )


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
