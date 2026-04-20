from __future__ import annotations

import shlex
from dataclasses import dataclass


CHAT_TYPE_ALIASES = {
    "channel": "channel",
    "group": "group",
    "supergroup": "supergroup",
    "private": "private",
    "канал": "channel",
    "группа": "group",
    "супергруппа": "supergroup",
    "чат": "group",
    "личка": "private",
}


@dataclass(frozen=True, slots=True)
class ParsedSourceAddCommand:
    reference: str | None
    chat_type: str | None
    title: str | None


@dataclass(frozen=True, slots=True)
class ParsedDigestTargetCommand:
    reference: str | None
    label: str | None


@dataclass(frozen=True, slots=True)
class ParsedStyleSetCommand:
    reference: str
    profile_key: str


@dataclass(frozen=True, slots=True)
class ResolvedChatCandidate:
    telegram_chat_id: int
    title: str
    handle: str | None
    chat_type: str

    @property
    def label(self) -> str:
        if self.handle:
            return f"@{self.handle}"
        return self.title

    @classmethod
    def from_chat_like(cls, chat: object | None) -> ResolvedChatCandidate | None:
        if chat is None:
            return None

        chat_id = getattr(chat, "id", None)
        chat_type = getattr(chat, "type", None)
        if chat_id is None or chat_type is None:
            return None

        title = _resolve_chat_title(chat)
        handle = _normalize_handle(getattr(chat, "username", None))
        return cls(
            telegram_chat_id=int(chat_id),
            title=title,
            handle=handle,
            chat_type=str(chat_type),
        )


class BotCommandParser:
    def parse_source_add_arguments(self, args: str | None) -> ParsedSourceAddCommand:
        tokens = _split_command_arguments(args)
        if not tokens:
            return ParsedSourceAddCommand(reference=None, chat_type=None, title=None)

        reference = tokens[0]
        chat_type = None
        remaining = tokens[1:]
        if remaining:
            parsed_type = CHAT_TYPE_ALIASES.get(remaining[0].strip().lower())
            if parsed_type is not None:
                chat_type = parsed_type
                remaining = remaining[1:]

        title = " ".join(remaining).strip() or None
        return ParsedSourceAddCommand(
            reference=reference,
            chat_type=chat_type,
            title=title,
        )

    def parse_digest_target_arguments(self, args: str | None) -> ParsedDigestTargetCommand:
        tokens = _split_command_arguments(args)
        if not tokens:
            return ParsedDigestTargetCommand(reference=None, label=None)

        reference = tokens[0]
        label = " ".join(tokens[1:]).strip() or None
        return ParsedDigestTargetCommand(reference=reference, label=label)

    def parse_style_set_arguments(self, args: str | None) -> ParsedStyleSetCommand:
        tokens = _split_command_arguments(args)
        if len(tokens) < 2:
            raise ValueError(
                "Для /style_set нужен chat_id или @username и profile_key. "
                "Пример: /style_set @mychannel friend_explain"
            )

        return ParsedStyleSetCommand(
            reference=tokens[0],
            profile_key=tokens[1].strip().lower(),
        )

    def parse_required_reference(self, args: str | None, *, command_name: str) -> str:
        tokens = _split_command_arguments(args)
        if not tokens:
            raise ValueError(
                f"Для /{command_name} нужен chat_id или @username. "
                f"Пример: /{command_name} @mychannel"
            )

        return tokens[0]

    def extract_source_candidate(self, message: object) -> ResolvedChatCandidate | None:
        direct_candidates = (
            self._extract_from_forward_origin(getattr(message, "forward_origin", None)),
            ResolvedChatCandidate.from_chat_like(getattr(message, "forward_from_chat", None)),
            ResolvedChatCandidate.from_chat_like(getattr(message, "sender_chat", None)),
        )
        for candidate in direct_candidates:
            if candidate is not None:
                return candidate

        reply = getattr(message, "reply_to_message", None)
        if reply is None:
            return None

        reply_candidates = (
            self._extract_from_forward_origin(getattr(reply, "forward_origin", None)),
            ResolvedChatCandidate.from_chat_like(getattr(reply, "forward_from_chat", None)),
            ResolvedChatCandidate.from_chat_like(getattr(reply, "sender_chat", None)),
        )
        for candidate in reply_candidates:
            if candidate is not None:
                return candidate

        return None

    def _extract_from_forward_origin(self, forward_origin: object | None) -> ResolvedChatCandidate | None:
        if forward_origin is None:
            return None

        chat = getattr(forward_origin, "chat", None)
        if chat is not None:
            return ResolvedChatCandidate.from_chat_like(chat)

        sender_chat = getattr(forward_origin, "sender_chat", None)
        if sender_chat is not None:
            return ResolvedChatCandidate.from_chat_like(sender_chat)

        return None


def _split_command_arguments(args: str | None) -> list[str]:
    if args is None:
        return []

    cleaned = args.strip()
    if not cleaned:
        return []

    try:
        return shlex.split(cleaned)
    except ValueError:
        return cleaned.split()


def _normalize_handle(handle: object | None) -> str | None:
    if not isinstance(handle, str):
        return None

    cleaned = handle.strip().lstrip("@")
    if not cleaned:
        return None

    return cleaned


def _resolve_chat_title(chat: object) -> str:
    title = getattr(chat, "title", None)
    if isinstance(title, str) and title.strip():
        return title.strip()

    first_name = getattr(chat, "first_name", None)
    last_name = getattr(chat, "last_name", None)
    name_parts = [part.strip() for part in (first_name, last_name) if isinstance(part, str) and part.strip()]
    if name_parts:
        return " ".join(name_parts)

    handle = _normalize_handle(getattr(chat, "username", None))
    if handle:
        return f"@{handle}"

    chat_id = getattr(chat, "id", None)
    return f"Источник {chat_id}"
