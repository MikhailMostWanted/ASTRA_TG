from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message

from services.startup import BotStartupService


router = Router(name=__name__)


@router.message(CommandStart())
async def handle_start_command(message: Message) -> None:
    service = BotStartupService()
    await message.answer(service.build_start_message())


@router.message(Command("help"))
async def handle_help_command(message: Message) -> None:
    service = BotStartupService()
    await message.answer(service.build_help_message())
