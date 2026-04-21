from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from services.reminder_extractor import ReminderExtractor
from services.reminder_formatter import ReminderFormatter
from services.reminder_models import ReminderActionResult, ReminderScanResult
from services.reminder_window import parse_reminder_scan_window
from storage.repositories import (
    ChatMemoryRepository,
    ChatRepository,
    MessageRepository,
    ReminderRepository,
    SettingRepository,
    TaskRepository,
)


@dataclass(slots=True)
class ReminderService:
    chat_repository: ChatRepository
    message_repository: MessageRepository
    chat_memory_repository: ChatMemoryRepository
    setting_repository: SettingRepository
    task_repository: TaskRepository
    reminder_repository: ReminderRepository
    extractor: ReminderExtractor
    formatter: ReminderFormatter

    async def scan(
        self,
        *,
        window_argument: str | None,
        source_reference: str | None,
        now: datetime | None = None,
    ) -> ReminderScanResult:
        scan_now = _ensure_utc(now or datetime.now(timezone.utc))
        window = parse_reminder_scan_window(window_argument, now=scan_now)
        source_chat = None
        if source_reference is not None:
            source_chat = await self.chat_repository.find_chat_by_handle_or_telegram_id(source_reference)
            if source_chat is None:
                raise ValueError("Источник для reminders_scan не найден. Проверь chat_id или @username.")

        records = await self.message_repository.get_messages_for_reminder_scan(
            window_start=window.start,
            window_end=window.end,
            chat_id=source_chat.id if source_chat is not None else None,
        )

        cards = []
        created_count = 0
        skipped_existing_count = 0

        for record in records:
            candidate = self.extractor.extract(record.message, now=scan_now)
            if candidate is None:
                continue

            existing_task = await self.task_repository.get_by_source_message_id(record.message.id)
            if existing_task is not None and existing_task.status != "candidate":
                skipped_existing_count += 1
                continue

            task, created = await self.task_repository.upsert_candidate(
                source_chat_id=record.chat.id,
                source_message_id=record.message.id,
                title=candidate.title,
                summary=candidate.summary,
                due_at=candidate.due_at,
                suggested_remind_at=candidate.suggested_remind_at,
                confidence=candidate.confidence,
            )
            reminder = await self.reminder_repository.upsert_candidate_for_task(
                task_id=task.id,
                remind_at=candidate.suggested_remind_at or (scan_now + timedelta(hours=1)),
                payload_json=_build_payload(record.chat.title, candidate),
            )
            loaded_task = await self.task_repository.get_task(task.id)
            loaded_reminder = await self.reminder_repository.get_reminder(reminder.id)
            if loaded_task is None or loaded_reminder is None:
                raise RuntimeError("Не удалось перечитать сохранённый reminder candidate.")
            cards.append(self.formatter.format_candidate_card(task=loaded_task, reminder=loaded_reminder))
            if created:
                created_count += 1

        return ReminderScanResult(
            summary_text=self.formatter.format_scan_summary(
                candidate_count=len(cards),
                window_label=window.label,
                source_label=source_chat.title if source_chat is not None else None,
                skipped_existing_count=skipped_existing_count,
            ),
            cards=cards,
            created_count=created_count,
            skipped_existing_count=skipped_existing_count,
        )

    async def approve_candidate(
        self,
        *,
        task_id: int,
        now: datetime | None = None,
    ) -> ReminderActionResult:
        execution_time = _ensure_utc(now or datetime.now(timezone.utc))
        return await self._change_candidate_state(
            task_id=task_id,
            action="approve",
            remind_at=None,
            now=execution_time,
        )

    async def reject_candidate(self, task_id: int) -> ReminderActionResult:
        return await self._change_candidate_state(
            task_id=task_id,
            action="reject",
            remind_at=None,
            now=datetime.now(timezone.utc),
        )

    async def postpone_candidate(
        self,
        *,
        task_id: int,
        now: datetime | None = None,
    ) -> ReminderActionResult:
        execution_time = _ensure_utc(now or datetime.now(timezone.utc))
        task = await self.task_repository.get_task(task_id)
        if task is None:
            raise ValueError("Кандидат не найден.")
        reminder = await self.reminder_repository.get_by_task_id(task.id)
        if reminder is None:
            raise ValueError("Reminder для кандидата не найден.")

        base_time = max(reminder.remind_at, execution_time)
        return await self._change_candidate_state(
            task_id=task_id,
            action="postpone",
            remind_at=base_time + timedelta(hours=1),
            now=execution_time,
        )

    async def build_tasks_message(self) -> str:
        return self.formatter.format_tasks(await self.task_repository.list_active_tasks())

    async def build_reminders_message(self) -> str:
        return self.formatter.format_reminders(await self.reminder_repository.list_active_reminders())

    async def _change_candidate_state(
        self,
        *,
        task_id: int,
        action: str,
        remind_at: datetime | None,
        now: datetime,
    ) -> ReminderActionResult:
        task = await self.task_repository.get_task(task_id)
        if task is None:
            raise ValueError("Кандидат не найден.")
        reminder = await self.reminder_repository.get_by_task_id(task.id)
        if reminder is None:
            raise ValueError("Reminder для кандидата не найден.")

        if task.status != "candidate":
            return ReminderActionResult(
                action="already_processed",
                task=task,
                reminder=reminder,
                text=self.formatter.format_action_result(
                    ReminderActionResult(
                        action="already_processed",
                        task=task,
                        reminder=reminder,
                        text="",
                    )
                ),
            )

        original_remind_at = reminder.remind_at
        if action == "reject":
            task = await self.task_repository.set_status(
                task.id,
                status="dismissed",
                needs_user_confirmation=True,
            )
            reminder = await self.reminder_repository.set_status(
                reminder.id,
                status="dismissed",
            )
        else:
            task = await self.task_repository.set_status(
                task.id,
                status="active",
                needs_user_confirmation=False,
            )
            if task is None:
                raise RuntimeError("Не удалось обновить статус задачи reminder.")
            reminder = await self.reminder_repository.set_status(
                reminder.id,
                status="active",
                remind_at=remind_at or reminder.remind_at or task.suggested_remind_at or (now + timedelta(hours=1)),
            )
            if reminder is None:
                raise RuntimeError("Не удалось обновить статус reminder.")

        if task is None or reminder is None:
            raise RuntimeError("Не удалось сохранить итоговое состояние reminder.")

        result = ReminderActionResult(
            action=action,
            task=task,
            reminder=reminder,
            text="",
            original_remind_at=original_remind_at,
        )
        return ReminderActionResult(
            action=result.action,
            task=result.task,
            reminder=result.reminder,
            text=self.formatter.format_action_result(result),
            original_remind_at=result.original_remind_at,
        )


def _build_payload(chat_title: str, candidate: Any) -> dict[str, Any]:
    return {
        "source_chat_title": chat_title,
        "source_sender_name": candidate.sender_name,
        "source_message_preview": candidate.source_message_preview,
        "reasons": list(candidate.reasons),
        "task_title": candidate.title,
    }


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
