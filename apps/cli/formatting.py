from __future__ import annotations

from pathlib import Path

from apps.cli.processes import ProcessState, StartResult, StopResult
from apps.cli.runtime import DatabaseCheckResult, DoctorSnapshot, ProviderCheckResult, RuntimeDiagnosticSnapshot


COMPONENT_LABELS = {
    "bot": "Bot",
    "worker": "Worker",
    "new-runtime": "New runtime",
}


def format_action_results(action: str, results: list[StartResult | StopResult]) -> str:
    lines = [f"Astra CLI / {action.capitalize()}"]
    for result in results:
        component_label = COMPONENT_LABELS[result.component]
        marker = "[OK]" if result.ok else "[WARN]"
        pid_suffix = f" pid={result.pid}" if result.pid is not None else ""
        lines.append(f"{marker} {component_label}: {result.detail}{pid_suffix}")
        lines.append(f"pid: {result.pid_path}")
        lines.append(f"log: {result.log_path}")
    return "\n".join(lines)


def format_status(
    *,
    repository_root: Path,
    env_path: Path,
    env_exists: bool,
    python_executable: Path,
    component_states: list[ProcessState],
    database: DatabaseCheckResult | None = None,
    provider: ProviderCheckResult | None = None,
) -> str:
    lines = [
        "Astra CLI / Status",
        f"repo_root: {repository_root}",
        f"python: {python_executable}",
        f".env: {_ready_marker(env_exists)} {env_path}",
    ]

    if database is not None:
        lines.append(
            f"database: {_ready_marker(database.available)} {database.detail}"
        )
        lines.append(f"database_url: {database.database_url}")
        lines.append(
            "sqlite_path: "
            f"{database.sqlite_path if database.sqlite_path is not None else 'не sqlite'}"
        )

    if provider is not None:
        lines.append(
            f"provider: {_provider_marker(provider)} "
            f"{provider.provider_name or 'disabled'}"
        )
        lines.append(f"provider_reason: {provider.reason}")

    for state in component_states:
        label = COMPONENT_LABELS[state.component]
        lines.append("")
        lines.extend(_format_component_status(label, state))

    return "\n".join(lines)


def format_doctor(snapshot: DoctorSnapshot) -> str:
    lines = ["Astra CLI / Doctor"]

    if snapshot.error is not None:
        lines.append(f"[WARN] Не удалось построить doctor-отчёт: {snapshot.error}")
        return "\n".join(lines)

    assert snapshot.doctor is not None
    assert snapshot.readiness is not None

    lines.append("ОК:")
    for item in snapshot.doctor.ok_items:
        lines.append(f"- {item}")

    lines.append("Предупреждения:")
    for item in snapshot.doctor.warnings:
        lines.append(f"- {item}")

    lines.append("Следующие шаги:")
    for index, item in enumerate(snapshot.doctor.next_steps, start=1):
        lines.append(f"{index}. {item}")

    next_command = snapshot.readiness.next_command
    if next_command:
        lines.append(f"Следующая рекомендуемая команда: {next_command}")

    return "\n".join(lines)


def format_logs(
    *,
    component_states: list[ProcessState],
    tail_lines: int,
    tail_lookup: dict[str, list[str]],
) -> str:
    lines = ["Astra CLI / Logs"]

    for state in component_states:
        label = COMPONENT_LABELS[state.component]
        lines.append(
            f"{label}: {state.log_path} ({'жив' if state.running else 'не запущен'})"
        )
        if tail_lines <= 0:
            continue

        lines.append(f"--- {label} / tail {tail_lines} ---")
        tail = tail_lookup.get(state.component, [])
        if tail:
            lines.extend(tail)
        else:
            lines.append("(лог пуст или ещё не создан)")

    return "\n".join(lines)


def format_runtime_status(status: dict[str, object]) -> str:
    new_runtime = _dict(status.get("newRuntime"))
    routes = _dict(status.get("routes")).get("routes")
    process = _dict(status.get("managedProcess"))
    backends = [str(item) for item in status.get("registeredBackends", []) or []]
    lines = ["Astra CLI / Runtime"]
    lines.append(f"registered_backends: {', '.join(backends)}")
    if process:
        lines.append(
            "managed_process: "
            f"{'running' if process.get('running') else 'stopped'} "
            f"pid={process.get('pid') or 'нет'}"
        )

    if new_runtime:
        lines.extend(_format_runtime_backend("new", new_runtime))

    if isinstance(routes, dict):
        lines.append("")
        lines.append("Routes:")
        for surface, route in routes.items():
            if not isinstance(route, dict):
                continue
            reason = route.get("reason") or "ok"
            lines.append(
                f"- {surface}: requested={route.get('requested')} "
                f"effective={route.get('effective')} reason={reason}"
            )

    return "\n".join(lines)


def format_runtime_health(health: dict[str, object]) -> str:
    lines = ["Astra CLI / Runtime health"]
    lines.extend(_format_runtime_backend("new", health))
    return "\n".join(lines)


def format_runtime_auth_action(payload: dict[str, object]) -> str:
    status = _dict(payload.get("status"))
    lines = ["Astra CLI / Runtime auth"]
    lines.append(f"action: {payload.get('kind') or 'unknown'}")
    lines.append(f"message: {payload.get('message') or 'нет'}")
    if status:
        lines.append("")
        lines.extend(_format_runtime_auth(status))
    return "\n".join(lines)


def format_runtime_diagnostics(snapshot: RuntimeDiagnosticSnapshot) -> str:
    lines = ["Astra CLI / Runtime diagnostics"]
    lines.append(f"checked_at: {snapshot.checked_at.isoformat()}")
    lines.append(f"database: {_ready_marker(snapshot.database.available)} {snapshot.database.detail}")
    lines.append("")
    lines.extend(_format_component_status("New runtime process", snapshot.process))
    lines.append("")
    lines.append(format_runtime_status(snapshot.status))
    return "\n".join(lines)


def _format_component_status(label: str, state: ProcessState) -> list[str]:
    marker = "[OK]" if state.running else "[WARN]" if state.stale_pid_file else "[OFF]"
    status_text = "запущен" if state.running else "не запущен"
    pid_value = str(state.pid) if state.pid is not None else "нет"
    lines = [
        f"{label}: {marker} {status_text}",
        f"detail: {state.detail}",
        f"pid: {pid_value}",
        f"pid_file: {state.pid_path}",
        f"log_file: {state.log_path}",
    ]
    if state.command:
        lines.append(f"command: {state.command}")
    return lines


def _format_runtime_backend(label: str, backend: dict[str, object]) -> list[str]:
    auth = _dict(backend.get("auth"))
    lines = [
        f"{label}: {_ready_marker(bool(backend.get('healthy')))} {backend.get('lifecycle')}",
        f"active: {backend.get('active')}",
        f"ready: {backend.get('ready')}",
        f"route_available: {backend.get('routeAvailable')}",
        f"uptime_seconds: {backend.get('uptimeSeconds')}",
        f"degraded_reason: {backend.get('degradedReason') or 'нет'}",
        f"unavailable_reason: {backend.get('unavailableReason') or 'нет'}",
        f"last_error: {backend.get('lastError') or 'нет'}",
    ]
    if auth:
        lines.extend(_format_runtime_auth(auth))
    return lines


def _format_runtime_auth(auth: dict[str, object]) -> list[str]:
    session = _dict(auth.get("session"))
    user = _dict(auth.get("user"))
    error = _dict(auth.get("error"))
    username = user.get("username")
    user_id = user.get("id")
    phone_hint = user.get("phoneHint")
    account_parts = [
        str(item)
        for item in (f"@{username}" if username else None, f"id={user_id}" if user_id else None, phone_hint)
        if item
    ]
    lines = [
        f"auth_state: {auth.get('authState')}",
        f"state: {auth.get('state') or 'нет'}",
        f"session_state: {auth.get('sessionState')}",
        f"session_path: {session.get('path')}",
        f"reason_code: {auth.get('reasonCode') or 'нет'}",
        f"auth_reason: {auth.get('reason') or 'нет'}",
        f"account: {', '.join(account_parts) if account_parts else 'нет'}",
        f"awaiting_code: {auth.get('awaitingCode')}",
        f"awaiting_password: {auth.get('awaitingPassword')}",
        f"updated_at: {auth.get('updatedAt') or 'нет'}",
    ]
    if error:
        lines.append(f"auth_error: {error.get('code') or 'нет'} {error.get('message') or ''}".rstrip())
    else:
        lines.append("auth_error: нет")
    return lines


def _ready_marker(ready: bool) -> str:
    return "[OK]" if ready else "[WARN]"


def _provider_marker(provider: ProviderCheckResult) -> str:
    if not provider.enabled:
        return "[OFF]"
    if provider.available:
        return "[OK]"
    return "[WARN]"


def _dict(value: object) -> dict[str, object]:
    return value if isinstance(value, dict) else {}
