from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


RuntimeBackend = Literal["legacy", "new"]
VALID_RUNTIME_BACKENDS: set[str] = {"legacy", "new"}


@dataclass(frozen=True, slots=True)
class RuntimeSwitches:
    """Feature switches for migrating one runtime surface at a time."""

    chat_roster: RuntimeBackend = "legacy"
    message_workspace: RuntimeBackend = "legacy"
    reply_generation: RuntimeBackend = "legacy"
    send_path: RuntimeBackend = "legacy"
    autopilot_control: RuntimeBackend = "legacy"

    @classmethod
    def from_settings(cls, settings) -> "RuntimeSwitches":
        return cls(
            chat_roster=_normalize_backend(
                settings.runtime_chat_roster_backend,
                field_name="runtime_chat_roster_backend",
            ),
            message_workspace=_normalize_backend(
                settings.runtime_message_workspace_backend,
                field_name="runtime_message_workspace_backend",
            ),
            reply_generation=_normalize_backend(
                settings.runtime_reply_generation_backend,
                field_name="runtime_reply_generation_backend",
            ),
            send_path=_normalize_backend(
                settings.runtime_send_path_backend,
                field_name="runtime_send_path_backend",
            ),
            autopilot_control=_normalize_backend(
                settings.runtime_autopilot_control_backend,
                field_name="runtime_autopilot_control_backend",
            ),
        )

    def requested_backends(self) -> dict[str, RuntimeBackend]:
        return {
            "chatRoster": self.chat_roster,
            "messageWorkspace": self.message_workspace,
            "replyGeneration": self.reply_generation,
            "sendPath": self.send_path,
            "autopilotControl": self.autopilot_control,
        }


def _normalize_backend(value: str | None, *, field_name: str) -> RuntimeBackend:
    normalized = (value or "legacy").strip().lower()
    if normalized not in VALID_RUNTIME_BACKENDS:
        allowed = ", ".join(sorted(VALID_RUNTIME_BACKENDS))
        raise ValueError(f"{field_name} must be one of: {allowed}.")
    return normalized  # type: ignore[return-value]
