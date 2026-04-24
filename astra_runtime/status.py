from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal

from astra_runtime.switches import RuntimeBackend


RuntimeLifecycle = Literal["stopped", "starting", "running", "stopping", "failed"]
RuntimeAuthState = Literal["unknown", "unauthorized", "authorizing", "authorized", "error"]
RuntimeSessionState = Literal["unknown", "missing", "available", "invalid"]
RuntimeAuthMachineState = Literal[
    "disabled",
    "idle",
    "code_requested",
    "awaiting_code",
    "awaiting_password",
    "authorized",
    "logout_in_progress",
    "error",
]


class RuntimeUnavailableError(RuntimeError):
    """Raised when a runtime surface is called before it is route-ready."""

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        action_hint: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.action_hint = action_hint


@dataclass(frozen=True, slots=True)
class RuntimeAuthSessionState:
    state: RuntimeAuthMachineState = "idle"
    auth_state: RuntimeAuthState = "unauthorized"
    session_state: RuntimeSessionState = "missing"
    user_id: int | None = None
    username: str | None = None
    phone_hint: str | None = None
    pending_phone: str | None = None
    phone_code_hash: str | None = None
    device_id: str | None = None
    device_name: str | None = None
    session_path: str | None = None
    updated_at: datetime | None = None
    state_changed_at: datetime | None = None
    code_requested_at: datetime | None = None
    authorized_at: datetime | None = None
    logout_started_at: datetime | None = None
    last_checked_at: datetime | None = None
    reason_code: str | None = None
    reason: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    error_at: datetime | None = None

    @property
    def authorized(self) -> bool:
        return self.state == "authorized" and self.session_state == "available"

    @property
    def awaiting_code(self) -> bool:
        return self.state in {"code_requested", "awaiting_code"}

    @property
    def awaiting_password(self) -> bool:
        return self.state == "awaiting_password"

    @property
    def can_request_code(self) -> bool:
        return self.state in {"idle", "error"}

    @property
    def can_submit_code(self) -> bool:
        return self.awaiting_code

    @property
    def can_submit_password(self) -> bool:
        return self.awaiting_password

    @property
    def can_logout(self) -> bool:
        return self.state in {
            "authorized",
            "awaiting_code",
            "awaiting_password",
            "error",
            "idle",
        }

    @property
    def can_reset(self) -> bool:
        return self.state != "disabled" or self.session_state != "missing"

    def to_payload(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "authState": self.auth_state,
            "sessionState": self.session_state,
            "authorized": self.authorized,
            "awaitingCode": self.awaiting_code,
            "awaitingPassword": self.awaiting_password,
            "canRequestCode": self.can_request_code,
            "canSubmitCode": self.can_submit_code,
            "canSubmitPassword": self.can_submit_password,
            "canLogout": self.can_logout,
            "canReset": self.can_reset,
            "user": {
                "id": self.user_id,
                "username": self.username,
                "phoneHint": self.phone_hint,
            },
            "device": {
                "id": self.device_id,
                "name": self.device_name,
            },
            "session": {
                "path": self.session_path,
                "stored": self.session_state == "available",
            },
            "updatedAt": _serialize_datetime(self.updated_at),
            "stateChangedAt": _serialize_datetime(self.state_changed_at),
            "codeRequestedAt": _serialize_datetime(self.code_requested_at),
            "authorizedAt": _serialize_datetime(self.authorized_at),
            "logoutStartedAt": _serialize_datetime(self.logout_started_at),
            "lastCheckedAt": _serialize_datetime(self.last_checked_at),
            "timestamps": {
                "updatedAt": _serialize_datetime(self.updated_at),
                "stateChangedAt": _serialize_datetime(self.state_changed_at),
                "codeRequestedAt": _serialize_datetime(self.code_requested_at),
                "authorizedAt": _serialize_datetime(self.authorized_at),
                "logoutStartedAt": _serialize_datetime(self.logout_started_at),
                "lastCheckedAt": _serialize_datetime(self.last_checked_at),
                "errorAt": _serialize_datetime(self.error_at),
            },
            "reasonCode": self.reason_code,
            "reason": self.reason,
            "error": (
                {
                    "code": self.error_code,
                    "message": self.error_message,
                    "at": _serialize_datetime(self.error_at),
                }
                if self.error_code or self.error_message or self.error_at
                else None
            ),
        }


@dataclass(frozen=True, slots=True)
class RuntimeBackendStatus:
    backend: RuntimeBackend
    name: str
    registered: bool
    lifecycle: RuntimeLifecycle
    active: bool
    healthy: bool
    ready: bool
    route_available: bool
    started_at: datetime | None = None
    stopped_at: datetime | None = None
    last_error: str | None = None
    degraded_reason: str | None = None
    unavailable_reason: str | None = None
    auth_session: RuntimeAuthSessionState | None = None
    capabilities: tuple[str, ...] = ()

    @property
    def uptime_seconds(self) -> float | None:
        if self.lifecycle != "running" or self.started_at is None:
            return None
        started = _ensure_utc(self.started_at)
        return max(0.0, (datetime.now(timezone.utc) - started).total_seconds())

    def to_payload(self) -> dict[str, Any]:
        return {
            "backend": self.backend,
            "name": self.name,
            "registered": self.registered,
            "lifecycle": self.lifecycle,
            "active": self.active,
            "healthy": self.healthy,
            "ready": self.ready,
            "routeAvailable": self.route_available,
            "startedAt": _serialize_datetime(self.started_at),
            "stoppedAt": _serialize_datetime(self.stopped_at),
            "uptimeSeconds": self.uptime_seconds,
            "lastError": self.last_error,
            "degradedReason": self.degraded_reason,
            "unavailableReason": self.unavailable_reason,
            "auth": self.auth_session.to_payload() if self.auth_session is not None else None,
            "capabilities": list(self.capabilities),
        }


@dataclass(frozen=True, slots=True)
class RuntimeRouteStatus:
    surface: str
    requested: RuntimeBackend
    effective: RuntimeBackend
    target_available: bool
    target_ready: bool
    reason: str | None = None
    status: str = "available"
    reason_code: str | None = None
    action_hint: str | None = None

    def to_payload(self) -> dict[str, Any]:
        return {
            "surface": self.surface,
            "requested": self.requested,
            "effective": self.effective,
            "targetAvailable": self.target_available,
            "targetReady": self.target_ready,
            "status": self.status,
            "reason": self.reason,
            "reasonCode": self.reason_code,
            "actionHint": self.action_hint,
        }


def _serialize_datetime(value: datetime | None) -> str | None:
    if value is None:
        return None
    return _ensure_utc(value).isoformat()


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
