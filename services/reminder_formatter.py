from __future__ import annotations

from dataclasses import dataclass

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from models import Reminder, Task
from services.memory_common import format_utc, truncate_text
from services.reminder_models import ReminderActionResult, RenderedReminderCard
from services.render_cards import (
    MARKER_OFF,
    MARKER_OK,
    MARKER_WARN,
    format_status_line,
    state_shell_lines,
)


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
                "Astra AFT / Reminders / Candidate",
                "",
                "Сводка",
                format_status_line(MARKER_WARN, "Статус", "требует подтверждения"),
                format_status_line(MARKER_OK, "Задача", task.title),
                format_status_line(MARKER_OK, "Напомнить", format_utc(reminder.remind_at)),
                "",
                "Контекст",
                format_status_line(MARKER_OK, "Чат", chat_title),
                format_status_line(MARKER_OK, "Связано с", source_sender),
                truncate_text(task.summary or payload.get("source_message_preview"), limit=180),
                "",
                "Детали",
                (
                    format_status_line(MARKER_OK, "Срок", format_utc(task.due_at))
                    if task.due_at is not None
                    else format_status_line(MARKER_OFF, "Срок", "не определён")
                ),
                format_status_line(MARKER_OK, "Уверенность", f"{round(task.confidence * 100)}%"),
                format_status_line(
                    MARKER_OK if reasons else MARKER_OFF,
                    "Почему замечено",
                    ", ".join(str(item) for item in reasons[:3]) if reasons else "детальная причина не сохранена",
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
                text="Позже",
                callback_data=build_reminder_callback_data("postpone", task_id),
            ),
            InlineKeyboardButton(
                text="Отклонить",
                callback_data=build_reminder_callback_data("reject", task_id),
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
            return "\n".join(
                [
                    "Astra AFT / Reminders / Скан",
                    "",
                    *state_shell_lines(
                        marker=MARKER_OFF,
                        status="Кандидаты не найдены",
                        meaning=f"За {window_label} {scope} новых задач не видно.",
                        next_step="Попробуй другое окно или дождись новых сообщений.",
                    ),
                ]
            )

        lines = [
            "Astra AFT / Reminders / Скан",
            "",
            "Сводка",
            format_status_line(MARKER_OK, "Найдено кандидатов", str(candidate_count)),
            format_status_line(MARKER_OK, "Окно", window_label),
            format_status_line(MARKER_OK, "Область", scope),
        ]
        if skipped_existing_count:
            lines.append(format_status_line(MARKER_OFF, "Уже обработано", str(skipped_existing_count)))
        lines.extend(["", "Следующий шаг", "Подтверди нужные карточки ниже."])
        return "\n".join(lines)

    def format_tasks(self, tasks: list[Task]) -> str:
        if not tasks:
            return "\n".join(
                [
                    "Astra AFT / Reminders / Tasks",
                    "",
                    *state_shell_lines(
                        marker=MARKER_OFF,
                        status="Активных задач нет",
                        meaning="Подтверждённые задачи пока не сохранены.",
                        next_step="/reminders_scan 24h",
                    ),
                ]
            )

        lines = ["Astra AFT / Reminders / Tasks", "", "Детали"]
        for index, task in enumerate(tasks[:10], start=1):
            reminder = _pick_primary_reminder(task.reminders)
            lines.extend(
                [
                    f"{index}. {task.title}",
                    format_status_line(MARKER_OK, "Статус", task.status),
                    (
                        format_status_line(MARKER_OK, "Срок", format_utc(task.due_at))
                        if task.due_at is not None
                        else format_status_line(MARKER_OFF, "Срок", "не задан")
                    ),
                    (
                        format_status_line(MARKER_OK, "Reminder", format_utc(reminder.remind_at))
                        if reminder is not None
                        else format_status_line(MARKER_OFF, "Reminder", "не задан")
                    ),
                    format_status_line(MARKER_OK, "Источник", _resolve_chat_title(task, reminder)),
                    f"Контекст: {truncate_text(task.summary, limit=160) or 'нет краткого контекста'}",
                    "",
                ]
            )
        return "\n".join(lines).rstrip()

    def format_reminders(self, reminders: list[Reminder]) -> str:
        if not reminders:
            return "\n".join(
                [
                    "Astra AFT / Reminders",
                    "",
                    *state_shell_lines(
                        marker=MARKER_OFF,
                        status="Активных напоминаний нет",
                        meaning="Подтверждённых будущих напоминаний пока нет.",
                        next_step="/reminders_scan 24h",
                    ),
                ]
            )

        lines = ["Astra AFT / Reminders", "", "Детали"]
        for index, reminder in enumerate(reminders[:10], start=1):
            task = reminder.task
            lines.extend(
                [
                    f"{index}. {task.title if task is not None else 'Без задачи'}",
                    format_status_line(MARKER_OK, "Сработает", format_utc(reminder.remind_at)),
                    format_status_line(MARKER_OK, "Статус", reminder.status),
                    format_status_line(MARKER_OK, "Источник", _resolve_chat_title(task, reminder)),
                    format_status_line(MARKER_OK if task is not None and not task.needs_user_confirmation else MARKER_WARN, "Подтверждено", "да" if task is not None and not task.needs_user_confirmation else "нет"),
                    "",
                ]
            )
        return "\n".join(lines).rstrip()

    def format_action_result(self, result: ReminderActionResult) -> str:
        task = result.task
        reminder = result.reminder
        action_title = {
            "approve": "Кандидат одобрен",
            "reject": "Кандидат отклонён",
            "postpone": "Кандидат подтверждён с переносом",
            "already_processed": "Кандидат уже обработан",
        }.get(result.action, "Состояние кандидата обновлено.")
        lines = [
            "Astra AFT / Reminders / Action",
            "",
            *state_shell_lines(
                marker=MARKER_OK,
                status=action_title,
                meaning=f"Задача: {task.title}.",
                next_step="/reminders",
            ),
            "",
            "Детали",
            format_status_line(MARKER_OK, "Статус задачи", task.status),
            format_status_line(MARKER_OK, "Reminder", format_utc(reminder.remind_at)),
            format_status_line(MARKER_OK, "Статус reminder", reminder.status),
            format_status_line(MARKER_OK, "Источник", _resolve_chat_title(task, reminder)),
        ]
        if result.action == "postpone" and result.original_remind_at is not None:
            lines.append(format_status_line(MARKER_OK, "Было", format_utc(result.original_remind_at)))
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
                "Astra AFT / Reminders / Delivery",
                "",
                "Сводка",
                format_status_line(MARKER_OK, "Задача", title),
                format_status_line(MARKER_OK, "Чат", chat_title),
                format_status_line(MARKER_OK, "Связано с", source_sender),
                "",
                "Контекст",
                context or "Краткий контекст не сохранён.",
                "",
                "Следующий шаг",
                f"{title.lower()} или перенести срок.",
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
