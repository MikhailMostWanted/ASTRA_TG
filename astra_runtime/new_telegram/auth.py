from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any, Protocol, cast

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from astra_runtime.new_telegram.config import NewTelegramRuntimeConfig
from astra_runtime.status import (
    RuntimeAuthSessionState,
    RuntimeAuthState,
    RuntimeSessionState,
)
from storage.repositories import SettingRepository


NEW_TELEGRAM_AUTH_SESSION_KEY = "runtime.new_telegram.auth_session"


class NewTelegramAuthSessionStore(Protocol):
    async def load(self, config: NewTelegramRuntimeConfig) -> RuntimeAuthSessionState: ...

    async def save(self, state: RuntimeAuthSessionState) -> None: ...

    async def clear(self, config: NewTelegramRuntimeConfig) -> RuntimeAuthSessionState: ...


class DatabaseNewTelegramAuthSessionStore:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def load(self, config: NewTelegramRuntimeConfig) -> RuntimeAuthSessionState:
        async with self._session_factory() as session:
            value = await SettingRepository(session).get_value(NEW_TELEGRAM_AUTH_SESSION_KEY)
        return build_auth_session_state(value, config=config)

    async def save(self, state: RuntimeAuthSessionState) -> None:
        async with self._session_factory() as session:
            await SettingRepository(session).set_value(
                key=NEW_TELEGRAM_AUTH_SESSION_KEY,
                value_json=_state_to_storage_payload(state),
                value_text=None,
            )
            await session.commit()

    async def clear(self, config: NewTelegramRuntimeConfig) -> RuntimeAuthSessionState:
        state = default_auth_session_state(config)
        await self.save(state)
        return state


def default_auth_session_state(config: NewTelegramRuntimeConfig) -> RuntimeAuthSessionState:
    session_exists = config.session_path.exists()
    session_state: RuntimeSessionState = "available" if session_exists else "missing"
    reason = (
        "Session file exists, but the new runtime has not verified Telegram auth yet."
        if session_exists
        else "New Telegram runtime is not authorized yet."
    )
    return RuntimeAuthSessionState(
        auth_state="unauthorized",
        session_state=session_state,
        device_name=config.device_name,
        session_path=str(config.session_path),
        updated_at=datetime.now(timezone.utc),
        reason=reason,
    )


def build_auth_session_state(
    value: object,
    *,
    config: NewTelegramRuntimeConfig,
) -> RuntimeAuthSessionState:
    if not isinstance(value, Mapping):
        return default_auth_session_state(config)

    session_exists = config.session_path.exists()
    raw_session_state = _read_literal(
        value.get("session_state"),
        allowed={"unknown", "missing", "available", "invalid"},
        fallback="available" if session_exists else "missing",
    )
    raw_auth_state = _read_literal(
        value.get("auth_state"),
        allowed={"unknown", "unauthorized", "authorizing", "authorized", "error"},
        fallback="unauthorized",
    )
    updated_at = _parse_datetime(value.get("updated_at"))
    return RuntimeAuthSessionState(
        auth_state=cast(RuntimeAuthState, raw_auth_state),
        session_state=cast(RuntimeSessionState, raw_session_state),
        user_id=_read_int(value.get("user_id")),
        username=_read_string(value.get("username")),
        phone_hint=_read_string(value.get("phone_hint")),
        device_id=_read_string(value.get("device_id")),
        device_name=_read_string(value.get("device_name")) or config.device_name,
        session_path=_read_string(value.get("session_path")) or str(config.session_path),
        updated_at=updated_at,
        reason=_read_string(value.get("reason")),
    )


def _state_to_storage_payload(state: RuntimeAuthSessionState) -> dict[str, Any]:
    return {
        "auth_state": state.auth_state,
        "session_state": state.session_state,
        "user_id": state.user_id,
        "username": state.username,
        "phone_hint": state.phone_hint,
        "device_id": state.device_id,
        "device_name": state.device_name,
        "session_path": state.session_path,
        "updated_at": (state.updated_at or datetime.now(timezone.utc)).isoformat(),
        "reason": state.reason,
    }


def _read_literal(value: object, *, allowed: set[str], fallback: str) -> str:
    if isinstance(value, str) and value in allowed:
        return value
    return fallback


def _read_string(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _read_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return None


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
