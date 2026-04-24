from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import re
from typing import Any

from astra_runtime.chat_identity import ChatIdentity
from astra_runtime.message_identity import MessageIdentity, build_message_key
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
    asset_session_files: tuple[Path, ...] | None = None,
) -> dict[str, Any]:
    identity = ChatIdentity(
        runtime_chat_id=chat.telegram_chat_id,
        local_chat_id=chat.id,
    )
    last_source_adapter = last_message.source_adapter if last_message is not None else None
    if chat.category == "fullaccess" or last_source_adapter == "fullaccess":
        sync_status = "fullaccess"
    elif message_count > 0:
        sync_status = "local"
    else:
        sync_status = "empty"
    avatar_url = _build_avatar_url(
        asset_session_files or ((session_file,) if session_file is not None else ()),
        chat.telegram_chat_id,
    )
    roster_last_activity_at = serialize_datetime(last_message.sent_at if last_message is not None else None)
    roster_last_preview = message_preview(
        last_message.raw_text if last_message is not None else None,
        fallback="Сообщений пока нет",
    )

    return {
        **identity.to_payload(),
        "identity": identity.to_payload(),
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
        "lastMessageKey": (
            _build_message_identity(
                runtime_chat_id=chat.telegram_chat_id,
                runtime_message_id=last_message.telegram_message_id,
                local_message_id=last_message.id,
            ).message_key
            if last_message is not None
            else None
        ),
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
        "avatarUrl": avatar_url,
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
        "rosterSource": "legacy",
        "rosterLastActivityAt": roster_last_activity_at,
        "rosterLastMessageKey": (
            _build_message_identity(
                runtime_chat_id=chat.telegram_chat_id,
                runtime_message_id=last_message.telegram_message_id,
                local_message_id=last_message.id,
            ).message_key
            if last_message is not None
            else None
        ),
        "rosterLastMessagePreview": roster_last_preview,
        "rosterLastDirection": last_message.direction if last_message is not None else None,
        "rosterLastSenderName": last_message.sender_name if last_message is not None else None,
        "rosterFreshness": build_roster_freshness(last_message.sent_at if last_message is not None else None),
        "unreadCount": 0,
        "unreadMentionCount": 0,
        "pinned": False,
        "muted": False,
        "archived": False,
        "assetHints": {
            "avatarCached": avatar_url is not None,
            "avatarSource": "cache" if avatar_url is not None else None,
        },
    }


def serialize_message(
    message: Message,
    *,
    session_file: Path | None = None,
    telegram_chat_id: int | None = None,
) -> dict[str, Any]:
    runtime_chat_id = telegram_chat_id if telegram_chat_id is not None else message.chat.telegram_chat_id
    identity = _build_message_identity(
        runtime_chat_id=runtime_chat_id,
        runtime_message_id=message.telegram_message_id,
        local_message_id=message.id,
    )
    reply_to_runtime_message_id = None
    if "reply_to_message" in message.__dict__:
        reply_to_message = message.__dict__.get("reply_to_message")
        if isinstance(reply_to_message, Message):
            reply_to_runtime_message_id = reply_to_message.telegram_message_id

    return {
        "id": message.id,
        **identity.to_payload(),
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
        "replyToLocalMessageId": message.reply_to_message_id,
        "replyToRuntimeMessageId": reply_to_runtime_message_id,
        "replyToMessageKey": (
            build_message_key(runtime_chat_id, reply_to_runtime_message_id)
            if reply_to_runtime_message_id is not None
            else None
        ),
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
        "replyOpportunityMode": suggestion.reply_opportunity_mode,
        "replyOpportunityReason": suggestion.reply_opportunity_reason,
        "replyRecommended": suggestion.reply_recommended,
        "fewShotFound": suggestion.few_shot_found,
        "fewShotMatchCount": suggestion.few_shot_match_count,
        "fewShotNotes": list(suggestion.few_shot_notes),
        "sourceMessageKey": suggestion.source_message_key,
        "sourceLocalMessageId": suggestion.source_local_message_id,
        "sourceRuntimeMessageId": suggestion.source_runtime_message_id,
        "sourceBackend": suggestion.source_backend,
        "focusScore": suggestion.focus_score,
        "selectionMessageCount": suggestion.selection_message_count,
        "fewShotStrategyBias": suggestion.few_shot_strategy_bias,
        "fewShotLengthHint": suggestion.few_shot_length_hint,
        "fewShotRhythmHint": suggestion.few_shot_rhythm_hint,
        "fewShotDominantTopicHint": suggestion.few_shot_dominant_topic_hint,
        "fewShotMessageCountHint": suggestion.few_shot_message_count_hint,
        "fewShotStyleMarkers": list(suggestion.few_shot_style_markers),
        "alternativeAction": suggestion.alternative_action,
        "trigger": _serialize_reply_trigger(suggestion, result),
        "focus": _serialize_reply_focus(suggestion),
        "opportunity": _serialize_reply_opportunity(suggestion),
        "retrieval": _serialize_reply_retrieval(suggestion),
        "style": _serialize_reply_style(suggestion),
        "fallback": {
            "code": suggestion.fallback_code,
            "reason": suggestion.fallback_reason,
        },
        "llmRefineRequested": suggestion.llm_refine_requested,
        "llmRefineApplied": suggestion.llm_refine_applied,
        "llmRefineProvider": suggestion.llm_refine_provider,
        "llmRefineNotes": list(suggestion.llm_refine_notes),
        "llmRefineGuardrailFlags": list(suggestion.llm_refine_guardrail_flags),
        "llmStatus": _serialize_reply_llm_status(suggestion),
        "llmDebug": {
            "mode": _serialize_reply_llm_status(suggestion)["mode"],
            "baselineMessages": list(suggestion.llm_refine_baseline_messages),
            "baselineText": "\n".join(suggestion.llm_refine_baseline_messages).strip() or None,
            "rawCandidate": suggestion.llm_refine_raw_candidate,
            "decisionReason": _serialize_llm_decision_reason(suggestion.llm_refine_decision_reason),
        },
        "variants": _build_reply_variants(suggestion),
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
        "readyForManualSend": report.ready_for_manual_send,
        "reason": report.reason,
    }


def _build_message_identity(
    *,
    runtime_chat_id: int,
    runtime_message_id: int,
    local_message_id: int | None,
) -> MessageIdentity:
    return MessageIdentity(
        runtime_chat_id=runtime_chat_id,
        runtime_message_id=runtime_message_id,
        local_message_id=local_message_id,
    )


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


def _build_avatar_url(
    session_file: Path | tuple[Path, ...] | None,
    telegram_chat_id: int,
) -> str | None:
    if isinstance(session_file, tuple):
        session_files = session_file
    elif session_file is None:
        session_files = ()
    else:
        session_files = (session_file,)

    if telegram_chat_id == 0:
        return None
    for candidate in session_files:
        cached = find_cached_variant(avatar_base_path(candidate, telegram_chat_id))
        if cached is None:
            continue
        version = int(cached.stat().st_mtime)
        return f"/api/media/avatars/{telegram_chat_id}?v={version}"
    return None


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


def build_roster_freshness(last_activity_at: datetime | None) -> dict[str, Any]:
    if last_activity_at is None:
        return {
            "mode": "empty",
            "label": "без активности",
            "lastActivityAt": None,
        }

    effective = last_activity_at
    if effective.tzinfo is None:
        effective = effective.replace(tzinfo=timezone.utc)
    else:
        effective = effective.astimezone(timezone.utc)

    age_seconds = max(0.0, (datetime.now(timezone.utc) - effective).total_seconds())
    if age_seconds <= 12 * 60 * 60:
        mode = "fresh"
        label = "свежее"
    elif age_seconds <= 3 * 24 * 60 * 60:
        mode = "recent"
        label = "недавнее"
    else:
        mode = "stale"
        label = "давно без апдейта"
    return {
        "mode": mode,
        "label": label,
        "lastActivityAt": serialize_datetime(effective),
    }


def _serialize_reply_llm_status(suggestion) -> dict[str, Any]:
    if suggestion.llm_refine_applied:
        return {
            "mode": "llm_refine",
            "label": "LLM-улучшение",
            "provider": suggestion.llm_refine_provider,
            "detail": (
                suggestion.llm_refine_notes[0]
                if suggestion.llm_refine_notes
                else "Финальный текст был мягко улучшен моделью."
            ),
        }
    if (
        suggestion.llm_refine_requested
        and suggestion.llm_refine_decision_reason is not None
        and suggestion.llm_refine_decision_reason.source == "guardrails"
    ):
        return {
            "mode": "rejected_by_guardrails",
            "label": "Отклонён guardrails",
            "provider": suggestion.llm_refine_provider,
            "detail": suggestion.llm_refine_decision_reason.detail,
        }
    if suggestion.llm_refine_requested:
        return {
            "mode": "fallback",
            "label": "Фоллбек",
            "provider": suggestion.llm_refine_provider,
            "detail": (
                suggestion.llm_refine_decision_reason.detail
                if suggestion.llm_refine_decision_reason is not None
                else suggestion.llm_refine_notes[0]
                if suggestion.llm_refine_notes
                else "Модель не дала пригодный результат, оставлен deterministic baseline."
            ),
        }
    return {
        "mode": "deterministic",
        "label": "Детерминированный",
        "provider": None,
        "detail": "Ответ собран локальным deterministic pipeline без внешнего refine.",
    }


def _serialize_llm_decision_reason(value) -> dict[str, Any] | None:
    if value is None:
        return None
    return {
        "source": value.source,
        "code": value.code,
        "summary": value.summary,
        "detail": value.detail,
        "flags": list(value.flags),
    }


def _build_reply_variants(suggestion) -> list[dict[str, Any]]:
    if getattr(suggestion, "variants", ()):
        return [
            {
                "id": variant.id,
                "label": variant.label,
                "description": variant.description,
                "text": variant.text,
            }
            for variant in suggestion.variants
            if getattr(variant, "text", "").strip()
        ]

    primary_text = suggestion.reply_text.strip() if suggestion.reply_text else ""
    styled_text = "\n".join(item for item in suggestion.reply_messages if item.strip()).strip()
    baseline_text = (suggestion.base_reply_text or "").strip()
    concise_text = _build_concise_variant_text(suggestion)

    candidates = [
        ("primary", "Основной", "Рекомендуемый вариант для отправки.", primary_text),
        ("concise", "Короче", "Более прямой и короткий ответ.", concise_text),
        (
            "baseline",
            "Базовый",
            "Более спокойный deterministic вариант без лишней полировки.",
            styled_text or baseline_text,
        ),
    ]

    variants: list[dict[str, Any]] = []
    seen_texts: set[str] = set()
    for variant_id, label, description, text in candidates:
        cleaned = text.strip()
        if not cleaned or cleaned in seen_texts:
            continue
        variants.append(
            {
                "id": variant_id,
                "label": label,
                "description": description,
                "text": cleaned,
            }
        )
        seen_texts.add(cleaned)
        if len(variants) >= 3:
            break
    return variants


def _build_concise_variant_text(suggestion) -> str:
    final_messages = tuple(item.strip() for item in suggestion.final_reply_messages if item.strip())
    if len(final_messages) >= 2:
        return final_messages[0]

    full_text = suggestion.reply_text.strip() if suggestion.reply_text else ""
    if not full_text:
        return ""

    sentences = [
        part.strip()
        for part in re.split(r"(?<=[.!?])\s+", full_text)
        if part.strip()
    ]
    if len(sentences) >= 2:
        return sentences[0]
    return full_text


def _serialize_reply_trigger(suggestion, result) -> dict[str, Any]:
    return {
        "messageKey": suggestion.source_message_key,
        "localMessageId": suggestion.source_local_message_id,
        "runtimeMessageId": suggestion.source_runtime_message_id,
        "senderName": result.source_sender_name,
        "preview": suggestion.source_message_preview,
        "sentAt": None,
        "backend": suggestion.source_backend,
    }


def _serialize_reply_focus(suggestion) -> dict[str, Any]:
    return {
        "label": suggestion.focus_label,
        "reason": suggestion.focus_reason,
        "score": suggestion.focus_score,
        "selectionMessageCount": suggestion.selection_message_count,
    }


def _serialize_reply_opportunity(suggestion) -> dict[str, Any]:
    return {
        "mode": suggestion.reply_opportunity_mode,
        "reason": suggestion.reply_opportunity_reason,
        "replyRecommended": suggestion.reply_recommended,
    }


def _serialize_reply_retrieval(suggestion) -> dict[str, Any]:
    return {
        "used": suggestion.few_shot_found,
        "matchCount": suggestion.few_shot_match_count,
        "strategyBias": suggestion.few_shot_strategy_bias,
        "lengthHint": suggestion.few_shot_length_hint,
        "rhythmHint": suggestion.few_shot_rhythm_hint,
        "dominantTopicHint": suggestion.few_shot_dominant_topic_hint,
        "messageCountHint": suggestion.few_shot_message_count_hint,
        "styleMarkers": list(suggestion.few_shot_style_markers),
        "notes": list(suggestion.few_shot_notes),
        "hits": [
            {
                "id": match.id,
                "chatId": match.chat_id,
                "chatTitle": match.chat_title,
                "inboundText": match.inbound_text,
                "outboundText": match.outbound_text,
                "exampleType": match.example_type,
                "sourcePersonKey": match.source_person_key,
                "qualityScore": match.quality_score,
                "score": match.score,
                "createdAt": serialize_datetime(match.created_at),
                "reasons": list(match.reasons),
            }
            for match in suggestion.few_shot_matches
        ],
    }


def _serialize_reply_style(suggestion) -> dict[str, Any]:
    return {
        "profileKey": suggestion.style_profile_key,
        "source": suggestion.style_source,
        "sourceReason": suggestion.style_source_reason,
        "notes": list(suggestion.style_notes),
        "personaApplied": suggestion.persona_applied,
        "personaNotes": list(suggestion.persona_notes),
    }
