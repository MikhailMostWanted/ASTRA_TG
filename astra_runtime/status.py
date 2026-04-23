from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal

from astra_runtime.switches import RuntimeBackend


RuntimeLifecycle = Literal["stopped", "starting", "running", "stopping", "failed"]
RuntimeAuthState = Literal["unknown", "unauthorized", "authorizing", "authorized", "error"]
RuntimeSessionState = Literal["unknown", "missing", "available", "invalid"]


class RuntimeUnavailableError(RuntimeError):
    """Raised when a runtime surface is called before it is route-ready."""


@dataclass(frozen=True, slots=True)
class RuntimeAuthSessionState:
    auth_state: RuntimeAuthState = "unauthorized"
    session_state: RuntimeSessionState = "missing"
    user_id: int | None = None
    username: str | None = None
    phone_hint: str | None = None
    device_id: str | None = None
    device_name: str | None = None
    session_path: str | None = None
    updated_at: datetime | None = None
    reason: str | None = None

    @property
    def authorized(self) -> bool:
        return self.auth_state == "authorized" and self.session_state == "available"

    def to_payload(self) -> dict[str, Any]:
        return {
            "authState": self.auth_state,
            "sessionState": self.session_state,
            "authorized": self.authorized,
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
            "reason": self.reason,
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

    def to_payload(self) -> dict[str, Any]:
        return {
            "surface": self.surface,
            "requested": self.requested,
            "effective": self.effective,
            "targetAvailable": self.target_available,
            "targetReady": self.target_ready,
            "reason": self.reason,
        }


def _serialize_datetime(value: datetime | None) -> str | None:
    if value is None:
        return None
    return _ensure_utc(value).isoformat()


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
