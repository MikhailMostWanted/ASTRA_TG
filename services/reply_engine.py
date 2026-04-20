from __future__ import annotations

from dataclasses import dataclass

from services.reply_context_builder import ReplyContextBuilder
from services.reply_classifier import ReplyClassifier
from services.reply_models import ReplyResult
from services.reply_strategy import ReplyStrategyResolver
from storage.repositories import ChatMemoryRepository, ChatRepository, MessageRepository, PersonMemoryRepository


@dataclass(slots=True)
class ReplyEngineService:
    chat_repository: ChatRepository
    message_repository: MessageRepository
    chat_memory_repository: ChatMemoryRepository
    person_memory_repository: PersonMemoryRepository
    context_builder: ReplyContextBuilder
    classifier: ReplyClassifier
    strategy_resolver: ReplyStrategyResolver

    async def build_reply(self, reference: str) -> ReplyResult:
        chat = await self.chat_repository.find_chat_by_handle_or_telegram_id(reference)
        if chat is None:
            return ReplyResult(
                kind="not_found",
                chat_id=None,
                chat_title=None,
                chat_reference=reference,
                error_message="Источник не найден. Проверь chat_id или @username.",
            )

        context_or_issue = await self.context_builder.build(chat)
        if hasattr(context_or_issue, "code"):
            return ReplyResult(
                kind=context_or_issue.code,
                chat_id=chat.id,
                chat_title=chat.title,
                chat_reference=_build_chat_reference(chat),
                error_message=context_or_issue.message,
            )

        classification = self.classifier.classify(context_or_issue)
        suggestion = self.strategy_resolver.resolve(
            context=context_or_issue,
            classification=classification,
        )
        return ReplyResult(
            kind="suggestion",
            chat_id=chat.id,
            chat_title=chat.title,
            chat_reference=_build_chat_reference(chat),
            suggestion=suggestion,
            source_sender_name=context_or_issue.target_message.sender_name,
            source_message_preview=suggestion.source_message_preview,
        )


def _build_chat_reference(chat) -> str:
    if getattr(chat, "handle", None):
        return f"@{chat.handle}"
    return str(chat.telegram_chat_id)
