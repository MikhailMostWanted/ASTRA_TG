from __future__ import annotations

from dataclasses import dataclass

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from models import Reminder, Task
from services.memory_common import format_utc, truncate_text
from services.reminder_models import ReminderActionResult, RenderedReminderCard


REMINDER_CALLBACK_PREFIX = "reminder"


@dataclass(frozen=True, slots=True)
class ParsedReminderCallback:
    action: str
    task_id: int


class ReminderFormatter:
    def format_candidate_card(self, *, task: Task, reminder: Reminder) -> RenderedReminderCard:
        payload = reminder.payload_json if isinstance(reminder.payload_json, dict) else {}
        chat_title = (
            task.source_chat.title
            if task.source_chat is not None
            else payload.get("source_chat_title", "Неизвестный чат")
        )
        source_sender = payload.get("source_sender_name") or "не указан"
        reasons = payload.get("reasons") or []
        text = "\n".join(
            [
                "Кандидат на задачу / reminder",
                "",
                f"Чат: {chat_title}",
                f"С кем связано: {source_sender}",
                f"Формулировка: {task.title}",
                f"Контекст: {truncate_text(task.summary or payload.get('source_message_preview'), limit=180)}",
                (
                    f"Срок: {format_utc(task.due_at)}"
                    if task.due_at is not None
                    else "Срок: не определён"
                ),
                f"Предлагаю напомнить: {format_utc(reminder.remind_at)}",
                f"Уверенность: {round(task.confidence * 100)}%",
                (
                    "Почему замечено: " + ", ".join(str(item) for item in reasons[:4])
                    if reasons
                    else "Почему замечено: детальная причина не сохранена"
                ),
            ]
        )
        return RenderedReminderCard(
            task_id=task.id,
            text=text,
            reply_markup=self.build_candidate_keyboard(task.id),
        )

    def build_candidate_keyboard(self, task_id: int) -> InlineKeyboardMarkup:
        builder = InlineKeyboardBuilder()
        builder.row(
            InlineKeyboardButton(
                text="Одобрить",
                callback_data=build_reminder_callback_data("approve", task_id),
            ),
            InlineKeyboardButton(
                text="Отменить",
                callback_data=build_reminder_callback_data("reject", task_id),
            ),
            InlineKeyboardButton(
                text="Позже",
                callback_data=build_reminder_callback_data("postpone", task_id),
            ),
        )
        return builder.as_markup()

    def format_scan_summary(
        self,
        *,
        candidate_count: int,
        window_label: str,
        source_label: str | None,
        skipped_existing_count: int,
    ) -> str:
        scope = f"по источнику {source_label}" if source_label else "по активным источникам"
        if candidate_count == 0:
            return f"За {window_label} {scope} кандидатов на задачи и reminders не найдено."

        lines = [
            f"Найдено кандидатов: {candidate_count}",
            f"Окно: {window_label}",
            f"Область сканирования: {scope}",
        ]
        if skipped_existing_count:
            lines.append(f"Пропущено уже обработанных сообщений: {skipped_existing_count}")
        lines.append("Ниже карточки для подтверждения.")
        return "\n".join(lines)

    def format_tasks(self, tasks: list[Task]) -> str:
        if not tasks:
            return "Активных задач пока нет."

        lines = ["Активные задачи", ""]
        for index, task in enumerate(tasks[:10], start=1):
            reminder = _pick_primary_reminder(task.reminders)
            lines.extend(
                [
                    f"{index}. {task.title}",
                    f"Статус: {task.status}",
                    (
                        f"Срок: {format_utc(task.due_at)}"
                        if task.due_at is not None
                        else "Срок: не задан"
                    ),
                    (
                        f"Reminder: {format_utc(reminder.remind_at)}"
                        if reminder is not None
                        else "Reminder: не задан"
                    ),
                    f"Источник: {_resolve_chat_title(task, reminder)}",
                    f"Контекст: {truncate_text(task.summary, limit=160) or 'нет краткого контекста'}",
                    "",
                ]
            )
        return "\n".join(lines).rstrip()

    def format_reminders(self, reminders: list[Reminder]) -> str:
        if not reminders:
            return "Активных напоминаний пока нет."

        lines = ["Активные напоминания", ""]
        for index, reminder in enumerate(reminders[:10], start=1):
            task = reminder.task
            lines.extend(
                [
                    f"{index}. {task.title if task is not None else 'Без задачи'}",
                    f"Сработает: {format_utc(reminder.remind_at)}",
                    f"Статус: {reminder.status}",
                    f"Источник: {_resolve_chat_title(task, reminder)}",
                    (
                        f"Подтверждено: {'да' if task is not None and not task.needs_user_confirmation else 'нет'}"
                    ),
                    "",
                ]
            )
        return "\n".join(lines).rstrip()

    def format_action_result(self, result: ReminderActionResult) -> str:
        task = result.task
        reminder = result.reminder
        action_title = {
            "approve": "Кандидат одобрен.",
            "reject": "Кандидат отклонён.",
            "postpone": "Кандидат подтверждён с переносом.",
            "already_processed": "Кандидат уже обработан.",
        }.get(result.action, "Состояние кандидата обновлено.")
        lines = [
            action_title,
            "",
            f"Задача: {task.title}",
            f"Статус задачи: {task.status}",
            f"Reminder: {format_utc(reminder.remind_at)}",
            f"Статус reminder: {reminder.status}",
            f"Источник: {_resolve_chat_title(task, reminder)}",
        ]
        if result.action == "postpone" and result.original_remind_at is not None:
            lines.insert(4, f"Было: {format_utc(result.original_remind_at)}")
        return "\n".join(lines)

    def format_delivery_packet(self, reminder: Reminder) -> str:
        payload = reminder.payload_json if isinstance(reminder.payload_json, dict) else {}
        task = reminder.task
        title = task.title if task is not None else payload.get("task_title", "Без названия")
        chat_title = _resolve_chat_title(task, reminder)
        source_sender = payload.get("source_sender_name") or "не указан"
        context = truncate_text(
            (task.summary if task is not None else None) or payload.get("source_message_preview"),
            limit=180,
        )
        return "\n".join(
            [
                "Reminder packet",
                "",
                f"Задача: {title}",
                f"Чат: {chat_title}",
                f"С кем связано: {source_sender}",
                f"Контекст: {context or 'краткий контекст не сохранён'}",
                f"Что лучше сделать сейчас: {title.lower()} и закрыть этот хвост, либо сразу перенести новый срок.",
            ]
        )


def build_reminder_callback_data(action: str, task_id: int) -> str:
    return f"{REMINDER_CALLBACK_PREFIX}:{action}:{task_id}"


def parse_reminder_callback_data(data: str | None) -> ParsedReminderCallback | None:
    if not data:
        return None

    parts = data.split(":")
    if len(parts) != 3 or parts[0] != REMINDER_CALLBACK_PREFIX:
        return None

    try:
        task_id = int(parts[2])
    except ValueError:
        return None

    return ParsedReminderCallback(action=parts[1], task_id=task_id)


def _pick_primary_reminder(reminders: list[Reminder]) -> Reminder | None:
    if not reminders:
        return None
    return sorted(reminders, key=lambda item: (item.remind_at, item.id))[0]


def _resolve_chat_title(task: Task | None, reminder: Reminder | None) -> str:
    if task is not None and task.source_chat is not None:
        return task.source_chat.title
    payload = reminder.payload_json if reminder is not None and isinstance(reminder.payload_json, dict) else {}
    return str(payload.get("source_chat_title", "Неизвестный чат"))
