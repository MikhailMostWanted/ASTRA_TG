from __future__ import annotations

from dataclasses import dataclass

from services.persona_core import PersonaStatusReport


@dataclass(slots=True)
class PersonaFormatter:
    def format_status(self, report: PersonaStatusReport) -> str:
        return "\n".join(
            [
                "Статус persona layer",
                "",
                f"Persona core: {'загружен' if report.core_loaded else 'не загружен'}",
                f"Версия: {report.version}",
                f"Источник: {report.source}",
                f"Активных core-правил: {report.active_core_rules}",
                (
                    "Persona enrichment для /reply: включён"
                    if report.reply_enrichment_enabled
                    else "Persona enrichment для /reply: выключен"
                ),
                f"Активных guardrail-checks: {report.active_guardrail_checks}",
                "Анти-паттерны: " + "; ".join(report.anti_pattern_rules[:5])
                if report.anti_pattern_rules
                else "Анти-паттерны: не заданы",
            ]
        )
