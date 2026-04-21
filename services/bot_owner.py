from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class BotOwnerRepositoryProtocol(Protocol):
    async def get_value(self, key: str) -> object: ...

    async def set_value(
        self,
        *,
        key: str,
        value_text: str | None = None,
        value_json: dict[str, object] | list[object] | None = None,
    ) -> object: ...


@dataclass(slots=True)
class BotOwnerService:
    repository: BotOwnerRepositoryProtocol

    async def remember_private_chat(self, chat: object | None) -> bool:
        if chat is None:
            return False

        chat_id = getattr(chat, "id", None)
        chat_type = getattr(chat, "type", None)
        normalized_chat_id = _coerce_int(chat_id)
        if normalized_chat_id is None or chat_type != "private":
            return False

        await self.repository.set_value(
            key="bot.owner_chat_id",
            value_text=str(normalized_chat_id),
        )
        return True

    async def get_owner_chat_id(self) -> int | None:
        raw_value = await self.repository.get_value("bot.owner_chat_id")
        if raw_value is None:
            return None

        return _coerce_int(raw_value)


def _coerce_int(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None
