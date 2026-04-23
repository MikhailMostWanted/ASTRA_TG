from __future__ import annotations

import argparse
import os
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from astra_runtime.manager import LegacyRuntimeBackend, RuntimeManager
from astra_runtime.new_telegram import (
    DatabaseNewTelegramAuthSessionStore,
    NewTelegramRuntimeConfig,
    NewTelegramRuntimeService,
)
from astra_runtime.switches import RuntimeSwitches
from apps.ops.app import run_ops as run_ops_app
from config.settings import Settings
from fullaccess.auth import FullAccessAuthService
from services.providers.manager import ProviderManager
from services.operational_state import OperationalStateService
from services.system_health import DoctorReport, SystemHealthService
from services.system_readiness import OperationalReport, SystemReadinessService
from storage.database import bootstrap_database, build_database_runtime
from storage.repositories import (
    ChatMemoryRepository,
    ChatRepository,
    ChatStyleOverrideRepository,
    DigestRepository,
    MessageRepository,
    PersonMemoryRepository,
    ReminderRepository,
    ReplyExampleRepository,
    SettingRepository,
    StyleProfileRepository,
    SystemRepository,
    TaskRepository,
)


ComponentName = Literal["bot", "worker", "new-runtime"]
COMPONENTS: tuple[ComponentName, ...] = ("bot", "worker")
PROCESS_COMPONENTS: tuple[ComponentName, ...] = ("bot", "worker", "new-runtime")
DEFAULT_WORKER_INTERVAL_SECONDS = 60.0

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
VAR_DIR = REPOSITORY_ROOT / "var"
RUN_DIR = VAR_DIR / "run"
LOG_DIR = VAR_DIR / "log"


@dataclass(frozen=True, slots=True)
class ComponentFiles:
    name: ComponentName
    pid_path: Path
    log_path: Path


@dataclass(frozen=True, slots=True)
class DatabaseCheckResult:
    database_url: str
    sqlite_path: Path | None
    available: bool
    detail: str


@dataclass(frozen=True, slots=True)
class ProviderCheckResult:
    enabled: bool
    configured: bool
    available: bool
    provider_name: str | None
    reason: str


@dataclass(frozen=True, slots=True)
class DoctorSnapshot:
    readiness: OperationalReport | None
    doctor: DoctorReport | None
    error: str | None


@dataclass(frozen=True, slots=True)
class RuntimeDiagnosticSnapshot:
    status: dict[str, Any]
    process: Any
    database: DatabaseCheckResult
    checked_at: datetime


@dataclass(frozen=True, slots=True)
class RuntimeManagerBundle:
    manager: RuntimeManager
    database: Any


def get_repository_root() -> Path:
    return REPOSITORY_ROOT


def get_env_path() -> Path:
    return REPOSITORY_ROOT / ".env"


def chdir_to_repository_root() -> Path:
    os.chdir(REPOSITORY_ROOT)
    return REPOSITORY_ROOT


def ensure_runtime_dirs() -> None:
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)


def get_component_files(component: ComponentName) -> ComponentFiles:
    component_name = _validate_component(component)
    return ComponentFiles(
        name=component_name,
        pid_path=RUN_DIR / f"astra-{component_name}.pid",
        log_path=LOG_DIR / f"astra-{component_name}.log",
    )


def iter_component_files(component: ComponentName | None = None) -> tuple[ComponentFiles, ...]:
    if component is not None:
        return (get_component_files(component),)
    return tuple(get_component_files(item) for item in COMPONENTS)


def tail_log(path: Path, *, lines: int) -> list[str]:
    if lines <= 0 or not path.exists():
        return []

    with path.open("r", encoding="utf-8", errors="replace") as handle:
        return list(deque((line.rstrip("\n") for line in handle), maxlen=lines))


async def check_database(settings: Settings) -> DatabaseCheckResult:
    sqlite_path = settings.sqlite_database_path
    if sqlite_path is not None and not sqlite_path.exists():
        return DatabaseCheckResult(
            database_url=settings.database_url,
            sqlite_path=sqlite_path,
            available=False,
            detail=f"SQLite база ещё не создана: {sqlite_path}",
        )

    runtime = build_database_runtime(settings)
    try:
        async with runtime.session_factory() as session:
            await session.execute(text("SELECT 1"))
        return DatabaseCheckResult(
            database_url=settings.database_url,
            sqlite_path=sqlite_path,
            available=True,
            detail="База данных отвечает.",
        )
    except SQLAlchemyError as error:
        return DatabaseCheckResult(
            database_url=settings.database_url,
            sqlite_path=sqlite_path,
            available=False,
            detail=f"База данных недоступна: {error}",
        )
    finally:
        await runtime.dispose()


async def check_provider(settings: Settings) -> ProviderCheckResult:
    status = await ProviderManager.from_settings(settings).get_status(check_api=True)
    return ProviderCheckResult(
        enabled=status.enabled,
        configured=status.configured,
        available=status.available,
        provider_name=status.provider_name,
        reason=status.reason,
    )


async def build_doctor_snapshot(settings: Settings) -> DoctorSnapshot:
    runtime = build_database_runtime(settings)
    try:
        await bootstrap_database(runtime)
        async with runtime.session_factory() as session:
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
                    settings,
                    setting_repository=setting_repository,
                ),
                fullaccess_auth_service=FullAccessAuthService(
                    settings=settings,
                    setting_repository=setting_repository,
                    message_repository=MessageRepository(session),
                ),
                settings=settings,
            ).build_report()
        return DoctorSnapshot(
            readiness=readiness,
            doctor=SystemHealthService().build_report(readiness),
            error=None,
        )
    except Exception as error:
        return DoctorSnapshot(
            readiness=None,
            doctor=None,
            error=str(error),
        )
    finally:
        await runtime.dispose()


async def run_ops_command(command: str, *, stdout: bool = False) -> int:
    return await run_ops_app(argparse.Namespace(command=command, stdout=stdout))


async def build_new_runtime_manager(settings: Settings | None = None) -> RuntimeManagerBundle:
    effective_settings = settings or Settings()
    runtime = build_database_runtime(effective_settings)
    await bootstrap_database(runtime)

    class _UnavailableLegacy:
        @property
        def chat_roster(self):
            return self

        @property
        def message_history(self):
            return self

        @property
        def reply_workspace(self):
            return self

        @property
        def message_sender(self):
            return self

        @property
        def autopilot(self):
            return self

    manager = RuntimeManager(RuntimeSwitches.from_settings(effective_settings))
    manager.register_backend(LegacyRuntimeBackend(_UnavailableLegacy()))
    manager.register_backend(
        NewTelegramRuntimeService(
            config=NewTelegramRuntimeConfig.from_settings(effective_settings),
            auth_store=DatabaseNewTelegramAuthSessionStore(runtime.session_factory),
            session_factory=runtime.session_factory,
        )
    )
    return RuntimeManagerBundle(manager=manager, database=runtime)


async def build_new_runtime_status(settings: Settings | None = None) -> dict[str, Any]:
    bundle = await build_new_runtime_manager(settings)
    try:
        status = await bundle.manager.status()
        from apps.cli.processes import inspect_process

        process = inspect_process("new-runtime")
        status["managedProcess"] = _serialize_process_state(process)
        async with bundle.database.session_factory() as session:
            snapshot = await OperationalStateService(SettingRepository(session)).get_named_snapshot(
                "new_runtime"
            )
        if snapshot is not None:
            status["operationalSnapshot"] = snapshot.payload
            snapshot_status = snapshot.payload.get("status")
            if (
                isinstance(snapshot_status, dict)
                and process.running
                and _snapshot_matches_process(snapshot_status, process)
            ):
                refreshed_snapshot = _refresh_runtime_uptime(snapshot_status)
                status["newRuntime"] = refreshed_snapshot
                backends = status.get("backends")
                if isinstance(backends, dict):
                    backends["new"] = refreshed_snapshot
        return status
    finally:
        await bundle.database.dispose()


async def build_new_runtime_diagnostics(settings: Settings | None = None) -> RuntimeDiagnosticSnapshot:
    effective_settings = settings or Settings()
    from apps.cli.processes import inspect_process

    database = await check_database(effective_settings)
    status = await build_new_runtime_status(effective_settings)
    return RuntimeDiagnosticSnapshot(
        status=status,
        process=inspect_process("new-runtime"),
        database=database,
        checked_at=datetime.now(timezone.utc),
    )


def _validate_component(component: str) -> ComponentName:
    if component not in PROCESS_COMPONENTS:
        raise ValueError(f"Неизвестный component: {component}")
    return component  # type: ignore[return-value]


def _serialize_process_state(state) -> dict[str, Any]:
    return {
        "component": state.component,
        "running": state.running,
        "managed": state.managed,
        "stalePidFile": state.stale_pid_file,
        "pid": state.pid,
        "command": state.command,
        "detail": state.detail,
        "pidPath": str(state.pid_path),
        "logPath": str(state.log_path),
    }


def _refresh_runtime_uptime(status: dict[str, Any]) -> dict[str, Any]:
    refreshed = dict(status)
    started_at = refreshed.get("startedAt")
    if refreshed.get("lifecycle") != "running" or not isinstance(started_at, str):
        return refreshed
    try:
        started = datetime.fromisoformat(started_at)
    except ValueError:
        return refreshed
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    else:
        started = started.astimezone(timezone.utc)
    refreshed["uptimeSeconds"] = max(
        0.0,
        (datetime.now(timezone.utc) - started).total_seconds(),
    )
    return refreshed


def _snapshot_matches_process(status: dict[str, Any], state) -> bool:
    started_at = status.get("startedAt")
    if not isinstance(started_at, str):
        return False
    try:
        started = datetime.fromisoformat(started_at)
    except ValueError:
        return False
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    else:
        started = started.astimezone(timezone.utc)
    try:
        pid_updated_at = datetime.fromtimestamp(state.pid_path.stat().st_mtime, tz=timezone.utc)
    except OSError:
        return False
    return started >= pid_updated_at - timedelta(seconds=2)
