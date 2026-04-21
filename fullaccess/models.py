from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from config.settings import Settings


@dataclass(frozen=True, slots=True)
class FullAccessConfig:
    enabled: bool
    api_id: int | None
    api_hash: str | None
    session_path: Path
    phone: str | None
    requested_readonly: bool
    effective_readonly: bool
    sync_limit: int

    @classmethod
    def from_settings(cls, settings: Settings) -> FullAccessConfig:
        return cls(
            enabled=settings.fullaccess_enabled,
            api_id=settings.fullaccess_api_id,
            api_hash=settings.fullaccess_api_hash,
            session_path=settings.fullaccess_session_file,
            phone=settings.fullaccess_phone,
            requested_readonly=settings.fullaccess_readonly,
            effective_readonly=True,
            sync_limit=max(1, int(settings.fullaccess_sync_limit)),
        )

    @property
    def api_credentials_configured(self) -> bool:
        return self.api_id is not None and bool(self.api_hash)

    @property
    def phone_configured(self) -> bool:
        return bool(self.phone and self.phone.strip())


@dataclass(frozen=True, slots=True)
class PendingAuthState:
    phone: str
    phone_code_hash: str
    requested_at: datetime


@dataclass(frozen=True, slots=True)
class FullAccessStatusReport:
    enabled: bool
    api_credentials_configured: bool
    phone_configured: bool
    session_path: Path
    session_exists: bool
    authorized: bool
    telethon_available: bool
    requested_readonly: bool
    effective_readonly: bool
    sync_limit: int
    pending_login: bool
    synced_chat_count: int
    synced_message_count: int
    ready_for_manual_sync: bool
    reason: str


@dataclass(frozen=True, slots=True)
class FullAccessLoginResult:
    kind: str
    phone: str | None = None
    instructions: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class FullAccessLogoutResult:
    session_removed: bool
    pending_auth_cleared: bool


@dataclass(frozen=True, slots=True)
class FullAccessChatSummary:
    telegram_chat_id: int
    title: str
    chat_type: str
    username: str | None = None

    @property
    def reference(self) -> str:
        if self.username:
            return f"@{self.username}"
        return str(self.telegram_chat_id)


@dataclass(frozen=True, slots=True)
class FullAccessChatListResult:
    chats: tuple[FullAccessChatSummary, ...]
    truncated: bool
    returned_count: int


@dataclass(frozen=True, slots=True)
class FullAccessRemoteMessage:
    telegram_message_id: int
    sender_id: int | None
    sender_name: str | None
    direction: str
    sent_at: datetime
    raw_text: str
    normalized_text: str
    reply_to_telegram_message_id: int | None
    forward_info: dict[str, Any] | list[Any] | None
    has_media: bool
    media_type: str | None
    entities_json: list[dict[str, Any]] | dict[str, Any] | None
    source_type: str


@dataclass(frozen=True, slots=True)
class FullAccessSyncResult:
    chat: FullAccessChatSummary
    local_chat_id: int
    chat_created: bool
    scanned_count: int
    created_count: int
    updated_count: int
    skipped_count: int

