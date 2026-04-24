from __future__ import annotations

from dataclasses import dataclass

from astra_runtime.contracts import (
    AutopilotControlSurface,
    ChatRoster,
    DraftReplyWorkspace,
    MessageHistory,
    MessageSender,
    TelegramRuntime,
)
from astra_runtime.status import RuntimeUnavailableError
from astra_runtime.switches import RuntimeBackend, RuntimeSwitches


@dataclass(frozen=True, slots=True)
class RuntimeRouteStatus:
    requested: RuntimeBackend
    effective: RuntimeBackend
    target_available: bool
    status: str

    @property
    def reason(self) -> str | None:
        if self.status == "available":
            return None
        return "New runtime is not registered yet."

    def to_payload(self) -> dict[str, object]:
        return {
            "requested": self.requested,
            "effective": self.effective,
            "targetAvailable": self.target_available,
            "targetReady": self.status == "available" and self.effective == "new",
            "status": self.status,
            "reason": self.reason,
            "reasonCode": None if self.status == "available" else "not_registered",
            "actionHint": None if self.status == "available" else "Проверь запуск нового Telegram runtime.",
        }


@dataclass(slots=True)
class RuntimeRouter:
    """Routes runtime surfaces between legacy and the future target core."""

    legacy: TelegramRuntime
    switches: RuntimeSwitches
    target: TelegramRuntime | None = None

    @property
    def chat_roster(self) -> ChatRoster:
        return self._select("chat_roster", self.switches.chat_roster)

    @property
    def message_history(self) -> MessageHistory:
        return self._select("message_history", self.switches.message_workspace)

    @property
    def reply_workspace(self) -> DraftReplyWorkspace:
        return self._select("reply_workspace", self.switches.reply_generation)

    @property
    def message_sender(self) -> MessageSender:
        return self._select("message_sender", self.switches.send_path)

    @property
    def autopilot(self) -> AutopilotControlSurface:
        return self._select("autopilot", self.switches.autopilot_control)

    def describe(self) -> dict[str, object]:
        return {
            "targetRegistered": self.target is not None,
            "routes": {
                "chatRoster": self._status(self.switches.chat_roster).to_payload(),
                "messageWorkspace": self._status(self.switches.message_workspace).to_payload(),
                "replyGeneration": self._status(self.switches.reply_generation).to_payload(),
                "sendPath": self._status(self.switches.send_path).to_payload(),
                "autopilotControl": self._status(self.switches.autopilot_control).to_payload(),
            },
        }

    def _select(self, component: str, requested: RuntimeBackend):
        if requested == "new" and self.target is not None:
            return getattr(self.target, component)
        if requested == "new":
            raise RuntimeUnavailableError(
                "New runtime is not registered yet.",
                code="not_registered",
                action_hint="Проверь запуск нового Telegram runtime.",
            )
        return getattr(self.legacy, component)

    def _status(self, requested: RuntimeBackend) -> RuntimeRouteStatus:
        effective: RuntimeBackend = requested
        status = "available"
        if requested == "new" and self.target is None:
            status = "unavailable"
        return RuntimeRouteStatus(
            requested=requested,
            effective=effective,
            target_available=self.target is not None,
            status=status,
        )
