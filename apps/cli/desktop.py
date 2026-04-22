from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import urlparse

from apps.cli.runtime import LOG_DIR, REPOSITORY_ROOT, RUN_DIR, VAR_DIR, ensure_runtime_dirs


APP_NAME = "Astra Desktop"
DEFAULT_API_URL = "http://127.0.0.1:8765"
DESKTOP_DIR = REPOSITORY_ROOT / "apps" / "desktop"
DESKTOP_TAURI_BUNDLE_PATH = (
    DESKTOP_DIR / "src-tauri" / "target" / "release" / "bundle" / "macos" / f"{APP_NAME}.app"
)
DESKTOP_LOCAL_BUILD_DIR = VAR_DIR / "desktop"
DESKTOP_LOCAL_APP_PATH = DESKTOP_LOCAL_BUILD_DIR / f"{APP_NAME}.app"
DESKTOP_INSTALL_DIR = Path.home() / "Applications"
DESKTOP_INSTALL_APP_PATH = DESKTOP_INSTALL_DIR / f"{APP_NAME}.app"
DESKTOP_SUPPORT_DIR = Path.home() / "Library" / "Application Support" / APP_NAME
DESKTOP_LAUNCHER_CONFIG_PATH = DESKTOP_SUPPORT_DIR / "launcher.json"
DESKTOP_API_PID_PATH = RUN_DIR / "astra-desktop-api.pid"
DESKTOP_API_LOG_PATH = LOG_DIR / "astra-desktop-api.log"


@dataclass(frozen=True, slots=True)
class DesktopLauncherConfig:
    app_name: str
    repo_root: str
    python_executable: str
    api_url: str
    api_host: str
    api_port: int
    pid_path: str
    log_path: str


@dataclass(frozen=True, slots=True)
class DesktopActionResult:
    ok: bool
    detail: str
    app_path: Path | None = None
    config_path: Path | None = None
    pid: int | None = None


def ensure_launcher_config(
    *,
    python_executable: str | None = None,
    api_url: str = DEFAULT_API_URL,
) -> tuple[DesktopLauncherConfig, Path]:
    ensure_runtime_dirs()
    DESKTOP_SUPPORT_DIR.mkdir(parents=True, exist_ok=True)

    effective_python = _resolve_python_executable(python_executable)
    target = urlparse(api_url)
    if target.scheme not in {"http", "https"} or not target.hostname or not target.port:
        raise ValueError(f"Некорректный desktop API URL: {api_url}")

    config = DesktopLauncherConfig(
        app_name=APP_NAME,
        repo_root=str(REPOSITORY_ROOT),
        python_executable=effective_python,
        api_url=api_url.rstrip("/"),
        api_host=target.hostname,
        api_port=target.port,
        pid_path=str(DESKTOP_API_PID_PATH),
        log_path=str(DESKTOP_API_LOG_PATH),
    )
    DESKTOP_LAUNCHER_CONFIG_PATH.write_text(
        json.dumps(asdict(config), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return config, DESKTOP_LAUNCHER_CONFIG_PATH


def build_desktop_app(
    *,
    python_executable: str | None = None,
    api_url: str = DEFAULT_API_URL,
) -> DesktopActionResult:
    _ensure_macos()
    _, config_path = ensure_launcher_config(
        python_executable=python_executable,
        api_url=api_url,
    )

    package_json = DESKTOP_DIR / "package.json"
    if not package_json.exists():
        raise ValueError(f"Desktop app не найден: {package_json}")

    _ensure_frontend_dependencies()
    _run_checked(["npm", "run", "tauri", "--", "build"], cwd=DESKTOP_DIR)

    if not DESKTOP_TAURI_BUNDLE_PATH.exists():
        raise ValueError(
            f"Tauri build завершился без .app bundle: {DESKTOP_TAURI_BUNDLE_PATH}"
        )

    DESKTOP_LOCAL_BUILD_DIR.mkdir(parents=True, exist_ok=True)
    _copy_app_bundle(DESKTOP_TAURI_BUNDLE_PATH, DESKTOP_LOCAL_APP_PATH)

    return DesktopActionResult(
        ok=True,
        detail="Локальный .app bundle собран.",
        app_path=DESKTOP_LOCAL_APP_PATH,
        config_path=config_path,
    )


def install_desktop_app(
    *,
    python_executable: str | None = None,
    api_url: str = DEFAULT_API_URL,
) -> DesktopActionResult:
    _ensure_macos()
    ensure_launcher_config(
        python_executable=python_executable,
        api_url=api_url,
    )
    source_app = DESKTOP_LOCAL_APP_PATH if DESKTOP_LOCAL_APP_PATH.exists() else None
    if source_app is None:
        source_app = build_desktop_app(
            python_executable=python_executable,
            api_url=api_url,
        ).app_path
    assert source_app is not None

    DESKTOP_INSTALL_DIR.mkdir(parents=True, exist_ok=True)
    _copy_app_bundle(source_app, DESKTOP_INSTALL_APP_PATH)

    return DesktopActionResult(
        ok=True,
        detail="Astra Desktop установлен в ~/Applications.",
        app_path=DESKTOP_INSTALL_APP_PATH,
        config_path=DESKTOP_LAUNCHER_CONFIG_PATH,
    )


def open_desktop_app(
    *,
    python_executable: str | None = None,
    api_url: str = DEFAULT_API_URL,
) -> DesktopActionResult:
    _ensure_macos()
    ensure_launcher_config(
        python_executable=python_executable,
        api_url=api_url,
    )

    app_path = None
    if DESKTOP_INSTALL_APP_PATH.exists():
        app_path = DESKTOP_INSTALL_APP_PATH
    elif DESKTOP_LOCAL_APP_PATH.exists():
        app_path = DESKTOP_LOCAL_APP_PATH
    else:
        app_path = build_desktop_app(
            python_executable=python_executable,
            api_url=api_url,
        ).app_path

    assert app_path is not None
    _run_checked(["open", str(app_path)], cwd=REPOSITORY_ROOT)

    return DesktopActionResult(
        ok=True,
        detail="Astra Desktop открыт.",
        app_path=app_path,
        config_path=DESKTOP_LAUNCHER_CONFIG_PATH,
    )


def stop_desktop_app(*, timeout_seconds: float = 8.0) -> DesktopActionResult:
    _ensure_macos()

    quit_result = subprocess.run(
        ["osascript", "-e", f'tell application "{APP_NAME}" to quit'],
        check=False,
        capture_output=True,
        text=True,
    )
    app_quit_requested = quit_result.returncode == 0

    stop_result = _stop_desktop_api_process(timeout_seconds=timeout_seconds)
    detail = "Desktop runtime остановлен."
    if app_quit_requested and stop_result.ok:
        detail = "Astra Desktop закрыт, bridge остановлен."
    elif app_quit_requested:
        detail = "Astra Desktop закрыт, bridge уже не работал."

    return DesktopActionResult(
        ok=True,
        detail=detail,
        app_path=DESKTOP_INSTALL_APP_PATH if DESKTOP_INSTALL_APP_PATH.exists() else DESKTOP_LOCAL_APP_PATH,
        config_path=DESKTOP_LAUNCHER_CONFIG_PATH if DESKTOP_LAUNCHER_CONFIG_PATH.exists() else None,
        pid=stop_result.pid,
    )


def _ensure_macos() -> None:
    if sys.platform != "darwin":
        raise ValueError("Desktop install/open workflow сейчас поддерживается только на macOS.")


def _resolve_python_executable(preferred: str | None) -> str:
    project_venv_python = REPOSITORY_ROOT / ".venv" / "bin" / "python"
    if project_venv_python.exists():
        return str(project_venv_python)
    return preferred or sys.executable


def _ensure_frontend_dependencies() -> None:
    node_modules = DESKTOP_DIR / "node_modules"
    if node_modules.exists():
        return
    _run_checked(["npm", "install"], cwd=DESKTOP_DIR)


def _copy_app_bundle(source: Path, destination: Path) -> None:
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(source, destination, symlinks=True)


def _run_checked(command: list[str], *, cwd: Path) -> None:
    result = subprocess.run(command, cwd=str(cwd), check=False)
    if result.returncode != 0:
        rendered = " ".join(command)
        raise ValueError(f"Команда завершилась с ошибкой ({result.returncode}): {rendered}")


@dataclass(frozen=True, slots=True)
class DesktopStopRuntimeResult:
    ok: bool
    detail: str
    pid: int | None = None


def _stop_desktop_api_process(*, timeout_seconds: float) -> DesktopStopRuntimeResult:
    ensure_runtime_dirs()
    pid = _read_pid(DESKTOP_API_PID_PATH)
    if pid is None:
        DESKTOP_API_PID_PATH.unlink(missing_ok=True)
        return DesktopStopRuntimeResult(
            ok=True,
            detail="Bridge уже не запущен.",
            pid=None,
        )

    if not _pid_exists(pid):
        DESKTOP_API_PID_PATH.unlink(missing_ok=True)
        return DesktopStopRuntimeResult(
            ok=True,
            detail="Bridge уже завершён, stale PID очищен.",
            pid=pid,
        )

    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        DESKTOP_API_PID_PATH.unlink(missing_ok=True)
        return DesktopStopRuntimeResult(
            ok=True,
            detail="Bridge уже завершён.",
            pid=pid,
        )

    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if not _pid_exists(pid):
            DESKTOP_API_PID_PATH.unlink(missing_ok=True)
            return DesktopStopRuntimeResult(
                ok=True,
                detail="Bridge остановлен через SIGTERM.",
                pid=pid,
            )
        time.sleep(0.1)

    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass

    if _pid_exists(pid):
        return DesktopStopRuntimeResult(
            ok=False,
            detail="Bridge не завершился даже после SIGKILL.",
            pid=pid,
        )

    DESKTOP_API_PID_PATH.unlink(missing_ok=True)
    return DesktopStopRuntimeResult(
        ok=True,
        detail="Bridge остановлен через SIGKILL после таймаута.",
        pid=pid,
    )


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
