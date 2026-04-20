from __future__ import annotations

from dataclasses import dataclass

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError

from services.command_parser import ResolvedChatCandidate


@dataclass(slots=True)
class TelegramChatResolver:
    bot: Bot

    async def resolve_chat(self, reference: str) -> ResolvedChatCandidate | None:
        chat_reference: int | str
        stripped_reference = reference.strip()
        if not stripped_reference:
            return None

        if stripped_reference.startswith("@"):
            chat_reference = stripped_reference
        else:
            try:
                chat_reference = int(stripped_reference)
            except ValueError:
                chat_reference = f"@{stripped_reference.lstrip('@')}"

        try:
            chat = await self.bot.get_chat(chat_reference)
        except TelegramAPIError:
            return None

        return ResolvedChatCandidate.from_chat_like(chat)
