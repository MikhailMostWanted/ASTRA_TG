from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class ReplyWorkspaceChat:
    id: int
    telegram_chat_id: int
    title: str
    handle: str | None
    type: str
    is_enabled: bool = False
    category: str | None = None
    summary_schedule: str | None = None
    reply_assist_enabled: bool = False
    auto_reply_mode: str | None = None
    exclude_from_memory: bool = False
    exclude_from_digest: bool = False


@dataclass(frozen=True, slots=True)
class ReplyWorkspaceMessage:
    id: int
    local_message_id: int | None
    runtime_message_id: int
    message_key: str | None
    chat_id: int
    direction: str
    source_adapter: str | None
    source_type: str | None
    sender_id: int | None
    sender_name: str | None
    sent_at: datetime | None
    raw_text: str
    normalized_text: str
    reply_to_message_id: int | None
    reply_to_local_message_id: int | None
    reply_to_runtime_message_id: int | None
    has_media: bool = False
    media_type: str | None = None
