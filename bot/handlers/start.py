from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bot.handlers.common import remember_owner_chat_if_private
from services.startup import BotStartupService


router = Router(name=__name__)


@router.message(CommandStart())
async def handle_start_command(
    message: Message,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await remember_owner_chat_if_private(message, session)
        service = BotStartupService()
        await message.answer(service.build_start_message())


@router.message(Command("help"))
async def handle_help_command(
    message: Message,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await remember_owner_chat_if_private(message, session)
        service = BotStartupService()
        await message.answer(service.build_help_message())
