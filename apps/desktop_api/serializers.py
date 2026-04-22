from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from apps.cli.processes import ProcessState
from fullaccess.cache import avatar_base_path, find_cached_variant, media_preview_base_path
from fullaccess.models import FullAccessChatSummary, FullAccessStatusReport, FullAccessSyncResult
from models import Chat, ChatMemory, Digest, DigestItem, Message, Reminder, Task
from services.reply_models import ReplyResult


def serialize_datetime(value: datetime | str | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc).isoformat()
    return value.astimezone(timezone.utc).isoformat()


def message_preview(text: str | None, *, fallback: str = "Без текста") -> str:
    cleaned = (text or "").strip()
    if not cleaned:
        return fallback
    compact = " ".join(cleaned.split())
    if len(compact) <= 140:
        return compact
    return f"{compact[:137].rstrip()}..."


def build_chat_reference(chat: Chat) -> str:
    if chat.handle:
        return f"@{chat.handle}"
    return str(chat.telegram_chat_id)


def serialize_process_state(state: ProcessState) -> dict[str, Any]:
    if state.running:
        status = "online"
    elif state.pid is not None and state.stale_pid_file:
        status = "warning"
    else:
        status = "offline"

    return {
        "component": state.component,
        "status": status,
        "running": state.running,
        "managed": state.managed,
        "stalePidFile": state.stale_pid_file,
        "pid": state.pid,
        "command": state.command,
        "detail": state.detail,
        "pidPath": str(state.pid_path),
        "logPath": str(state.log_path),
    }


def serialize_chat(
    chat: Chat,
    *,
    message_count: int,
    last_message: Message | None,
    memory: ChatMemory | None = None,
    is_digest_target: bool = False,
    session_file: Path | None = None,
) -> dict[str, Any]:
    last_source_adapter = last_message.source_adapter if last_message is not None else None
    if chat.category == "fullaccess" or last_source_adapter == "fullaccess":
        sync_status = "fullaccess"
    elif message_count > 0:
        sync_status = "local"
    else:
        sync_status = "empty"

    return {
        "id": chat.id,
        "telegramChatId": chat.telegram_chat_id,
        "reference": build_chat_reference(chat),
        "title": chat.title,
        "handle": chat.handle,
        "type": chat.type,
        "enabled": chat.is_enabled,
        "category": chat.category,
        "summarySchedule": chat.summary_schedule,
        "replyAssistEnabled": chat.reply_assist_enabled,
        "autoReplyMode": chat.auto_reply_mode,
        "excludeFromMemory": chat.exclude_from_memory,
        "excludeFromDigest": chat.exclude_from_digest,
        "isDigestTarget": is_digest_target,
        "messageCount": message_count,
        "lastMessageAt": serialize_datetime(last_message.sent_at if last_message is not None else None),
        "lastMessageId": last_message.id if last_message is not None else None,
        "lastTelegramMessageId": (
            last_message.telegram_message_id if last_message is not None else None
        ),
        "lastMessagePreview": message_preview(
            last_message.raw_text if last_message is not None else None,
            fallback="Сообщений пока нет",
        ),
        "lastDirection": last_message.direction if last_message is not None else None,
        "lastSourceAdapter": last_source_adapter,
        "lastSenderName": last_message.sender_name if last_message is not None else None,
        "avatarUrl": _build_avatar_url(session_file, chat.telegram_chat_id),
        "syncStatus": sync_status,
        "memory": (
            {
                "summaryShort": memory.chat_summary_short,
                "currentState": memory.current_state,
                "updatedAt": serialize_datetime(memory.updated_at),
                "pendingCount": len(memory.pending_tasks_json or []),
                "topics": list(memory.dominant_topics_json or []),
            }
            if memory is not None
            else None
        ),
        "favorite": False,
    }


def serialize_message(
    message: Message,
    *,
    session_file: Path | None = None,
    telegram_chat_id: int | None = None,
) -> dict[str, Any]:
    return {
        "id": message.id,
        "telegramMessageId": message.telegram_message_id,
        "chatId": message.chat_id,
        "direction": message.direction,
        "sourceAdapter": message.source_adapter,
        "sourceType": message.source_type,
        "senderId": message.sender_id,
        "senderName": message.sender_name,
        "sentAt": serialize_datetime(message.sent_at),
        "text": message.raw_text,
        "normalizedText": message.normalized_text,
        "replyToMessageId": message.reply_to_message_id,
        "hasMedia": message.has_media,
        "mediaType": message.media_type,
        "mediaPreviewUrl": _build_media_preview_url(
            session_file,
            telegram_chat_id=telegram_chat_id,
            telegram_message_id=message.telegram_message_id,
        ),
        "forwardInfo": message.forward_info,
        "entities": message.entities_json,
        "preview": message_preview(message.raw_text),
    }


def serialize_reply_result(result: ReplyResult) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "kind": result.kind,
        "chatId": result.chat_id,
        "chatTitle": result.chat_title,
        "chatReference": result.chat_reference,
        "errorMessage": result.error_message,
        "sourceSenderName": result.source_sender_name,
        "sourceMessagePreview": result.source_message_preview,
    }
    suggestion = result.suggestion
    if suggestion is None:
        payload["suggestion"] = None
        return payload

    payload["suggestion"] = {
        "baseReplyText": suggestion.base_reply_text,
        "replyMessages": list(suggestion.reply_messages),
        "finalReplyMessages": list(suggestion.final_reply_messages),
        "replyText": suggestion.reply_text,
        "styleProfileKey": suggestion.style_profile_key,
        "styleSource": suggestion.style_source,
        "styleNotes": list(suggestion.style_notes),
        "personaApplied": suggestion.persona_applied,
        "personaNotes": list(suggestion.persona_notes),
        "guardrailFlags": list(suggestion.guardrail_flags),
        "reasonShort": suggestion.reason_short,
        "riskLabel": suggestion.risk_label,
        "confidence": suggestion.confidence,
        "strategy": suggestion.strategy,
        "sourceMessageId": suggestion.source_message_id,
        "chatId": suggestion.chat_id,
        "situation": suggestion.situation,
        "sourceMessagePreview": suggestion.source_message_preview,
        "focusLabel": suggestion.focus_label,
        "focusReason": suggestion.focus_reason,
        "fewShotFound": suggestion.few_shot_found,
        "fewShotMatchCount": suggestion.few_shot_match_count,
        "fewShotNotes": list(suggestion.few_shot_notes),
        "alternativeAction": suggestion.alternative_action,
        "llmRefineRequested": suggestion.llm_refine_requested,
        "llmRefineApplied": suggestion.llm_refine_applied,
        "llmRefineProvider": suggestion.llm_refine_provider,
        "llmRefineNotes": list(suggestion.llm_refine_notes),
        "llmRefineGuardrailFlags": list(suggestion.llm_refine_guardrail_flags),
    }
    return payload


def serialize_fullaccess_status(report: FullAccessStatusReport) -> dict[str, Any]:
    return {
        "enabled": report.enabled,
        "apiCredentialsConfigured": report.api_credentials_configured,
        "phoneConfigured": report.phone_configured,
        "sessionPath": str(report.session_path),
        "sessionExists": report.session_exists,
        "authorized": report.authorized,
        "telethonAvailable": report.telethon_available,
        "requestedReadonly": report.requested_readonly,
        "effectiveReadonly": report.effective_readonly,
        "syncLimit": report.sync_limit,
        "pendingLogin": report.pending_login,
        "syncedChatCount": report.synced_chat_count,
        "syncedMessageCount": report.synced_message_count,
        "readyForManualSync": report.ready_for_manual_sync,
        "reason": report.reason,
    }


def serialize_fullaccess_chat(
    chat: FullAccessChatSummary,
    *,
    session_file: Path | None = None,
) -> dict[str, Any]:
    return {
        "telegramChatId": chat.telegram_chat_id,
        "title": chat.title,
        "chatType": chat.chat_type,
        "username": chat.username,
        "reference": chat.reference,
        "avatarUrl": _build_avatar_url(session_file, chat.telegram_chat_id),
    }


def serialize_fullaccess_sync_result(
    result: FullAccessSyncResult,
    *,
    session_file: Path | None = None,
) -> dict[str, Any]:
    return {
        "chat": serialize_fullaccess_chat(result.chat, session_file=session_file),
        "localChatId": result.local_chat_id,
        "chatCreated": result.chat_created,
        "scannedCount": result.scanned_count,
        "createdCount": result.created_count,
        "updatedCount": result.updated_count,
        "skippedCount": result.skipped_count,
    }


def serialize_digest_item(item: DigestItem) -> dict[str, Any]:
    return {
        "id": item.id,
        "sourceChatId": item.source_chat_id,
        "sourceChatTitle": item.source_chat.title if item.source_chat is not None else None,
        "sourceMessageId": item.source_message_id,
        "title": item.title,
        "summary": item.summary,
        "link": item.link,
        "sortOrder": item.sort_order,
    }


def serialize_digest(digest: Digest) -> dict[str, Any]:
    return {
        "id": digest.id,
        "chatId": digest.chat_id,
        "windowStart": serialize_datetime(digest.window_start),
        "windowEnd": serialize_datetime(digest.window_end),
        "summaryShort": digest.summary_short,
        "summaryLong": digest.summary_long,
        "deliveredToChatId": digest.delivered_to_chat_id,
        "deliveredMessageId": digest.delivered_message_id,
        "createdAt": serialize_datetime(digest.created_at),
        "items": [serialize_digest_item(item) for item in digest.items],
    }


def serialize_task(task: Task) -> dict[str, Any]:
    source_preview = None
    if task.source_message is not None:
        source_preview = message_preview(task.source_message.raw_text)
    return {
        "id": task.id,
        "status": task.status,
        "title": task.title,
        "summary": task.summary,
        "dueAt": serialize_datetime(task.due_at),
        "suggestedRemindAt": serialize_datetime(task.suggested_remind_at),
        "confidence": task.confidence,
        "needsUserConfirmation": task.needs_user_confirmation,
        "sourceChatId": task.source_chat_id,
        "sourceChatTitle": task.source_chat.title if task.source_chat is not None else None,
        "sourceMessageId": task.source_message_id,
        "sourceMessagePreview": source_preview,
        "createdAt": serialize_datetime(task.created_at),
        "updatedAt": serialize_datetime(task.updated_at),
    }


def serialize_reminder(reminder: Reminder) -> dict[str, Any]:
    return {
        "id": reminder.id,
        "taskId": reminder.task_id,
        "status": reminder.status,
        "remindAt": serialize_datetime(reminder.remind_at),
        "lastNotificationAt": serialize_datetime(reminder.last_notification_at),
        "payload": reminder.payload_json,
        "task": serialize_task(reminder.task) if reminder.task is not None else None,
        "createdAt": serialize_datetime(reminder.created_at),
        "updatedAt": serialize_datetime(reminder.updated_at),
    }


def _build_avatar_url(session_file: Path | None, telegram_chat_id: int) -> str | None:
    if session_file is None or telegram_chat_id == 0:
        return None

    cached = find_cached_variant(avatar_base_path(session_file, telegram_chat_id))
    if cached is None:
        return None
    version = int(cached.stat().st_mtime)
    return f"/api/media/avatars/{telegram_chat_id}?v={version}"


def _build_media_preview_url(
    session_file: Path | None,
    *,
    telegram_chat_id: int | None,
    telegram_message_id: int | None,
) -> str | None:
    if session_file is None or telegram_chat_id is None or telegram_message_id is None:
        return None

    cached = find_cached_variant(
        media_preview_base_path(
            session_file,
            telegram_chat_id=telegram_chat_id,
            telegram_message_id=telegram_message_id,
        )
    )
    if cached is None:
        return None
    version = int(cached.stat().st_mtime)
    return (
        f"/api/media/messages/{telegram_chat_id}/{telegram_message_id}"
        f"?v={version}"
    )
