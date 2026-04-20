from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass
from datetime import datetime, timezone
from typing import Any


MEDIA_FIELDS = (
    "animation",
    "audio",
    "contact",
    "document",
    "game",
    "location",
    "photo",
    "poll",
    "sticker",
    "video",
    "video_note",
    "voice",
)


@dataclass(frozen=True, slots=True)
class NormalizedTelegramMessage:
    telegram_message_id: int
    sender_id: int | None
    sender_name: str | None
    source_adapter: str
    source_type: str
    sent_at: datetime
    raw_text: str
    normalized_text: str
    reply_to_telegram_message_id: int | None
    forward_info: dict[str, Any] | list[Any] | None
    has_media: bool
    media_type: str | None
    entities_json: list[dict[str, Any]] | None


def normalize_telegram_message(
    message: object,
    *,
    source_adapter: str = "telegram",
) -> NormalizedTelegramMessage:
    raw_text = _extract_raw_text(message)
    media_type = _detect_media_type(message)
    entities = _extract_entities(message)
    sender_id, sender_name = _extract_sender(message)
    sent_at = _normalize_datetime(getattr(message, "date", None))
    chat = getattr(message, "chat", None)

    return NormalizedTelegramMessage(
        telegram_message_id=int(getattr(message, "message_id")),
        sender_id=sender_id,
        sender_name=sender_name,
        source_adapter=source_adapter,
        source_type="channel_post" if getattr(chat, "type", None) == "channel" else "message",
        sent_at=sent_at,
        raw_text=raw_text,
        normalized_text=normalize_text(raw_text),
        reply_to_telegram_message_id=_extract_reply_to_message_id(message),
        forward_info=_extract_forward_info(message),
        has_media=media_type is not None,
        media_type=media_type,
        entities_json=entities,
    )


def normalize_text(value: str | None) -> str:
    if value is None:
        return ""
    return " ".join(value.split())


def _extract_raw_text(message: object) -> str:
    text = getattr(message, "text", None)
    if isinstance(text, str):
        return text

    caption = getattr(message, "caption", None)
    if isinstance(caption, str):
        return caption

    return ""


def _extract_sender(message: object) -> tuple[int | None, str | None]:
    sender_chat = getattr(message, "sender_chat", None)
    if sender_chat is not None:
        sender_id = getattr(sender_chat, "id", None)
        sender_name = _extract_chat_title(sender_chat)
        return _coerce_int(sender_id), sender_name

    from_user = getattr(message, "from_user", None)
    if from_user is None:
        return None, None

    return _coerce_int(getattr(from_user, "id", None)), _extract_user_name(from_user)


def _extract_reply_to_message_id(message: object) -> int | None:
    reply = getattr(message, "reply_to_message", None)
    if reply is None:
        return None

    return _coerce_int(getattr(reply, "message_id", None))


def _extract_forward_info(message: object) -> dict[str, Any] | list[Any] | None:
    forward_origin = getattr(message, "forward_origin", None)
    if forward_origin is not None:
        payload = _to_json_compatible(forward_origin)
        return payload if isinstance(payload, (dict, list)) else None

    legacy_payload = {
        "forward_from_chat": _to_json_compatible(getattr(message, "forward_from_chat", None)),
        "forward_from": _to_json_compatible(getattr(message, "forward_from", None)),
        "forward_sender_name": _to_json_compatible(
            getattr(message, "forward_sender_name", None)
        ),
        "forward_signature": _to_json_compatible(getattr(message, "forward_signature", None)),
        "forward_date": _to_json_compatible(getattr(message, "forward_date", None)),
    }
    compact_payload = {
        key: value
        for key, value in legacy_payload.items()
        if value is not None
    }
    return compact_payload or None


def _extract_entities(message: object) -> list[dict[str, Any]] | None:
    raw_text = getattr(message, "text", None)
    entities = getattr(message, "entities", None) if isinstance(raw_text, str) else None
    if entities is None:
        entities = getattr(message, "caption_entities", None)
    if entities is None:
        return None

    normalized_entities: list[dict[str, Any]] = []
    for entity in entities:
        payload = _to_json_compatible(entity)
        if isinstance(payload, dict):
            normalized_entities.append(payload)

    return normalized_entities or None


def _detect_media_type(message: object) -> str | None:
    for field_name in MEDIA_FIELDS:
        value = getattr(message, field_name, None)
        if value is None:
            continue
        if isinstance(value, (list, tuple, set)) and len(value) == 0:
            continue
        return field_name
    return None


def _extract_user_name(user: object) -> str | None:
    first_name = getattr(user, "first_name", None)
    last_name = getattr(user, "last_name", None)
    name_parts = [
        part.strip()
        for part in (first_name, last_name)
        if isinstance(part, str) and part.strip()
    ]
    if name_parts:
        return " ".join(name_parts)

    username = getattr(user, "username", None)
    if isinstance(username, str) and username.strip():
        return f"@{username.strip().lstrip('@')}"

    return None


def _extract_chat_title(chat: object) -> str | None:
    title = getattr(chat, "title", None)
    if isinstance(title, str) and title.strip():
        return title.strip()

    username = getattr(chat, "username", None)
    if isinstance(username, str) and username.strip():
        return f"@{username.strip().lstrip('@')}"

    return None


def _normalize_datetime(value: object) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    return datetime.now(timezone.utc)


def _coerce_int(value: object) -> int | None:
    if value is None:
        return None

    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _to_json_compatible(value: object) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value

    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc).isoformat()
        return value.astimezone(timezone.utc).isoformat()

    if isinstance(value, dict):
        return {
            str(key): _to_json_compatible(item)
            for key, item in value.items()
            if item is not None
        }

    if isinstance(value, (list, tuple, set)):
        return [_to_json_compatible(item) for item in value]

    if hasattr(value, "model_dump"):
        return _to_json_compatible(value.model_dump(exclude_none=True))

    if is_dataclass(value):
        return _to_json_compatible(asdict(value))

    if hasattr(value, "__dict__"):
        return _to_json_compatible(
            {
                key: item
                for key, item in vars(value).items()
                if not key.startswith("_") and item is not None
            }
        )

    return str(value)
