from __future__ import annotations

from dataclasses import dataclass, field

from services.providers.guardrails import ReplyRefinementGuardrails
from services.providers.manager import ProviderManager
from services.providers.models import LLMDecisionReason, ReplyRefinementCandidate
from services.providers.prompts import build_reply_refine_request
from services.reply_models import ReplyVariant
from services.reply_postprocessor import normalize_variant_id, postprocess_variant_text


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
    variants: tuple[ReplyVariant, ...] = ()


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
        few_shot_support=None,
        classification=None,
    ) -> ReplyRefinementOutcome:
        request = build_reply_refine_request(
            context=context,
            baseline_messages=baseline_messages,
            style_selection=style_selection,
            persona_state=persona_state,
            few_shot_support=few_shot_support,
            classification=classification,
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
                    summary="LLM-улучшение не применено.",
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
                variants=_convert_variants(execution.value),
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
            variants=_convert_variants(execution.value),
        )


def _convert_variants(candidate: ReplyRefinementCandidate) -> tuple[ReplyVariant, ...]:
    labels = {
        "primary": ("Основной", "Главный живой вариант для отправки."),
        "short": ("Короче", "Более короткая версия без воды."),
        "soft": ("Мягче", "Более мягкая и аккуратная подача."),
        "owner_style": ("В моём стиле", "Более разговорный и каскадный ритм."),
    }
    variants: list[ReplyVariant] = []
    for item in candidate.variants:
        variant_id = normalize_variant_id(item.id)
        cleaned = postprocess_variant_text(item.text, variant_id=variant_id)
        if not cleaned:
            continue
        label, description = labels.get(variant_id, ("Вариант", "Рабочая версия ответа."))
        variants.append(
            ReplyVariant(
                id=variant_id,
                label=label,
                description=description,
                text=cleaned,
            )
        )
    return tuple(variants)
