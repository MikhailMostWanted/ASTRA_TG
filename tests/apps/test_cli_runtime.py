from apps.cli.app import build_parser
from apps.cli.formatting import (
    format_runtime_auth_action,
    format_runtime_health,
    format_runtime_status,
)
from apps.cli.processes import build_managed_command


def test_cli_runtime_parser_exposes_ops_commands() -> None:
    parser = build_parser()

    assert parser.parse_args(["runtime", "status"]).runtime_command == "status"
    assert parser.parse_args(["runtime", "start"]).runtime_command == "start"
    assert parser.parse_args(["runtime", "stop"]).runtime_command == "stop"
    assert parser.parse_args(["runtime", "health"]).runtime_command == "health"
    assert parser.parse_args(["runtime", "diagnose"]).runtime_command == "diagnose"
    assert parser.parse_args(["runtime", "login"]).runtime_command == "login"
    assert parser.parse_args(["runtime", "code", "24680"]).code == "24680"
    assert parser.parse_args(["runtime", "password"]).password is None
    assert parser.parse_args(["runtime", "logout"]).runtime_command == "logout"
    assert parser.parse_args(["runtime", "reset"]).runtime_command == "reset"


def test_new_runtime_process_entrypoint_is_separate_from_bot_worker() -> None:
    command = build_managed_command("new-runtime", python_executable="/python")

    assert command == ["/python", "-m", "apps.cli", "_run-new-runtime"]


def test_runtime_formatters_include_health_readiness_and_auth_state() -> None:
    payload = {
        "registeredBackends": ["legacy", "new"],
        "managedProcess": {"running": False, "pid": None},
        "routes": {
            "targetRegistered": True,
            "routes": {
                "chatRoster": {
                    "requested": "new",
                    "effective": "legacy",
                    "reason": "not route-ready",
                }
            },
        },
        "newRuntime": {
            "healthy": True,
            "lifecycle": "running",
            "active": False,
            "ready": False,
            "routeAvailable": False,
            "uptimeSeconds": 1.2,
            "degradedReason": None,
            "unavailableReason": "disabled",
            "lastError": None,
            "auth": {
                "state": "awaiting_code",
                "authState": "unauthorized",
                "sessionState": "missing",
                "reasonCode": "awaiting_code",
                "session": {"path": "/tmp/new.session"},
                "user": {"id": None, "username": None, "phoneHint": None},
                "error": None,
                "awaitingCode": True,
                "awaitingPassword": False,
                "reason": "auth required",
                "updatedAt": "2026-04-23T10:00:00+00:00",
            },
        },
    }

    status_text = format_runtime_status(payload)
    health_text = format_runtime_health(payload["newRuntime"])
    action_text = format_runtime_auth_action(
        {
            "kind": "code_requested",
            "message": "Код отправлен.",
            "status": payload["newRuntime"]["auth"],
        }
    )

    assert "Astra CLI / Runtime" in status_text
    assert "managed_process: stopped pid=нет" in status_text
    assert "chatRoster: requested=new effective=legacy reason=not route-ready" in status_text
    assert "auth_state: unauthorized" in status_text
    assert "state: awaiting_code" in status_text
    assert "reason_code: awaiting_code" in status_text
    assert "Astra CLI / Runtime health" in health_text
    assert "session_state: missing" in health_text
    assert "Astra CLI / Runtime auth" in action_text
    assert "action: code_requested" in action_text
