"""Target runtime boundary for the Astra architecture pivot."""

from astra_runtime.contracts import (
    AutopilotControlSurface,
    ChatRoster,
    DraftReplyWorkspace,
    MessageHistory,
    MessageSender,
    TelegramRuntime,
)
from astra_runtime.manager import LegacyRuntimeBackend, RuntimeManager, StaticRuntimeBackend
from astra_runtime.router import RuntimeRouter
from astra_runtime.status import RuntimeBackendStatus, RuntimeUnavailableError
from astra_runtime.switches import RuntimeSwitches

__all__ = [
    "AutopilotControlSurface",
    "ChatRoster",
    "DraftReplyWorkspace",
    "LegacyRuntimeBackend",
    "MessageHistory",
    "MessageSender",
    "RuntimeBackendStatus",
    "RuntimeManager",
    "RuntimeRouter",
    "RuntimeSwitches",
    "RuntimeUnavailableError",
    "StaticRuntimeBackend",
    "TelegramRuntime",
]
