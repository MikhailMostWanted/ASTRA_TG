from __future__ import annotations

from dataclasses import dataclass

from services.bot_commands import BOT_COMMAND_SPECS, iter_command_sections


@dataclass(frozen=True, slots=True)
class HelpFormatter:
    def build_message(self) -> str:
        lines = ["Команды Astra AFT", ""]

        for section in iter_command_sections():
            specs = [spec for spec in BOT_COMMAND_SPECS if spec.section == section.key]
            if not specs:
                continue
            lines.append(section.title)
            for spec in specs:
                lines.append(f"/{spec.command} — {spec.description}")
            lines.append("")

        lines.append("Быстрый старт: /onboarding")
        lines.append("Живая готовность: /status, /checklist, /doctor")
        return "\n".join(lines)
