from aiogram import Router
from aiogram.filters import Command
from aiogram.filters.command import CommandObject
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from services.chat_memory_builder import ChatMemoryBuilder
from services.command_parser import BotCommandParser
from services.digest_builder import DigestBuilder
from services.digest_engine import DigestEngineService, DigestPublisherService
from services.digest_formatter import DigestFormatter
from services.digest_target import DigestTargetService
from services.memory_builder import MemoryService
from services.memory_formatter import MemoryFormatter
from services.people_memory_builder import PeopleMemoryBuilder
from services.persona_adapter import PersonaAdapter
from services.persona_core import PersonaCoreService
from services.persona_formatter import PersonaFormatter
from services.persona_guardrails import PersonaGuardrails
from services.reply_classifier import ReplyClassifier
from services.reply_context_builder import ReplyContextBuilder
from services.reply_engine import ReplyEngineService
from services.reply_formatter import ReplyFormatter
from services.reply_strategy import ReplyStrategyResolver
from services.style_adapter import StyleAdapter
from services.style_formatter import StyleFormatter
from services.style_profiles import StyleProfileService
from services.style_selector import StyleSelectorService
from services.source_registry import SourceRegistryService
from services.status_summary import BotStatusService
from services.telegram_lookup import TelegramChatResolver
from storage.repositories import (
    ChatRepository,
    ChatMemoryRepository,
    ChatStyleOverrideRepository,
    DigestRepository,
    MessageRepository,
    PersonMemoryRepository,
    SettingRepository,
    StyleProfileRepository,
    SystemRepository,
)


router = Router(name=__name__)
PARSER = BotCommandParser()


@router.message(Command("status"))
async def handle_status_command(
    message: Message,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        service = _build_status_service(session)
        await message.answer(await service.build_status_message())


@router.message(Command("sources"))
async def handle_sources_command(
    message: Message,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        service = _build_status_service(session)
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
        service = _build_status_service(session)
        await message.answer(await service.build_settings_message())


@router.message(Command("persona_status"))
async def handle_persona_status_command(
    message: Message,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        service = _build_persona_service(session)
        formatter = PersonaFormatter()
        report = await service.build_status_report()

    await message.answer(formatter.format_status(report))


@router.message(Command("reply"))
async def handle_reply_command(
    message: Message,
    command: CommandObject,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    try:
        reference = PARSER.parse_required_reference(command.args, command_name="reply")
    except ValueError as error:
        await message.answer(str(error))
        return

    async with session_factory() as session:
        service = _build_reply_service(session)
        formatter = ReplyFormatter()
        result = await service.build_reply(reference)

    await message.answer(formatter.format_result(result))


@router.message(Command("style_profiles"))
async def handle_style_profiles_command(
    message: Message,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        service = _build_style_service(session)
        formatter = StyleFormatter()
        await message.answer(formatter.format_profiles(await service.list_profiles()))


@router.message(Command("style_set"))
async def handle_style_set_command(
    message: Message,
    command: CommandObject,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        service = _build_style_service(session)
        formatter = StyleFormatter()
        try:
            parsed = PARSER.parse_style_set_arguments(command.args)
            report = await service.set_chat_override(
                reference=parsed.reference,
                profile_key=parsed.profile_key,
            )
        except ValueError as error:
            await message.answer(str(error))
            return

        await session.commit()

    await message.answer(formatter.format_status(report))


@router.message(Command("style_unset"))
async def handle_style_unset_command(
    message: Message,
    command: CommandObject,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    try:
        reference = PARSER.parse_required_reference(command.args, command_name="style_unset")
    except ValueError as error:
        await message.answer(str(error))
        return

    async with session_factory() as session:
        service = _build_style_service(session)
        formatter = StyleFormatter()
        try:
            report = await service.unset_chat_override(reference=reference)
        except ValueError as error:
            await message.answer(str(error))
            return

        await session.commit()

    await message.answer(formatter.format_status(report))


@router.message(Command("style_status"))
async def handle_style_status_command(
    message: Message,
    command: CommandObject,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    try:
        reference = PARSER.parse_required_reference(command.args, command_name="style_status")
    except ValueError as error:
        await message.answer(str(error))
        return

    async with session_factory() as session:
        service = _build_style_service(session)
        formatter = StyleFormatter()
        try:
            report = await service.build_style_status(reference)
        except ValueError as error:
            await message.answer(str(error))
            return

    await message.answer(formatter.format_status(report))


@router.message(Command("digest_now"))
async def handle_digest_now_command(
    message: Message,
    command: CommandObject,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        digest_repository = DigestRepository(session)
        engine = DigestEngineService(
            message_repository=MessageRepository(session),
            digest_repository=digest_repository,
            setting_repository=SettingRepository(session),
            builder=DigestBuilder(),
            formatter=DigestFormatter(),
        )
        try:
            plan = await engine.build_manual_digest(command.args)
        except ValueError as error:
            await message.answer(str(error))
            return

        publish_result = await DigestPublisherService(digest_repository).publish(
            plan=plan,
            preview_chat_id=message.chat.id,
            sender=message.bot,
        )
        await session.commit()

    if publish_result.notice:
        await message.answer(publish_result.notice)


@router.message(Command("memory_rebuild"))
async def handle_memory_rebuild_command(
    message: Message,
    command: CommandObject,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    reference = None
    if command.args and command.args.strip():
        reference = PARSER.parse_required_reference(
            command.args,
            command_name="memory_rebuild",
        )

    async with session_factory() as session:
        service = _build_memory_service(session)
        try:
            result = await service.rebuild(reference)
        except ValueError as error:
            await message.answer(str(error))
            return

        await session.commit()

    await message.answer(result.to_user_message())


@router.message(Command("chat_memory"))
async def handle_chat_memory_command(
    message: Message,
    command: CommandObject,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    reference = None
    if command.args and command.args.strip():
        reference = PARSER.parse_required_reference(
            command.args,
            command_name="chat_memory",
        )

    async with session_factory() as session:
        service = _build_memory_service(session)
        await message.answer(await service.build_chat_memory_card(reference))


@router.message(Command("person_memory"))
async def handle_person_memory_command(
    message: Message,
    command: CommandObject,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    query = command.args.strip() if command.args and command.args.strip() else None

    async with session_factory() as session:
        service = _build_memory_service(session)
        await message.answer(await service.build_person_memory_card(query))


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


def _build_status_service(session: AsyncSession) -> BotStatusService:
    return BotStatusService(
        chat_repository=ChatRepository(session),
        setting_repository=SettingRepository(session),
        system_repository=SystemRepository(session),
        message_repository=MessageRepository(session),
        digest_repository=DigestRepository(session),
        chat_memory_repository=ChatMemoryRepository(session),
        person_memory_repository=PersonMemoryRepository(session),
        style_profile_repository=StyleProfileRepository(session),
        chat_style_override_repository=ChatStyleOverrideRepository(session),
    )


def _build_memory_service(session: AsyncSession) -> MemoryService:
    return MemoryService(
        chat_repository=ChatRepository(session),
        message_repository=MessageRepository(session),
        digest_repository=DigestRepository(session),
        setting_repository=SettingRepository(session),
        chat_memory_repository=ChatMemoryRepository(session),
        person_memory_repository=PersonMemoryRepository(session),
        chat_builder=ChatMemoryBuilder(),
        people_builder=PeopleMemoryBuilder(),
        formatter=MemoryFormatter(),
    )


def _build_reply_service(session: AsyncSession) -> ReplyEngineService:
    message_repository = MessageRepository(session)
    chat_memory_repository = ChatMemoryRepository(session)
    person_memory_repository = PersonMemoryRepository(session)
    setting_repository = SettingRepository(session)
    return ReplyEngineService(
        chat_repository=ChatRepository(session),
        message_repository=message_repository,
        chat_memory_repository=chat_memory_repository,
        person_memory_repository=person_memory_repository,
        context_builder=ReplyContextBuilder(
            message_repository=message_repository,
            chat_memory_repository=chat_memory_repository,
            person_memory_repository=person_memory_repository,
        ),
        classifier=ReplyClassifier(),
        strategy_resolver=ReplyStrategyResolver(),
        style_selector=StyleSelectorService(
            style_profile_repository=StyleProfileRepository(session),
            chat_style_override_repository=ChatStyleOverrideRepository(session),
            chat_memory_repository=chat_memory_repository,
            person_memory_repository=person_memory_repository,
        ),
        style_adapter=StyleAdapter(),
        persona_core_service=PersonaCoreService(setting_repository),
        persona_adapter=PersonaAdapter(),
        persona_guardrails=PersonaGuardrails(),
    )


def _build_style_service(session: AsyncSession) -> StyleProfileService:
    chat_repository = ChatRepository(session)
    style_profile_repository = StyleProfileRepository(session)
    chat_style_override_repository = ChatStyleOverrideRepository(session)
    return StyleProfileService(
        chat_repository=chat_repository,
        style_profile_repository=style_profile_repository,
        chat_style_override_repository=chat_style_override_repository,
        selector=StyleSelectorService(
            style_profile_repository=style_profile_repository,
            chat_style_override_repository=chat_style_override_repository,
            chat_memory_repository=ChatMemoryRepository(session),
            person_memory_repository=PersonMemoryRepository(session),
        ),
    )


def _build_persona_service(session: AsyncSession) -> PersonaCoreService:
    return PersonaCoreService(SettingRepository(session))
