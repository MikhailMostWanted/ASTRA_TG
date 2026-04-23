from __future__ import annotations

from services.persona_adapter import PersonaAdapter
from services.persona_core import PersonaCoreService
from services.persona_guardrails import PersonaGuardrails
from services.providers.manager import ProviderManager
from services.providers.reply_refiner import ReplyLLMRefiner
from services.reply_classifier import ReplyClassifier
from services.reply_context_builder import ReplyContextBuilder
from services.reply_engine import ReplyEngineService
from services.reply_examples_retriever import ReplyExamplesRetriever
from services.reply_strategy import ReplyStrategyResolver
from services.style_adapter import StyleAdapter
from services.style_selector import StyleSelectorService
from storage.repositories import (
    ChatMemoryRepository,
    ChatRepository,
    ChatStyleOverrideRepository,
    MessageRepository,
    PersonMemoryRepository,
    ReplyExampleRepository,
    SettingRepository,
    StyleProfileRepository,
)


def build_reply_service(settings, session) -> ReplyEngineService:
    message_repository = MessageRepository(session)
    chat_memory_repository = ChatMemoryRepository(session)
    person_memory_repository = PersonMemoryRepository(session)
    setting_repository = SettingRepository(session)
    provider_manager = ProviderManager.from_settings(
        settings,
        setting_repository=setting_repository,
    )
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
        reply_examples_retriever=ReplyExamplesRetriever(
            reply_example_repository=ReplyExampleRepository(session),
        ),
        reply_refiner=ReplyLLMRefiner(provider_manager=provider_manager),
        setting_repository=setting_repository,
    )
