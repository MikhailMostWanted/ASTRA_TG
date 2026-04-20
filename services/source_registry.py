from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from models import Chat
from services.command_parser import ParsedSourceAddCommand, ResolvedChatCandidate
from storage.repositories import ChatRepository


class ChatResolverProtocol(Protocol):
    async def resolve_chat(self, reference: str) -> ResolvedChatCandidate | None:
        """Возвращает данные Telegram-чата по ссылке или chat_id."""


@dataclass(frozen=True, slots=True)
class SourceMutationResult:
    chat: Chat
    action: str
    note: str | None = None

    def to_user_message(self) -> str:
        action_label = "добавлен" if self.action == "created" else "обновлён"
        lines = [
            f"Источник {action_label}.",
            "",
            f"Название: {self.chat.title}",
            f"ID Telegram: {self.chat.telegram_chat_id}",
            f"Тип: {self.chat.type}",
            f"Статус: {'активен' if self.chat.is_enabled else 'выключен'}",
        ]
        if self.chat.handle:
            lines.append(f"Username: @{self.chat.handle}")
        if self.note:
            lines.extend(["", self.note])
        return "\n".join(lines)


@dataclass(frozen=True, slots=True)
class SourceToggleResult:
    chat: Chat
    is_enabled: bool

    def to_user_message(self) -> str:
        status_label = "включён" if self.is_enabled else "выключен"
        return (
            f"Источник {status_label}.\n\n"
            f"Название: {self.chat.title}\n"
            f"ID Telegram: {self.chat.telegram_chat_id}\n"
            f"Тип: {self.chat.type}"
        )


@dataclass(slots=True)
class SourceRegistryService:
    repository: ChatRepository
    resolver: ChatResolverProtocol | None = None

    async def register_source(
        self,
        command: ParsedSourceAddCommand,
        *,
        fallback_source: ResolvedChatCandidate | None = None,
    ) -> SourceMutationResult:
        candidate, note = await self._resolve_candidate(command, fallback_source=fallback_source)
        existing_chat = await self.repository.get_by_telegram_chat_id(candidate.telegram_chat_id)
        title = command.title or _pick_title(candidate, existing_chat=existing_chat)
        handle = candidate.handle or (existing_chat.handle if existing_chat is not None else None)
        chat_type = command.chat_type or _pick_chat_type(candidate, existing_chat=existing_chat)

        chat = await self.repository.upsert_chat(
            telegram_chat_id=candidate.telegram_chat_id,
            title=title,
            handle=handle,
            chat_type=chat_type,
            is_enabled=True,
        )
        return SourceMutationResult(
            chat=chat,
            action="created" if existing_chat is None else "updated",
            note=note,
        )

    async def set_source_enabled(
        self,
        reference: str,
        *,
        is_enabled: bool,
    ) -> SourceToggleResult | None:
        chat = await self.repository.set_chat_enabled(reference, is_enabled=is_enabled)
        if chat is None:
            return None

        return SourceToggleResult(chat=chat, is_enabled=is_enabled)

    async def _resolve_candidate(
        self,
        command: ParsedSourceAddCommand,
        *,
        fallback_source: ResolvedChatCandidate | None,
    ) -> tuple[ResolvedChatCandidate, str | None]:
        if command.reference:
            resolved_from_reference = await self._resolve_reference(command.reference)
            if resolved_from_reference is not None:
                return resolved_from_reference, None

            if fallback_source is not None and _matches_reference(fallback_source, command.reference):
                return fallback_source, None

            if _looks_like_chat_id(command.reference):
                chat_id = int(command.reference)
                return (
                    ResolvedChatCandidate(
                        telegram_chat_id=chat_id,
                        title=command.title or f"Источник {chat_id}",
                        handle=None,
                        chat_type=command.chat_type or "unknown",
                    ),
                    "Telegram не отдал полные данные по этому ID чата, поэтому источник сохранён "
                    "с ручным названием. Позже его можно обновить через @username или форвард.",
                )

            raise ValueError(
                "Бот не смог получить ID чата по этому @username. "
                "Добавь источник по chat_id или перешли сообщение из нужного канала/группы."
            )

        if fallback_source is not None:
            return fallback_source, None

        raise ValueError(
            "Укажи chat_id или @username, либо перешли сообщение из нужного канала/группы."
        )

    async def _resolve_reference(self, reference: str) -> ResolvedChatCandidate | None:
        if self.resolver is None:
            return None
        return await self.resolver.resolve_chat(reference)


def _looks_like_chat_id(reference: str) -> bool:
    try:
        int(reference)
    except ValueError:
        return False
    return True


def _matches_reference(candidate: ResolvedChatCandidate, reference: str) -> bool:
    normalized_reference = reference.strip().lower()
    if not normalized_reference:
        return False

    if normalized_reference.startswith("@"):
        return candidate.handle is not None and candidate.handle.lower() == normalized_reference.lstrip("@")

    try:
        return candidate.telegram_chat_id == int(normalized_reference)
    except ValueError:
        return candidate.handle is not None and candidate.handle.lower() == normalized_reference


def _pick_title(candidate: ResolvedChatCandidate, *, existing_chat: Chat | None) -> str:
    if existing_chat is not None and candidate.title.startswith("Источник "):
        return existing_chat.title
    return candidate.title


def _pick_chat_type(candidate: ResolvedChatCandidate, *, existing_chat: Chat | None) -> str:
    if candidate.chat_type != "unknown":
        return candidate.chat_type
    if existing_chat is not None:
        return existing_chat.type
    return "unknown"
