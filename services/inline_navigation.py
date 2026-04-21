from __future__ import annotations

from dataclasses import dataclass


SCREEN_HOME = "home"
SCREEN_STATUS = "status"
SCREEN_CHECKLIST = "checklist"
SCREEN_DOCTOR = "doctor"
SCREEN_SOURCES = "sources"
SCREEN_DIGEST = "digest"
SCREEN_MEMORY = "memory"
SCREEN_REPLY = "reply"
SCREEN_REMINDERS = "reminders"
SCREEN_SOURCES_HELP = "sources_help"
SCREEN_REPLY_HELP = "reply_help"


OVERVIEW_SCREENS: tuple[str, ...] = (
    SCREEN_HOME,
    SCREEN_STATUS,
    SCREEN_CHECKLIST,
    SCREEN_DOCTOR,
    SCREEN_SOURCES,
    SCREEN_DIGEST,
    SCREEN_MEMORY,
    SCREEN_REPLY,
    SCREEN_REMINDERS,
)


@dataclass(frozen=True, slots=True)
class ParsedInlineRoute:
    kind: str
    screen: str | None = None
    arg: str | None = None
    data: str | None = None


def home_route() -> str:
    return "ux:home"


def screen_route(screen: str) -> str:
    if screen == SCREEN_HOME:
        return home_route()
    return f"ux:{screen}"


def refresh_route(screen: str) -> str:
    return f"ux:refresh:{screen}"


def back_route(screen: str) -> str:
    return f"ux:back:{screen}"


def sources_help_route() -> str:
    return "ux:sources:help"


def digest_run_route(window: str) -> str:
    return f"ux:digest:run:{window}"


def memory_rebuild_route() -> str:
    return "ux:memory:rebuild"


def reply_help_route() -> str:
    return "ux:reply:help"


def reminders_scan_route(window: str) -> str:
    return f"ux:reminders:scan:{window}"


def reminders_tasks_route() -> str:
    return "ux:reminders:tasks"


def reminders_list_route() -> str:
    return "ux:reminders:list"


def parse_inline_route(data: str | None) -> ParsedInlineRoute | None:
    if data is None or not data.startswith("ux:"):
        return None

    if data == home_route():
        return ParsedInlineRoute(kind="screen", screen=SCREEN_HOME, data=data)

    parts = data.split(":")
    if len(parts) == 2 and parts[1] in OVERVIEW_SCREENS:
        return ParsedInlineRoute(kind="screen", screen=parts[1], data=data)
    if len(parts) == 3 and parts[1] == "refresh":
        return ParsedInlineRoute(kind="refresh", screen=parts[2], data=data)
    if len(parts) == 3 and parts[1] == "back":
        return ParsedInlineRoute(kind="back", screen=parts[2], data=data)
    if parts == ["ux", "sources", "help"]:
        return ParsedInlineRoute(kind="screen", screen=SCREEN_SOURCES_HELP, data=data)
    if len(parts) == 4 and parts[1] == "digest" and parts[2] == "run":
        return ParsedInlineRoute(kind="digest_run", screen=SCREEN_DIGEST, arg=parts[3], data=data)
    if parts == ["ux", "memory", "rebuild"]:
        return ParsedInlineRoute(kind="memory_rebuild", screen=SCREEN_MEMORY, data=data)
    if parts == ["ux", "reply", "help"]:
        return ParsedInlineRoute(kind="screen", screen=SCREEN_REPLY_HELP, data=data)
    if len(parts) == 4 and parts[1] == "reminders" and parts[2] == "scan":
        return ParsedInlineRoute(
            kind="reminders_scan",
            screen=SCREEN_REMINDERS,
            arg=parts[3],
            data=data,
        )
    if parts == ["ux", "reminders", "tasks"]:
        return ParsedInlineRoute(kind="reminders_tasks", screen=SCREEN_REMINDERS, data=data)
    if parts == ["ux", "reminders", "list"]:
        return ParsedInlineRoute(kind="reminders_list", screen=SCREEN_REMINDERS, data=data)
    return None
