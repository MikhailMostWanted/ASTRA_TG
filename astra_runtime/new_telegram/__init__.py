"""Managed target Telegram runtime shell.

This package is intentionally separate from the legacy fullaccess/Telethon
contour. It owns only lifecycle, status and future auth/session contracts at
this stage.
"""

from astra_runtime.new_telegram.auth import (
    NEW_TELEGRAM_AUTH_SESSION_KEY,
    DatabaseNewTelegramAuthSessionStore,
    NewTelegramAuthSessionStore,
)
from astra_runtime.new_telegram.config import NewTelegramRuntimeConfig
from astra_runtime.new_telegram.runtime import NewTelegramRuntimeService

__all__ = [
    "DatabaseNewTelegramAuthSessionStore",
    "NEW_TELEGRAM_AUTH_SESSION_KEY",
    "NewTelegramAuthSessionStore",
    "NewTelegramRuntimeConfig",
    "NewTelegramRuntimeService",
]
