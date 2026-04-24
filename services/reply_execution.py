from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
import hashlib
from typing import Any, Literal

from astra_runtime.chat_identity import ChatIdentity, parse_runtime_only_chat_id
from services.reply_signal import has_resolution_signal, is_weak_reply_signal
from services.workflow_journal import WorkflowJournalService, build_workflow_event
from storage.repositories import ChatRepository


ReplyExecutionMode = Literal["off", "draft", "semi_auto", "autopilot"]
ReplyExecutionStatus = Literal[
    "idle",
    "suggestion_ready",
    "awaiting_confirmation",
    "sending",
    "sent",
    "skipped",
    "blocked",
    "failed",
    "cooldown",
]

GLOBAL_POLICY_KEY = "reply_execution.global_policy"
CHAT_POLICY_PREFIX = "reply_execution.chat_policy."
CHAT_STATE_PREFIX = "reply_execution.state."
DEFAULT_COOLDOWN_SECONDS = 900
DEFAULT_MIN_PREPARE_CONFIDENCE = 0.58
DEFAULT_MIN_SEND_CONFIDENCE = 0.72
MAX_ACTIVITY_LIMIT = 20

VALID_MODES: tuple[ReplyExecutionMode, ...] = ("off", "draft", "semi_auto", "autopilot")
MODE_RANK: dict[ReplyExecutionMode, int] = {
    "off": 0,
    "draft": 1,
    "semi_auto": 2,
    "autopilot": 3,
}


REASON_MESSAGES: dict[str, str] = {
    "global_mode_off": "Глобальный режим ответов выключен.",
    "chat_mode_off": "Режим ответов для чата выключен.",
    "emergency_stop_active": "Активен global kill switch: автоматические действия остановлены.",
    "autopilot_paused": "Автопилот поставлен на паузу: автоматическая отправка запрещена.",
    "chat_not_trusted": "Чат не добавлен в trusted list для полуавтомата.",
    "chat_not_allowed_for_autopilot": "Чат не разрешён для автопилота.",
    "channel_not_allowed": "Для каналов автоответ запрещён глобальной policy.",
    "missing_suggestion": "Reply-контур не подготовил usable suggestion.",
    "hold_marked": "Reply-контур пометил контекст как hold / не отвечать.",
    "weak_trigger": "Trigger слишком слабый для автоматического действия.",
    "low_confidence": "Уверенность ниже порога для текущего режима.",
    "cooldown_active": "Чат находится в cooldown после недавней отправки.",
    "duplicate_execution": "Такое действие по этому trigger уже подготовлено.",
    "duplicate_send": "Такое сообщение по этому trigger уже отправлялось.",
    "no_new_signal": "Новый meaningful signal после последнего действия не появился.",
    "topic_closed_by_last_action": "Последнее действие уже закрыло тему.",
    "anti_loop_outbound_tail": "Хвост чата выглядит как серия исходящих без нового входящего сигнала.",
    "send_path_unavailable": "Новый send-path сейчас недоступен для управляемого автоответа.",
    "runtime_degraded": "Workspace/runtime находится в degraded или fallback состоянии.",
    "draft_created": "Режим draft: suggestion сохранён как черновик без отправки.",
    "confirm_required": "Режим semi_auto: подготовлен черновик, требуется один явный confirm.",
    "autopilot_send_allowed": "Режим autopilot: все safeguards пройдены, можно отправлять через new send-path.",
    "off_noop": "Режим off: автоматических действий нет.",
    "sent": "Сообщение отправлено через new send-path.",
    "send_failed": "Отправка через new send-path не удалась.",
    "confirm_not_pending": "Для этого чата нет pending action, который ждёт confirm.",
    "confirm_id_mismatch": "Pending action не совпадает с confirm-запросом.",
    "invalid_transition": "State machine отклонила некорректный повторный переход.",
}


@dataclass(frozen=True, slots=True)
class ReplyExecutionGlobalPolicy:
    mode: ReplyExecutionMode = "off"
    emergency_stop: bool = False
    autopilot_paused: bool = False
    allow_channels: bool = False
    cooldown_seconds: int = DEFAULT_COOLDOWN_SECONDS
    min_prepare_confidence: float = DEFAULT_MIN_PREPARE_CONFIDENCE
    min_send_confidence: float = DEFAULT_MIN_SEND_CONFIDENCE

    @property
    def master_enabled(self) -> bool:
        return self.mode != "off" and not self.emergency_stop

    def capped_mode(self) -> ReplyExecutionMode:
        if self.emergency_stop or self.mode == "off":
            return "off"
        if self.autopilot_paused and self.mode == "autopilot":
            return "semi_auto"
        return self.mode

    def to_payload(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "globalMode": self.mode,
            "masterEnabled": self.master_enabled,
            "master_enabled": self.master_enabled,
            "emergencyStop": self.emergency_stop,
            "emergency_stop": self.emergency_stop,
            "autopilotPaused": self.autopilot_paused,
            "autopilot_paused": self.autopilot_paused,
            "allowChannels": self.allow_channels,
            "allow_channels": self.allow_channels,
            "cooldownSeconds": self.cooldown_seconds,
            "cooldown_seconds": self.cooldown_seconds,
            "minPrepareConfidence": self.min_prepare_confidence,
            "min_prepare_confidence": self.min_prepare_confidence,
            "minSendConfidence": self.min_send_confidence,
            "min_send_confidence": self.min_send_confidence,
        }

    @classmethod
    def from_payload(cls, payload: object) -> "ReplyExecutionGlobalPolicy":
        if not isinstance(payload, dict):
            return cls()
        mode = normalize_reply_execution_mode(
            _pick_str(payload, "mode")
            or _pick_str(payload, "globalMode")
            or ("autopilot" if payload.get("master_enabled") is True else None),
            fallback="off",
        )
        return cls(
            mode=mode,
            emergency_stop=_pick_bool(payload, "emergency_stop", "emergencyStop", default=False),
            autopilot_paused=_pick_bool(payload, "autopilot_paused", "autopilotPaused", default=False),
            allow_channels=_pick_bool(payload, "allow_channels", "allowChannels", default=False),
            cooldown_seconds=max(30, _pick_int(payload, "cooldown_seconds", "cooldownSeconds", default=DEFAULT_COOLDOWN_SECONDS)),
            min_prepare_confidence=_clamp_float(
                _pick_float(payload, "min_prepare_confidence", "minPrepareConfidence", default=DEFAULT_MIN_PREPARE_CONFIDENCE)
            ),
            min_send_confidence=_clamp_float(
                _pick_float(payload, "min_send_confidence", "minSendConfidence", default=DEFAULT_MIN_SEND_CONFIDENCE)
            ),
        )


@dataclass(frozen=True, slots=True)
class ReplyExecutionChatPolicy:
    chat_key: str
    requested_chat_id: int
    runtime_chat_id: int | None
    local_chat_id: int | None
    mode: ReplyExecutionMode = "off"
    trusted: bool = False
    autopilot_allowed: bool = False
    source: str = "default"

    def effective_mode(self, global_policy: ReplyExecutionGlobalPolicy) -> ReplyExecutionMode:
        global_mode = global_policy.capped_mode()
        if global_mode == "off" or self.mode == "off":
            return "off"
        return min((global_mode, self.mode), key=lambda item: MODE_RANK[item])

    def to_payload(self, *, global_policy: ReplyExecutionGlobalPolicy) -> dict[str, Any]:
        effective_mode = self.effective_mode(global_policy)
        return {
            "chatKey": self.chat_key,
            "requestedChatId": self.requested_chat_id,
            "runtimeChatId": self.runtime_chat_id,
            "localChatId": self.local_chat_id,
            "mode": self.mode,
            "chatMode": self.mode,
            "effectiveMode": effective_mode,
            "trusted": self.trusted,
            "allowed": self.autopilot_allowed,
            "autopilotAllowed": self.autopilot_allowed,
            "canAutoSend": effective_mode == "autopilot" and self.trusted and self.autopilot_allowed,
            "source": self.source,
        }


@dataclass(frozen=True, slots=True)
class ReplyExecutionContext:
    requested_chat_id: int
    chat_key: str
    runtime_chat_id: int | None
    local_chat_id: int | None
    chat_type: str | None
    source_backend: str | None
    workspace_source: str | None
    workspace_degraded: bool
    send_available: bool
    send_effective_backend: str | None
    latest_message_direction: str | None
    latest_message_key: str | None
    latest_message_text: str | None
    outbound_tail_count: int
    suggestion_available: bool
    reply_text: str | None
    confidence: float | None
    strategy: str | None
    reply_recommended: bool
    trigger: str | None
    focus: str | None
    opportunity: str | None
    opportunity_reason: str | None
    source_message_id: int | None
    source_message_key: str | None
    source_runtime_message_id: int | None
    source_message_preview: str | None
    draft_scope_key: str | None


@dataclass(frozen=True, slots=True)
class ReplyExecutionDecision:
    mode: ReplyExecutionMode
    effective_mode: ReplyExecutionMode
    status: ReplyExecutionStatus
    action: str
    allowed: bool
    reason_code: str
    reason: str
    confidence: float | None
    trigger: str | None
    focus: str | None
    opportunity: str | None
    source_message_id: int | None
    source_message_key: str | None
    source_runtime_message_id: int | None
    reply_text: str | None
    draft_scope_key: str | None
    execution_id: str | None
    execution_key: str | None

    def to_payload(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "effectiveMode": self.effective_mode,
            "status": self.status,
            "action": self.action,
            "allowed": self.allowed,
            "reason": self.reason,
            "reasonCode": self.reason_code,
            "reason_code": self.reason_code,
            "confidence": self.confidence,
            "trigger": self.trigger,
            "focus": self.focus,
            "opportunity": self.opportunity,
            "sourceMessageId": self.source_message_id,
            "sourceMessageKey": self.source_message_key,
            "sourceRuntimeMessageId": self.source_runtime_message_id,
            "replyText": self.reply_text,
            "draftScopeKey": self.draft_scope_key,
            "pendingDraftStatus": "awaiting_confirmation" if self.status == "awaiting_confirmation" else "draft" if self.status == "suggestion_ready" else None,
            "executionId": self.execution_id,
            "executionKey": self.execution_key,
        }


@dataclass(frozen=True, slots=True)
class ReplyExecutionRunResult:
    decision: ReplyExecutionDecision
    autopilot: dict[str, Any]
    pending_send: dict[str, Any] | None = None


@dataclass(slots=True)
class ReplyExecutionStateMachine:
    transitions: dict[ReplyExecutionStatus, dict[str, ReplyExecutionStatus]] = field(default_factory=lambda: {
        "idle": {
            "skip": "skipped",
            "block": "blocked",
            "duplicate": "idle",
            "prepare_draft": "suggestion_ready",
            "await_confirm": "awaiting_confirmation",
            "send_request": "sending",
        },
        "suggestion_ready": {
            "skip": "skipped",
            "block": "blocked",
            "duplicate": "suggestion_ready",
            "prepare_draft": "suggestion_ready",
            "await_confirm": "awaiting_confirmation",
            "send_request": "sending",
            "new_signal": "idle",
        },
        "awaiting_confirmation": {
            "skip": "skipped",
            "block": "blocked",
            "duplicate": "awaiting_confirmation",
            "await_confirm": "awaiting_confirmation",
            "confirm": "sending",
            "cancel": "skipped",
            "new_signal": "idle",
        },
        "sending": {
            "duplicate": "sending",
            "send_succeeded": "sent",
            "send_failed": "failed",
        },
        "sent": {
            "duplicate": "sent",
            "cooldown_start": "cooldown",
            "new_signal": "idle",
        },
        "skipped": {
            "skip": "skipped",
            "block": "blocked",
            "duplicate": "skipped",
            "prepare_draft": "suggestion_ready",
            "await_confirm": "awaiting_confirmation",
            "send_request": "sending",
            "new_signal": "idle",
        },
        "blocked": {
            "skip": "skipped",
            "block": "blocked",
            "duplicate": "blocked",
            "prepare_draft": "suggestion_ready",
            "await_confirm": "awaiting_confirmation",
            "send_request": "sending",
            "new_signal": "idle",
        },
        "failed": {
            "skip": "skipped",
            "block": "blocked",
            "duplicate": "failed",
            "prepare_draft": "suggestion_ready",
            "await_confirm": "awaiting_confirmation",
            "send_request": "sending",
            "new_signal": "idle",
        },
        "cooldown": {
            "skip": "skipped",
            "block": "blocked",
            "duplicate": "cooldown",
            "cooldown_tick": "cooldown",
            "new_signal": "idle",
        },
    })

    def next_status(self, current_status: str | None, event: str) -> ReplyExecutionStatus:
        normalized_status = normalize_reply_execution_status(current_status)
        target = self.transitions.get(normalized_status, {}).get(event)
        if target is None:
            raise ReplyExecutionTransitionError(
                f"Invalid reply execution transition: {normalized_status} --{event}."
            )
        return target

    def evaluate(
        self,
        *,
        global_policy: ReplyExecutionGlobalPolicy,
        chat_policy: ReplyExecutionChatPolicy,
        state: dict[str, Any],
        context: ReplyExecutionContext,
    ) -> ReplyExecutionDecision:
        effective_mode = chat_policy.effective_mode(global_policy)
        execution_key = _build_execution_key(context=context, mode=effective_mode)
        execution_id = _build_execution_id(execution_key)
        base = {
            "mode": chat_policy.mode,
            "effective_mode": effective_mode,
            "confidence": context.confidence,
            "trigger": context.trigger,
            "focus": context.focus,
            "opportunity": context.opportunity,
            "source_message_id": context.source_message_id,
            "source_message_key": context.source_message_key,
            "source_runtime_message_id": context.source_runtime_message_id,
            "reply_text": context.reply_text,
            "draft_scope_key": context.draft_scope_key,
            "execution_id": execution_id,
            "execution_key": execution_key,
        }

        if global_policy.emergency_stop:
            return self._decision(**base, status="blocked", action="none", allowed=False, reason_code="emergency_stop_active")
        if global_policy.mode == "off":
            return self._decision(**base, status="idle", action="none", allowed=False, reason_code="global_mode_off")
        if chat_policy.mode == "off" or effective_mode == "off":
            reason_code = "chat_mode_off" if chat_policy.mode == "off" else "global_mode_off"
            return self._decision(**base, status="idle", action="none", allowed=False, reason_code=reason_code)
        if global_policy.autopilot_paused and chat_policy.mode == "autopilot" and global_policy.mode == "autopilot":
            base["effective_mode"] = "semi_auto"
            effective_mode = "semi_auto"

        if effective_mode in {"semi_auto", "autopilot"} and not chat_policy.trusted:
            return self._decision(**base, status="blocked", action="none", allowed=False, reason_code="chat_not_trusted")
        if effective_mode == "autopilot" and not chat_policy.autopilot_allowed:
            return self._decision(**base, status="blocked", action="none", allowed=False, reason_code="chat_not_allowed_for_autopilot")
        if context.chat_type == "channel" and effective_mode in {"semi_auto", "autopilot"} and not global_policy.allow_channels:
            return self._decision(**base, status="blocked", action="none", allowed=False, reason_code="channel_not_allowed")
        if not context.suggestion_available or not context.reply_text:
            return self._decision(**base, status="skipped", action="none", allowed=False, reason_code="missing_suggestion")
        if (
            context.strategy == "не отвечать"
            or not context.reply_recommended
            or context.opportunity in {"hold", "no_reply", "none"}
        ):
            return self._decision(**base, status="skipped", action="none", allowed=False, reason_code="hold_marked")
        if is_weak_reply_signal(context.source_message_preview):
            return self._decision(**base, status="blocked", action="none", allowed=False, reason_code="weak_trigger")

        threshold = (
            global_policy.min_send_confidence
            if effective_mode == "autopilot"
            else global_policy.min_prepare_confidence
        )
        if context.confidence is None or context.confidence < threshold:
            return self._decision(**base, status="blocked", action="none", allowed=False, reason_code="low_confidence")

        cooldown_until = parse_datetime(state.get("cooldown_until") or state.get("cooldownUntil"))
        if cooldown_until is not None and cooldown_until > datetime.now(timezone.utc):
            return self._decision(**base, status="cooldown", action="none", allowed=False, reason_code="cooldown_active")

        if execution_key and execution_key == state.get("last_sent_execution_key"):
            return self._decision(**base, status="blocked", action="none", allowed=False, reason_code="duplicate_send")
        if _same_signal(state, context):
            return self._decision(**base, status="blocked", action="none", allowed=False, reason_code="no_new_signal")
        if _pending_matches(state, execution_key):
            return self._decision(**base, status=normalize_reply_execution_status(state.get("status")), action="none", allowed=False, reason_code="duplicate_execution")
        if _topic_closed_by_last_action(state, context):
            return self._decision(**base, status="blocked", action="none", allowed=False, reason_code="topic_closed_by_last_action")
        if context.outbound_tail_count >= 2:
            return self._decision(**base, status="blocked", action="none", allowed=False, reason_code="anti_loop_outbound_tail")
        if context.latest_message_direction == "outbound" and context.opportunity != "follow_up_after_self":
            return self._decision(**base, status="blocked", action="none", allowed=False, reason_code="topic_closed_by_last_action")
        if context.latest_message_text and has_resolution_signal(context.latest_message_text):
            return self._decision(**base, status="blocked", action="none", allowed=False, reason_code="topic_closed_by_last_action")

        if effective_mode == "draft":
            return self._decision(**base, status="suggestion_ready", action="draft", allowed=True, reason_code="draft_created")
        if effective_mode == "semi_auto":
            if not _new_send_path_ready(context):
                return self._decision(**base, status="blocked", action="none", allowed=False, reason_code="send_path_unavailable")
            return self._decision(**base, status="awaiting_confirmation", action="confirm", allowed=True, reason_code="confirm_required")
        if effective_mode == "autopilot":
            if context.workspace_degraded or context.workspace_source == "fallback_to_legacy":
                return self._decision(**base, status="blocked", action="none", allowed=False, reason_code="runtime_degraded")
            if not _new_send_path_ready(context):
                return self._decision(**base, status="blocked", action="none", allowed=False, reason_code="send_path_unavailable")
            return self._decision(**base, status="sending", action="send", allowed=True, reason_code="autopilot_send_allowed")

        return self._decision(**base, status="skipped", action="none", allowed=False, reason_code="off_noop")

    def _decision(
        self,
        *,
        mode: ReplyExecutionMode,
        effective_mode: ReplyExecutionMode,
        status: ReplyExecutionStatus,
        action: str,
        allowed: bool,
        reason_code: str,
        confidence: float | None,
        trigger: str | None,
        focus: str | None,
        opportunity: str | None,
        source_message_id: int | None,
        source_message_key: str | None,
        source_runtime_message_id: int | None,
        reply_text: str | None,
        draft_scope_key: str | None,
        execution_id: str | None,
        execution_key: str | None,
    ) -> ReplyExecutionDecision:
        return ReplyExecutionDecision(
            mode=mode,
            effective_mode=effective_mode,
            status=status,
            action=action,
            allowed=allowed,
            reason_code=reason_code,
            reason=REASON_MESSAGES.get(reason_code, reason_code),
            confidence=confidence,
            trigger=trigger,
            focus=focus,
            opportunity=opportunity,
            source_message_id=source_message_id,
            source_message_key=source_message_key,
            source_runtime_message_id=source_runtime_message_id,
            reply_text=reply_text,
            draft_scope_key=draft_scope_key,
            execution_id=execution_id,
            execution_key=execution_key,
        )


class ReplyExecutionTransitionError(RuntimeError):
    pass


@dataclass(slots=True)
class ReplyExecutionService:
    chat_repository: ChatRepository
    setting_repository: Any
    journal: WorkflowJournalService
    machine: ReplyExecutionStateMachine = field(default_factory=ReplyExecutionStateMachine)

    async def get_global_policy(self) -> ReplyExecutionGlobalPolicy:
        return ReplyExecutionGlobalPolicy.from_payload(
            await self.setting_repository.get_value(GLOBAL_POLICY_KEY)
        )

    async def update_global_policy(
        self,
        *,
        mode: str | None = None,
        master_enabled: bool | None = None,
        emergency_stop: bool | None = None,
        autopilot_paused: bool | None = None,
        allow_channels: bool | None = None,
    ) -> ReplyExecutionGlobalPolicy:
        current = await self.get_global_policy()
        next_mode = current.mode
        if mode is not None:
            next_mode = normalize_reply_execution_mode(mode, fallback=current.mode)
        elif master_enabled is not None:
            next_mode = "autopilot" if master_enabled else "off"
        next_policy = ReplyExecutionGlobalPolicy(
            mode=next_mode,
            emergency_stop=current.emergency_stop if emergency_stop is None else bool(emergency_stop),
            autopilot_paused=current.autopilot_paused if autopilot_paused is None else bool(autopilot_paused),
            allow_channels=current.allow_channels if allow_channels is None else bool(allow_channels),
            cooldown_seconds=current.cooldown_seconds,
            min_prepare_confidence=current.min_prepare_confidence,
            min_send_confidence=current.min_send_confidence,
        )
        await self.setting_repository.set_value(
            key=GLOBAL_POLICY_KEY,
            value_json=next_policy.to_payload(),
            value_text=None,
        )
        return next_policy

    async def emergency_stop(self) -> ReplyExecutionGlobalPolicy:
        return await self.update_global_policy(mode="off", emergency_stop=True, autopilot_paused=True)

    async def pause_autopilot(self, *, paused: bool = True) -> ReplyExecutionGlobalPolicy:
        return await self.update_global_policy(autopilot_paused=paused)

    async def get_chat_policy_for_payload(
        self,
        *,
        requested_chat_id: int,
        chat_payload: dict[str, Any] | None = None,
    ) -> ReplyExecutionChatPolicy:
        identity = await self._resolve_chat_identity(
            requested_chat_id=requested_chat_id,
            chat_payload=chat_payload,
        )
        return await self._load_chat_policy(identity=identity, chat_payload=chat_payload)

    async def update_chat_policy(
        self,
        *,
        requested_chat_id: int,
        chat_payload: dict[str, Any] | None = None,
        mode: str | None = None,
        trusted: bool | None = None,
        autopilot_allowed: bool | None = None,
        allowed: bool | None = None,
    ) -> ReplyExecutionChatPolicy:
        identity = await self._resolve_chat_identity(
            requested_chat_id=requested_chat_id,
            chat_payload=chat_payload,
        )
        current = await self._load_chat_policy(identity=identity, chat_payload=chat_payload)
        next_mode = current.mode if mode is None else normalize_reply_execution_mode(mode, fallback=current.mode)
        next_trusted = current.trusted if trusted is None else bool(trusted)
        next_allowed = current.autopilot_allowed if autopilot_allowed is None and allowed is None else bool(
            autopilot_allowed if autopilot_allowed is not None else allowed
        )

        if identity["local_chat_id"] is not None:
            chat = await self.chat_repository.get_by_id(int(identity["local_chat_id"]))
            if chat is not None:
                chat.reply_assist_enabled = next_trusted
                chat.auto_reply_mode = next_mode
                await self.chat_repository.session.flush()

        payload = {
            "mode": next_mode,
            "trusted": next_trusted,
            "autopilotAllowed": next_allowed,
            "autopilot_allowed": next_allowed,
            "updatedAt": _now_iso(),
        }
        await self.setting_repository.set_value(
            key=_chat_policy_key(str(identity["chat_key"])),
            value_json=payload,
            value_text=None,
        )
        return ReplyExecutionChatPolicy(
            chat_key=str(identity["chat_key"]),
            requested_chat_id=requested_chat_id,
            runtime_chat_id=identity["runtime_chat_id"],
            local_chat_id=identity["local_chat_id"],
            mode=next_mode,
            trusted=next_trusted,
            autopilot_allowed=next_allowed,
            source="settings",
        )

    async def evaluate_workspace(
        self,
        *,
        requested_chat_id: int,
        workspace_payload: dict[str, Any],
        actor: str = "desktop",
    ) -> ReplyExecutionRunResult:
        chat_payload = workspace_payload.get("chat") if isinstance(workspace_payload.get("chat"), dict) else {}
        global_policy = await self.get_global_policy()
        chat_policy = await self.get_chat_policy_for_payload(
            requested_chat_id=requested_chat_id,
            chat_payload=chat_payload,
        )
        state = await self._load_state(chat_policy.chat_key)
        context = build_reply_execution_context(
            requested_chat_id=requested_chat_id,
            workspace_payload=workspace_payload,
            chat_policy=chat_policy,
        )
        decision = self.machine.evaluate(
            global_policy=global_policy,
            chat_policy=chat_policy,
            state=state,
            context=context,
        )
        state = await self._apply_decision(
            chat_policy=chat_policy,
            global_policy=global_policy,
            state=state,
            context=context,
            decision=decision,
            actor=actor,
        )
        autopilot = await self._build_autopilot_payload(
            global_policy=global_policy,
            chat_policy=chat_policy,
            state=state,
            decision=decision,
        )
        pending_send = (
            _pending_action_payload(state)
            if decision.allowed and decision.action == "send"
            else None
        )
        return ReplyExecutionRunResult(
            decision=decision,
            autopilot=autopilot,
            pending_send=pending_send,
        )

    async def get_status_payload(
        self,
        *,
        requested_chat_id: int | None = None,
        chat_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        global_policy = await self.get_global_policy()
        payload: dict[str, Any] = {
            "policy": global_policy.to_payload(),
            "globalPolicy": global_policy.to_payload(),
            "settings": _legacy_global_settings_payload(global_policy),
            "activity": list(await self.journal.list_global_events(limit=MAX_ACTIVITY_LIMIT)),
        }
        if requested_chat_id is not None:
            chat_policy = await self.get_chat_policy_for_payload(
                requested_chat_id=requested_chat_id,
                chat_payload=chat_payload,
            )
            state = await self._load_state(chat_policy.chat_key)
            decision = _state_decision_fallback(chat_policy=chat_policy, global_policy=global_policy, state=state)
            payload["chatPolicy"] = chat_policy.to_payload(global_policy=global_policy)
            payload["autopilot"] = await self._build_autopilot_payload(
                global_policy=global_policy,
                chat_policy=chat_policy,
                state=state,
                decision=decision,
            )
        return payload

    async def prepare_confirm_send(
        self,
        *,
        requested_chat_id: int,
        chat_payload: dict[str, Any] | None = None,
        pending_id: str | None = None,
    ) -> tuple[ReplyExecutionChatPolicy, dict[str, Any], dict[str, Any]]:
        global_policy = await self.get_global_policy()
        chat_policy = await self.get_chat_policy_for_payload(
            requested_chat_id=requested_chat_id,
            chat_payload=chat_payload,
        )
        state = await self._load_state(chat_policy.chat_key)
        pending = _pending_action_payload(state)
        if pending is None or state.get("status") != "awaiting_confirmation":
            decision = _manual_decision(
                chat_policy=chat_policy,
                global_policy=global_policy,
                state=state,
                reason_code="confirm_not_pending",
                status="blocked",
            )
            await self._record_decision_once(
                chat_policy=chat_policy,
                decision=decision,
                actor="desktop",
                automatic=False,
                action="confirm_blocked",
                state=state,
            )
            raise ReplyExecutionActionError(decision.reason, code=decision.reason_code, autopilot=await self._build_autopilot_payload(
                global_policy=global_policy,
                chat_policy=chat_policy,
                state=state,
                decision=decision,
            ))
        if pending_id is not None and pending.get("id") != pending_id and pending.get("executionId") != pending_id:
            decision = _manual_decision(
                chat_policy=chat_policy,
                global_policy=global_policy,
                state=state,
                reason_code="confirm_id_mismatch",
                status="blocked",
            )
            await self._record_decision_once(
                chat_policy=chat_policy,
                decision=decision,
                actor="desktop",
                automatic=False,
                action="confirm_blocked",
                state=state,
            )
            raise ReplyExecutionActionError(decision.reason, code=decision.reason_code, autopilot=await self._build_autopilot_payload(
                global_policy=global_policy,
                chat_policy=chat_policy,
                state=state,
                decision=decision,
            ))

        next_status = self.machine.next_status(state.get("status"), "confirm")
        state["status"] = next_status
        state["updated_at"] = _now_iso()
        state["last_reason_code"] = "confirm_required"
        await self._save_state(chat_policy.chat_key, state)
        await self._record_decision_once(
            chat_policy=chat_policy,
            decision=_decision_from_pending(
                pending,
                chat_policy=chat_policy,
                global_policy=global_policy,
                status="sending",
                action="send",
                allowed=True,
                reason_code="confirm_required",
            ),
            actor="desktop",
            automatic=False,
            action="confirm_send",
            state=state,
        )
        return chat_policy, state, pending

    async def mark_sent(
        self,
        *,
        chat_policy: ReplyExecutionChatPolicy,
        state: dict[str, Any],
        pending: dict[str, Any],
        sent_payload: dict[str, Any],
        actor: str,
        automatic: bool,
    ) -> dict[str, Any]:
        global_policy = await self.get_global_policy()
        sent_identity = sent_payload.get("sentMessageIdentity") if isinstance(sent_payload.get("sentMessageIdentity"), dict) else {}
        sent_message = sent_payload.get("sentMessage") if isinstance(sent_payload.get("sentMessage"), dict) else {}
        sent_message_id = _pick_int(sent_identity, "localMessageId") or _pick_int(sent_message, "localMessageId") or _pick_int(sent_message, "id")
        runtime_message_id = _pick_int(sent_identity, "runtimeMessageId") or _pick_int(sent_message, "runtimeMessageId")
        message_key = _pick_str(sent_identity, "messageKey") or _pick_str(sent_message, "messageKey")
        next_status = self.machine.next_status(state.get("status"), "send_succeeded")
        cooldown_until = datetime.now(timezone.utc) + timedelta(seconds=max(30, global_policy.cooldown_seconds))
        state.update(
            {
                "status": next_status,
                "pending_draft": None,
                "last_sent_at": _now_iso(),
                "last_sent_message_id": sent_message_id,
                "last_sent_runtime_message_id": runtime_message_id,
                "last_sent_message_key": message_key,
                "last_sent_source_message_id": pending.get("sourceMessageId") or pending.get("source_message_id"),
                "last_sent_source_message_key": pending.get("sourceMessageKey") or pending.get("source_message_key"),
                "last_sent_execution_key": pending.get("executionKey") or pending.get("execution_key"),
                "last_execution_key": pending.get("executionKey") or pending.get("execution_key"),
                "cooldown_until": cooldown_until.isoformat(),
                "last_reason_code": "sent",
                "updated_at": _now_iso(),
            }
        )
        state["status"] = self.machine.next_status(state.get("status"), "cooldown_start")
        await self._save_state(chat_policy.chat_key, state)
        decision = _decision_from_pending(
            pending,
            chat_policy=chat_policy,
            global_policy=global_policy,
            status="sent",
            action="send",
            allowed=True,
            reason_code="sent",
        )
        await self._append_journal(
            chat_policy=chat_policy,
            decision=decision,
            actor=actor,
            automatic=automatic,
            action="send",
            status="sent",
            message=REASON_MESSAGES["sent"],
            sent_message_id=sent_message_id,
            sent_message_key=message_key,
            source_backend="new",
        )
        return state

    async def mark_failed(
        self,
        *,
        chat_policy: ReplyExecutionChatPolicy,
        state: dict[str, Any],
        pending: dict[str, Any],
        error: str,
        actor: str,
        automatic: bool,
    ) -> dict[str, Any]:
        try:
            state["status"] = self.machine.next_status(state.get("status"), "send_failed")
        except ReplyExecutionTransitionError:
            state["status"] = "failed"
        state["last_error"] = error
        state["last_reason_code"] = "send_failed"
        state["updated_at"] = _now_iso()
        await self._save_state(chat_policy.chat_key, state)
        global_policy = await self.get_global_policy()
        decision = _decision_from_pending(
            pending,
            chat_policy=chat_policy,
            global_policy=global_policy,
            status="failed",
            action="send",
            allowed=False,
            reason_code="send_failed",
        )
        await self._append_journal(
            chat_policy=chat_policy,
            decision=decision,
            actor=actor,
            automatic=automatic,
            action="send",
            status="failed",
            message=REASON_MESSAGES["send_failed"],
            error_code="send_failed",
            source_backend="new",
        )
        return state

    async def _apply_decision(
        self,
        *,
        chat_policy: ReplyExecutionChatPolicy,
        global_policy: ReplyExecutionGlobalPolicy,
        state: dict[str, Any],
        context: ReplyExecutionContext,
        decision: ReplyExecutionDecision,
        actor: str,
    ) -> dict[str, Any]:
        event = _event_for_decision(decision)
        current_status = normalize_reply_execution_status(state.get("status"))
        if current_status == "cooldown" and decision.reason_code != "cooldown_active":
            state["status"] = self.machine.next_status(current_status, "new_signal")
        try:
            next_status = self.machine.next_status(state.get("status"), event)
        except ReplyExecutionTransitionError:
            invalid = replace(
                decision,
                status="blocked",
                action="none",
                allowed=False,
                reason_code="invalid_transition",
                reason=REASON_MESSAGES["invalid_transition"],
            )
            await self._record_decision_once(
                chat_policy=chat_policy,
                decision=invalid,
                actor=actor,
                automatic=True,
                action="blocked",
                state=state,
            )
            state["status"] = "blocked"
            state["last_reason_code"] = invalid.reason_code
            state["updated_at"] = _now_iso()
            await self._save_state(chat_policy.chat_key, state)
            return state

        state["status"] = next_status
        state["mode"] = decision.effective_mode
        state["last_reason_code"] = decision.reason_code
        state["last_reason"] = decision.reason
        state["last_decision_at"] = _now_iso()
        state["updated_at"] = _now_iso()
        if decision.execution_key:
            state["last_execution_key"] = decision.execution_key
        if decision.source_message_id is not None:
            state["last_evaluated_source_message_id"] = decision.source_message_id
        if decision.source_message_key is not None:
            state["last_evaluated_source_message_key"] = decision.source_message_key

        if decision.allowed and decision.action in {"draft", "confirm", "send"}:
            state["pending_draft"] = _build_pending_action(
                decision=decision,
                context=context,
                status="awaiting_confirmation" if decision.action in {"confirm", "send"} else "draft",
            )
            action = "send_requested" if decision.action == "send" else "confirm_awaited" if decision.action == "confirm" else "draft_created"
            await self._append_journal(
                chat_policy=chat_policy,
                decision=decision,
                actor=actor,
                automatic=True,
                action=action,
                status=decision.status,
                message=decision.reason,
                source_backend=context.source_backend,
            )
        else:
            await self._record_decision_once(
                chat_policy=chat_policy,
                decision=decision,
                actor=actor,
                automatic=True,
                action="blocked" if decision.status in {"blocked", "cooldown"} else "skipped",
                state=state,
                source_backend=context.source_backend,
            )

        await self._save_state(chat_policy.chat_key, state)
        return state

    async def _build_autopilot_payload(
        self,
        *,
        global_policy: ReplyExecutionGlobalPolicy,
        chat_policy: ReplyExecutionChatPolicy,
        state: dict[str, Any],
        decision: ReplyExecutionDecision,
    ) -> dict[str, Any]:
        cooldown_until = parse_datetime(state.get("cooldown_until") or state.get("cooldownUntil"))
        journal = await self.journal.list_chat_events(
            chat_policy.local_chat_id or chat_policy.requested_chat_id,
            limit=8,
        )
        return {
            "masterEnabled": global_policy.master_enabled,
            "allowChannels": global_policy.allow_channels,
            "globalMode": global_policy.mode,
            "emergencyStop": global_policy.emergency_stop,
            "autopilotPaused": global_policy.autopilot_paused,
            "mode": chat_policy.mode,
            "effectiveMode": chat_policy.effective_mode(global_policy),
            "trusted": chat_policy.trusted,
            "allowed": chat_policy.autopilot_allowed,
            "autopilotAllowed": chat_policy.autopilot_allowed,
            "writeReady": decision.reason_code != "send_path_unavailable",
            "policy": {
                "global": global_policy.to_payload(),
                "chat": chat_policy.to_payload(global_policy=global_policy),
            },
            "state": {
                "status": normalize_reply_execution_status(state.get("status")),
                "reasonCode": state.get("last_reason_code"),
                "reason": state.get("last_reason"),
                "updatedAt": state.get("updated_at"),
                "lastDecisionAt": state.get("last_decision_at"),
            },
            "decision": decision.to_payload(),
            "pendingDraft": _pending_action_payload(state),
            "lastSentAt": state.get("last_sent_at") if isinstance(state.get("last_sent_at"), str) else None,
            "lastSentSourceMessageId": _pick_int(state, "last_sent_source_message_id"),
            "lastSentSourceMessageKey": _pick_str(state, "last_sent_source_message_key"),
            "lastSentMessageKey": _pick_str(state, "last_sent_message_key"),
            "cooldown": _build_cooldown_payload(cooldown_until=cooldown_until),
            "journal": list(journal),
        }

    async def _load_state(self, chat_key: str) -> dict[str, Any]:
        payload = await self.setting_repository.get_value(_chat_state_key(chat_key))
        if not isinstance(payload, dict):
            return {"status": "idle", "updated_at": _now_iso()}
        normalized = dict(payload)
        normalized["status"] = normalize_reply_execution_status(normalized.get("status"))
        return normalized

    async def _save_state(self, chat_key: str, payload: dict[str, Any]) -> None:
        await self.setting_repository.set_value(
            key=_chat_state_key(chat_key),
            value_json=payload,
            value_text=None,
        )

    async def _resolve_chat_identity(
        self,
        *,
        requested_chat_id: int,
        chat_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload = chat_payload if isinstance(chat_payload, dict) else {}
        runtime_chat_id = _pick_int(payload, "runtimeChatId") or _pick_int(payload, "telegramChatId")
        local_chat_id = _pick_int(payload, "localChatId")
        chat_key = _pick_str(payload, "chatKey")

        if int(requested_chat_id) > 0:
            chat = await self.chat_repository.get_by_id(int(requested_chat_id))
            if chat is not None:
                return {
                    "requested_chat_id": int(requested_chat_id),
                    "runtime_chat_id": int(chat.telegram_chat_id),
                    "local_chat_id": chat.id,
                    "chat_key": ChatIdentity(runtime_chat_id=chat.telegram_chat_id, local_chat_id=chat.id).chat_key,
                }
        elif runtime_chat_id is None:
            runtime_chat_id = parse_runtime_only_chat_id(int(requested_chat_id))

        if runtime_chat_id is not None and local_chat_id is None:
            chat = await self.chat_repository.get_by_telegram_chat_id(int(runtime_chat_id))
            if chat is not None:
                local_chat_id = chat.id

        if runtime_chat_id is None and chat_key:
            parsed = _parse_chat_key(chat_key)
            if parsed is not None:
                runtime_chat_id = parsed

        if runtime_chat_id is None:
            runtime_chat_id = int(requested_chat_id)

        if chat_key is None:
            chat_key = ChatIdentity(
                runtime_chat_id=int(runtime_chat_id),
                local_chat_id=local_chat_id,
            ).chat_key
        return {
            "requested_chat_id": int(requested_chat_id),
            "runtime_chat_id": int(runtime_chat_id),
            "local_chat_id": local_chat_id,
            "chat_key": chat_key,
        }

    async def _load_chat_policy(
        self,
        *,
        identity: dict[str, Any],
        chat_payload: dict[str, Any] | None = None,
    ) -> ReplyExecutionChatPolicy:
        stored = await self.setting_repository.get_value(_chat_policy_key(str(identity["chat_key"])))
        stored_payload = stored if isinstance(stored, dict) else {}
        payload = chat_payload if isinstance(chat_payload, dict) else {}
        chat_mode: ReplyExecutionMode = normalize_reply_execution_mode(
            _pick_str(stored_payload, "mode")
            or _pick_str(payload, "autoReplyMode")
            or _pick_str(payload, "mode"),
            fallback="off",
        )
        trusted = _pick_bool(
            stored_payload,
            "trusted",
            default=bool(payload.get("replyAssistEnabled", False)),
        )
        autopilot_allowed = _pick_bool(
            stored_payload,
            "autopilot_allowed",
            "autopilotAllowed",
            "allowed",
            default=False,
        )

        if identity["local_chat_id"] is not None:
            chat = await self.chat_repository.get_by_id(int(identity["local_chat_id"]))
            if chat is not None:
                chat_mode = normalize_reply_execution_mode(chat.auto_reply_mode, fallback=chat_mode)
                trusted = bool(chat.reply_assist_enabled)

        return ReplyExecutionChatPolicy(
            chat_key=str(identity["chat_key"]),
            requested_chat_id=int(identity["requested_chat_id"]),
            runtime_chat_id=identity["runtime_chat_id"],
            local_chat_id=identity["local_chat_id"],
            mode=chat_mode,
            trusted=trusted,
            autopilot_allowed=autopilot_allowed,
            source="settings" if stored_payload else "chat" if identity["local_chat_id"] is not None else "default",
        )

    async def _record_decision_once(
        self,
        *,
        chat_policy: ReplyExecutionChatPolicy,
        decision: ReplyExecutionDecision,
        actor: str,
        automatic: bool,
        action: str,
        state: dict[str, Any],
        source_backend: str | None = None,
    ) -> None:
        guard_key = f"{decision.execution_key or 'none'}:{decision.reason_code}:{action}"
        if state.get("last_journal_guard_key") == guard_key:
            return
        state["last_journal_guard_key"] = guard_key
        await self._append_journal(
            chat_policy=chat_policy,
            decision=decision,
            actor=actor,
            automatic=automatic,
            action=action,
            status=decision.status,
            message=decision.reason,
            source_backend=source_backend,
        )

    async def _append_journal(
        self,
        *,
        chat_policy: ReplyExecutionChatPolicy,
        decision: ReplyExecutionDecision,
        actor: str,
        automatic: bool,
        action: str,
        status: str,
        message: str,
        sent_message_id: int | None = None,
        sent_message_key: str | None = None,
        error_code: str | None = None,
        source_backend: str | None = None,
    ) -> None:
        await self.journal.append_chat_event(
            chat_policy.local_chat_id or chat_policy.requested_chat_id,
            build_workflow_event(
                action=action,
                mode=decision.effective_mode,
                status=status,
                actor=actor,
                automatic=automatic,
                message=message,
                reason=decision.reason,
                reason_code=decision.reason_code,
                confidence=decision.confidence,
                trigger=decision.trigger,
                focus=decision.focus,
                opportunity=decision.opportunity,
                chat_id=chat_policy.local_chat_id or chat_policy.requested_chat_id,
                source_message_id=decision.source_message_id,
                sent_message_id=sent_message_id,
                text_preview=_preview_text(decision.reply_text),
                chat_key=chat_policy.chat_key,
                runtime_chat_id=chat_policy.runtime_chat_id,
                backend=source_backend,
                draft_scope_key=decision.draft_scope_key,
                sent_message_key=sent_message_key,
                error_code=error_code,
                execution_id=decision.execution_id,
                allowed=decision.allowed,
            ),
        )


class ReplyExecutionActionError(RuntimeError):
    def __init__(self, message: str, *, code: str, autopilot: dict[str, Any]) -> None:
        super().__init__(message)
        self.code = code
        self.autopilot = autopilot


def normalize_reply_execution_mode(
    value: str | None,
    *,
    fallback: ReplyExecutionMode = "off",
) -> ReplyExecutionMode:
    if value is None:
        return fallback
    normalized = value.strip().lower().replace("-", "_")
    if not normalized:
        return fallback
    if normalized in {"confirm", "manual", "semi", "semi-auto"}:
        return "semi_auto"
    if normalized in VALID_MODES:
        return normalized  # type: ignore[return-value]
    return fallback


def normalize_reply_execution_status(value: object) -> ReplyExecutionStatus:
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {
            "idle",
            "suggestion_ready",
            "awaiting_confirmation",
            "sending",
            "sent",
            "skipped",
            "blocked",
            "failed",
            "cooldown",
        }:
            return normalized  # type: ignore[return-value]
    return "idle"


def build_reply_execution_context(
    *,
    requested_chat_id: int,
    workspace_payload: dict[str, Any],
    chat_policy: ReplyExecutionChatPolicy,
) -> ReplyExecutionContext:
    chat = workspace_payload.get("chat") if isinstance(workspace_payload.get("chat"), dict) else {}
    reply = workspace_payload.get("reply") if isinstance(workspace_payload.get("reply"), dict) else {}
    reply_context = workspace_payload.get("replyContext") if isinstance(workspace_payload.get("replyContext"), dict) else {}
    status = workspace_payload.get("status") if isinstance(workspace_payload.get("status"), dict) else {}
    availability = status.get("availability") if isinstance(status.get("availability"), dict) else {}
    send_path = status.get("sendPath") if isinstance(status.get("sendPath"), dict) else {}
    messages = workspace_payload.get("messages") if isinstance(workspace_payload.get("messages"), list) else []
    latest_message = next((item for item in reversed(messages) if isinstance(item, dict)), None)
    suggestion = reply.get("suggestion") if isinstance(reply.get("suggestion"), dict) else None
    trigger_payload = suggestion.get("trigger") if isinstance(suggestion, dict) and isinstance(suggestion.get("trigger"), dict) else {}
    focus_payload = suggestion.get("focus") if isinstance(suggestion, dict) and isinstance(suggestion.get("focus"), dict) else {}
    opportunity_payload = suggestion.get("opportunity") if isinstance(suggestion, dict) and isinstance(suggestion.get("opportunity"), dict) else {}
    source_message_key = (
        _pick_str(reply_context, "sourceMessageKey")
        or _pick_str(suggestion, "sourceMessageKey")
        or _pick_str(trigger_payload, "messageKey")
    )
    source_message_id = (
        _pick_int(reply_context, "sourceLocalMessageId")
        or _pick_int(suggestion, "sourceLocalMessageId")
        or _pick_int(suggestion, "sourceMessageId")
        or _pick_int(trigger_payload, "localMessageId")
    )
    source_runtime_message_id = (
        _pick_int(reply_context, "sourceRuntimeMessageId")
        or _pick_int(suggestion, "sourceRuntimeMessageId")
        or _pick_int(trigger_payload, "runtimeMessageId")
    )
    return ReplyExecutionContext(
        requested_chat_id=requested_chat_id,
        chat_key=chat_policy.chat_key,
        runtime_chat_id=chat_policy.runtime_chat_id,
        local_chat_id=chat_policy.local_chat_id,
        chat_type=_pick_str(chat, "type"),
        source_backend=(
            _pick_str(reply_context, "sourceBackend")
            or _pick_str(suggestion, "sourceBackend")
            or _pick_str(trigger_payload, "backend")
            or _pick_str(status.get("messageSource") if isinstance(status.get("messageSource"), dict) else {}, "backend")
        ),
        workspace_source=_pick_str(status, "source"),
        workspace_degraded=bool(status.get("degraded")),
        send_available=bool(availability.get("sendAvailable")),
        send_effective_backend=_pick_str(send_path, "effective") or _pick_str(status, "effectiveBackend"),
        latest_message_direction=_pick_str(latest_message, "direction"),
        latest_message_key=_pick_str(latest_message, "messageKey"),
        latest_message_text=_pick_str(latest_message, "text") or _pick_str(latest_message, "preview"),
        outbound_tail_count=_outbound_tail_count(messages),
        suggestion_available=isinstance(suggestion, dict),
        reply_text=_pick_str(suggestion, "replyText"),
        confidence=_pick_float_or_none(suggestion, "confidence"),
        strategy=_pick_str(suggestion, "strategy"),
        reply_recommended=bool(
            opportunity_payload.get("replyRecommended")
            if "replyRecommended" in opportunity_payload
            else suggestion.get("replyRecommended") if isinstance(suggestion, dict) and "replyRecommended" in suggestion
            else True
        ),
        trigger=(
            _pick_str(reply_context, "focusLabel")
            or _pick_str(focus_payload, "label")
            or _pick_str(suggestion, "focusLabel")
        ),
        focus=_pick_str(focus_payload, "label") or _pick_str(suggestion, "focusLabel") or _pick_str(reply_context, "focusLabel"),
        opportunity=(
            _pick_str(opportunity_payload, "mode")
            or _pick_str(suggestion, "replyOpportunityMode")
            or _pick_str(reply_context, "replyOpportunityMode")
        ),
        opportunity_reason=(
            _pick_str(opportunity_payload, "reason")
            or _pick_str(suggestion, "replyOpportunityReason")
            or _pick_str(reply_context, "replyOpportunityReason")
        ),
        source_message_id=source_message_id,
        source_message_key=source_message_key,
        source_runtime_message_id=source_runtime_message_id,
        source_message_preview=(
            _pick_str(reply_context, "sourceMessagePreview")
            or _pick_str(trigger_payload, "preview")
            or _pick_str(suggestion, "sourceMessagePreview")
            or _pick_str(reply, "sourceMessagePreview")
        ),
        draft_scope_key=_pick_str(reply_context, "draftScopeKey"),
    )


def parse_datetime(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _event_for_decision(decision: ReplyExecutionDecision) -> str:
    if decision.reason_code == "duplicate_execution":
        return "duplicate"
    if decision.allowed and decision.action == "draft":
        return "prepare_draft"
    if decision.allowed and decision.action == "confirm":
        return "await_confirm"
    if decision.allowed and decision.action == "send":
        return "send_request"
    if decision.status == "cooldown":
        return "cooldown_tick"
    if decision.status == "blocked":
        return "block"
    return "skip"


def _build_pending_action(
    *,
    decision: ReplyExecutionDecision,
    context: ReplyExecutionContext,
    status: str,
) -> dict[str, Any]:
    created_at = _now_iso()
    pending_id = decision.execution_id or _build_execution_id(decision.execution_key)
    return {
        "id": pending_id,
        "executionId": pending_id,
        "execution_id": pending_id,
        "executionKey": decision.execution_key,
        "execution_key": decision.execution_key,
        "text": decision.reply_text,
        "mode": decision.effective_mode,
        "status": status,
        "createdAt": created_at,
        "created_at": created_at,
        "sourceMessageId": decision.source_message_id,
        "source_message_id": decision.source_message_id,
        "sourceMessageKey": decision.source_message_key,
        "source_message_key": decision.source_message_key,
        "sourceRuntimeMessageId": decision.source_runtime_message_id,
        "source_runtime_message_id": decision.source_runtime_message_id,
        "draftScopeKey": decision.draft_scope_key,
        "draft_scope_key": decision.draft_scope_key,
        "confidence": decision.confidence,
        "trigger": decision.trigger,
        "focus": decision.focus,
        "focus_label": decision.focus,
        "opportunity": decision.opportunity,
        "reply_opportunity_reason": context.opportunity_reason,
        "source_message_preview": context.source_message_preview,
        "sourceBackend": context.source_backend,
        "source_backend": context.source_backend,
        "backend": "new" if decision.action == "send" else context.source_backend,
    }


def _pending_action_payload(state: dict[str, Any]) -> dict[str, Any] | None:
    pending = state.get("pending_draft")
    if not isinstance(pending, dict):
        return None
    return dict(pending)


def _build_execution_key(
    *,
    context: ReplyExecutionContext,
    mode: ReplyExecutionMode,
) -> str | None:
    if not context.reply_text:
        return None
    basis = "|".join(
        [
            context.chat_key,
            mode,
            context.source_message_key or str(context.source_message_id or context.source_runtime_message_id or "none"),
            context.draft_scope_key or "none",
            context.reply_text.strip(),
        ]
    )
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()


def _build_execution_id(execution_key: str | None) -> str | None:
    if execution_key is None:
        return None
    return f"rex_{execution_key[:16]}"


def _same_signal(state: dict[str, Any], context: ReplyExecutionContext) -> bool:
    if context.source_message_key and state.get("last_sent_source_message_key") == context.source_message_key:
        return True
    if context.source_message_id is not None and state.get("last_sent_source_message_id") == context.source_message_id:
        return True
    return False


def _pending_matches(state: dict[str, Any], execution_key: str | None) -> bool:
    pending = _pending_action_payload(state)
    if pending is None or execution_key is None:
        return False
    return (
        pending.get("executionKey") == execution_key
        or pending.get("execution_key") == execution_key
    )


def _topic_closed_by_last_action(state: dict[str, Any], context: ReplyExecutionContext) -> bool:
    last_sent_source_key = state.get("last_sent_source_message_key")
    if context.source_message_key and last_sent_source_key == context.source_message_key:
        return True
    last_sent_at = parse_datetime(state.get("last_sent_at"))
    if last_sent_at is None:
        return False
    if context.latest_message_direction == "outbound" and context.latest_message_key == state.get("last_sent_message_key"):
        return True
    return False


def _new_send_path_ready(context: ReplyExecutionContext) -> bool:
    return context.send_available and context.send_effective_backend == "new"


def _legacy_global_settings_payload(policy: ReplyExecutionGlobalPolicy) -> dict[str, Any]:
    return {
        "master_enabled": policy.master_enabled,
        "allow_channels": policy.allow_channels,
        "cooldown_seconds": policy.cooldown_seconds,
        "min_prepare_confidence": policy.min_prepare_confidence,
        "min_send_confidence": policy.min_send_confidence,
    }


def _state_decision_fallback(
    *,
    chat_policy: ReplyExecutionChatPolicy,
    global_policy: ReplyExecutionGlobalPolicy,
    state: dict[str, Any],
) -> ReplyExecutionDecision:
    reason_code = str(state.get("last_reason_code") or "off_noop")
    return ReplyExecutionDecision(
        mode=chat_policy.mode,
        effective_mode=chat_policy.effective_mode(global_policy),
        status=normalize_reply_execution_status(state.get("status")),
        action="none",
        allowed=False,
        reason_code=reason_code,
        reason=REASON_MESSAGES.get(reason_code, reason_code),
        confidence=None,
        trigger=None,
        focus=None,
        opportunity=None,
        source_message_id=None,
        source_message_key=None,
        source_runtime_message_id=None,
        reply_text=None,
        draft_scope_key=None,
        execution_id=None,
        execution_key=None,
    )


def _manual_decision(
    *,
    chat_policy: ReplyExecutionChatPolicy,
    global_policy: ReplyExecutionGlobalPolicy,
    state: dict[str, Any],
    reason_code: str,
    status: ReplyExecutionStatus,
) -> ReplyExecutionDecision:
    pending = _pending_action_payload(state) or {}
    return _decision_from_pending(
        pending,
        chat_policy=chat_policy,
        global_policy=global_policy,
        status=status,
        action="none",
        allowed=False,
        reason_code=reason_code,
    )


def _decision_from_pending(
    pending: dict[str, Any],
    *,
    chat_policy: ReplyExecutionChatPolicy,
    global_policy: ReplyExecutionGlobalPolicy,
    status: ReplyExecutionStatus,
    action: str,
    allowed: bool,
    reason_code: str,
) -> ReplyExecutionDecision:
    return ReplyExecutionDecision(
        mode=chat_policy.mode,
        effective_mode=chat_policy.effective_mode(global_policy),
        status=status,
        action=action,
        allowed=allowed,
        reason_code=reason_code,
        reason=REASON_MESSAGES.get(reason_code, reason_code),
        confidence=_pick_float_or_none(pending, "confidence"),
        trigger=_pick_str(pending, "trigger"),
        focus=_pick_str(pending, "focus") or _pick_str(pending, "focus_label"),
        opportunity=_pick_str(pending, "opportunity"),
        source_message_id=_pick_int(pending, "sourceMessageId") or _pick_int(pending, "source_message_id"),
        source_message_key=_pick_str(pending, "sourceMessageKey") or _pick_str(pending, "source_message_key"),
        source_runtime_message_id=_pick_int(pending, "sourceRuntimeMessageId") or _pick_int(pending, "source_runtime_message_id"),
        reply_text=_pick_str(pending, "text"),
        draft_scope_key=_pick_str(pending, "draftScopeKey") or _pick_str(pending, "draft_scope_key"),
        execution_id=_pick_str(pending, "executionId") or _pick_str(pending, "execution_id"),
        execution_key=_pick_str(pending, "executionKey") or _pick_str(pending, "execution_key"),
    )


def _build_cooldown_payload(*, cooldown_until: datetime | None) -> dict[str, Any]:
    if cooldown_until is None:
        return {"active": False, "remainingSeconds": 0, "until": None}
    remaining_seconds = max(0, int((cooldown_until - datetime.now(timezone.utc)).total_seconds()))
    return {
        "active": remaining_seconds > 0,
        "remainingSeconds": remaining_seconds,
        "until": cooldown_until.isoformat(),
    }


def _outbound_tail_count(messages: list[Any]) -> int:
    count = 0
    for item in reversed(messages):
        if not isinstance(item, dict):
            continue
        if item.get("direction") != "outbound":
            break
        count += 1
    return count


def _chat_policy_key(chat_key: str) -> str:
    return f"{CHAT_POLICY_PREFIX}{chat_key}"


def _chat_state_key(chat_key: str) -> str:
    return f"{CHAT_STATE_PREFIX}{chat_key}"


def _parse_chat_key(value: str | None) -> int | None:
    if not value or not value.startswith("telegram:"):
        return None
    try:
        return int(value.split(":", 1)[1])
    except (TypeError, ValueError):
        return None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _preview_text(value: str | None) -> str | None:
    if not value:
        return None
    compact = " ".join(value.split()).strip()
    if len(compact) <= 120:
        return compact
    return f"{compact[:117].rstrip()}..."


def _pick_str(payload: object, *keys: str) -> str | None:
    if not isinstance(payload, dict):
        return None
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _pick_int(payload: object, *keys: str, default: int | None = None) -> int | None:
    if not isinstance(payload, dict):
        return default
    for key in keys:
        value = payload.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, int):
            return value
    return default


def _pick_bool(payload: object, *keys: str, default: bool) -> bool:
    if not isinstance(payload, dict):
        return default
    for key in keys:
        value = payload.get(key)
        if isinstance(value, bool):
            return value
    return default


def _pick_float(payload: object, *keys: str, default: float) -> float:
    value = _pick_float_or_none(payload, *keys)
    return default if value is None else value


def _pick_float_or_none(payload: object, *keys: str) -> float | None:
    if not isinstance(payload, dict):
        return None
    for key in keys:
        value = payload.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, int | float):
            return float(value)
    return None


def _clamp_float(value: float) -> float:
    return max(0.0, min(1.0, float(value)))
