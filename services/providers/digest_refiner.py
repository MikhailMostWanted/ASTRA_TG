from __future__ import annotations

from dataclasses import dataclass, field, replace

from services.digest_builder import DigestBuildResult
from services.providers.guardrails import DigestImprovementGuardrails
from services.providers.manager import ProviderManager
from services.providers.models import DigestImprovementCandidate, LLMDecisionReason
from services.providers.prompts import build_digest_improve_request


@dataclass(frozen=True, slots=True)
class DigestRefinementOutcome:
    requested: bool
    applied: bool
    build_result: DigestBuildResult
    notes: tuple[str, ...]
    flags: tuple[str, ...]
    provider_name: str | None = None
    baseline_summary_short: str | None = None
    baseline_overview_lines: tuple[str, ...] = ()
    baseline_key_source_lines: tuple[str, ...] = ()
    raw_candidate_text: str | None = None
    decision_reason: LLMDecisionReason | None = None


@dataclass(slots=True)
class DigestLLMRefiner:
    provider_manager: ProviderManager
    guardrails: DigestImprovementGuardrails = field(default_factory=DigestImprovementGuardrails)

    async def refine(self, build_result) -> DigestRefinementOutcome:
        request = build_digest_improve_request(build_result=build_result)
        execution = await self.provider_manager.improve_digest(request)
        provider_name = execution.provider_name
        if not execution.ok or not isinstance(execution.value, DigestImprovementCandidate):
            detail = (
                f"{execution.reason or 'Provider improve недоступен.'} "
                "Показан детерминированный digest."
            )
            return DigestRefinementOutcome(
                requested=True,
                applied=False,
                build_result=build_result,
                notes=(detail,),
                flags=(),
                provider_name=provider_name,
                baseline_summary_short=build_result.summary_short,
                baseline_overview_lines=tuple(build_result.overview_lines),
                baseline_key_source_lines=tuple(build_result.key_source_lines),
                decision_reason=LLMDecisionReason(
                    source="provider",
                    code="provider_fallback",
                    summary="LLM improve для digest не применён.",
                    detail=detail,
                ),
            )

        decision = self.guardrails.apply(
            candidate=execution.value,
            baseline_summary_short=request.baseline_summary_short,
            baseline_overview_lines=request.baseline_overview_lines,
            baseline_key_source_lines=request.baseline_key_source_lines,
            source_titles=request.source_titles,
        )
        if decision.used_fallback:
            return DigestRefinementOutcome(
                requested=True,
                applied=False,
                build_result=build_result,
                notes=(
                    "LLM-кандидат для digest отклонён guardrails, оставил детерминированный вариант.",
                ),
                flags=decision.flags,
                provider_name=provider_name,
                baseline_summary_short=build_result.summary_short,
                baseline_overview_lines=tuple(build_result.overview_lines),
                baseline_key_source_lines=tuple(build_result.key_source_lines),
                raw_candidate_text=execution.value.raw_text,
                decision_reason=decision.rejection,
            )

        refined_result = replace(
            build_result,
            summary_short=decision.summary_short,
            overview_lines=list(decision.overview_lines),
            key_source_lines=list(decision.key_source_lines),
        )
        return DigestRefinementOutcome(
            requested=True,
            applied=True,
            build_result=refined_result,
            notes=(f"Подчистил wording digest через {provider_name or 'provider'}.",),
            flags=decision.flags,
            provider_name=provider_name,
            baseline_summary_short=build_result.summary_short,
            baseline_overview_lines=tuple(build_result.overview_lines),
            baseline_key_source_lines=tuple(build_result.key_source_lines),
            raw_candidate_text=execution.value.raw_text,
        )
