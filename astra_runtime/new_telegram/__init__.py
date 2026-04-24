"""Managed target Telegram runtime shell.

This package is intentionally separate from the legacy fullaccess/Telethon
contour. It owns only lifecycle, status and future auth/session contracts at
this stage.
"""

from astra_runtime.new_telegram.auth import (
    NEW_TELEGRAM_AUTH_SESSION_KEY,
    NewTelegramAuthActionError,
    NewTelegramAuthActionResult,
    NewTelegramAuthController,
    DatabaseNewTelegramAuthSessionStore,
    NewTelegramAuthSessionStore,
)
from astra_runtime.new_telegram.config import NewTelegramRuntimeConfig
from astra_runtime.new_telegram.history import NewTelegramMessageHistory
from astra_runtime.new_telegram.reply import NewTelegramReplyWorkspace
from astra_runtime.new_telegram.runtime import NewTelegramRuntimeService
from astra_runtime.new_telegram.send import NewTelegramMessageSender
from astra_runtime.new_telegram.transport import (
    NewTelegramAccount,
    NewTelegramAuthClientError,
    NewTelegramChatSummary,
    NewTelegramDialogMessage,
    NewTelegramDialogSummary,
    NewTelegramRemoteMessage,
    NewTelegramSendResult,
    NewTelegramPasswordRequiredError,
    build_new_telegram_auth_client,
    build_new_telegram_history_client,
    build_new_telegram_roster_client,
    build_new_telegram_send_client,
    close_managed_new_telegram_clients,
    delete_session_file,
    telethon_is_available,
)

__all__ = [
    "DatabaseNewTelegramAuthSessionStore",
    "NEW_TELEGRAM_AUTH_SESSION_KEY",
    "NewTelegramAccount",
    "NewTelegramAuthActionError",
    "NewTelegramAuthActionResult",
    "NewTelegramAuthClientError",
    "NewTelegramAuthController",
    "NewTelegramAuthSessionStore",
    "NewTelegramChatSummary",
    "NewTelegramRuntimeConfig",
    "NewTelegramRuntimeService",
    "NewTelegramDialogMessage",
    "NewTelegramDialogSummary",
    "NewTelegramMessageHistory",
    "NewTelegramMessageSender",
    "NewTelegramPasswordRequiredError",
    "NewTelegramReplyWorkspace",
    "NewTelegramRemoteMessage",
    "NewTelegramSendResult",
    "build_new_telegram_auth_client",
    "build_new_telegram_history_client",
    "build_new_telegram_roster_client",
    "build_new_telegram_send_client",
    "close_managed_new_telegram_clients",
    "delete_session_file",
    "telethon_is_available",
]
