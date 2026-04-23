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
from astra_runtime.new_telegram.runtime import NewTelegramRuntimeService
from astra_runtime.new_telegram.transport import (
    NewTelegramAccount,
    NewTelegramAuthClientError,
    NewTelegramPasswordRequiredError,
    build_new_telegram_auth_client,
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
    "NewTelegramRuntimeConfig",
    "NewTelegramRuntimeService",
    "NewTelegramPasswordRequiredError",
    "build_new_telegram_auth_client",
    "delete_session_file",
    "telethon_is_available",
]
