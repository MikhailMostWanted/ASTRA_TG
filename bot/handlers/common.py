from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from services.bot_owner import BotOwnerService
from storage.repositories import SettingRepository


async def remember_owner_chat_if_private(
    message: Message,
    session: AsyncSession,
) -> bool:
    stored = await BotOwnerService(SettingRepository(session)).remember_private_chat(message.chat)
    if stored:
        await session.commit()
    return stored
