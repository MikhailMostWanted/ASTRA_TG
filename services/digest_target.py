from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from services.command_parser import ParsedDigestTargetCommand, ResolvedChatCandidate
from storage.repositories import SettingRepository


DIGEST_TARGET_CHAT_ID_KEY = "digest.target.chat_id"
DIGEST_TARGET_LABEL_KEY = "digest.target.label"
DIGEST_TARGET_TYPE_KEY = "digest.target.type"


class ChatResolverProtocol(Protocol):
    async def resolve_chat(self, reference: str) -> ResolvedChatCandidate | None:
        """Возвращает данные Telegram-чата по ссылке или chat_id."""


@dataclass(frozen=True, slots=True)
class DigestTargetSnapshot:
    chat_id: int | None
    label: str | None
    chat_type: str | None

    @property
    def is_configured(self) -> bool:
        return self.chat_id is not None


@dataclass(frozen=True, slots=True)
class DigestTargetSaveResult:
    snapshot: DigestTargetSnapshot
    note: str | None = None

    @property
    def chat_id(self) -> int | None:
        return self.snapshot.chat_id

    @property
    def label(self) -> str | None:
        return self.snapshot.label

    @property
    def chat_type(self) -> str | None:
        return self.snapshot.chat_type

    def to_user_message(self) -> str:
        lines = [
            "Канал доставки digest сохранён.",
            "",
            f"ID Telegram: {self.snapshot.chat_id}",
            f"Подпись: {self.snapshot.label or 'не задана'}",
            f"Тип: {self.snapshot.chat_type or 'неизвестно'}",
        ]
        if self.note:
            lines.extend(["", self.note])
        return "\n".join(lines)


@dataclass(slots=True)
class DigestTargetService:
    repository: SettingRepository
    resolver: ChatResolverProtocol | None = None

    async def get_target(self) -> DigestTargetSnapshot:
        chat_id_value = await self.repository.get_value(DIGEST_TARGET_CHAT_ID_KEY)
        label = await self.repository.get_value(DIGEST_TARGET_LABEL_KEY)
        chat_type = await self.repository.get_value(DIGEST_TARGET_TYPE_KEY)
        return DigestTargetSnapshot(
            chat_id=_parse_optional_int(chat_id_value),
            label=label if isinstance(label, str) else None,
            chat_type=chat_type if isinstance(chat_type, str) else None,
        )

    async def set_target(
        self,
        command: ParsedDigestTargetCommand,
        *,
        fallback_source: ResolvedChatCandidate | None = None,
    ) -> DigestTargetSaveResult:
        candidate, note = await self._resolve_candidate(command, fallback_source=fallback_source)

        snapshot = DigestTargetSnapshot(
            chat_id=candidate.telegram_chat_id,
            label=command.label or _build_candidate_label(candidate),
            chat_type=candidate.chat_type,
        )
        await self.repository.set_value(
            key=DIGEST_TARGET_CHAT_ID_KEY,
            value_text=str(snapshot.chat_id),
        )
        await self.repository.set_value(
            key=DIGEST_TARGET_LABEL_KEY,
            value_text=snapshot.label,
        )
        await self.repository.set_value(
            key=DIGEST_TARGET_TYPE_KEY,
            value_text=snapshot.chat_type,
        )
        return DigestTargetSaveResult(snapshot=snapshot, note=note)

    async def _resolve_candidate(
        self,
        command: ParsedDigestTargetCommand,
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
                        title=command.label or f"Канал {chat_id}",
                        handle=None,
                        chat_type="unknown",
                    ),
                    "Telegram не отдал описание этого чата, поэтому канал доставки сохранён по chat_id.",
                )

            raise ValueError(
                "Бот не смог определить chat_id по этому @username. "
                "Укажи chat_id или перешли сообщение из нужного канала."
            )

        if fallback_source is not None:
            return fallback_source, None

        raise ValueError(
            "Укажи chat_id или @username, либо перешли сообщение из нужного канала."
        )

    async def _resolve_reference(self, reference: str) -> ResolvedChatCandidate | None:
        if self.resolver is None:
            return None
        return await self.resolver.resolve_chat(reference)


def _parse_optional_int(value: object) -> int | None:
    if value is None:
        return None

    try:
        return int(value)
    except (TypeError, ValueError):
        return None


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


def _build_candidate_label(candidate: ResolvedChatCandidate) -> str:
    if candidate.handle:
        return f"@{candidate.handle}"
    return candidate.title
