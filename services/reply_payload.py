from __future__ import annotations

from typing import Any


STAGED_SEND_DISABLED_REASON = (
    "Send-path на этом этапе остаётся выключенным. Сначала проверь варианты и черновик."
)


def decorate_reply_payload(
    payload: dict[str, Any],
    *,
    send_enabled: bool = False,
    mark_sent_enabled: bool = True,
    disabled_reason: str | None = None,
) -> dict[str, Any]:
    payload["actions"] = {
        "copy": True,
        "refresh": True,
        "pasteToTelegram": False,
        "send": send_enabled,
        "markSent": mark_sent_enabled,
        "variants": {
            "primary": True,
            "short": True,
            "soft": True,
            "owner_style": True,
            "style": True,
        },
        "disabledReason": disabled_reason or (None if send_enabled else STAGED_SEND_DISABLED_REASON),
    }
    return payload


def build_reply_context_payload(
    *,
    reply_payload: dict[str, Any],
    message_payloads: list[dict[str, Any]],
    source_backend: str,
) -> dict[str, Any]:
    suggestion = reply_payload.get("suggestion") if isinstance(reply_payload.get("suggestion"), dict) else None
    if suggestion is None:
        return {
            "available": False,
            "sourceBackend": source_backend,
            "focusLabel": None,
            "focusReason": reply_payload.get("errorMessage"),
            "replyOpportunityMode": None,
            "replyOpportunityReason": None,
            "sourceMessageKey": None,
            "sourceRuntimeMessageId": None,
            "sourceLocalMessageId": None,
            "sourceSenderName": reply_payload.get("sourceSenderName"),
            "sourceMessagePreview": reply_payload.get("sourceMessagePreview"),
            "sourceSentAt": None,
            "draftScopeBasis": None,
            "draftScopeKey": None,
        }

    trigger = suggestion.get("trigger") if isinstance(suggestion.get("trigger"), dict) else {}
    focus = suggestion.get("focus") if isinstance(suggestion.get("focus"), dict) else {}
    opportunity = suggestion.get("opportunity") if isinstance(suggestion.get("opportunity"), dict) else {}

    source_message_key = _pick_string(trigger.get("messageKey"))
    source_runtime_message_id = _pick_number(trigger.get("runtimeMessageId"))
    source_local_message_id = _pick_number(trigger.get("localMessageId"))
    source_message = next(
        (
            message
            for message in message_payloads
            if (
                source_message_key is not None
                and message.get("messageKey") == source_message_key
            )
            or (
                source_local_message_id is not None
                and message.get("localMessageId") == source_local_message_id
            )
            or (
                source_runtime_message_id is not None
                and message.get("runtimeMessageId") == source_runtime_message_id
            )
        ),
        None,
    )
    source_message_preview = (
        _pick_string(trigger.get("preview"))
        or reply_payload.get("sourceMessagePreview")
        or suggestion.get("sourceMessagePreview")
        or (source_message.get("preview") if source_message is not None else None)
    )
    source_sender_name = (
        _pick_string(trigger.get("senderName"))
        or reply_payload.get("sourceSenderName")
        or (source_message.get("senderName") if source_message is not None else None)
    )
    draft_scope_basis = {
        "sourceMessageKey": source_message_key or (source_message.get("messageKey") if source_message is not None else None),
        "sourceMessageId": source_local_message_id,
        "runtimeMessageId": source_runtime_message_id or (source_message.get("runtimeMessageId") if source_message is not None else None),
        "focusLabel": _pick_string(focus.get("label")) or suggestion.get("focusLabel"),
        "sourceMessagePreview": source_message_preview,
        "replyOpportunityMode": _pick_string(opportunity.get("mode")) or suggestion.get("replyOpportunityMode"),
    }
    return {
        "available": True,
        "sourceBackend": source_backend,
        "focusLabel": draft_scope_basis["focusLabel"],
        "focusReason": _pick_string(focus.get("reason")) or suggestion.get("focusReason"),
        "replyOpportunityMode": draft_scope_basis["replyOpportunityMode"],
        "replyOpportunityReason": _pick_string(opportunity.get("reason")) or suggestion.get("replyOpportunityReason"),
        "sourceMessageKey": draft_scope_basis["sourceMessageKey"],
        "sourceRuntimeMessageId": draft_scope_basis["runtimeMessageId"],
        "sourceLocalMessageId": draft_scope_basis["sourceMessageId"],
        "sourceSenderName": source_sender_name,
        "sourceMessagePreview": source_message_preview,
        "sourceSentAt": _pick_string(trigger.get("sentAt")) or (source_message.get("sentAt") if source_message is not None else None),
        "draftScopeBasis": draft_scope_basis,
        "draftScopeKey": "::".join(
            [
                str(draft_scope_basis["sourceMessageKey"] or draft_scope_basis["sourceMessageId"] or "none"),
                str(draft_scope_basis["focusLabel"] or "none"),
                str(draft_scope_basis["replyOpportunityMode"] or "none"),
                str(draft_scope_basis["sourceMessagePreview"] or "none"),
            ]
        ),
    }


def _pick_string(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value
    return None


def _pick_number(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return None
