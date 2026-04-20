from __future__ import annotations

from dataclasses import dataclass

from models import Chat, ChatMemory, Message, PersonMemory


@dataclass(frozen=True, slots=True)
class ReplyContextIssue:
    code: str
    message: str


@dataclass(frozen=True, slots=True)
class ReplyContext:
    chat: Chat
    recent_messages: tuple[Message, ...]
    latest_message: Message
    target_message: Message
    chat_memory: ChatMemory | None
    person_memory: PersonMemory | None
    linked_people: tuple[PersonMemory, ...]
    topic_hints: tuple[str, ...]
    pending_loops: tuple[str, ...]
    recent_conflicts: tuple[str, ...]

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
    alternative_action: str | None = None


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
    alternative_action: str | None = None

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
