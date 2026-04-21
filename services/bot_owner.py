from __future__ import annotations

from dataclasses import dataclass

from storage.repositories import SettingRepository


@dataclass(slots=True)
class BotOwnerService:
    repository: SettingRepository

    async def remember_private_chat(self, chat: object | None) -> bool:
        if chat is None:
            return False

        chat_id = getattr(chat, "id", None)
        chat_type = getattr(chat, "type", None)
        if chat_id is None or chat_type != "private":
            return False

        await self.repository.set_value(
            key="bot.owner_chat_id",
            value_text=str(int(chat_id)),
        )
        return True

    async def get_owner_chat_id(self) -> int | None:
        raw_value = await self.repository.get_value("bot.owner_chat_id")
        if raw_value is None:
            return None

        try:
            return int(raw_value)
        except (TypeError, ValueError):
            return None
