from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bot.handlers.common import remember_owner_chat_if_private
from services.error_handling import user_safe_handler
from services.setup_ui import SetupUIService
from services.startup import BotStartupService


router = Router(name=__name__)


@router.message(CommandStart())
@user_safe_handler("bot.start")
async def handle_start_command(
    message: Message,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        owner_chat_known = await remember_owner_chat_if_private(message, session)
        service = BotStartupService()
        setup_ui = SetupUIService.from_session(session)
        await message.answer(
            service.build_start_message(),
            reply_markup=await setup_ui.build_start_keyboard(owner_chat_known=owner_chat_known),
        )


@router.message(Command("onboarding"))
@user_safe_handler("bot.onboarding")
async def handle_onboarding_command(
    message: Message,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await remember_owner_chat_if_private(message, session)
        service = BotStartupService()
        await message.answer(service.build_onboarding_message())


@router.message(Command("help"))
@user_safe_handler("bot.help")
async def handle_help_command(
    message: Message,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await remember_owner_chat_if_private(message, session)
        service = BotStartupService()
        await message.answer(service.build_help_message())
