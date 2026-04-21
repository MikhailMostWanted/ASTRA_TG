from __future__ import annotations

from dataclasses import dataclass
from typing import TypeAlias

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from services.inline_navigation import back_route, home_route, refresh_route


ButtonSpec: TypeAlias = tuple[str, str]

MARKER_OK = "[OK]"
MARKER_WARN = "[WARN]"
MARKER_ERR = "[ERR]"
MARKER_OPT = "[OPT]"
MARKER_EXP = "[EXP]"
MARKER_OFF = "[OFF]"


@dataclass(frozen=True, slots=True)
class RenderedCard:
    text: str
    reply_markup: InlineKeyboardMarkup | None = None


def render_home_card(
    *,
    title: str,
    summary_lines: list[str],
    detail_lines: list[str],
    next_step: str,
    rows: list[list[ButtonSpec]],
) -> RenderedCard:
    return RenderedCard(
        text=_build_card_text(
            title=title,
            summary_lines=summary_lines,
            detail_lines=detail_lines,
            next_step=next_step,
        ),
        reply_markup=build_keyboard(rows),
    )


def render_overview_card(
    *,
    title: str,
    summary_lines: list[str],
    detail_lines: list[str],
    next_step: str,
    rows: list[list[ButtonSpec]],
    back_screen: str | None,
    current_screen: str,
) -> RenderedCard:
    keyboard_rows = [*rows, utility_row(back_screen=back_screen, current_screen=current_screen)]
    return RenderedCard(
        text=_build_card_text(
            title=title,
            summary_lines=summary_lines,
            detail_lines=detail_lines,
            next_step=next_step,
        ),
        reply_markup=build_keyboard(keyboard_rows),
    )


def render_help_card(
    *,
    title: str,
    lines: list[str],
    next_step: str,
    rows: list[list[ButtonSpec]],
) -> RenderedCard:
    text_lines = [title, "", *lines]
    if next_step:
        text_lines.extend(["", "Следующий шаг", next_step])
    return RenderedCard(text="\n".join(text_lines), reply_markup=build_keyboard(rows))


def render_text_card(
    *,
    title: str,
    lines: list[str],
    rows: list[list[ButtonSpec]],
    back_screen: str | None = None,
    current_screen: str | None = None,
) -> RenderedCard:
    keyboard_rows = [*rows]
    if current_screen is not None:
        keyboard_rows.append(utility_row(back_screen=back_screen, current_screen=current_screen))
    text_lines = [title]
    if lines:
        text_lines.extend(["", *lines])
    return RenderedCard(text="\n".join(text_lines), reply_markup=build_keyboard(keyboard_rows))


def state_shell_lines(
    *,
    marker: str,
    status: str,
    meaning: str,
    next_step: str,
) -> list[str]:
    return [
        f"{marker} {status}",
        "",
        "Что это значит",
        meaning,
        "",
        "Что делать дальше",
        next_step,
    ]


def format_status_line(marker: str, label: str, detail: str) -> str:
    return f"{marker} {label}: {detail}"


def ready_marker(value: bool) -> str:
    return MARKER_OK if value else MARKER_WARN


def compact_text(value: str, *, limit: int = 72) -> str:
    normalized = " ".join(value.split()).strip()
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 3].rstrip() + "..."


def build_start_keyboard(*, primary_label: str) -> InlineKeyboardMarkup:
    return build_keyboard(
        [
            [(primary_label, home_route())],
            [("Чеклист", "ux:checklist"), ("Статус", "ux:status")],
        ]
    )


def build_keyboard(rows: list[list[ButtonSpec]]) -> InlineKeyboardMarkup:
    inline_keyboard: list[list[InlineKeyboardButton]] = []
    for row in rows:
        buttons = [
            InlineKeyboardButton(text=text, callback_data=callback_data)
            for text, callback_data in row
        ]
        inline_keyboard.append(buttons)
    return InlineKeyboardMarkup(inline_keyboard=inline_keyboard)


def utility_row(*, back_screen: str | None, current_screen: str) -> list[ButtonSpec]:
    row: list[ButtonSpec] = []
    if back_screen is not None:
        row.append(("Назад", back_route(back_screen)))
    row.extend(
        [
            ("Домой", home_route()),
            ("Обновить", refresh_route(current_screen)),
        ]
    )
    return row


def _build_card_text(
    *,
    title: str,
    summary_lines: list[str],
    detail_lines: list[str],
    next_step: str,
) -> str:
    lines = [title, "", "Сводка", *summary_lines]
    if detail_lines:
        lines.extend(["", *detail_lines])
    if next_step:
        lines.extend(["", "Следующий шаг", next_step])
    return "\n".join(lines)
