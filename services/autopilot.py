from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from fullaccess.send import FullAccessLocalSendResult, FullAccessSendService
from services.reply_models import ReplyResult
from services.workflow_journal import WorkflowJournalService, build_workflow_event


AUTOPILOT_GLOBAL_KEY = "autopilot.global"
AUTOPILOT_CHAT_STATE_PREFIX = "autopilot.chat."
AUTOPILOT_MODES = {"off", "draft", "confirm", "semi_auto", "autopilot"}
DEFAULT_COOLDOWN_SECONDS = 900
DEFAULT_MIN_PREPARE_CONFIDENCE = 0.58
DEFAULT_MIN_SEND_CONFIDENCE = 0.72


@dataclass(frozen=True, slots=True)
class AutopilotGlobalSettings:
    master_enabled: bool = False
    allow_channels: bool = False
    cooldown_seconds: int = DEFAULT_COOLDOWN_SECONDS
    min_prepare_confidence: float = DEFAULT_MIN_PREPARE_CONFIDENCE
    min_send_confidence: float = DEFAULT_MIN_SEND_CONFIDENCE

    def to_payload(self) -> dict[str, Any]:
        return {
            "master_enabled": self.master_enabled,
            "allow_channels": self.allow_channels,
            "cooldown_seconds": self.cooldown_seconds,
            "min_prepare_confidence": self.min_prepare_confidence,
            "min_send_confidence": self.min_send_confidence,
        }


@dataclass(frozen=True, slots=True)
class AutopilotDecision:
    mode: str
    action: str
    allowed: bool
    reason: str
    confidence: float | None
    trigger: str | None
    source_message_id: int | None
    reply_text: str | None
    pending_draft_status: str | None = None


@dataclass(frozen=True, slots=True)
class AutopilotRunResult:
    decision: AutopilotDecision
    send_result: FullAccessLocalSendResult | None = None


@dataclass(slots=True)
class AutopilotService:
    """Legacy autopilot state machine behind AutopilotControlSurface.

    Keep this service stable while the new reply/send/autopilot contour is
    introduced next to it. New autonomous behavior should enter via the runtime
    contracts, not by growing this legacy service.
    """

    chat_repository: Any
    setting_repository: Any
    send_service: FullAccessSendService
    journal: WorkflowJournalService

    async def get_global_settings(self) -> AutopilotGlobalSettings:
        payload = await self.setting_repository.get_value(AUTOPILOT_GLOBAL_KEY)
        if not isinstance(payload, dict):
            return AutopilotGlobalSettings()
        return AutopilotGlobalSettings(
            master_enabled=bool(payload.get("master_enabled", False)),
            allow_channels=bool(payload.get("allow_channels", False)),
            cooldown_seconds=max(30, int(payload.get("cooldown_seconds", DEFAULT_COOLDOWN_SECONDS))),
            min_prepare_confidence=max(
                0.0,
                min(1.0, float(payload.get("min_prepare_confidence", DEFAULT_MIN_PREPARE_CONFIDENCE))),
            ),
            min_send_confidence=max(
                0.0,
                min(1.0, float(payload.get("min_send_confidence", DEFAULT_MIN_SEND_CONFIDENCE))),
            ),
        )

    async def update_global_settings(
        self,
        *,
        master_enabled: bool | None = None,
        allow_channels: bool | None = None,
    ) -> dict[str, Any]:
        current = await self.get_global_settings()
        next_settings = AutopilotGlobalSettings(
            master_enabled=current.master_enabled if master_enabled is None else master_enabled,
            allow_channels=current.allow_channels if allow_channels is None else allow_channels,
            cooldown_seconds=current.cooldown_seconds,
            min_prepare_confidence=current.min_prepare_confidence,
            min_send_confidence=current.min_send_confidence,
        )
        await self.setting_repository.set_value(
            key=AUTOPILOT_GLOBAL_KEY,
            value_json=next_settings.to_payload(),
            value_text=None,
        )
        return next_settings.to_payload()

    async def update_chat_settings(
        self,
        chat,
        *,
        trusted: bool | None = None,
        mode: str | None = None,
    ):
        normalized_mode = normalize_autopilot_mode(mode, fallback=normalize_autopilot_mode(chat.auto_reply_mode))
        if trusted is not None:
            chat.reply_assist_enabled = trusted
        if mode is not None:
            chat.auto_reply_mode = normalized_mode
        await self.chat_repository.session.flush()
        return chat

    async def stop_chat(self, chat_id: int) -> None:
        await self._save_chat_state(
            chat_id,
            {
                **(await self._load_chat_state(chat_id)),
                "pending_draft": None,
            },
        )

    async def build_chat_overview(
        self,
        *,
        chat,
        reply_result: ReplyResult | None,
        write_ready: bool,
    ) -> dict[str, Any]:
        global_settings = await self.get_global_settings()
        state = await self._load_chat_state(chat.id)
        decision = self._evaluate(
            chat=chat,
            reply_result=reply_result,
            global_settings=global_settings,
            state=state,
            write_ready=write_ready,
        )
        cooldown = _build_cooldown_payload(
            cooldown_until=_parse_datetime(state.get("cooldown_until")),
        )
        return {
            "masterEnabled": global_settings.master_enabled,
            "allowChannels": global_settings.allow_channels,
            "mode": normalize_autopilot_mode(chat.auto_reply_mode),
            "trusted": bool(chat.reply_assist_enabled),
            "writeReady": write_ready,
            "decision": {
                "mode": decision.mode,
                "action": decision.action,
                "allowed": decision.allowed,
                "reason": decision.reason,
                "confidence": decision.confidence,
                "trigger": decision.trigger,
                "sourceMessageId": decision.source_message_id,
                "replyText": decision.reply_text,
                "pendingDraftStatus": decision.pending_draft_status,
            },
            "pendingDraft": state.get("pending_draft") if isinstance(state.get("pending_draft"), dict) else None,
            "lastSentAt": state.get("last_sent_at") if isinstance(state.get("last_sent_at"), str) else None,
            "lastSentSourceMessageId": state.get("last_source_message_id"),
            "cooldown": cooldown,
            "journal": list(await self.journal.list_chat_events(chat.id)),
        }

    async def run_for_chat(
        self,
        *,
        chat,
        reply_result: ReplyResult,
        actor: str,
        write_ready: bool,
        dry_run: bool = False,
    ) -> AutopilotRunResult:
        global_settings = await self.get_global_settings()
        state = await self._load_chat_state(chat.id)
        decision = self._evaluate(
            chat=chat,
            reply_result=reply_result,
            global_settings=global_settings,
            state=state,
            write_ready=write_ready,
        )
        if dry_run or not decision.allowed:
            if not decision.allowed:
                await self._record_blocked(chat_id=chat.id, decision=decision, actor=actor)
            return AutopilotRunResult(decision=decision)

        if decision.action in {"draft", "confirm"}:
            await self._save_pending_draft(chat_id=chat.id, reply_result=reply_result, decision=decision)
            await self.journal.append_chat_event(
                chat.id,
                build_workflow_event(
                    action=decision.action,
                    mode=decision.mode,
                    status="prepared",
                    actor=actor,
                    automatic=True,
                    message="Автопилот подготовил черновик.",
                    reason=decision.reason,
                    confidence=decision.confidence,
                    trigger=decision.trigger,
                    chat_id=chat.id,
                    source_message_id=decision.source_message_id,
                    text_preview=_preview_text(decision.reply_text),
                ),
            )
            return AutopilotRunResult(decision=decision)

        send_result = await self.send_service.send_chat_message(
            chat,
            text=decision.reply_text or "",
            reply_to_source_message_id=decision.source_message_id,
            trigger="autopilot",
        )
        await self._mark_sent(
            chat_id=chat.id,
            source_message_id=decision.source_message_id,
            sent_message_id=send_result.sent_message_id,
            cooldown_seconds=global_settings.cooldown_seconds,
        )
        await self.journal.append_chat_event(
            chat.id,
            build_workflow_event(
                action="send",
                mode=decision.mode,
                status="sent",
                actor=actor,
                automatic=True,
                message="Автопилот отправил сообщение.",
                reason=decision.reason,
                confidence=decision.confidence,
                trigger=decision.trigger,
                chat_id=chat.id,
                source_message_id=decision.source_message_id,
                sent_message_id=send_result.sent_message_id,
                text_preview=_preview_text(decision.reply_text),
            ),
        )
        return AutopilotRunResult(
            decision=decision,
            send_result=send_result,
        )

    async def record_manual_send(
        self,
        *,
        chat_id: int,
        source_message_id: int | None,
        sent_message_id: int,
        text: str,
        actor: str,
    ) -> None:
        await self._mark_sent(
            chat_id=chat_id,
            source_message_id=source_message_id,
            sent_message_id=sent_message_id,
            cooldown_seconds=(await self.get_global_settings()).cooldown_seconds,
        )
        await self.journal.append_chat_event(
            chat_id,
            build_workflow_event(
                action="manual_send",
                mode="manual",
                status="sent",
                actor=actor,
                automatic=False,
                message="Сообщение отправлено вручную из desktop.",
                chat_id=chat_id,
                source_message_id=source_message_id,
                sent_message_id=sent_message_id,
                text_preview=_preview_text(text),
            ),
        )

    async def _record_blocked(
        self,
        *,
        chat_id: int,
        decision: AutopilotDecision,
        actor: str,
    ) -> None:
        state = await self._load_chat_state(chat_id)
        last_blocked = state.get("last_blocked_source_message_id")
        if last_blocked == decision.source_message_id and state.get("last_blocked_reason") == decision.reason:
            return
        state["last_blocked_source_message_id"] = decision.source_message_id
        state["last_blocked_reason"] = decision.reason
        await self._save_chat_state(chat_id, state)
        await self.journal.append_chat_event(
            chat_id,
            build_workflow_event(
                action="blocked",
                mode=decision.mode,
                status="blocked",
                actor=actor,
                automatic=True,
                message="Автопилот не стал отвечать.",
                reason=decision.reason,
                confidence=decision.confidence,
                trigger=decision.trigger,
                chat_id=chat_id,
                source_message_id=decision.source_message_id,
                text_preview=_preview_text(decision.reply_text),
            ),
        )

    async def _mark_sent(
        self,
        *,
        chat_id: int,
        source_message_id: int | None,
        sent_message_id: int,
        cooldown_seconds: int,
    ) -> None:
        state = await self._load_chat_state(chat_id)
        state["pending_draft"] = None
        state["last_sent_at"] = datetime.now(timezone.utc).isoformat()
        state["last_source_message_id"] = source_message_id
        state["last_sent_message_id"] = sent_message_id
        state["cooldown_until"] = (
            datetime.now(timezone.utc) + timedelta(seconds=max(30, cooldown_seconds))
        ).isoformat()
        await self._save_chat_state(chat_id, state)

    async def _save_pending_draft(
        self,
        *,
        chat_id: int,
        reply_result: ReplyResult,
        decision: AutopilotDecision,
    ) -> None:
        suggestion = reply_result.suggestion
        if suggestion is None:
            return
        state = await self._load_chat_state(chat_id)
        current = state.get("pending_draft")
        if (
            isinstance(current, dict)
            and current.get("source_message_id") == decision.source_message_id
            and current.get("text") == decision.reply_text
            and current.get("mode") == decision.mode
        ):
            return
        state["pending_draft"] = {
            "text": decision.reply_text,
            "mode": decision.mode,
            "status": "await_confirmation" if decision.action == "confirm" else "draft",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "source_message_id": decision.source_message_id,
            "confidence": decision.confidence,
            "trigger": decision.trigger,
            "focus_label": suggestion.focus_label,
            "source_message_preview": suggestion.source_message_preview,
            "reply_opportunity_reason": suggestion.reply_opportunity_reason,
        }
        await self._save_chat_state(chat_id, state)

    async def _load_chat_state(self, chat_id: int) -> dict[str, Any]:
        payload = await self.setting_repository.get_value(f"{AUTOPILOT_CHAT_STATE_PREFIX}{chat_id}")
        return payload if isinstance(payload, dict) else {}

    async def _save_chat_state(self, chat_id: int, payload: dict[str, Any]) -> None:
        await self.setting_repository.set_value(
            key=f"{AUTOPILOT_CHAT_STATE_PREFIX}{chat_id}",
            value_json=payload,
            value_text=None,
        )

    def _evaluate(
        self,
        *,
        chat,
        reply_result: ReplyResult | None,
        global_settings: AutopilotGlobalSettings,
        state: dict[str, Any],
        write_ready: bool,
    ) -> AutopilotDecision:
        mode = normalize_autopilot_mode(chat.auto_reply_mode)
        suggestion = reply_result.suggestion if reply_result is not None else None
        confidence = suggestion.confidence if suggestion is not None else None
        trigger = suggestion.focus_label if suggestion is not None else None
        source_message_id = suggestion.source_message_id if suggestion is not None else None
        reply_text = suggestion.reply_text if suggestion is not None else None

        if mode == "off":
            return AutopilotDecision(
                mode=mode,
                action="none",
                allowed=False,
                reason="Режим автопилота для чата выключен.",
                confidence=confidence,
                trigger=trigger,
                source_message_id=source_message_id,
                reply_text=reply_text,
            )
        if not global_settings.master_enabled:
            return AutopilotDecision(
                mode=mode,
                action="none",
                allowed=False,
                reason="Глобальный мастер-переключатель автопилота выключен.",
                confidence=confidence,
                trigger=trigger,
                source_message_id=source_message_id,
                reply_text=reply_text,
            )
        if not getattr(chat, "reply_assist_enabled", False):
            return AutopilotDecision(
                mode=mode,
                action="none",
                allowed=False,
                reason="Чат не добавлен в trusted list.",
                confidence=confidence,
                trigger=trigger,
                source_message_id=source_message_id,
                reply_text=reply_text,
            )
        if getattr(chat, "type", None) == "channel" and not global_settings.allow_channels:
            return AutopilotDecision(
                mode=mode,
                action="none",
                allowed=False,
                reason="Для каналов автопилот запрещён без явного списка разрешённых.",
                confidence=confidence,
                trigger=trigger,
                source_message_id=source_message_id,
                reply_text=reply_text,
            )
        if suggestion is None or not reply_text or suggestion.strategy == "не отвечать":
            return AutopilotDecision(
                mode=mode,
                action="none",
                allowed=False,
                reason="Триггер слишком слабый: reply-контур не рекомендует писать.",
                confidence=confidence,
                trigger=trigger,
                source_message_id=source_message_id,
                reply_text=reply_text,
            )
        if confidence is None or confidence < (
            global_settings.min_send_confidence if mode == "autopilot" else global_settings.min_prepare_confidence
        ):
            return AutopilotDecision(
                mode=mode,
                action="none",
                allowed=False,
                reason="Уверенность ниже порога для автодействия.",
                confidence=confidence,
                trigger=trigger,
                source_message_id=source_message_id,
                reply_text=reply_text,
            )
        if state.get("last_source_message_id") == source_message_id:
            return AutopilotDecision(
                mode=mode,
                action="none",
                allowed=False,
                reason="Новый meaningful signal не появился, повторять ответ нельзя.",
                confidence=confidence,
                trigger=trigger,
                source_message_id=source_message_id,
                reply_text=reply_text,
            )
        cooldown_until = _parse_datetime(state.get("cooldown_until"))
        if cooldown_until is not None and cooldown_until > datetime.now(timezone.utc):
            return AutopilotDecision(
                mode=mode,
                action="none",
                allowed=False,
                reason="Сработала пауза: чат ещё в антиспам-окне.",
                confidence=confidence,
                trigger=trigger,
                source_message_id=source_message_id,
                reply_text=reply_text,
            )
        pending_draft = state.get("pending_draft")
        if (
            isinstance(pending_draft, dict)
            and pending_draft.get("source_message_id") == source_message_id
            and pending_draft.get("text") == reply_text
            and mode in {"draft", "confirm"}
        ):
            return AutopilotDecision(
                mode=mode,
                action="none",
                allowed=False,
                reason="Черновик по этому триггеру уже подготовлен.",
                confidence=confidence,
                trigger=trigger,
                source_message_id=source_message_id,
                reply_text=reply_text,
            )
        if mode == "draft":
            return AutopilotDecision(
                mode=mode,
                action="draft",
                allowed=True,
                reason="Режим «Черновик»: подготовить текст без отправки.",
                confidence=confidence,
                trigger=trigger,
                source_message_id=source_message_id,
                reply_text=reply_text,
                pending_draft_status="draft",
            )
        if mode == "confirm":
            return AutopilotDecision(
                mode=mode,
                action="confirm",
                allowed=True,
                reason="Режим «Полуавтомат»: нужен один явный confirm на отправку.",
                confidence=confidence,
                trigger=trigger,
                source_message_id=source_message_id,
                reply_text=reply_text,
                pending_draft_status="await_confirmation",
            )
        if not write_ready:
            return AutopilotDecision(
                mode=mode,
                action="none",
                allowed=False,
                reason="Режим записи сейчас недоступен, поэтому автопилот не может отправить сообщение.",
                confidence=confidence,
                trigger=trigger,
                source_message_id=source_message_id,
                reply_text=reply_text,
            )
        return AutopilotDecision(
            mode=mode,
            action="send",
            allowed=True,
            reason="Режим «Автопилот»: trigger достаточно сильный, сообщение можно отправить автоматически.",
            confidence=confidence,
            trigger=trigger,
            source_message_id=source_message_id,
            reply_text=reply_text,
        )


def normalize_autopilot_mode(value: str | None, *, fallback: str = "off") -> str:
    if value is None:
        return fallback
    normalized = value.strip().lower()
    if not normalized:
        return fallback
    if normalized == "manual":
        return "confirm"
    if normalized == "semi_auto":
        return "confirm"
    if normalized in AUTOPILOT_MODES:
        return normalized
    return fallback


def _build_cooldown_payload(*, cooldown_until: datetime | None) -> dict[str, Any]:
    if cooldown_until is None:
        return {"active": False, "remainingSeconds": 0, "until": None}
    remaining_seconds = max(0, int((cooldown_until - datetime.now(timezone.utc)).total_seconds()))
    return {
        "active": remaining_seconds > 0,
        "remainingSeconds": remaining_seconds,
        "until": cooldown_until.isoformat(),
    }


def _parse_datetime(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _preview_text(value: str | None) -> str | None:
    if not value:
        return None
    compact = " ".join(value.split()).strip()
    if len(compact) <= 120:
        return compact
    return f"{compact[:117].rstrip()}..."
