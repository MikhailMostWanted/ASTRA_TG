from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


GLOBAL_JOURNAL_KEY = "workflow.journal.global"
CHAT_JOURNAL_PREFIX = "workflow.journal.chat."
DEFAULT_LIMIT = 12
MAX_STORED_EVENTS = 40


@dataclass(frozen=True, slots=True)
class WorkflowJournalEvent:
    timestamp: str
    action: str
    mode: str
    status: str
    actor: str
    automatic: bool
    message: str
    reason: str | None = None
    reason_code: str | None = None
    confidence: float | None = None
    trigger: str | None = None
    focus: str | None = None
    opportunity: str | None = None
    chat_id: int | None = None
    source_message_id: int | None = None
    sent_message_id: int | None = None
    text_preview: str | None = None
    chat_key: str | None = None
    runtime_chat_id: int | None = None
    backend: str | None = None
    draft_scope_key: str | None = None
    sent_message_key: str | None = None
    error_code: str | None = None
    execution_id: str | None = None
    allowed: bool | None = None

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "timestamp": self.timestamp,
            "action": self.action,
            "mode": self.mode,
            "status": self.status,
            "actor": self.actor,
            "automatic": self.automatic,
            "message": self.message,
            "reason": self.reason,
            "reason_code": self.reason_code,
            "reasonCode": self.reason_code,
            "confidence": self.confidence,
            "trigger": self.trigger,
            "focus": self.focus,
            "opportunity": self.opportunity,
            "chat_id": self.chat_id,
            "source_message_id": self.source_message_id,
            "sent_message_id": self.sent_message_id,
            "text_preview": self.text_preview,
            "chat_key": self.chat_key,
            "runtime_chat_id": self.runtime_chat_id,
            "backend": self.backend,
            "draft_scope_key": self.draft_scope_key,
            "sent_message_key": self.sent_message_key,
            "error_code": self.error_code,
            "execution_id": self.execution_id,
            "executionId": self.execution_id,
            "allowed": self.allowed,
        }
        return payload


@dataclass(slots=True)
class WorkflowJournalService:
    setting_repository: Any
    limit: int = DEFAULT_LIMIT

    async def append_chat_event(
        self,
        chat_id: int,
        event: WorkflowJournalEvent,
    ) -> None:
        await self._append_event(self._chat_key(chat_id), event)
        await self._append_event(GLOBAL_JOURNAL_KEY, event)

    async def list_chat_events(
        self,
        chat_id: int,
        *,
        limit: int | None = None,
    ) -> tuple[dict[str, Any], ...]:
        return await self._list_events(self._chat_key(chat_id), limit=limit)

    async def list_global_events(
        self,
        *,
        limit: int | None = None,
    ) -> tuple[dict[str, Any], ...]:
        return await self._list_events(GLOBAL_JOURNAL_KEY, limit=limit)

    async def _append_event(self, key: str, event: WorkflowJournalEvent) -> None:
        current = await self.setting_repository.get_value(key)
        events = [item for item in (current if isinstance(current, list) else []) if isinstance(item, dict)]
        events.insert(0, event.to_payload())
        await self.setting_repository.set_value(
            key=key,
            value_json=events[:MAX_STORED_EVENTS],
            value_text=None,
        )

    async def _list_events(
        self,
        key: str,
        *,
        limit: int | None = None,
    ) -> tuple[dict[str, Any], ...]:
        payload = await self.setting_repository.get_value(key)
        if not isinstance(payload, list):
            return ()
        normalized = [item for item in payload if isinstance(item, dict)]
        return tuple(normalized[: max(1, int(limit or self.limit))])

    def _chat_key(self, chat_id: int) -> str:
        return f"{CHAT_JOURNAL_PREFIX}{chat_id}"


def build_workflow_event(
    *,
    action: str,
    mode: str,
    status: str,
    actor: str,
    automatic: bool,
    message: str,
    reason: str | None = None,
    reason_code: str | None = None,
    confidence: float | None = None,
    trigger: str | None = None,
    focus: str | None = None,
    opportunity: str | None = None,
    chat_id: int | None = None,
    source_message_id: int | None = None,
    sent_message_id: int | None = None,
    text_preview: str | None = None,
    chat_key: str | None = None,
    runtime_chat_id: int | None = None,
    backend: str | None = None,
    draft_scope_key: str | None = None,
    sent_message_key: str | None = None,
    error_code: str | None = None,
    execution_id: str | None = None,
    allowed: bool | None = None,
) -> WorkflowJournalEvent:
    return WorkflowJournalEvent(
        timestamp=datetime.now(timezone.utc).isoformat(),
        action=action,
        mode=mode,
        status=status,
        actor=actor,
        automatic=automatic,
        message=message,
        reason=reason,
        reason_code=reason_code,
        confidence=confidence,
        trigger=trigger,
        focus=focus,
        opportunity=opportunity,
        chat_id=chat_id,
        source_message_id=source_message_id,
        sent_message_id=sent_message_id,
        text_preview=text_preview,
        chat_key=chat_key,
        runtime_chat_id=runtime_chat_id,
        backend=backend,
        draft_scope_key=draft_scope_key,
        sent_message_key=sent_message_key,
        error_code=error_code,
        execution_id=execution_id,
        allowed=allowed,
    )
