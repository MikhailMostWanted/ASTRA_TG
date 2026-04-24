from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol


class OperationalStateRepositoryProtocol(Protocol):
    async def get_value(self, key: str) -> object: ...

    async def set_value(
        self,
        *,
        key: str,
        value_json: dict[str, Any] | list[Any] | None = None,
        value_text: str | None = None,
    ) -> object: ...


ERROR_KEY_MAP = {
    "worker": "ops.error.worker.last",
    "provider": "ops.error.provider.last",
    "fullaccess": "ops.error.fullaccess.last",
    "new_runtime": "ops.error.runtime.new.last",
}

SNAPSHOT_KEY_MAP = {
    "bot_startup": "ops.startup.bot.last",
    "worker_startup": "ops.startup.worker.last",
    "worker_run": "ops.worker.last_run",
    "backup": "ops.backup.last",
    "export": "ops.export.last",
    "fullaccess_sync": "ops.fullaccess.last_sync",
    "new_runtime": "ops.runtime.new.status",
    "chat_roster": "ops.runtime.chat_roster.last",
    "message_workspace": "ops.runtime.message_workspace.last",
    "manual_send": "ops.manual_send.last",
    "reply_execution": "ops.reply_execution.last",
    "live_status": "ops.live.status",
}

FULLACCESS_CHAT_SYNC_PREFIX = "ops.fullaccess.chat_sync."
LIVE_ACTIVITY_KEY = "ops.live.activity.recent"
MAX_LIVE_ACTIVITY_EVENTS = 40


@dataclass(frozen=True, slots=True)
class OperationalEvent:
    timestamp: datetime | None
    message: str | None
    payload: dict[str, Any]


@dataclass(slots=True)
class OperationalStateService:
    repository: OperationalStateRepositoryProtocol

    async def record_error(
        self,
        component: str,
        *,
        message: str,
        timestamp: datetime | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        key = ERROR_KEY_MAP[component]
        await self._store_json(
            key,
            {
                "timestamp": _serialize_timestamp(timestamp),
                "message": message,
                **(details or {}),
            },
        )

    async def get_error(self, component: str) -> OperationalEvent | None:
        key = ERROR_KEY_MAP[component]
        return await self.get_snapshot(key)

    async def record_startup_report(
        self,
        app_name: str,
        *,
        can_start: bool,
        warnings: tuple[str, ...],
        critical_issues: tuple[str, ...],
    ) -> None:
        key = SNAPSHOT_KEY_MAP[f"{app_name}_startup"]
        await self._store_json(
            key,
            {
                "timestamp": _serialize_timestamp(None),
                "can_start": can_start,
                "warnings": list(warnings),
                "critical_issues": list(critical_issues),
            },
        )

    async def record_worker_run(
        self,
        *,
        processed_count: int,
        delivered_count: int,
        failed_count: int,
        skipped_count: int,
        blocked_count: int,
        jobs_total: int,
        jobs_failed: int,
    ) -> None:
        await self._store_json(
            SNAPSHOT_KEY_MAP["worker_run"],
            {
                "timestamp": _serialize_timestamp(None),
                "processed_count": processed_count,
                "delivered_count": delivered_count,
                "failed_count": failed_count,
                "skipped_count": skipped_count,
                "blocked_count": blocked_count,
                "jobs_total": jobs_total,
                "jobs_failed": jobs_failed,
            },
        )

    async def record_backup(self, *, path: str, source_path: str) -> None:
        await self._store_json(
            SNAPSHOT_KEY_MAP["backup"],
            {
                "timestamp": _serialize_timestamp(None),
                "path": path,
                "source_path": source_path,
            },
        )

    async def record_export(self, *, path: str) -> None:
        await self._store_json(
            SNAPSHOT_KEY_MAP["export"],
            {
                "timestamp": _serialize_timestamp(None),
                "path": path,
            },
        )

    async def record_fullaccess_sync(
        self,
        *,
        reference: str,
        scanned_count: int,
        created_count: int,
        updated_count: int,
        skipped_count: int,
        trigger: str = "manual",
    ) -> None:
        await self._store_json(
            SNAPSHOT_KEY_MAP["fullaccess_sync"],
            {
                "timestamp": _serialize_timestamp(None),
                "reference": reference,
                "scanned_count": scanned_count,
                "created_count": created_count,
                "updated_count": updated_count,
                "skipped_count": skipped_count,
                "trigger": trigger,
            },
        )

    async def record_fullaccess_chat_sync(
        self,
        *,
        local_chat_id: int,
        telegram_chat_id: int,
        reference: str,
        scanned_count: int,
        created_count: int,
        updated_count: int,
        skipped_count: int,
        trigger: str = "manual",
    ) -> None:
        await self._store_json(
            f"{FULLACCESS_CHAT_SYNC_PREFIX}{local_chat_id}",
            {
                "timestamp": _serialize_timestamp(None),
                "local_chat_id": local_chat_id,
                "telegram_chat_id": telegram_chat_id,
                "reference": reference,
                "scanned_count": scanned_count,
                "created_count": created_count,
                "updated_count": updated_count,
                "skipped_count": skipped_count,
                "trigger": trigger,
            },
        )

    async def record_runtime_status(
        self,
        *,
        backend: str,
        status: dict[str, Any],
    ) -> None:
        if backend != "new":
            return
        await self._store_json(
            SNAPSHOT_KEY_MAP["new_runtime"],
            {
                "timestamp": _serialize_timestamp(None),
                "status": status,
            },
        )

    async def record_chat_roster_status(self, *, payload: dict[str, Any]) -> None:
        await self._store_json(
            SNAPSHOT_KEY_MAP["chat_roster"],
            {
                "timestamp": _serialize_timestamp(None),
                "payload": payload,
            },
        )

    async def get_chat_roster_status(self) -> OperationalEvent | None:
        return await self.get_named_snapshot("chat_roster")

    async def record_message_workspace_status(self, *, payload: dict[str, Any]) -> None:
        await self._store_json(
            SNAPSHOT_KEY_MAP["message_workspace"],
            {
                "timestamp": _serialize_timestamp(None),
                "payload": payload,
            },
        )

    async def get_message_workspace_status(self) -> OperationalEvent | None:
        return await self.get_named_snapshot("message_workspace")

    async def record_manual_send(self, *, payload: dict[str, Any]) -> None:
        await self._store_json(
            SNAPSHOT_KEY_MAP["manual_send"],
            {
                "timestamp": _serialize_timestamp(None),
                "payload": payload,
            },
        )

    async def get_manual_send_status(self) -> OperationalEvent | None:
        return await self.get_named_snapshot("manual_send")

    async def record_reply_execution(self, *, payload: dict[str, Any]) -> None:
        await self._store_json(
            SNAPSHOT_KEY_MAP["reply_execution"],
            {
                "timestamp": _serialize_timestamp(None),
                "payload": payload,
            },
        )

    async def get_reply_execution_status(self) -> OperationalEvent | None:
        return await self.get_named_snapshot("reply_execution")

    async def record_live_status(self, *, payload: dict[str, Any]) -> None:
        await self._store_json(
            SNAPSHOT_KEY_MAP["live_status"],
            {
                "timestamp": _serialize_timestamp(None),
                "payload": payload,
            },
        )

    async def get_live_status(self) -> OperationalEvent | None:
        return await self.get_named_snapshot("live_status")

    async def record_live_activity(self, *, payload: dict[str, Any]) -> None:
        current = await self.repository.get_value(LIVE_ACTIVITY_KEY)
        events = [item for item in (current if isinstance(current, list) else []) if isinstance(item, dict)]
        events.insert(
            0,
            {
                "timestamp": _serialize_timestamp(None),
                **payload,
            },
        )
        await self.repository.set_value(
            key=LIVE_ACTIVITY_KEY,
            value_json=events[:MAX_LIVE_ACTIVITY_EVENTS],
            value_text=None,
        )

    async def list_live_activity(self, *, limit: int = 12) -> tuple[dict[str, Any], ...]:
        payload = await self.repository.get_value(LIVE_ACTIVITY_KEY)
        if not isinstance(payload, list):
            return ()
        normalized = [item for item in payload if isinstance(item, dict)]
        return tuple(normalized[: max(1, int(limit))])

    async def get_fullaccess_chat_sync(self, local_chat_id: int) -> OperationalEvent | None:
        return await self.get_snapshot(f"{FULLACCESS_CHAT_SYNC_PREFIX}{local_chat_id}")

    async def get_named_snapshot(self, name: str) -> OperationalEvent | None:
        key = SNAPSHOT_KEY_MAP[name]
        return await self.get_snapshot(key)

    async def get_snapshot(self, key: str) -> OperationalEvent | None:
        payload = await self.repository.get_value(key)
        if not isinstance(payload, dict):
            return None
        return OperationalEvent(
            timestamp=_parse_timestamp(payload.get("timestamp")),
            message=_read_message(payload),
            payload=payload,
        )

    async def _store_json(self, key: str, payload: dict[str, Any]) -> None:
        if not hasattr(self.repository, "set_value"):
            return
        await self.repository.set_value(key=key, value_json=payload, value_text=None)


def _serialize_timestamp(value: datetime | None) -> str:
    effective = value or datetime.now(timezone.utc)
    if effective.tzinfo is None:
        effective = effective.replace(tzinfo=timezone.utc)
    else:
        effective = effective.astimezone(timezone.utc)
    return effective.isoformat()


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _read_message(payload: dict[str, Any]) -> str | None:
    message = payload.get("message")
    if isinstance(message, str) and message.strip():
        return message.strip()
    return None
