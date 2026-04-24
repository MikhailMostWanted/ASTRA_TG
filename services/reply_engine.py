from __future__ import annotations

from dataclasses import dataclass, field

from models import Chat
from core.logging import get_logger, log_event
from services.persona_adapter import PersonaAdapter
from services.persona_core import PersonaCoreService
from services.persona_guardrails import PersonaGuardrails
from services.providers.reply_refiner import ReplyLLMRefiner
from services.reply_context_builder import ReplyContextBuilder
from services.reply_examples_models import ReplyExamplesRetrievalResult
from services.reply_examples_retriever import ReplyExamplesRetriever
from services.reply_classifier import ReplyClassifier
from services.reply_models import ReplyContextIssue, ReplyResult, ReplySuggestion
from services.reply_strategy import ReplyStrategyResolver
from services.reply_variants import ReplyVariantBuilder
from services.style_adapter import StyleAdapter
from services.style_selector import StyleSelectorService
from storage.repositories import (
    ChatMemoryRepository,
    ChatRepository,
    MessageRepository,
    PersonMemoryRepository,
    SettingRepository,
)


LOGGER = get_logger(__name__)


@dataclass(slots=True)
class ReplyEngineService:
    """Legacy deterministic reply builder kept behind DraftReplyWorkspace.

    The migration target is a replaceable reply workspace/runtime. Keep new
    routing and product behavior outside this class unless it is required to
    preserve the current legacy path.
    """

    chat_repository: ChatRepository
    message_repository: MessageRepository
    chat_memory_repository: ChatMemoryRepository
    person_memory_repository: PersonMemoryRepository
    context_builder: ReplyContextBuilder
    classifier: ReplyClassifier
    strategy_resolver: ReplyStrategyResolver
    style_selector: StyleSelectorService
    style_adapter: StyleAdapter
    persona_core_service: PersonaCoreService
    persona_adapter: PersonaAdapter
    persona_guardrails: PersonaGuardrails
    reply_examples_retriever: ReplyExamplesRetriever | None = None
    reply_refiner: ReplyLLMRefiner | None = None
    setting_repository: SettingRepository | None = None
    variant_builder: ReplyVariantBuilder = field(default_factory=ReplyVariantBuilder)

    async def build_reply(
        self,
        reference: str,
        *,
        use_provider_refinement: bool | None = None,
        workspace_messages=None,
        source_backend: str | None = None,
        history_payload: dict[str, object] | None = None,
        freshness_payload: dict[str, object] | None = None,
        status_payload: dict[str, object] | None = None,
    ) -> ReplyResult:
        should_try_provider = await self._should_use_provider_refinement(use_provider_refinement)
        log_event(
            LOGGER,
            20,
            "reply.build.started",
            "Начата сборка reply.",
            reference=reference,
            llm_requested=should_try_provider,
        )
        chat = await self.chat_repository.find_chat_by_handle_or_telegram_id(reference)
        if chat is None:
            log_event(
                LOGGER,
                30,
                "reply.build.not_found",
                "Источник для reply не найден.",
                reference=reference,
            )
            return ReplyResult(
                kind="not_found",
                chat_id=None,
                chat_title=None,
                chat_reference=reference,
                error_message="Источник не найден. Проверь chat_id или @username.",
            )

        return await self.build_reply_for_chat(
            chat,
            reference=reference,
            use_provider_refinement=use_provider_refinement,
            workspace_messages=workspace_messages,
            source_backend=source_backend,
            history_payload=history_payload,
            freshness_payload=freshness_payload,
            status_payload=status_payload,
        )

    async def build_reply_for_chat(
        self,
        chat,
        *,
        reference: str | None = None,
        use_provider_refinement: bool | None = None,
        workspace_messages=None,
        source_backend: str | None = None,
        history_payload: dict[str, object] | None = None,
        freshness_payload: dict[str, object] | None = None,
        status_payload: dict[str, object] | None = None,
    ) -> ReplyResult:
        chat_reference = reference or _build_chat_reference(chat)
        should_try_provider = await self._should_use_provider_refinement(use_provider_refinement)
        context_or_issue = await self.context_builder.build(
            chat,
            recent_messages=workspace_messages,
            source_backend=source_backend,
            history_payload=history_payload,
            freshness_payload=freshness_payload,
            status_payload=status_payload,
        )
        if isinstance(context_or_issue, ReplyContextIssue):
            return ReplyResult(
                kind=context_or_issue.code,
                chat_id=chat.id,
                chat_title=chat.title,
                chat_reference=chat_reference,
                error_message=context_or_issue.message,
            )

        classification = self.classifier.classify(context_or_issue)
        if self.reply_examples_retriever is None:
            few_shot_support = ReplyExamplesRetrievalResult(
                matches=(),
                support_used=False,
                match_count=0,
                confidence_delta=0.0,
                strategy_bias=None,
                length_hint=None,
                rhythm_hint=None,
                opener_hint=None,
                dominant_topic_hint=None,
                notes=("Похожих реальных ответов не нашёл.",),
            )
        else:
            few_shot_support = await self.reply_examples_retriever.retrieve_for_context(
                context_or_issue,
                limit=5,
            )
        draft = self.strategy_resolver.resolve(
            context=context_or_issue,
            classification=classification,
            few_shot_support=few_shot_support,
        )
        style_selection = await self.style_selector.select_for_context(context_or_issue)
        styled_reply = self.style_adapter.adapt(
            draft_text=draft.base_reply_text,
            profile=style_selection.profile,
            strategy=draft.strategy,
            few_shot_support=few_shot_support,
        )
        persona_state = await self.persona_core_service.load_state()
        final_messages = styled_reply.messages
        guardrail_flags: tuple[str, ...] = ()
        persona_notes: tuple[str, ...]
        persona_applied = False
        if (
            persona_state.enabled
            and persona_state.core is not None
            and persona_state.guardrails is not None
        ):
            adapted_reply = self.persona_adapter.adapt(
                messages=styled_reply.messages,
                profile=style_selection.profile,
                persona_core=persona_state.core,
                strategy=draft.strategy,
            )
            guardrail_decision = self.persona_guardrails.apply(
                proposed_messages=adapted_reply.messages,
                fallback_messages=styled_reply.messages,
                profile=style_selection.profile,
                persona_core=persona_state.core,
                guardrails=persona_state.guardrails,
            )
            final_messages = guardrail_decision.messages
            guardrail_flags = guardrail_decision.flags
            persona_applied = adapted_reply.applied and not guardrail_decision.used_fallback
            notes = list(adapted_reply.notes)
            if guardrail_decision.used_fallback:
                notes.append("Guardrail вернул более безопасную style-aware серию.")
            elif guardrail_decision.flags:
                notes.append("Guardrail слегка поджал рискованные места.")
            persona_notes = tuple(notes)
        else:
            persona_notes = (
                ("Persona enrichment выключен.",)
                if not persona_state.enabled
                else ("Persona core не загружен, оставил style-aware серию.",)
            )

        llm_requested = False
        llm_applied = False
        llm_notes: tuple[str, ...] = ()
        llm_flags: tuple[str, ...] = ()
        llm_provider_name: str | None = None
        llm_baseline_messages = final_messages
        llm_raw_candidate: str | None = None
        llm_decision_reason = None
        llm_variants = ()
        if should_try_provider and self.reply_refiner is not None and classification.should_reply:
            refinement = await self.reply_refiner.refine(
                context=context_or_issue,
                style_selection=style_selection,
                persona_state=persona_state,
                baseline_messages=llm_baseline_messages,
                few_shot_support=few_shot_support,
                classification=classification,
            )
            llm_requested = refinement.requested
            llm_applied = refinement.applied
            llm_notes = refinement.notes
            llm_flags = refinement.flags
            llm_provider_name = refinement.provider_name
            llm_baseline_messages = refinement.baseline_messages or llm_baseline_messages
            llm_raw_candidate = refinement.raw_candidate_text
            llm_decision_reason = refinement.decision_reason
            final_messages = refinement.messages
            llm_variants = refinement.variants
            if llm_requested and not llm_applied:
                log_event(
                    LOGGER,
                    30,
                    "reply.provider.fallback",
                    "Улучшение ответа провайдером не применено, оставлена детерминированная база.",
                    reference=chat_reference,
                    provider_name=llm_provider_name,
                )

        variants = (
            self.variant_builder.build(
                final_messages=final_messages,
                baseline_messages=llm_baseline_messages,
                provider_variants=llm_variants,
                few_shot_support=few_shot_support,
                profile=style_selection.profile,
            )
            if classification.should_reply and draft.strategy != "не отвечать"
            else ()
        )

        log_event(
            LOGGER,
            20,
            "reply.build.completed",
            "Reply собран.",
            reference=chat_reference,
            applied_provider=llm_applied,
            style_profile=style_selection.profile.key,
        )
        return ReplyResult(
            kind="suggestion",
            chat_id=chat.id,
            chat_title=chat.title,
            chat_reference=chat_reference,
            suggestion=ReplySuggestion(
                base_reply_text=draft.base_reply_text,
                reply_messages=styled_reply.messages,
                final_reply_messages=final_messages,
                style_profile_key=style_selection.profile.key,
                style_source=style_selection.source,
                style_notes=styled_reply.notes,
                persona_applied=persona_applied,
                persona_notes=persona_notes,
                guardrail_flags=guardrail_flags,
                reason_short=draft.reason_short,
                risk_label=draft.risk_label,
                confidence=draft.confidence,
                strategy=draft.strategy,
                source_message_id=draft.source_message_id,
                chat_id=draft.chat_id,
                situation=draft.situation,
                source_message_preview=draft.source_message_preview,
                focus_label=draft.focus_label,
                focus_reason=draft.focus_reason,
                focus_score=draft.focus_score,
                selection_message_count=draft.selection_message_count,
                source_message_key=draft.source_message_key,
                source_local_message_id=draft.source_local_message_id,
                source_runtime_message_id=draft.source_runtime_message_id,
                source_backend=draft.source_backend,
                reply_opportunity_mode=context_or_issue.reply_opportunity_mode,
                reply_opportunity_reason=context_or_issue.reply_opportunity_reason,
                reply_recommended=classification.should_reply and draft.strategy != "не отвечать",
                few_shot_found=few_shot_support.support_used,
                few_shot_match_count=draft.few_shot_match_count,
                few_shot_notes=draft.few_shot_notes or few_shot_support.notes,
                few_shot_matches=draft.few_shot_matches,
                few_shot_strategy_bias=draft.few_shot_strategy_bias,
                few_shot_length_hint=draft.few_shot_length_hint,
                few_shot_rhythm_hint=draft.few_shot_rhythm_hint,
                few_shot_dominant_topic_hint=draft.few_shot_dominant_topic_hint,
                few_shot_message_count_hint=draft.few_shot_message_count_hint,
                few_shot_style_markers=draft.few_shot_style_markers,
                style_source_reason=style_selection.source_reason,
                alternative_action=draft.alternative_action,
                llm_refine_requested=llm_requested,
                llm_refine_applied=llm_applied,
                llm_refine_provider=llm_provider_name,
                llm_refine_notes=llm_notes,
                llm_refine_guardrail_flags=llm_flags,
                llm_refine_baseline_messages=llm_baseline_messages,
                llm_refine_raw_candidate=llm_raw_candidate,
                llm_refine_decision_reason=llm_decision_reason,
                variants=variants,
            ),
            source_sender_name=context_or_issue.target_message.sender_name,
            source_message_preview=draft.source_message_preview,
        )

    async def _should_use_provider_refinement(
        self,
        use_provider_refinement: bool | None,
    ) -> bool:
        if use_provider_refinement is not None:
            return use_provider_refinement
        if self.reply_refiner is None:
            return False
        status = await self.reply_refiner.provider_manager.get_status()
        return bool(status.reply_refine_available)


def _build_chat_reference(chat: Chat) -> str:
    if getattr(chat, "handle", None):
        return f"@{chat.handle}"
    return str(chat.telegram_chat_id)
