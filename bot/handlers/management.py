from aiogram import Router
from aiogram.filters import Command
from aiogram.filters.command import CommandObject
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from services.command_parser import BotCommandParser
from services.digest_target import DigestTargetService
from services.source_registry import SourceRegistryService
from services.status_summary import BotStatusService
from services.telegram_lookup import TelegramChatResolver
from storage.repositories import ChatRepository, SettingRepository, SystemRepository


router = Router(name=__name__)
PARSER = BotCommandParser()


@router.message(Command("status"))
async def handle_status_command(
    message: Message,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        service = BotStatusService(
            chat_repository=ChatRepository(session),
            setting_repository=SettingRepository(session),
            system_repository=SystemRepository(session),
        )
        await message.answer(await service.build_status_message())


@router.message(Command("sources"))
async def handle_sources_command(
    message: Message,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        service = BotStatusService(
            chat_repository=ChatRepository(session),
            setting_repository=SettingRepository(session),
            system_repository=SystemRepository(session),
        )
        for response_text in await service.build_sources_messages():
            await message.answer(response_text)


@router.message(Command("source_add"))
async def handle_source_add_command(
    message: Message,
    command: CommandObject,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    fallback_source = PARSER.extract_source_candidate(message)
    async with session_factory() as session:
        service = SourceRegistryService(
            repository=ChatRepository(session),
            resolver=TelegramChatResolver(message.bot),
        )
        try:
            result = await service.register_source(
                PARSER.parse_source_add_arguments(command.args),
                fallback_source=fallback_source,
            )
        except ValueError as error:
            await message.answer(str(error))
            return

        await session.commit()

    await message.answer(result.to_user_message())


@router.message(Command("source_disable"))
async def handle_source_disable_command(
    message: Message,
    command: CommandObject,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _handle_source_toggle(
        message=message,
        command=command,
        session_factory=session_factory,
        is_enabled=False,
        command_name="source_disable",
    )


@router.message(Command("source_enable"))
async def handle_source_enable_command(
    message: Message,
    command: CommandObject,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _handle_source_toggle(
        message=message,
        command=command,
        session_factory=session_factory,
        is_enabled=True,
        command_name="source_enable",
    )


@router.message(Command("digest_target"))
async def handle_digest_target_command(
    message: Message,
    command: CommandObject,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    fallback_source = PARSER.extract_source_candidate(message)
    async with session_factory() as session:
        service = DigestTargetService(
            repository=SettingRepository(session),
            resolver=TelegramChatResolver(message.bot),
        )
        try:
            result = await service.set_target(
                PARSER.parse_digest_target_arguments(command.args),
                fallback_source=fallback_source,
            )
        except ValueError as error:
            await message.answer(str(error))
            return

        await session.commit()

    await message.answer(result.to_user_message())


@router.message(Command("settings"))
async def handle_settings_command(
    message: Message,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        service = BotStatusService(
            chat_repository=ChatRepository(session),
            setting_repository=SettingRepository(session),
            system_repository=SystemRepository(session),
        )
        await message.answer(await service.build_settings_message())


async def _handle_source_toggle(
    *,
    message: Message,
    command: CommandObject,
    session_factory: async_sessionmaker[AsyncSession],
    is_enabled: bool,
    command_name: str,
) -> None:
    try:
        reference = PARSER.parse_required_reference(command.args, command_name=command_name)
    except ValueError as error:
        await message.answer(str(error))
        return

    async with session_factory() as session:
        service = SourceRegistryService(
            repository=ChatRepository(session),
            resolver=TelegramChatResolver(message.bot),
        )
        result = await service.set_source_enabled(reference, is_enabled=is_enabled)
        if result is None:
            await message.answer("Источник не найден. Проверь chat_id или @username.")
            return

        await session.commit()

    await message.answer(result.to_user_message())
