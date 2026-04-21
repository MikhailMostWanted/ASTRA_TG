from __future__ import annotations

from dataclasses import dataclass

from fullaccess.models import (
    FullAccessChatListResult,
    FullAccessLoginResult,
    FullAccessLogoutResult,
    FullAccessStatusReport,
    FullAccessSyncResult,
)
from services.render_cards import (
    MARKER_EXP,
    MARKER_OFF,
    MARKER_OK,
    MARKER_WARN,
    format_status_line,
    state_shell_lines,
)


@dataclass(slots=True, frozen=True)
class FullAccessFormatter:
    def format_status(self, report: FullAccessStatusReport) -> str:
        lines = [
            "Astra AFT / Full-access",
            "",
            "Сводка",
            (
                f"{MARKER_EXP if report.enabled else MARKER_OFF} Experimental слой: "
                f"{'включён' if report.enabled else 'выключен'}"
            ),
            f"Ручной sync: {'да' if report.ready_for_manual_sync else 'нет'}",
            "",
            "Детали",
            format_status_line(
                _marker(report.enabled, report.api_credentials_configured),
                "api_id/api_hash",
                "настроены" if report.api_credentials_configured else "не настроены",
            ),
            format_status_line(
                _marker(report.enabled, report.phone_configured),
                "Телефон",
                "задан" if report.phone_configured else "не задан",
            ),
            format_status_line(
                _marker(report.enabled, report.session_exists),
                "Session",
                "найдена" if report.session_exists else "не найдена",
            ),
            format_status_line(
                _marker(report.enabled, report.authorized),
                "Авторизация",
                "да" if report.authorized else "нет",
            ),
            format_status_line(
                _marker(report.enabled, report.effective_readonly),
                "Read-only",
                "активен" if report.effective_readonly else "не активен",
            ),
            format_status_line(MARKER_OK, "Sync limit", str(report.sync_limit)),
            format_status_line(
                MARKER_OK if report.synced_chat_count else MARKER_OFF,
                "Синхронизировано чатов",
                str(report.synced_chat_count),
            ),
            format_status_line(
                MARKER_OK if report.synced_message_count else MARKER_OFF,
                "Синхронизировано сообщений",
                str(report.synced_message_count),
            ),
            format_status_line(
                MARKER_OK if report.ready_for_manual_sync else MARKER_WARN if report.enabled else MARKER_OFF,
                "Причина",
                report.reason,
            ),
            "",
            "Следующий шаг",
            _next_step(report),
        ]
        return "\n".join(lines)

    def format_login(self, result: FullAccessLoginResult) -> str:
        headers = {
            "already_authorized": "Пользовательская session уже авторизована.",
            "code_requested": "Код входа Telegram запрошен.",
            "authorized": "Пользовательская session авторизована.",
            "password_required": "Telegram запросил пароль 2FA.",
        }
        marker = (
            MARKER_OK
            if result.kind in {"already_authorized", "authorized"}
            else MARKER_WARN
            if result.kind == "password_required"
            else MARKER_EXP
        )
        lines = [
            "Astra AFT / Full-access / Login",
            "",
            *state_shell_lines(
                marker=marker,
                status=headers.get(result.kind, "Операция завершена.").rstrip("."),
                meaning="Авторизация нужна только для ручного read-only sync.",
                next_step="Следуй инструкции ниже." if result.instructions else "/fullaccess_status",
            ),
        ]
        if result.phone:
            lines.extend(
                ["", "Детали", format_status_line(MARKER_OK, "Телефон", result.phone)]
            )
        if result.instructions:
            lines.extend(["", "Инструкция", *result.instructions])
        return "\n".join(lines)

    def format_logout(self, result: FullAccessLogoutResult) -> str:
        return "\n".join(
            [
                "Astra AFT / Full-access / Logout",
                "",
                *state_shell_lines(
                    marker=MARKER_OK,
                    status="Локальный logout завершён",
                    meaning="User-session очищена только локально.",
                    next_step="/fullaccess_status",
                ),
                "",
                "Детали",
                format_status_line(
                    MARKER_OK if result.session_removed else MARKER_OFF,
                    "Session файл удалён",
                    "да" if result.session_removed else "нет",
                ),
                format_status_line(
                    MARKER_OK if result.pending_auth_cleared else MARKER_OFF,
                    "Pending auth очищен",
                    "да" if result.pending_auth_cleared else "нет",
                ),
            ]
        )

    def format_chat_list(self, result: FullAccessChatListResult) -> str:
        if not result.chats:
            return "\n".join(
                [
                    "Astra AFT / Full-access / Чаты",
                    "",
                    *state_shell_lines(
                        marker=MARKER_OFF,
                        status="Список чатов пуст",
                        meaning="Авторизация есть, но доступных user-чатов не найдено.",
                        next_step="/fullaccess_status",
                    ),
                ]
            )

        lines = [
            "Astra AFT / Full-access / Чаты",
            "",
            "Сводка",
            f"Показано чатов: {len(result.chats)}",
            "",
            "Детали",
        ]
        for index, chat in enumerate(result.chats, start=1):
            parts = [f"{index}. {chat.title}", str(chat.telegram_chat_id), chat.chat_type]
            if chat.username:
                parts.append(f"@{chat.username}")
            lines.append(" | ".join(parts))

        if result.truncated:
            lines.extend(
                [
                    "",
                    f"{MARKER_WARN} Список урезан до первых чатов, без массового импорта.",
                ]
            )

        return "\n".join(lines)

    def format_sync_result(self, result: FullAccessSyncResult) -> str:
        return "\n".join(
            [
                "Astra AFT / Full-access / Sync",
                "",
                *state_shell_lines(
                    marker=MARKER_OK,
                    status="Ручной sync завершён",
                    meaning=f"Сохранено новых сообщений: {result.created_count}.",
                    next_step="Открой Sources, Memory или Reply.",
                ),
                "",
                "Детали",
                format_status_line(MARKER_OK, "Чат", result.chat.title),
                format_status_line(MARKER_OK, "ID Telegram", str(result.chat.telegram_chat_id)),
                format_status_line(MARKER_OK, "Локальный chat_id", str(result.local_chat_id)),
                format_status_line(
                    MARKER_OK if result.chat_created else MARKER_OFF,
                    "Новый источник",
                    "да" if result.chat_created else "нет",
                ),
                format_status_line(MARKER_OK, "Просмотрено сообщений", str(result.scanned_count)),
                format_status_line(
                    MARKER_OK if result.created_count else MARKER_OFF,
                    "Новых сохранено",
                    str(result.created_count),
                ),
                format_status_line(
                    MARKER_OK if result.updated_count else MARKER_OFF,
                    "Обновлено",
                    str(result.updated_count),
                ),
                format_status_line(
                    MARKER_OK if result.skipped_count else MARKER_OFF,
                    "Пропущено",
                    str(result.skipped_count),
                ),
            ]
        )


def _marker(enabled: bool, ready: bool) -> str:
    if ready:
        return MARKER_OK
    return MARKER_WARN if enabled else MARKER_OFF


def _next_step(report: FullAccessStatusReport) -> str:
    if not report.enabled:
        return "Core-путь работает и без full-access."
    if not report.authorized:
        return "/fullaccess_login"
    if report.ready_for_manual_sync:
        return "/fullaccess_chats"
    return "/fullaccess_status"
