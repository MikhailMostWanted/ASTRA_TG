from __future__ import annotations

from pathlib import Path

from apps.cli.processes import ProcessState, StartResult, StopResult
from apps.cli.runtime import DatabaseCheckResult, DoctorSnapshot, ProviderCheckResult


COMPONENT_LABELS = {
    "bot": "Bot",
    "worker": "Worker",
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


def _ready_marker(ready: bool) -> str:
    return "[OK]" if ready else "[WARN]"


def _provider_marker(provider: ProviderCheckResult) -> str:
    if not provider.enabled:
        return "[OFF]"
    if provider.available:
        return "[OK]"
    return "[WARN]"
