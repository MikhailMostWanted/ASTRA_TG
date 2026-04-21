from typing import cast

from aiogram import Bot, Router
from aiogram.filters import Command
from aiogram.filters.command import CommandObject
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bot.handlers.common import remember_owner_chat_if_private
from config.settings import Settings
from fullaccess.auth import FullAccessAuthService
from fullaccess.formatter import FullAccessFormatter
from fullaccess.sync import FullAccessSyncService
from services.chat_memory_builder import ChatMemoryBuilder
from services.command_parser import BotCommandParser
from services.digest_builder import DigestBuilder
from services.digest_engine import DigestEngineService, DigestPublisherService, MessageSenderProtocol
from services.digest_formatter import DigestFormatter
from services.digest_target import DigestTargetService
from services.memory_builder import MemoryService
from services.memory_formatter import MemoryFormatter
from services.people_memory_builder import PeopleMemoryBuilder
from services.persona_adapter import PersonaAdapter
from services.persona_core import PersonaCoreService
from services.persona_formatter import PersonaFormatter
from services.persona_guardrails import PersonaGuardrails
from services.providers.digest_refiner import DigestLLMRefiner
from services.providers.manager import ProviderManager
from services.providers.reply_refiner import ReplyLLMRefiner
from services.reply_classifier import ReplyClassifier
from services.reply_context_builder import ReplyContextBuilder
from services.reply_engine import ReplyEngineService
from services.reply_examples_builder import ReplyExamplesBuilder
from services.reply_examples_formatter import ReplyExamplesFormatter
from services.reply_examples_retriever import ReplyExamplesRetriever
from services.error_handling import user_safe_handler
from services.reply_formatter import ReplyFormatter
from services.reply_models import ReplyContextIssue
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
    ReplyExampleRepository,
    ReminderRepository,
    SettingRepository,
    StyleProfileRepository,
    SystemRepository,
    TaskRepository,
)


router = Router(name=__name__)
PARSER = BotCommandParser()


@router.message(Command("status"))
@user_safe_handler("bot.status")
async def handle_status_command(
    message: Message,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await remember_owner_chat_if_private(message, session)
        service = _build_status_service(session)
        await message.answer(await service.build_status_message())


@router.message(Command("checklist"))
@user_safe_handler("bot.checklist")
async def handle_checklist_command(
    message: Message,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await remember_owner_chat_if_private(message, session)
        service = _build_status_service(session)
        await message.answer(await service.build_checklist_message())


@router.message(Command("doctor"))
@user_safe_handler("bot.doctor")
async def handle_doctor_command(
    message: Message,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await remember_owner_chat_if_private(message, session)
        service = _build_status_service(session)
        await message.answer(await service.build_doctor_message())


@router.message(Command("provider_status"))
@user_safe_handler("bot.provider_status")
async def handle_provider_status_command(
    message: Message,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await remember_owner_chat_if_private(message, session)
        service = _build_status_service(session)
        await message.answer(await service.build_provider_status_message())


@router.message(Command("fullaccess_status"))
@user_safe_handler("bot.fullaccess_status")
async def handle_fullaccess_status_command(
    message: Message,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await remember_owner_chat_if_private(message, session)
        service = _build_fullaccess_auth_service(session)
        formatter = FullAccessFormatter()
        await message.answer(formatter.format_status(await service.build_status_report()))


@router.message(Command("fullaccess_login"))
@user_safe_handler("bot.fullaccess_login")
async def handle_fullaccess_login_command(
    message: Message,
    command: CommandObject,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    login_code = command.args.strip() if command.args and command.args.strip() else None
    if login_code and len(login_code.split()) > 1:
        await message.answer(
            "Через бота поддержан только код Telegram. Если нужен пароль 2FA, "
            "используй локальный helper: python -m fullaccess.cli login --code <код>."
        )
        return

    async with session_factory() as session:
        await remember_owner_chat_if_private(message, session)
        service = _build_fullaccess_auth_service(session)
        formatter = FullAccessFormatter()
        try:
            result = (
                await service.complete_login(login_code)
                if login_code is not None
                else await service.begin_login()
            )
        except ValueError as error:
            await message.answer(str(error))
            return
        await session.commit()

    await message.answer(formatter.format_login(result))


@router.message(Command("fullaccess_logout"))
@user_safe_handler("bot.fullaccess_logout")
async def handle_fullaccess_logout_command(
    message: Message,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await remember_owner_chat_if_private(message, session)
        service = _build_fullaccess_auth_service(session)
        formatter = FullAccessFormatter()
        result = await service.logout()
        await session.commit()

    await message.answer(formatter.format_logout(result))


@router.message(Command("fullaccess_chats"))
@user_safe_handler("bot.fullaccess_chats")
async def handle_fullaccess_chats_command(
    message: Message,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await remember_owner_chat_if_private(message, session)
        service = _build_fullaccess_sync_service(session)
        formatter = FullAccessFormatter()
        try:
            result = await service.list_chats()
        except ValueError as error:
            await message.answer(str(error))
            return

    await message.answer(formatter.format_chat_list(result))


@router.message(Command("fullaccess_sync"))
@user_safe_handler("bot.fullaccess_sync")
async def handle_fullaccess_sync_command(
    message: Message,
    command: CommandObject,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    try:
        reference = PARSER.parse_required_reference(command.args, command_name="fullaccess_sync")
    except ValueError as error:
        await message.answer(str(error))
        return

    async with session_factory() as session:
        await remember_owner_chat_if_private(message, session)
        service = _build_fullaccess_sync_service(session)
        formatter = FullAccessFormatter()
        try:
            result = await service.sync_chat(reference)
        except ValueError as error:
            await message.answer(str(error))
            return
        await session.commit()

    await message.answer(formatter.format_sync_result(result))


@router.message(Command("sources"))
@user_safe_handler("bot.sources")
async def handle_sources_command(
    message: Message,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await remember_owner_chat_if_private(message, session)
        service = _build_status_service(session)
        for response_text in await service.build_sources_messages():
            await message.answer(response_text)


@router.message(Command("source_add"))
@user_safe_handler("bot.source_add")
async def handle_source_add_command(
    message: Message,
    command: CommandObject,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    fallback_source = PARSER.extract_source_candidate(message)
    async with session_factory() as session:
        await remember_owner_chat_if_private(message, session)
        service = SourceRegistryService(
            repository=ChatRepository(session),
            resolver=TelegramChatResolver(_require_aiogram_bot(message.bot)),
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
@user_safe_handler("bot.source_disable")
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
@user_safe_handler("bot.source_enable")
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
@user_safe_handler("bot.digest_target")
async def handle_digest_target_command(
    message: Message,
    command: CommandObject,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    fallback_source = PARSER.extract_source_candidate(message)
    async with session_factory() as session:
        await remember_owner_chat_if_private(message, session)
        service = DigestTargetService(
            repository=SettingRepository(session),
            resolver=TelegramChatResolver(_require_aiogram_bot(message.bot)),
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
@user_safe_handler("bot.settings")
async def handle_settings_command(
    message: Message,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await remember_owner_chat_if_private(message, session)
        service = _build_status_service(session)
        await message.answer(await service.build_settings_message())


@router.message(Command("persona_status"))
@user_safe_handler("bot.persona_status")
async def handle_persona_status_command(
    message: Message,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await remember_owner_chat_if_private(message, session)
        service = _build_persona_service(session)
        formatter = PersonaFormatter()
        report = await service.build_status_report()

    await message.answer(formatter.format_status(report))


@router.message(Command("reply"))
@user_safe_handler("bot.reply")
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
        await remember_owner_chat_if_private(message, session)
        service = _build_reply_service(session)
        formatter = ReplyFormatter()
        result = await service.build_reply(reference)

    await message.answer(formatter.format_result(result))


@router.message(Command("reply_llm"))
@user_safe_handler("bot.reply_llm")
async def handle_reply_llm_command(
    message: Message,
    command: CommandObject,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    try:
        reference = PARSER.parse_required_reference(command.args, command_name="reply_llm")
    except ValueError as error:
        await message.answer(str(error))
        return

    async with session_factory() as session:
        await remember_owner_chat_if_private(message, session)
        service = _build_reply_service(session)
        formatter = ReplyFormatter()
        result = await service.build_reply(
            reference,
            use_provider_refinement=True,
        )

    await message.answer(formatter.format_result(result))


@router.message(Command("examples_rebuild"))
@user_safe_handler("bot.examples_rebuild")
async def handle_examples_rebuild_command(
    message: Message,
    command: CommandObject,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    reference = None
    if command.args and command.args.strip():
        try:
            reference = PARSER.parse_required_reference(
                command.args,
                command_name="examples_rebuild",
            )
        except ValueError as error:
            await message.answer(str(error))
            return

    async with session_factory() as session:
        await remember_owner_chat_if_private(message, session)
        builder = _build_reply_examples_builder(session)
        formatter = ReplyExamplesFormatter()
        try:
            result = await builder.rebuild(reference)
        except ValueError as error:
            await message.answer(str(error))
            return
        await session.commit()

    await message.answer(formatter.format_rebuild_result(result))


@router.message(Command("reply_examples"))
@user_safe_handler("bot.reply_examples")
async def handle_reply_examples_command(
    message: Message,
    command: CommandObject,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    try:
        reference = PARSER.parse_required_reference(command.args, command_name="reply_examples")
    except ValueError as error:
        await message.answer(str(error))
        return

    async with session_factory() as session:
        await remember_owner_chat_if_private(message, session)
        chat_repository = ChatRepository(session)
        formatter = ReplyExamplesFormatter()
        chat = await chat_repository.find_chat_by_handle_or_telegram_id(reference)
        if chat is None:
            await message.answer("Источник не найден. Проверь chat_id или @username.")
            return

        context_or_issue = _build_reply_context_builder(session).build(chat)
        context_or_issue = await context_or_issue
        if isinstance(context_or_issue, ReplyContextIssue):
            await message.answer(context_or_issue.message)
            return

        retrieval = await _build_reply_examples_retriever(session).retrieve_for_context(
            context_or_issue,
            limit=5,
        )
        await message.answer(
            formatter.format_matches(
                chat_title=chat.title,
                chat_reference=reference if str(reference).startswith("@") else str(chat.telegram_chat_id),
                retrieval_result=retrieval,
            )
        )


@router.message(Command("style_profiles"))
@user_safe_handler("bot.style_profiles")
async def handle_style_profiles_command(
    message: Message,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await remember_owner_chat_if_private(message, session)
        service = _build_style_service(session)
        formatter = StyleFormatter()
        await message.answer(formatter.format_profiles(await service.list_profiles()))


@router.message(Command("style_set"))
@user_safe_handler("bot.style_set")
async def handle_style_set_command(
    message: Message,
    command: CommandObject,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await remember_owner_chat_if_private(message, session)
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
@user_safe_handler("bot.style_unset")
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
        await remember_owner_chat_if_private(message, session)
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
@user_safe_handler("bot.style_status")
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
        await remember_owner_chat_if_private(message, session)
        service = _build_style_service(session)
        formatter = StyleFormatter()
        try:
            report = await service.build_style_status(reference)
        except ValueError as error:
            await message.answer(str(error))
            return

    await message.answer(formatter.format_status(report))


@router.message(Command("digest_now"))
@user_safe_handler("bot.digest_now")
async def handle_digest_now_command(
    message: Message,
    command: CommandObject,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await remember_owner_chat_if_private(message, session)
        digest_repository = DigestRepository(session)
        engine = _build_digest_service(session)
        try:
            plan = await engine.build_manual_digest(command.args)
        except ValueError as error:
            await message.answer(str(error))
            return

        publish_result = await DigestPublisherService(digest_repository).publish(
            plan=plan,
            preview_chat_id=message.chat.id,
            sender=_require_message_sender(message.bot),
        )
        await session.commit()

    if publish_result.notice:
        await message.answer(publish_result.notice)


@router.message(Command("digest_llm"))
@user_safe_handler("bot.digest_llm")
async def handle_digest_llm_command(
    message: Message,
    command: CommandObject,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await remember_owner_chat_if_private(message, session)
        digest_repository = DigestRepository(session)
        engine = _build_digest_service(session)
        try:
            plan = await engine.build_manual_digest(
                command.args,
                use_provider_improvement=True,
            )
        except ValueError as error:
            await message.answer(str(error))
            return

        publish_result = await DigestPublisherService(digest_repository).publish(
            plan=plan,
            preview_chat_id=message.chat.id,
            sender=_require_message_sender(message.bot),
        )
        await session.commit()

    llm_notice = _build_digest_llm_notice(plan)
    if llm_notice:
        await message.answer(llm_notice)
    if publish_result.notice:
        await message.answer(publish_result.notice)


@router.message(Command("memory_rebuild"))
@user_safe_handler("bot.memory_rebuild")
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
        await remember_owner_chat_if_private(message, session)
        service = _build_memory_service(session)
        try:
            result = await service.rebuild(reference)
        except ValueError as error:
            await message.answer(str(error))
            return

        await session.commit()

    await message.answer(result.to_user_message())


@router.message(Command("chat_memory"))
@user_safe_handler("bot.chat_memory")
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
        await remember_owner_chat_if_private(message, session)
        service = _build_memory_service(session)
        await message.answer(await service.build_chat_memory_card(reference))


@router.message(Command("person_memory"))
@user_safe_handler("bot.person_memory")
async def handle_person_memory_command(
    message: Message,
    command: CommandObject,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    query = command.args.strip() if command.args and command.args.strip() else None

    async with session_factory() as session:
        await remember_owner_chat_if_private(message, session)
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
        await remember_owner_chat_if_private(message, session)
        service = SourceRegistryService(
            repository=ChatRepository(session),
            resolver=TelegramChatResolver(_require_aiogram_bot(message.bot)),
        )
        result = await service.set_source_enabled(reference, is_enabled=is_enabled)
        if result is None:
            await message.answer("Источник не найден. Проверь chat_id или @username.")
            return

        await session.commit()

    await message.answer(result.to_user_message())


def _build_status_service(session: AsyncSession) -> BotStatusService:
    return BotStatusService(
        settings=Settings(),
        chat_repository=ChatRepository(session),
        setting_repository=SettingRepository(session),
        system_repository=SystemRepository(session),
        message_repository=MessageRepository(session),
        digest_repository=DigestRepository(session),
        chat_memory_repository=ChatMemoryRepository(session),
        person_memory_repository=PersonMemoryRepository(session),
        style_profile_repository=StyleProfileRepository(session),
        chat_style_override_repository=ChatStyleOverrideRepository(session),
        task_repository=TaskRepository(session),
        reminder_repository=ReminderRepository(session),
        reply_example_repository=ReplyExampleRepository(session),
        provider_manager=_build_provider_manager(),
        fullaccess_auth_service=_build_fullaccess_auth_service(session),
    )


def _require_aiogram_bot(bot: Bot | None) -> Bot:
    if bot is None:
        raise RuntimeError("Aiogram bot недоступен в текущем апдейте.")
    return bot


def _require_message_sender(bot: Bot | None) -> MessageSenderProtocol:
    if bot is None:
        raise RuntimeError("Aiogram bot недоступен в текущем апдейте.")
    return cast(MessageSenderProtocol, bot)


def _build_fullaccess_auth_service(session: AsyncSession) -> FullAccessAuthService:
    settings = Settings()
    return FullAccessAuthService(
        settings=settings,
        setting_repository=SettingRepository(session),
        message_repository=MessageRepository(session),
    )


def _build_fullaccess_sync_service(session: AsyncSession) -> FullAccessSyncService:
    return FullAccessSyncService(
        settings=Settings(),
        chat_repository=ChatRepository(session),
        message_repository=MessageRepository(session),
        setting_repository=SettingRepository(session),
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
    provider_manager = _build_provider_manager()
    if isinstance(provider_manager, ProviderManager):
        provider_manager.setting_repository = setting_repository
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
        reply_examples_retriever=_build_reply_examples_retriever(session),
        reply_refiner=ReplyLLMRefiner(provider_manager=provider_manager),
        setting_repository=setting_repository,
    )


def _build_digest_service(session: AsyncSession) -> DigestEngineService:
    provider_manager = _build_provider_manager()
    if isinstance(provider_manager, ProviderManager):
        provider_manager.setting_repository = SettingRepository(session)
    return DigestEngineService(
        message_repository=MessageRepository(session),
        digest_repository=DigestRepository(session),
        setting_repository=SettingRepository(session),
        builder=DigestBuilder(),
        formatter=DigestFormatter(),
        digest_refiner=DigestLLMRefiner(
            provider_manager=provider_manager,
        ),
    )


def _build_reply_context_builder(session: AsyncSession) -> ReplyContextBuilder:
    message_repository = MessageRepository(session)
    chat_memory_repository = ChatMemoryRepository(session)
    person_memory_repository = PersonMemoryRepository(session)
    return ReplyContextBuilder(
        message_repository=message_repository,
        chat_memory_repository=chat_memory_repository,
        person_memory_repository=person_memory_repository,
    )


def _build_reply_examples_builder(session: AsyncSession) -> ReplyExamplesBuilder:
    return ReplyExamplesBuilder(
        chat_repository=ChatRepository(session),
        message_repository=MessageRepository(session),
        reply_example_repository=ReplyExampleRepository(session),
    )


def _build_reply_examples_retriever(session: AsyncSession) -> ReplyExamplesRetriever:
    return ReplyExamplesRetriever(
        reply_example_repository=ReplyExampleRepository(session),
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


def _build_provider_manager() -> ProviderManager:
    return ProviderManager.from_settings(Settings())


def _build_digest_llm_notice(plan) -> str | None:
    if not plan.llm_refine_requested:
        return None
    header = (
        f"LLM-improve: применён ({plan.llm_refine_provider or 'provider'})"
        if plan.llm_refine_applied
        else "LLM-improve: fallback, показан детерминированный digest."
    )
    notes = " ".join(plan.llm_refine_notes).strip()
    if plan.llm_refine_guardrail_flags:
        guardrails = ", ".join(plan.llm_refine_guardrail_flags)
        notes = f"{notes} Guardrails: {guardrails}.".strip()
    return "\n".join(line for line in (header, notes) if line)
