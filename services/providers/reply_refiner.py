from __future__ import annotations

from dataclasses import dataclass, field

from services.providers.guardrails import ReplyRefinementGuardrails
from services.providers.manager import ProviderManager
from services.providers.models import ReplyRefinementCandidate
from services.providers.prompts import build_reply_refine_request


@dataclass(frozen=True, slots=True)
class ReplyRefinementOutcome:
    requested: bool
    applied: bool
    messages: tuple[str, ...]
    notes: tuple[str, ...]
    flags: tuple[str, ...]
    provider_name: str | None = None


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
            return ReplyRefinementOutcome(
                requested=True,
                applied=False,
                messages=baseline_messages,
                notes=(
                    f"{execution.reason or 'Provider refine недоступен.'} Показан детерминированный вариант.",
                ),
                flags=(),
                provider_name=provider_name,
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
            )
        return ReplyRefinementOutcome(
            requested=True,
            applied=True,
            messages=decision.messages,
            notes=(f"Аккуратно refine-нул baseline через {provider_name or 'provider'}.",),
            flags=decision.flags,
            provider_name=provider_name,
        )
