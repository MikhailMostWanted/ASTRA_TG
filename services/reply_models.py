from __future__ import annotations

from dataclasses import dataclass

from models import Chat, ChatMemory, Message, PersonMemory
from services.providers.models import LLMDecisionReason


@dataclass(frozen=True, slots=True)
class ReplyContextIssue:
    code: str
    message: str


@dataclass(frozen=True, slots=True)
class ReplyContext:
    chat: Chat
    recent_messages: tuple[Message, ...]
    working_messages: tuple[Message, ...]
    broader_tail_messages: tuple[Message, ...]
    latest_message: Message
    target_message: Message
    focus_label: str
    focus_reason: str
    focus_score: float
    chat_memory: ChatMemory | None
    person_memory: PersonMemory | None
    linked_people: tuple[PersonMemory, ...]
    topic_hints: tuple[str, ...]
    pending_loops: tuple[str, ...]
    recent_conflicts: tuple[str, ...]
    unanswered_questions: tuple[str, ...]
    pending_promises: tuple[str, ...]
    emotional_signals: tuple[str, ...]
    local_dynamics: tuple[str, ...]
    reply_opportunity_mode: str
    reply_opportunity_reason: str

    @property
    def has_memory_support(self) -> bool:
        return self.chat_memory is not None or self.person_memory is not None or bool(self.linked_people)


@dataclass(frozen=True, slots=True)
class ReplyClassification:
    situation: str
    reason: str
    has_question: bool
    has_request: bool
    has_tension: bool
    should_reply: bool
    needs_softness: bool
    topic_hint: str | None


@dataclass(frozen=True, slots=True)
class ReplyDraft:
    base_reply_text: str
    reason_short: str
    risk_label: str
    confidence: float
    strategy: str
    source_message_id: int
    chat_id: int
    situation: str
    source_message_preview: str
    focus_label: str
    focus_reason: str
    few_shot_match_count: int = 0
    few_shot_notes: tuple[str, ...] = ()
    alternative_action: str | None = None


@dataclass(frozen=True, slots=True)
class ReplyVariant:
    id: str
    label: str
    description: str
    text: str


@dataclass(frozen=True, slots=True)
class ReplySuggestion:
    base_reply_text: str
    reply_messages: tuple[str, ...]
    final_reply_messages: tuple[str, ...]
    style_profile_key: str
    style_source: str
    style_notes: tuple[str, ...]
    persona_applied: bool
    persona_notes: tuple[str, ...]
    guardrail_flags: tuple[str, ...]
    reason_short: str
    risk_label: str
    confidence: float
    strategy: str
    source_message_id: int
    chat_id: int
    situation: str
    source_message_preview: str
    focus_label: str
    focus_reason: str
    reply_opportunity_mode: str
    reply_opportunity_reason: str
    few_shot_found: bool
    few_shot_match_count: int
    few_shot_notes: tuple[str, ...]
    alternative_action: str | None = None
    llm_refine_requested: bool = False
    llm_refine_applied: bool = False
    llm_refine_provider: str | None = None
    llm_refine_notes: tuple[str, ...] = ()
    llm_refine_guardrail_flags: tuple[str, ...] = ()
    llm_refine_baseline_messages: tuple[str, ...] = ()
    llm_refine_raw_candidate: str | None = None
    llm_refine_decision_reason: LLMDecisionReason | None = None
    variants: tuple[ReplyVariant, ...] = ()

    @property
    def reply_text(self) -> str:
        if self.final_reply_messages:
            return "\n".join(self.final_reply_messages)
        if self.reply_messages:
            return "\n".join(self.reply_messages)
        return self.base_reply_text


@dataclass(frozen=True, slots=True)
class ReplyResult:
    kind: str
    chat_id: int | None
    chat_title: str | None
    chat_reference: str | None
    suggestion: ReplySuggestion | None = None
    error_message: str | None = None
    source_sender_name: str | None = None
    source_message_preview: str | None = None
