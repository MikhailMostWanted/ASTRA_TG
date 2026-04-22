from __future__ import annotations

from dataclasses import dataclass

from fullaccess.copy import LOCAL_LOGIN_COMMAND
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
            "🧪 Full-access",
            "",
            "Экспериментальный read-only слой для ручной синхронизации.",
            (
                "Статус: авторизован."
                if report.authorized
                else "Статус: не авторизован."
            ),
            f"Сессия: {'есть' if report.session_exists else 'нет'}.",
            f"Ручная синхронизация: {'готова' if report.ready_for_manual_sync else 'пока не готова'}.",
            "",
            "Следующий шаг",
            _next_step(report),
            "",
            "Тех. детали",
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
                "Сессия",
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
            format_status_line(MARKER_OK, "Лимит синхронизации", str(report.sync_limit)),
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
        ]
        return "\n".join(lines)

    def format_login(self, result: FullAccessLoginResult) -> str:
        headers = {
            "already_authorized": "Локальный вход уже завершён.",
            "code_requested": "Код запрошен безопасно.",
            "authorized": "Локальный вход завершён.",
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
            "🧪 Локальный вход",
            "",
            f"{marker} {headers.get(result.kind, 'Операция завершена.').rstrip('.')}",
            "Код в бот отправлять не нужно.",
            "Авторизация нужна только для ручной read-only синхронизации.",
        ]
        if result.phone:
            lines.extend(
                ["", "Тех. детали", format_status_line(MARKER_OK, "Телефон", result.phone)]
            )
        if result.instructions:
            lines.extend(["", "Следующий шаг", f"Команда: {LOCAL_LOGIN_COMMAND}", "", *result.instructions])
        else:
            lines.extend(["", "Следующий шаг", "Вернись в бот и нажми «Обновить»."])
        return "\n".join(lines)

    def format_logout(self, result: FullAccessLogoutResult) -> str:
        return "\n".join(
            [
                "🧪 Full-access / Выход",
                "",
                *state_shell_lines(
                    marker=MARKER_OK,
                    status="Локальный logout завершён",
                    meaning="User-session очищена только локально.",
                    next_step="Открой Full-access и нажми «Обновить».",
                ),
                "",
                "Тех. детали",
                format_status_line(
                    MARKER_OK if result.session_removed else MARKER_OFF,
                    "Файл сессии удалён",
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
                    "🧪 Чаты для синхронизации",
                    "",
                    *state_shell_lines(
                        marker=MARKER_OFF,
                        status="Список чатов пуст",
                        meaning="Авторизация есть, но доступных user-чатов не найдено.",
                        next_step="Вернись в Full-access и нажми «Обновить».",
                    ),
                ]
            )

        lines = [
            "🧪 Чаты для синхронизации",
            "",
            f"Показано чатов: {len(result.chats)}.",
            "Выбери один чат для ручной синхронизации.",
            "",
            "Тех. детали",
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
                "🧪 Sync завершён",
                "",
                "История подтянута локально и безопасно.",
                f"Новых сообщений: {result.created_count}.",
                f"Чат: {result.chat.title}.",
                "",
                "Следующий шаг",
                "Открой Источники, Память или Ответы.",
                "",
                "Тех. детали",
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
        return "Основной путь работает и без full-access."
    if not report.authorized:
        return f"Войди локально через CLI: {LOCAL_LOGIN_COMMAND}"
    if report.ready_for_manual_sync:
        return "Открой список чатов и запусти ручную синхронизацию."
    return "Обнови статус после локального входа."
