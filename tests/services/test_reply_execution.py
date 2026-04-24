from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from services.reply_execution import (
    ReplyExecutionChatPolicy,
    ReplyExecutionContext,
    ReplyExecutionGlobalPolicy,
    ReplyExecutionStateMachine,
    ReplyExecutionTransitionError,
)


def test_reply_execution_state_machine_transitions_are_explicit() -> None:
    machine = ReplyExecutionStateMachine()

    assert machine.next_status("idle", "prepare_draft") == "suggestion_ready"
    assert machine.next_status("idle", "await_confirm") == "awaiting_confirmation"
    assert machine.next_status("awaiting_confirmation", "confirm") == "sending"
    assert machine.next_status("awaiting_confirmation", "duplicate") == "awaiting_confirmation"
    assert machine.next_status("sending", "send_succeeded") == "sent"
    assert machine.next_status("sent", "cooldown_start") == "cooldown"

    with pytest.raises(ReplyExecutionTransitionError):
        machine.next_status("idle", "confirm")


def test_reply_execution_policy_defaults_are_safe_and_capped_by_global_mode() -> None:
    machine = ReplyExecutionStateMachine()
    context = _context()
    default_chat = ReplyExecutionChatPolicy(
        chat_key="telegram:-1001",
        requested_chat_id=1,
        runtime_chat_id=-1001,
        local_chat_id=1,
    )

    global_off = machine.evaluate(
        global_policy=ReplyExecutionGlobalPolicy(),
        chat_policy=default_chat,
        state={},
        context=context,
    )
    assert global_off.allowed is False
    assert global_off.reason_code == "global_mode_off"

    capped = machine.evaluate(
        global_policy=ReplyExecutionGlobalPolicy(mode="draft"),
        chat_policy=ReplyExecutionChatPolicy(
            chat_key="telegram:-1001",
            requested_chat_id=1,
            runtime_chat_id=-1001,
            local_chat_id=1,
            mode="autopilot",
            trusted=True,
            autopilot_allowed=True,
        ),
        state={},
        context=context,
    )
    assert capped.allowed is True
    assert capped.action == "draft"
    assert capped.effective_mode == "draft"


def test_reply_execution_safeguards_block_weak_low_confidence_untrusted_and_unavailable_send() -> None:
    machine = ReplyExecutionStateMachine()
    global_policy = ReplyExecutionGlobalPolicy(mode="autopilot")
    autopilot_chat = ReplyExecutionChatPolicy(
        chat_key="telegram:-1001",
        requested_chat_id=1,
        runtime_chat_id=-1001,
        local_chat_id=1,
        mode="autopilot",
        trusted=True,
        autopilot_allowed=True,
    )

    untrusted = machine.evaluate(
        global_policy=global_policy,
        chat_policy=ReplyExecutionChatPolicy(
            chat_key="telegram:-1001",
            requested_chat_id=1,
            runtime_chat_id=-1001,
            local_chat_id=1,
            mode="autopilot",
            trusted=False,
            autopilot_allowed=True,
        ),
        state={},
        context=_context(),
    )
    assert untrusted.reason_code == "chat_not_trusted"

    low_confidence = machine.evaluate(
        global_policy=global_policy,
        chat_policy=autopilot_chat,
        state={},
        context=_context(confidence=0.4),
    )
    assert low_confidence.reason_code == "low_confidence"

    weak = machine.evaluate(
        global_policy=global_policy,
        chat_policy=autopilot_chat,
        state={},
        context=_context(source_message_preview="ок"),
    )
    assert weak.reason_code == "weak_trigger"

    no_send_path = machine.evaluate(
        global_policy=global_policy,
        chat_policy=autopilot_chat,
        state={},
        context=_context(send_available=False, send_effective_backend="legacy"),
    )
    assert no_send_path.reason_code == "send_path_unavailable"

    degraded = machine.evaluate(
        global_policy=global_policy,
        chat_policy=autopilot_chat,
        state={},
        context=_context(workspace_degraded=True),
    )
    assert degraded.reason_code == "runtime_degraded"


def test_reply_execution_cooldown_antiduplicate_and_emergency_stop() -> None:
    machine = ReplyExecutionStateMachine()
    global_policy = ReplyExecutionGlobalPolicy(mode="autopilot")
    chat_policy = ReplyExecutionChatPolicy(
        chat_key="telegram:-1001",
        requested_chat_id=1,
        runtime_chat_id=-1001,
        local_chat_id=1,
        mode="autopilot",
        trusted=True,
        autopilot_allowed=True,
    )
    allowed = machine.evaluate(
        global_policy=global_policy,
        chat_policy=chat_policy,
        state={},
        context=_context(),
    )
    assert allowed.allowed is True
    assert allowed.action == "send"
    assert allowed.to_payload()["sourceBackend"] == "new_runtime"
    assert allowed.to_payload()["freshnessMode"] == "fresh"
    assert allowed.to_payload()["liveSource"] == "desktop_live_coordinator"

    duplicate = machine.evaluate(
        global_policy=global_policy,
        chat_policy=chat_policy,
        state={"last_sent_execution_key": allowed.execution_key},
        context=_context(),
    )
    assert duplicate.reason_code == "duplicate_send"

    cooldown = machine.evaluate(
        global_policy=global_policy,
        chat_policy=chat_policy,
        state={"cooldown_until": (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()},
        context=_context(source_message_key="telegram:-1001:11", source_runtime_message_id=11),
    )
    assert cooldown.status == "cooldown"
    assert cooldown.reason_code == "cooldown_active"

    emergency = machine.evaluate(
        global_policy=ReplyExecutionGlobalPolicy(mode="autopilot", emergency_stop=True),
        chat_policy=chat_policy,
        state={},
        context=_context(),
    )
    assert emergency.status == "blocked"
    assert emergency.reason_code == "emergency_stop_active"


def _context(
    *,
    confidence: float = 0.9,
    source_message_preview: str = "Сможешь посмотреть это сегодня?",
    send_available: bool = True,
    send_effective_backend: str = "new",
    source_message_key: str = "telegram:-1001:10",
    source_runtime_message_id: int = 10,
    workspace_degraded: bool = False,
) -> ReplyExecutionContext:
    return ReplyExecutionContext(
        requested_chat_id=1,
        chat_key="telegram:-1001",
        runtime_chat_id=-1001,
        local_chat_id=1,
        chat_type="group",
        source_backend="new_runtime",
        workspace_source="new",
        freshness_mode="fresh",
        freshness_sync_trigger="runtime_poll",
        live_source="desktop_live_coordinator",
        live_new_message_count=1,
        workspace_degraded=workspace_degraded,
        send_available=send_available,
        send_effective_backend=send_effective_backend,
        latest_message_direction="inbound",
        latest_message_key=source_message_key,
        latest_message_text=source_message_preview,
        outbound_tail_count=0,
        suggestion_available=True,
        reply_text="Да, посмотрю сейчас.",
        confidence=confidence,
        strategy="ответить коротко",
        reply_recommended=True,
        trigger="вопрос",
        focus="вопрос",
        opportunity="direct_reply",
        opportunity_reason="Последний входящий вопрос без ответа.",
        source_message_id=None,
        source_message_key=source_message_key,
        source_runtime_message_id=source_runtime_message_id,
        source_message_preview=source_message_preview,
        draft_scope_key=f"{source_message_key}::вопрос::direct_reply::Сможешь посмотреть это сегодня?",
    )
