from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from core.logging import get_logger, log_event
from services.reply_signal import (
    has_emotional_signal,
    has_follow_up_commitment_signal,
    has_open_loop_signal,
    has_question_signal,
    has_request_signal,
    has_resolution_signal,
    is_weak_reply_signal,
)


LOGGER = get_logger(__name__)
DEFAULT_ACTIVE_REFRESH_SECONDS = 5
DEFAULT_ROSTER_REFRESH_SECONDS = 8
DEFAULT_ERROR_COOLDOWN_SECONDS = 20


@dataclass(frozen=True, slots=True)
class LiveRefreshResult:
    payload: dict[str, Any]
    event: dict[str, Any]
    execute_reply_modes: bool = False
    from_cache: bool = False


@dataclass(slots=True)
class LiveActiveChatState:
    chat_id: int
    paused: bool = False
    cached_workspace: dict[str, Any] | None = None
    last_message_keys: tuple[str, ...] = ()
    last_meaningful_signature: str | None = None
    last_refresh_at: datetime | None = None
    last_success_at: datetime | None = None
    last_error: str | None = None
    last_error_at: datetime | None = None
    degraded_until: datetime | None = None
    total_new_messages: int = 0
    total_meaningful_messages: int = 0
    last_reason_code: str | None = None
    last_action: str | None = None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)


@dataclass(slots=True)
class LiveRosterState:
    cached_roster: dict[str, Any] | None = None
    last_item_keys: dict[str, str | None] = field(default_factory=dict)
    last_refresh_at: datetime | None = None
    last_success_at: datetime | None = None
    last_error: str | None = None
    last_error_at: datetime | None = None
    degraded_until: datetime | None = None
    last_reason_code: str | None = None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)


class DesktopLiveCoordinator:
    """Coordinates cheap desktop polling without weakening reply/send safeguards."""

    def __init__(
        self,
        *,
        active_refresh_seconds: int = DEFAULT_ACTIVE_REFRESH_SECONDS,
        roster_refresh_seconds: int = DEFAULT_ROSTER_REFRESH_SECONDS,
        error_cooldown_seconds: int = DEFAULT_ERROR_COOLDOWN_SECONDS,
    ) -> None:
        self.active_refresh_seconds = max(2, active_refresh_seconds)
        self.roster_refresh_seconds = max(4, roster_refresh_seconds)
        self.error_cooldown_seconds = max(5, error_cooldown_seconds)
        self._active_states: dict[int, LiveActiveChatState] = {}
        self._roster_state = LiveRosterState()
        self._roster_states: dict[str, LiveRosterState] = {"default": self._roster_state}

    async def refresh_active_chat(
        self,
        *,
        chat_id: int,
        fetch_workspace: Callable[[], Awaitable[dict[str, Any]]],
        fetch_messages: Callable[[], Awaitable[dict[str, Any]]],
        force: bool = False,
        reason: str = "poll",
    ) -> LiveRefreshResult:
        state = self._active_states.setdefault(int(chat_id), LiveActiveChatState(chat_id=int(chat_id)))
        async with state.lock:
            now = _now()
            if state.paused and state.cached_workspace is not None and not force:
                event = self._active_event(
                    state=state,
                    status="paused",
                    reason_code="live_paused",
                    reason=reason,
                    started_at=now,
                    new_messages=0,
                    meaningful_messages=0,
                    reply_action="skipped",
                    source="cache",
                    record=True,
                )
                return LiveRefreshResult(
                    payload=_decorate_workspace_with_live(state.cached_workspace, event),
                    event=event,
                    from_cache=True,
                )

            cooldown_event = self._cooldown_event(state=state, now=now, reason=reason)
            if cooldown_event is not None and state.cached_workspace is not None and not force:
                return LiveRefreshResult(
                    payload=_decorate_workspace_with_live(state.cached_workspace, cooldown_event),
                    event=cooldown_event,
                    from_cache=True,
                )

            if (
                state.cached_workspace is not None
                and not force
                and state.last_refresh_at is not None
                and now - state.last_refresh_at < timedelta(seconds=self.active_refresh_seconds)
            ):
                event = self._active_event(
                    state=state,
                    status="cached",
                    reason_code="interval_not_due",
                    reason=reason,
                    started_at=now,
                    new_messages=0,
                    meaningful_messages=0,
                    reply_action="skipped",
                    source="cache",
                )
                return LiveRefreshResult(
                    payload=_decorate_workspace_with_live(state.cached_workspace, event),
                    event=event,
                    from_cache=True,
                )

            first_refresh = state.cached_workspace is None
            try:
                if first_refresh or force:
                    workspace = await fetch_workspace()
                    new_messages = _new_message_count(
                        previous_keys=state.last_message_keys,
                        messages=_message_payloads(workspace),
                    )
                    meaningful_messages = _meaningful_message_count(
                        previous_keys=state.last_message_keys,
                        messages=_message_payloads(workspace),
                    )
                    event = self._active_event(
                        state=state,
                        status="refreshed",
                        reason_code="initial_snapshot" if first_refresh else "manual_refresh",
                        reason=reason,
                        started_at=now,
                        new_messages=new_messages,
                        meaningful_messages=meaningful_messages,
                        reply_action="started",
                        source="workspace",
                        record=True,
                    )
                    self._record_active_success(state, workspace=workspace, event=event)
                    return LiveRefreshResult(
                        payload=_decorate_workspace_with_live(workspace, event),
                        event=event,
                        execute_reply_modes=True,
                    )

                messages_payload = await fetch_messages()
                merged = _merge_messages_payload_into_workspace(
                    state.cached_workspace,
                    messages_payload,
                )
                previous_keys = state.last_message_keys
                new_messages = _new_message_count(
                    previous_keys=previous_keys,
                    messages=_message_payloads(merged),
                )
                meaningful_messages = _meaningful_message_count(
                    previous_keys=previous_keys,
                    messages=_message_payloads(merged),
                )

                if meaningful_messages > 0:
                    workspace = await fetch_workspace()
                    event = self._active_event(
                        state=state,
                        status="refreshed",
                        reason_code="meaningful_signal",
                        reason=reason,
                        started_at=now,
                        new_messages=_new_message_count(
                            previous_keys=previous_keys,
                            messages=_message_payloads(workspace),
                        ),
                        meaningful_messages=_meaningful_message_count(
                            previous_keys=previous_keys,
                            messages=_message_payloads(workspace),
                        ),
                        reply_action="started",
                        source="workspace",
                        record=True,
                    )
                    self._record_active_success(state, workspace=workspace, event=event)
                    return LiveRefreshResult(
                        payload=_decorate_workspace_with_live(workspace, event),
                        event=event,
                        execute_reply_modes=True,
                    )

                reason_code = "no_new_signal" if new_messages > 0 else "no_new_messages"
                event = self._active_event(
                    state=state,
                    status="refreshed",
                    reason_code=reason_code,
                    reason=reason,
                    started_at=now,
                    new_messages=new_messages,
                    meaningful_messages=0,
                    reply_action="skipped",
                    source="messages",
                    record=new_messages > 0,
                )
                self._record_active_success(state, workspace=merged, event=event)
                return LiveRefreshResult(
                    payload=_decorate_workspace_with_live(merged, event),
                    event=event,
                    execute_reply_modes=False,
                )
            except Exception as error:
                event = self._record_active_error(state, error=error, started_at=now, reason=reason)
                if state.cached_workspace is not None:
                    return LiveRefreshResult(
                        payload=_decorate_workspace_with_live(state.cached_workspace, event),
                        event=event,
                        from_cache=True,
                    )
                raise

    async def refresh_roster(
        self,
        *,
        fetch_roster: Callable[[], Awaitable[dict[str, Any]]],
        force: bool = False,
        reason: str = "poll",
        cache_key: str = "default",
    ) -> LiveRefreshResult:
        state = self._roster_states.setdefault(_cache_key(cache_key), LiveRosterState())
        async with state.lock:
            now = _now()
            if (
                state.cached_roster is not None
                and state.degraded_until is not None
                and state.degraded_until > now
                and not force
            ):
                event = self._roster_event(
                    state=state,
                    status="degraded",
                    reason_code="error_cooldown",
                    reason=reason,
                    started_at=now,
                    changed_items=0,
                    source="cache",
                    record=True,
                )
                return LiveRefreshResult(
                    payload=_decorate_roster_with_live(state.cached_roster, event),
                    event=event,
                    from_cache=True,
                )

            if (
                state.cached_roster is not None
                and not force
                and state.last_refresh_at is not None
                and now - state.last_refresh_at < timedelta(seconds=self.roster_refresh_seconds)
            ):
                event = self._roster_event(
                    state=state,
                    status="cached",
                    reason_code="interval_not_due",
                    reason=reason,
                    started_at=now,
                    changed_items=0,
                    source="cache",
                )
                return LiveRefreshResult(
                    payload=_decorate_roster_with_live(state.cached_roster, event),
                    event=event,
                    from_cache=True,
                )

            try:
                payload = await fetch_roster()
            except Exception as error:
                event = self._record_roster_error(state, error=error, started_at=now, reason=reason)
                if state.cached_roster is not None:
                    return LiveRefreshResult(
                        payload=_decorate_roster_with_live(state.cached_roster, event),
                        event=event,
                        from_cache=True,
                    )
                raise

            changed_items = _count_changed_roster_items(state.last_item_keys, payload)
            event = self._roster_event(
                state=state,
                status="refreshed",
                reason_code="manual_refresh" if force else "roster_poll",
                reason=reason,
                started_at=now,
                changed_items=changed_items,
                source="roster",
                record=force or changed_items > 0,
            )
            state.cached_roster = payload
            state.last_item_keys = _roster_item_keys(payload)
            state.last_refresh_at = _now()
            state.last_success_at = state.last_refresh_at
            state.last_error = None
            state.last_error_at = None
            state.degraded_until = None
            state.last_reason_code = str(event["reasonCode"])
            return LiveRefreshResult(
                payload=_decorate_roster_with_live(payload, event),
                event=event,
            )

    def pause_active_chat(self, *, chat_id: int, paused: bool) -> dict[str, Any]:
        state = self._active_states.setdefault(int(chat_id), LiveActiveChatState(chat_id=int(chat_id)))
        state.paused = bool(paused)
        state.last_reason_code = "live_paused" if paused else "live_resumed"
        event = self._active_event(
            state=state,
            status="paused" if paused else "live",
            reason_code="live_paused" if paused else "live_resumed",
            reason="control",
            started_at=_now(),
            new_messages=0,
            meaningful_messages=0,
            reply_action="skipped",
            source="control",
            record=True,
        )
        return event

    def clear_errors(self, *, chat_id: int | None = None) -> dict[str, Any]:
        if chat_id is None:
            states = list(self._active_states.values())
            roster_states = list(self._roster_states.values())
        else:
            states = [self._active_states.setdefault(int(chat_id), LiveActiveChatState(chat_id=int(chat_id)))]
            roster_states = []
        for roster_state in roster_states:
            roster_state.last_error = None
            roster_state.last_error_at = None
            roster_state.degraded_until = None
            roster_state.last_reason_code = "error_cleared"
        for state in states:
            state.last_error = None
            state.last_error_at = None
            state.degraded_until = None
            state.last_reason_code = "error_cleared"
        return {
            "timestamp": _serialize(_now()),
            "scope": "all" if chat_id is None else "active_chat",
            "chatId": chat_id,
            "status": "cleared",
            "reasonCode": "error_cleared",
        }

    def update_active_payload(self, *, chat_id: int, workspace: dict[str, Any]) -> None:
        state = self._active_states.setdefault(int(chat_id), LiveActiveChatState(chat_id=int(chat_id)))
        state.cached_workspace = workspace
        state.last_message_keys = _message_keys(_message_payloads(workspace))
        state.last_meaningful_signature = _meaningful_signature(_message_payloads(workspace))

    def _cooldown_event(
        self,
        *,
        state: LiveActiveChatState,
        now: datetime,
        reason: str,
    ) -> dict[str, Any] | None:
        if state.degraded_until is None or state.degraded_until <= now:
            return None
        return self._active_event(
            state=state,
            status="degraded",
            reason_code="error_cooldown",
            reason=reason,
            started_at=now,
            new_messages=0,
            meaningful_messages=0,
            reply_action="skipped",
            source="cache",
            record=True,
        )

    def _record_active_success(
        self,
        state: LiveActiveChatState,
        *,
        workspace: dict[str, Any],
        event: dict[str, Any],
    ) -> None:
        completed_at = _now()
        state.cached_workspace = workspace
        state.last_message_keys = _message_keys(_message_payloads(workspace))
        state.last_meaningful_signature = _meaningful_signature(_message_payloads(workspace))
        state.last_refresh_at = completed_at
        state.last_success_at = completed_at
        state.last_error = None
        state.last_error_at = None
        state.degraded_until = None
        state.total_new_messages += int(event.get("newMessageCount") or 0)
        state.total_meaningful_messages += int(event.get("meaningfulMessageCount") or 0)
        state.last_reason_code = str(event.get("reasonCode") or "")
        state.last_action = str(event.get("replyAction") or "")
        log_event(
            LOGGER,
            logging.INFO,
            "desktop.live.active_refresh",
            "Live active chat refresh завершён.",
            chat_id=state.chat_id,
            status=event.get("status"),
            reason_code=event.get("reasonCode"),
            new_messages=event.get("newMessageCount"),
            meaningful_messages=event.get("meaningfulMessageCount"),
            latency_ms=event.get("latencyMs"),
        )

    def _record_active_error(
        self,
        state: LiveActiveChatState,
        *,
        error: Exception,
        started_at: datetime,
        reason: str,
    ) -> dict[str, Any]:
        now = _now()
        state.last_refresh_at = now
        state.last_error = str(error)
        state.last_error_at = now
        state.degraded_until = now + timedelta(seconds=self.error_cooldown_seconds)
        state.last_reason_code = "refresh_error"
        event = self._active_event(
            state=state,
            status="degraded",
            reason_code="refresh_error",
            reason=reason,
            started_at=started_at,
            new_messages=0,
            meaningful_messages=0,
            reply_action="skipped",
            source="error",
            error=str(error),
            record=True,
        )
        log_event(
            LOGGER,
            logging.WARNING,
            "desktop.live.active_refresh_failed",
            "Live active chat refresh завершился ошибкой.",
            chat_id=state.chat_id,
            error=str(error),
            latency_ms=event.get("latencyMs"),
        )
        return event

    def _record_roster_error(
        self,
        state: LiveRosterState,
        *,
        error: Exception,
        started_at: datetime,
        reason: str,
    ) -> dict[str, Any]:
        now = _now()
        state.last_refresh_at = now
        state.last_error = str(error)
        state.last_error_at = now
        state.degraded_until = now + timedelta(seconds=self.error_cooldown_seconds)
        state.last_reason_code = "refresh_error"
        event = self._roster_event(
            state=state,
            status="degraded",
            reason_code="refresh_error",
            reason=reason,
            started_at=started_at,
            changed_items=0,
            source="error",
            error=str(error),
            record=True,
        )
        log_event(
            LOGGER,
            logging.WARNING,
            "desktop.live.roster_refresh_failed",
            "Live roster refresh завершился ошибкой.",
            error=str(error),
            latency_ms=event.get("latencyMs"),
        )
        return event

    def _active_event(
        self,
        *,
        state: LiveActiveChatState,
        status: str,
        reason_code: str,
        reason: str,
        started_at: datetime,
        new_messages: int,
        meaningful_messages: int,
        reply_action: str,
        source: str,
        error: str | None = None,
        record: bool = False,
    ) -> dict[str, Any]:
        now = _now()
        return {
            "scope": "active_chat",
            "source": "desktop_live_coordinator",
            "status": status,
            "active": status != "paused",
            "paused": state.paused,
            "reason": reason,
            "reasonCode": reason_code,
            "chatId": state.chat_id,
            "newMessageCount": max(0, int(new_messages)),
            "meaningfulMessageCount": max(0, int(meaningful_messages)),
            "totalNewMessageCount": state.total_new_messages + max(0, int(new_messages)),
            "totalMeaningfulMessageCount": state.total_meaningful_messages + max(0, int(meaningful_messages)),
            "replyAction": reply_action,
            "replySkippedReason": reason_code if reply_action == "skipped" else None,
            "refreshSource": source,
            "syncing": False,
            "lastUpdatedAt": _serialize(now if status not in {"cached", "paused"} else state.last_refresh_at),
            "lastSuccessAt": _serialize(state.last_success_at),
            "lastError": error or state.last_error,
            "lastErrorAt": _serialize(state.last_error_at),
            "degraded": status == "degraded" or bool(error or state.last_error),
            "degradedUntil": _serialize(state.degraded_until),
            "nextRefreshAfter": _serialize(now + timedelta(seconds=self.active_refresh_seconds)),
            "intervalSeconds": self.active_refresh_seconds,
            "latencyMs": _latency_ms(started_at),
            "record": record,
            "timestamp": _serialize(now),
        }

    def _roster_event(
        self,
        *,
        state: LiveRosterState,
        status: str,
        reason_code: str,
        reason: str,
        started_at: datetime,
        changed_items: int,
        source: str,
        error: str | None = None,
        record: bool = False,
    ) -> dict[str, Any]:
        now = _now()
        return {
            "scope": "roster",
            "source": "desktop_live_coordinator",
            "status": status,
            "reason": reason,
            "reasonCode": reason_code,
            "changedItemCount": max(0, int(changed_items)),
            "refreshSource": source,
            "syncing": False,
            "lastUpdatedAt": _serialize(now if status != "cached" else state.last_refresh_at),
            "lastSuccessAt": _serialize(state.last_success_at),
            "lastError": error or state.last_error,
            "lastErrorAt": _serialize(state.last_error_at),
            "degraded": status == "degraded" or bool(error or state.last_error),
            "degradedUntil": _serialize(state.degraded_until),
            "nextRefreshAfter": _serialize(now + timedelta(seconds=self.roster_refresh_seconds)),
            "intervalSeconds": self.roster_refresh_seconds,
            "latencyMs": _latency_ms(started_at),
            "record": record,
            "timestamp": _serialize(now),
        }


def _decorate_workspace_with_live(payload: dict[str, Any], event: dict[str, Any]) -> dict[str, Any]:
    decorated = dict(payload)
    live = dict(event)
    decorated["live"] = live
    status = dict(decorated.get("status") if isinstance(decorated.get("status"), dict) else {})
    status["live"] = live
    if live.get("lastError") and not status.get("syncError"):
        status["syncError"] = live.get("lastError")
    if live.get("degraded"):
        status["degraded"] = True
        status["degradedReason"] = status.get("degradedReason") or live.get("lastError")
    decorated["status"] = status
    return decorated


def _decorate_roster_with_live(payload: dict[str, Any], event: dict[str, Any]) -> dict[str, Any]:
    decorated = dict(payload)
    live = dict(event)
    decorated["live"] = live
    roster = dict(decorated.get("roster") if isinstance(decorated.get("roster"), dict) else {})
    roster["live"] = live
    if live.get("lastError") and not roster.get("lastError"):
        roster["lastError"] = live.get("lastError")
    if live.get("degraded"):
        roster["degraded"] = True
        roster["degradedReason"] = roster.get("degradedReason") or live.get("lastError")
    decorated["roster"] = roster
    return decorated


def _merge_messages_payload_into_workspace(
    workspace: dict[str, Any] | None,
    messages_payload: dict[str, Any],
) -> dict[str, Any]:
    if workspace is None:
        return dict(messages_payload)
    merged = dict(workspace)
    for key in ("chat", "messages", "history", "status", "refreshedAt"):
        if key in messages_payload:
            merged[key] = messages_payload[key]
    freshness = dict(merged.get("freshness") if isinstance(merged.get("freshness"), dict) else {})
    status = messages_payload.get("status") if isinstance(messages_payload.get("status"), dict) else {}
    if status:
        freshness["lastSyncAt"] = status.get("lastUpdatedAt") or messages_payload.get("refreshedAt")
        freshness["syncTrigger"] = status.get("syncTrigger")
        freshness["updatedNow"] = bool(status.get("updatedNow"))
        freshness["syncError"] = status.get("syncError")
    merged["freshness"] = freshness
    return merged


def _message_payloads(payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(payload, dict) or not isinstance(payload.get("messages"), list):
        return []
    return [item for item in payload["messages"] if isinstance(item, dict)]


def _message_keys(messages: list[dict[str, Any]]) -> tuple[str, ...]:
    keys: list[str] = []
    for message in messages:
        key = message.get("messageKey")
        if isinstance(key, str) and key.strip():
            keys.append(key)
            continue
        runtime_id = message.get("runtimeMessageId")
        if isinstance(runtime_id, int):
            keys.append(str(runtime_id))
    return tuple(keys)


def _new_message_count(*, previous_keys: tuple[str, ...], messages: list[dict[str, Any]]) -> int:
    previous = set(previous_keys)
    return sum(1 for key in _message_keys(messages) if key not in previous)


def _meaningful_message_count(*, previous_keys: tuple[str, ...], messages: list[dict[str, Any]]) -> int:
    previous = set(previous_keys)
    return sum(
        1
        for message in messages
        if _message_identity(message) not in previous and _is_meaningful_message(message)
    )


def _meaningful_signature(messages: list[dict[str, Any]]) -> str | None:
    for message in reversed(messages):
        if _is_meaningful_message(message):
            return _message_identity(message)
    return None


def _message_identity(message: dict[str, Any]) -> str:
    key = message.get("messageKey")
    if isinstance(key, str) and key.strip():
        return key
    runtime_id = message.get("runtimeMessageId")
    if isinstance(runtime_id, int):
        return str(runtime_id)
    return ""


def _is_meaningful_message(message: dict[str, Any]) -> bool:
    text = _message_text(message)
    if bool(message.get("hasMedia")) and message.get("direction") == "inbound":
        return True
    if not text:
        return False
    if is_weak_reply_signal(text):
        return False
    if message.get("direction") == "outbound":
        return (
            has_resolution_signal(text)
            or has_follow_up_commitment_signal(text)
            or len(text) >= 24
        )
    return (
        has_question_signal(text)
        or has_request_signal(text)
        or has_open_loop_signal(text)
        or has_emotional_signal(text)
        or len(text) >= 24
    )


def _message_text(message: dict[str, Any]) -> str:
    for key in ("text", "normalizedText", "preview"):
        value = message.get(key)
        if isinstance(value, str) and value.strip():
            return " ".join(value.split()).strip()
    return ""


def _roster_item_keys(payload: dict[str, Any]) -> dict[str, str | None]:
    items = payload.get("items") if isinstance(payload.get("items"), list) else []
    result: dict[str, str | None] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        chat_key = item.get("chatKey")
        if not isinstance(chat_key, str) or not chat_key.strip():
            continue
        last_key = item.get("rosterLastMessageKey") or item.get("lastMessageKey")
        result[chat_key] = last_key if isinstance(last_key, str) else None
    return result


def _count_changed_roster_items(previous: dict[str, str | None], payload: dict[str, Any]) -> int:
    current = _roster_item_keys(payload)
    changed = 0
    for chat_key, last_key in current.items():
        if chat_key not in previous or previous.get(chat_key) != last_key:
            changed += 1
    return changed


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _cache_key(value: str) -> str:
    normalized = " ".join(str(value or "default").split()).strip()
    return normalized or "default"


def _serialize(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc).isoformat()
    return value.astimezone(timezone.utc).isoformat()


def _latency_ms(started_at: datetime) -> int:
    return max(0, int((_now() - started_at).total_seconds() * 1000))
