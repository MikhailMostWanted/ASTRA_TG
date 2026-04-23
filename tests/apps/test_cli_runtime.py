from apps.cli.app import build_parser
from apps.cli.formatting import format_runtime_health, format_runtime_status
from apps.cli.processes import build_managed_command


def test_cli_runtime_parser_exposes_ops_commands() -> None:
    parser = build_parser()

    assert parser.parse_args(["runtime", "status"]).runtime_command == "status"
    assert parser.parse_args(["runtime", "start"]).runtime_command == "start"
    assert parser.parse_args(["runtime", "stop"]).runtime_command == "stop"
    assert parser.parse_args(["runtime", "health"]).runtime_command == "health"
    assert parser.parse_args(["runtime", "diagnose"]).runtime_command == "diagnose"


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
                "authState": "unauthorized",
                "sessionState": "missing",
                "session": {"path": "/tmp/new.session"},
                "reason": "auth required",
            },
        },
    }

    status_text = format_runtime_status(payload)
    health_text = format_runtime_health(payload["newRuntime"])

    assert "Astra CLI / Runtime" in status_text
    assert "managed_process: stopped pid=нет" in status_text
    assert "chatRoster: requested=new effective=legacy reason=not route-ready" in status_text
    assert "auth_state: unauthorized" in status_text
    assert "Astra CLI / Runtime health" in health_text
    assert "session_state: missing" in health_text
