from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from apps.cli.runtime import ComponentName, ensure_runtime_dirs, get_component_files, get_repository_root


INTERNAL_COMPONENT_COMMANDS: dict[ComponentName, str] = {
    "bot": "_run-bot",
    "worker": "_run-worker",
}


@dataclass(frozen=True, slots=True)
class ProcessState:
    component: ComponentName
    pid_path: Path
    log_path: Path
    pid: int | None
    running: bool
    managed: bool
    stale_pid_file: bool
    command: str | None
    detail: str


@dataclass(frozen=True, slots=True)
class StartResult:
    component: ComponentName
    ok: bool
    started: bool
    pid: int | None
    detail: str
    pid_path: Path
    log_path: Path


@dataclass(frozen=True, slots=True)
class StopResult:
    component: ComponentName
    ok: bool
    stopped: bool
    pid: int | None
    detail: str
    pid_path: Path
    log_path: Path


def build_managed_command(
    component: ComponentName,
    *,
    python_executable: str | None = None,
) -> list[str]:
    executable = python_executable or sys.executable
    return [
        executable,
        "-m",
        "apps.cli",
        INTERNAL_COMPONENT_COMMANDS[component],
    ]


def inspect_process(component: ComponentName) -> ProcessState:
    files = get_component_files(component)
    pid = _read_pid(files.pid_path)

    if pid is None:
        return ProcessState(
            component=component,
            pid_path=files.pid_path,
            log_path=files.log_path,
            pid=None,
            running=False,
            managed=False,
            stale_pid_file=False,
            command=None,
            detail="PID-файл отсутствует.",
        )

    if not _pid_exists(pid):
        return ProcessState(
            component=component,
            pid_path=files.pid_path,
            log_path=files.log_path,
            pid=pid,
            running=False,
            managed=False,
            stale_pid_file=True,
            command=None,
            detail="PID-файл найден, но процесс уже завершён.",
        )

    command = _read_process_command(pid)
    if not _matches_expected_command(component, command):
        return ProcessState(
            component=component,
            pid_path=files.pid_path,
            log_path=files.log_path,
            pid=pid,
            running=False,
            managed=False,
            stale_pid_file=True,
            command=command,
            detail="PID-файл указывает на другой процесс, он не будет остановлен.",
        )

    return ProcessState(
        component=component,
        pid_path=files.pid_path,
        log_path=files.log_path,
        pid=pid,
        running=True,
        managed=True,
        stale_pid_file=False,
        command=command,
        detail="Процесс запущен через astra CLI.",
    )


def start_component(
    component: ComponentName,
    *,
    python_executable: str | None = None,
    start_wait_seconds: float = 0.3,
) -> StartResult:
    ensure_runtime_dirs()
    files = get_component_files(component)
    state = inspect_process(component)

    if state.running:
        return StartResult(
            component=component,
            ok=True,
            started=False,
            pid=state.pid,
            detail="Уже запущен.",
            pid_path=files.pid_path,
            log_path=files.log_path,
        )

    recovered_stale_pid = state.pid is not None and state.stale_pid_file
    if recovered_stale_pid:
        files.pid_path.unlink(missing_ok=True)

    command = build_managed_command(component, python_executable=python_executable)
    start_label = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with files.log_path.open("a", encoding="utf-8") as handle:
        handle.write(f"\n=== astra start {component} {start_label} ===\n")
        handle.flush()
        process = subprocess.Popen(
            command,
            cwd=str(get_repository_root()),
            stdin=subprocess.DEVNULL,
            stdout=handle,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )

    _write_pid(files.pid_path, process.pid)
    time.sleep(start_wait_seconds)

    if process.poll() is not None:
        files.pid_path.unlink(missing_ok=True)
        return StartResult(
            component=component,
            ok=False,
            started=False,
            pid=process.pid,
            detail=(
                f"Процесс завершился сразу с кодом {process.returncode}. "
                f"См. лог: {files.log_path}"
            ),
            pid_path=files.pid_path,
            log_path=files.log_path,
        )

    detail = "Запущен."
    if recovered_stale_pid:
        detail = "Запущен после очистки stale PID-файла."

    return StartResult(
        component=component,
        ok=True,
        started=True,
        pid=process.pid,
        detail=detail,
        pid_path=files.pid_path,
        log_path=files.log_path,
    )


def stop_component(
    component: ComponentName,
    *,
    timeout_seconds: float = 10.0,
) -> StopResult:
    files = get_component_files(component)
    state = inspect_process(component)

    if state.pid is None:
        return StopResult(
            component=component,
            ok=True,
            stopped=False,
            pid=None,
            detail="Не запущен.",
            pid_path=files.pid_path,
            log_path=files.log_path,
        )

    if not state.running:
        files.pid_path.unlink(missing_ok=True)
        return StopResult(
            component=component,
            ok=True,
            stopped=False,
            pid=state.pid,
            detail="Процесс уже не запущен, stale PID-файл удалён.",
            pid_path=files.pid_path,
            log_path=files.log_path,
        )

    try:
        os.killpg(state.pid, signal.SIGTERM)
    except ProcessLookupError:
        files.pid_path.unlink(missing_ok=True)
        return StopResult(
            component=component,
            ok=True,
            stopped=True,
            pid=state.pid,
            detail="Процесс уже завершён.",
            pid_path=files.pid_path,
            log_path=files.log_path,
        )

    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if not _pid_exists(state.pid):
            files.pid_path.unlink(missing_ok=True)
            return StopResult(
                component=component,
                ok=True,
                stopped=True,
                pid=state.pid,
                detail="Остановлен через SIGTERM.",
                pid_path=files.pid_path,
                log_path=files.log_path,
            )
        time.sleep(0.1)

    try:
        os.killpg(state.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass

    if _pid_exists(state.pid):
        return StopResult(
            component=component,
            ok=False,
            stopped=False,
            pid=state.pid,
            detail="Процесс не завершился даже после SIGKILL.",
            pid_path=files.pid_path,
            log_path=files.log_path,
        )

    files.pid_path.unlink(missing_ok=True)
    return StopResult(
        component=component,
        ok=True,
        stopped=True,
        pid=state.pid,
        detail="Остановлен через SIGKILL после таймаута.",
        pid_path=files.pid_path,
        log_path=files.log_path,
    )


def _write_pid(path: Path, pid: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{pid}\n", encoding="utf-8")


def _read_pid(path: Path) -> int | None:
    if not path.exists():
        return None
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except ValueError:
        return None


def _pid_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _read_process_command(pid: int) -> str | None:
    result = subprocess.run(
        ["ps", "-p", str(pid), "-o", "command="],
        check=False,
        capture_output=True,
        text=True,
    )
    command = result.stdout.strip()
    return command or None


def _matches_expected_command(component: ComponentName, command: str | None) -> bool:
    if not command:
        return False
    return INTERNAL_COMPONENT_COMMANDS[component] in command and "apps.cli" in command
