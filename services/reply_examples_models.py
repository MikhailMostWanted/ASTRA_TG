from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class ReplyExamplesRebuildResult:
    examples_created: int
    chats_processed: int
    messages_scanned: int
    scope_reference: str | None = None


@dataclass(frozen=True, slots=True)
class ReplyExampleMatch:
    id: int
    chat_id: int
    chat_title: str
    inbound_text: str
    outbound_text: str
    example_type: str
    source_person_key: str | None
    quality_score: float
    score: float
    created_at: datetime
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ReplyExamplesRetrievalResult:
    matches: tuple[ReplyExampleMatch, ...]
    support_used: bool
    match_count: int
    confidence_delta: float
    strategy_bias: str | None
    length_hint: str | None
    rhythm_hint: str | None
    opener_hint: str | None
    dominant_topic_hint: str | None
    notes: tuple[str, ...]

    @property
    def top_score(self) -> float | None:
        if not self.matches:
            return None
        return self.matches[0].score
