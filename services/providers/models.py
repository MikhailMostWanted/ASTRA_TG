from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ProviderTask(str, Enum):
    REWRITE_REPLY = "rewrite_reply"
    IMPROVE_DIGEST = "improve_digest"
    SUMMARIZE_MESSAGES = "summarize_messages"
    ANALYZE_CONTEXT = "analyze_context"


@dataclass(frozen=True, slots=True)
class ProviderPrompt:
    task: ProviderTask
    system_instructions: str
    user_input: str
    response_format: str = "text"


@dataclass(frozen=True, slots=True)
class RewriteReplyRequest:
    prompt: ProviderPrompt
    baseline_messages: tuple[str, ...]
    allowed_context: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DigestImproveRequest:
    prompt: ProviderPrompt
    baseline_summary_short: str
    baseline_overview_lines: tuple[str, ...]
    baseline_key_source_lines: tuple[str, ...]
    source_titles: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SummarizeMessagesRequest:
    prompt: ProviderPrompt


@dataclass(frozen=True, slots=True)
class AnalyzeContextRequest:
    prompt: ProviderPrompt


@dataclass(frozen=True, slots=True)
class ReplyRefinementCandidate:
    messages: tuple[str, ...]
    raw_text: str
    model_name: str | None = None


@dataclass(frozen=True, slots=True)
class LLMDecisionReason:
    source: str
    code: str
    summary: str
    detail: str
    flags: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class DigestImprovementCandidate:
    summary_short: str
    overview_lines: tuple[str, ...]
    key_source_lines: tuple[str, ...]
    raw_text: str
    model_name: str | None = None


@dataclass(frozen=True, slots=True)
class ProviderExecutionResult:
    ok: bool
    reason: str | None = None
    value: object | None = None
    provider_name: str | None = None

    @classmethod
    def success(
        cls,
        value: object,
        *,
        provider_name: str | None = None,
        reason: str | None = None,
    ) -> "ProviderExecutionResult":
        return cls(
            ok=True,
            reason=reason,
            value=value,
            provider_name=provider_name,
        )

    @classmethod
    def failure(
        cls,
        reason: str,
        *,
        provider_name: str | None = None,
    ) -> "ProviderExecutionResult":
        return cls(
            ok=False,
            reason=reason,
            value=None,
            provider_name=provider_name,
        )


@dataclass(frozen=True, slots=True)
class ProviderStatus:
    enabled: bool
    configured: bool
    provider_name: str | None
    model_fast: str | None
    model_deep: str | None
    timeout_seconds: float
    available: bool
    reason: str
    reply_refine_enabled: bool
    digest_refine_enabled: bool
    reply_refine_available: bool
    digest_refine_available: bool
    api_checked: bool = False
