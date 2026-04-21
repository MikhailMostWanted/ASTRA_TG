from __future__ import annotations

import asyncio
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from config.settings import Settings
from fullaccess.auth import FullAccessAuthService
from services.operational_state import OperationalStateService
from services.providers.manager import ProviderManager
from services.system_readiness import SystemReadinessService
from storage.repositories import (
    ChatMemoryRepository,
    ChatRepository,
    ChatStyleOverrideRepository,
    DigestRepository,
    MessageRepository,
    PersonMemoryRepository,
    ReplyExampleRepository,
    ReminderRepository,
    SettingRepository,
    StyleProfileRepository,
    SystemRepository,
    TaskRepository,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
BACKUP_DIR = REPOSITORY_ROOT / "var" / "backups"
EXPORT_DIR = REPOSITORY_ROOT / "var" / "exports"


@dataclass(frozen=True, slots=True)
class BackupResult:
    created: bool
    path: Path
    source_path: Path


@dataclass(frozen=True, slots=True)
class ExportResult:
    path: Path
    payload: dict[str, object]


@dataclass(slots=True)
class OperationalBackupService:
    settings: Settings
    session_factory: async_sessionmaker[AsyncSession] | None = None

    async def create_backup(self) -> BackupResult:
        source_path = self.settings.sqlite_database_path
        if source_path is None:
            raise ValueError("Backup поддержан только для SQLite database_url.")
        if not source_path.exists():
            raise ValueError(f"SQLite база не найдена: {source_path}")

        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        backup_path = BACKUP_DIR / f"astra-backup-{_timestamp_label()}.sqlite3"
        await asyncio.to_thread(_backup_sqlite_file, source_path, backup_path)

        if self.session_factory is not None:
            async with self.session_factory() as session:
                await OperationalStateService(SettingRepository(session)).record_backup(
                    path=str(backup_path),
                    source_path=str(source_path),
                )
                await session.commit()

        return BackupResult(
            created=True,
            path=backup_path,
            source_path=source_path,
        )


@dataclass(slots=True)
class OperationalExportService:
    settings: Settings
    session_factory: async_sessionmaker[AsyncSession]

    async def export_summary(self) -> ExportResult:
        payload = await self.build_summary()
        EXPORT_DIR.mkdir(parents=True, exist_ok=True)
        export_path = EXPORT_DIR / f"operational-summary-{_timestamp_label()}.json"
        export_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        async with self.session_factory() as session:
            await OperationalStateService(SettingRepository(session)).record_export(
                path=str(export_path),
            )
            await session.commit()

        return ExportResult(path=export_path, payload=payload)

    async def build_summary(self) -> dict[str, object]:
        async with self.session_factory() as session:
            setting_repository = SettingRepository(session)
            readiness = await SystemReadinessService(
                chat_repository=ChatRepository(session),
                setting_repository=setting_repository,
                system_repository=SystemRepository(session),
                message_repository=MessageRepository(session),
                digest_repository=DigestRepository(session),
                chat_memory_repository=ChatMemoryRepository(session),
                person_memory_repository=PersonMemoryRepository(session),
                style_profile_repository=StyleProfileRepository(session),
                chat_style_override_repository=ChatStyleOverrideRepository(session),
                task_repository=TaskRepository(session),
                reminder_repository=ReminderRepository(session),
                reply_example_repository=ReplyExampleRepository(session),
                provider_manager=ProviderManager.from_settings(
                    self.settings,
                    setting_repository=setting_repository,
                ),
                fullaccess_auth_service=FullAccessAuthService(
                    settings=self.settings,
                    setting_repository=setting_repository,
                    message_repository=MessageRepository(session),
                ),
                settings=self.settings,
            ).build_report()
            facts = readiness.facts

            return {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "database": {
                    "database_url": self.settings.database_url,
                    "sqlite_path": str(self.settings.sqlite_database_path)
                    if self.settings.sqlite_database_path is not None
                    else None,
                    "schema_revision": facts.schema_revision,
                },
                "counts": {
                    "sources": facts.total_sources,
                    "active_sources": facts.active_sources,
                    "messages": facts.total_messages,
                    "digests": facts.total_digests,
                    "memory_cards": facts.chat_memory_cards + facts.person_memory_cards,
                    "chat_memory_cards": facts.chat_memory_cards,
                    "person_memory_cards": facts.person_memory_cards,
                    "reply_examples": facts.reply_examples,
                    "tasks": facts.candidate_tasks + facts.confirmed_tasks,
                    "candidate_tasks": facts.candidate_tasks,
                    "confirmed_tasks": facts.confirmed_tasks,
                    "reminders": facts.active_reminders,
                },
                "provider": {
                    "enabled": facts.provider_status.enabled,
                    "configured": facts.provider_status.configured,
                    "available": facts.provider_status.available,
                    "provider_name": facts.provider_status.provider_name,
                    "reason": facts.provider_status.reason,
                },
                "fullaccess": {
                    "enabled": bool(facts.fullaccess_status and facts.fullaccess_status.enabled),
                    "ready": bool(
                        facts.fullaccess_status
                        and facts.fullaccess_status.ready_for_manual_sync
                    ),
                    "reason": facts.fullaccess_status.reason
                    if facts.fullaccess_status is not None
                    else "Experimental full-access выключен.",
                },
                "timestamps": {
                    "last_message_at": _serialize_timestamp(facts.last_message_at),
                    "last_digest_at": _serialize_timestamp(facts.last_digest_at),
                    "last_memory_rebuild_at": _serialize_timestamp(facts.last_memory_rebuild_at),
                    "last_reminder_notification_at": _serialize_timestamp(
                        facts.last_reminder_notification
                    ),
                    "last_fullaccess_sync_at": _serialize_timestamp(
                        facts.last_fullaccess_sync_at
                    ),
                    "last_backup_at": _serialize_timestamp(facts.last_backup_at),
                    "last_export_at": _serialize_timestamp(facts.last_export_at),
                },
                "operational": {
                    "owner_chat_id": facts.owner_chat_id,
                    "backup_tool_available": facts.backup_tool_available,
                    "export_tool_available": facts.export_tool_available,
                    "startup_warnings": list(facts.startup_warnings),
                    "recent_errors": {
                        "worker": facts.recent_worker_error,
                        "provider": facts.recent_provider_error,
                        "fullaccess": facts.recent_fullaccess_error,
                    },
                },
            }


def _backup_sqlite_file(source_path: Path, backup_path: Path) -> None:
    with sqlite3.connect(str(source_path)) as source_connection:
        with sqlite3.connect(str(backup_path)) as backup_connection:
            source_connection.backup(backup_connection)


def _timestamp_label() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def _serialize_timestamp(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    else:
        value = value.astimezone(timezone.utc)
    return value.isoformat()
