from __future__ import annotations

from dataclasses import dataclass, field

from services.providers.guardrails import ReplyRefinementGuardrails
from services.providers.manager import ProviderManager
from services.providers.models import LLMDecisionReason, ReplyRefinementCandidate
from services.providers.prompts import build_reply_refine_request


@dataclass(frozen=True, slots=True)
class ReplyRefinementOutcome:
    requested: bool
    applied: bool
    messages: tuple[str, ...]
    notes: tuple[str, ...]
    flags: tuple[str, ...]
    provider_name: str | None = None
    baseline_messages: tuple[str, ...] = ()
    raw_candidate_text: str | None = None
    decision_reason: LLMDecisionReason | None = None


@dataclass(slots=True)
class ReplyLLMRefiner:
    provider_manager: ProviderManager
    guardrails: ReplyRefinementGuardrails = field(default_factory=ReplyRefinementGuardrails)

    async def refine(
        self,
        *,
        context,
        style_selection,
        persona_state,
        baseline_messages: tuple[str, ...],
    ) -> ReplyRefinementOutcome:
        request = build_reply_refine_request(
            context=context,
            baseline_messages=baseline_messages,
            style_selection=style_selection,
            persona_state=persona_state,
        )
        execution = await self.provider_manager.rewrite_reply(request)
        provider_name = execution.provider_name
        if not execution.ok or not isinstance(execution.value, ReplyRefinementCandidate):
            detail = (
                f"{execution.reason or 'Provider refine недоступен.'} "
                "Показан детерминированный вариант."
            )
            return ReplyRefinementOutcome(
                requested=True,
                applied=False,
                messages=baseline_messages,
                notes=(detail,),
                flags=(),
                provider_name=provider_name,
                baseline_messages=baseline_messages,
                decision_reason=LLMDecisionReason(
                    source="provider",
                    code="provider_fallback",
                    summary="LLM refine не применён.",
                    detail=detail,
                ),
            )

        decision = self.guardrails.apply(
            candidate=execution.value,
            baseline_messages=baseline_messages,
            allowed_context=request.allowed_context,
            profile=style_selection.profile,
            persona_state=persona_state,
        )
        if decision.used_fallback:
            return ReplyRefinementOutcome(
                requested=True,
                applied=False,
                messages=decision.messages,
                notes=(
                    "LLM-кандидат отклонён guardrails, оставил детерминированный baseline.",
                ),
                flags=decision.flags,
                provider_name=provider_name,
                baseline_messages=baseline_messages,
                raw_candidate_text=execution.value.raw_text,
                decision_reason=decision.rejection,
            )
        return ReplyRefinementOutcome(
            requested=True,
            applied=True,
            messages=decision.messages,
            notes=(f"Аккуратно refine-нул baseline через {provider_name or 'provider'}.",),
            flags=decision.flags,
            provider_name=provider_name,
            baseline_messages=baseline_messages,
            raw_candidate_text=execution.value.raw_text,
        )
