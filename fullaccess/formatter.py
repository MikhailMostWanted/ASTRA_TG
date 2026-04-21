from __future__ import annotations

from dataclasses import dataclass

from fullaccess.models import (
    FullAccessChatListResult,
    FullAccessLoginResult,
    FullAccessLogoutResult,
    FullAccessStatusReport,
    FullAccessSyncResult,
)


@dataclass(slots=True, frozen=True)
class FullAccessFormatter:
    def format_status(self, report: FullAccessStatusReport) -> str:
        lines = [
            "Experimental full-access",
            "",
            f"Слой: {'включен' if report.enabled else 'выключен'}",
            (
                "api_id/api_hash: настроены"
                if report.api_credentials_configured
                else "api_id/api_hash: не настроены"
            ),
            f"FULLACCESS_PHONE: {'задан' if report.phone_configured else 'не задан'}",
            f"Локальная session: {'найдена' if report.session_exists else 'не найдена'}",
            f"Авторизация: {'да' if report.authorized else 'нет'}",
            f"Read-only: {'активен' if report.effective_readonly else 'не активен'}",
            f"Sync limit: {report.sync_limit}",
            f"Синхронизировано чатов: {report.synced_chat_count}",
            f"Синхронизировано сообщений: {report.synced_message_count}",
            (
                "Готов к ручному sync: да"
                if report.ready_for_manual_sync
                else "Готов к ручному sync: нет"
            ),
            f"Причина: {report.reason}",
        ]
        return "\n".join(lines)

    def format_login(self, result: FullAccessLoginResult) -> str:
        headers = {
            "already_authorized": "Пользовательская session уже авторизована.",
            "code_requested": "Код входа Telegram запрошен.",
            "authorized": "Пользовательская session авторизована.",
            "password_required": "Telegram запросил пароль 2FA.",
        }
        lines = [headers.get(result.kind, "Операция завершена.")]
        if result.phone:
            lines.extend(["", f"Телефон: {result.phone}"])
        if result.instructions:
            lines.extend(["", *result.instructions])
        return "\n".join(lines)

    def format_logout(self, result: FullAccessLogoutResult) -> str:
        return "\n".join(
            [
                "Локальный full-access logout завершён.",
                "",
                f"Session файл удалён: {'да' if result.session_removed else 'нет'}",
                (
                    f"Pending auth очищен: {'да' if result.pending_auth_cleared else 'нет'}"
                ),
            ]
        )

    def format_chat_list(self, result: FullAccessChatListResult) -> str:
        if not result.chats:
            return "Авторизация есть, но список чатов пуст."

        lines = [
            "Доступные user-чаты full-access",
            "",
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
                    "Список урезан. Показываю только первые чаты, без массового импорта.",
                ]
            )

        return "\n".join(lines)

    def format_sync_result(self, result: FullAccessSyncResult) -> str:
        return "\n".join(
            [
                "Ручной full-access sync завершён.",
                "",
                f"Чат: {result.chat.title}",
                f"ID Telegram: {result.chat.telegram_chat_id}",
                f"Локальный chat_id: {result.local_chat_id}",
                f"Новый chat registry entry: {'да' if result.chat_created else 'нет'}",
                f"Просмотрено сообщений: {result.scanned_count}",
                f"Новых сохранено: {result.created_count}",
                f"Обновлено: {result.updated_count}",
                f"Пропущено: {result.skipped_count}",
            ]
        )
