from aiogram import F, Router
from aiogram.filters import Command
from aiogram.filters.command import CommandObject
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bot.handlers.common import remember_owner_chat_if_private
from services.command_parser import BotCommandParser
from services.error_handling import user_safe_handler
from services.reminder_extractor import ReminderExtractor
from services.reminder_formatter import ReminderFormatter, parse_reminder_callback_data
from services.reminder_service import ReminderService
from storage.repositories import (
    ChatMemoryRepository,
    ChatRepository,
    MessageRepository,
    ReminderRepository,
    SettingRepository,
    TaskRepository,
)


router = Router(name=__name__)
PARSER = BotCommandParser()


@router.message(Command("reminders_scan"))
@user_safe_handler("bot.reminders_scan")
async def handle_reminders_scan_command(
    message: Message,
    command: CommandObject,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await remember_owner_chat_if_private(message, session)
        service = _build_reminder_service(session)
        try:
            parsed = PARSER.parse_reminder_scan_arguments(command.args)
            result = await service.scan(
                window_argument=parsed.window_argument,
                source_reference=parsed.reference,
            )
        except ValueError as error:
            await message.answer(str(error))
            return

        await session.commit()

    await message.answer(result.summary_text)
    for card in result.cards:
        await message.answer(card.text, reply_markup=card.reply_markup)


@router.message(Command("tasks"))
@user_safe_handler("bot.tasks")
async def handle_tasks_command(
    message: Message,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await remember_owner_chat_if_private(message, session)
        service = _build_reminder_service(session)
        text = await service.build_tasks_message()

    await message.answer(text)


@router.message(Command("reminders"))
@user_safe_handler("bot.reminders")
async def handle_reminders_command(
    message: Message,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await remember_owner_chat_if_private(message, session)
        service = _build_reminder_service(session)
        text = await service.build_reminders_message()

    await message.answer(text)


@router.callback_query(F.data.startswith("reminder:"))
@user_safe_handler("bot.reminder_callback")
async def handle_reminder_callback(
    callback: CallbackQuery,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    parsed = parse_reminder_callback_data(callback.data)
    if parsed is None:
        await callback.answer("Некорректный callback reminder.", show_alert=True)
        return

    async with session_factory() as session:
        callback_message = callback.message
        if isinstance(callback_message, Message):
            await remember_owner_chat_if_private(callback_message, session)
        service = _build_reminder_service(session)
        try:
            if parsed.action == "approve":
                result = await service.approve_candidate(task_id=parsed.task_id)
                notice = "Кандидат одобрен."
            elif parsed.action == "reject":
                result = await service.reject_candidate(parsed.task_id)
                notice = "Кандидат отклонён."
            elif parsed.action == "postpone":
                result = await service.postpone_candidate(task_id=parsed.task_id)
                notice = "Напоминание перенесено."
            else:
                await callback.answer("Неизвестное действие для reminder.", show_alert=True)
                return
        except ValueError as error:
            await callback.answer(str(error), show_alert=True)
            return

        await session.commit()

    if isinstance(callback_message, Message):
        await callback_message.edit_text(result.text)
    await callback.answer(notice)


def _build_reminder_service(session: AsyncSession) -> ReminderService:
    return ReminderService(
        chat_repository=ChatRepository(session),
        message_repository=MessageRepository(session),
        chat_memory_repository=ChatMemoryRepository(session),
        setting_repository=SettingRepository(session),
        task_repository=TaskRepository(session),
        reminder_repository=ReminderRepository(session),
        extractor=ReminderExtractor(),
        formatter=ReminderFormatter(),
    )
