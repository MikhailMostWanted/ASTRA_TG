from __future__ import annotations

from dataclasses import dataclass

from services.style_profiles import StyleProfileSnapshot, StyleStatusReport


@dataclass(slots=True)
class StyleFormatter:
    def format_profiles(self, profiles: tuple[StyleProfileSnapshot, ...]) -> str:
        lines = ["Доступные style-профили", ""]
        for profile in profiles:
            lines.append(
                f"{profile.key} — {profile.description} "
                f"(режим: {profile.message_mode}, цель: {profile.target_message_count})"
            )
        return "\n".join(lines)

    def format_status(self, report: StyleStatusReport) -> str:
        selection = report.selection
        lines = [
            f"Чат: {report.chat_title}",
            f"Источник: {report.chat_reference}",
        ]
        if report.note:
            lines.extend(["", report.note])
        lines.extend(
            [
                "",
                f"Ручной override: {selection.override_profile_key or 'не задан'}",
                f"Эффективный профиль: {selection.profile.key}",
                (
                    "Источник профиля: ручной override"
                    if selection.source == "override"
                    else "Источник профиля: автовыбор"
                ),
                f"Почему: {selection.source_reason}",
                f"Описание: {selection.profile.description}",
            ]
        )
        return "\n".join(lines)

    def format_reply_messages(self, messages: tuple[str, ...]) -> list[str]:
        return [f"{index}. {message}" for index, message in enumerate(messages, start=1)]
