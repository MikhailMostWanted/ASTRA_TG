from __future__ import annotations

from dataclasses import dataclass, field

from services.reply_models import ReplyResult
from services.style_formatter import StyleFormatter


@dataclass(slots=True)
class ReplyFormatter:
    style_formatter: StyleFormatter = field(default_factory=StyleFormatter)

    def format_result(self, result: ReplyResult) -> str:
        if result.kind != "suggestion" or result.suggestion is None:
            lines = []
            if result.chat_title:
                lines.append(f"Чат: {result.chat_title}")
                if result.chat_reference:
                    lines.append(f"Источник: {result.chat_reference}")
                lines.append("")
            lines.append(result.error_message or "Подсказку сейчас собрать не получилось.")
            return "\n".join(lines)

        suggestion = result.suggestion
        lines = [
            f"Чат: {result.chat_title}",
            f"Источник: {result.chat_reference}",
            f"Ориентир: {result.source_message_preview or suggestion.source_message_preview}",
            "",
            (
                f"Режим / стиль: {suggestion.style_profile_key} (автовыбор)"
                if suggestion.style_source == "fallback"
                else f"Режим / стиль: {suggestion.style_profile_key} (ручной override)"
            ),
            f"Persona: {'да' if suggestion.persona_applied else 'нет'}",
            "Итоговая серия:",
            *self.style_formatter.format_reply_messages(
                suggestion.final_reply_messages or suggestion.reply_messages
            ),
            "",
            f"Почему: {suggestion.reason_short}",
            f"Что сделал style-слой: {'; '.join(suggestion.style_notes)}",
            f"Что сделал persona-слой: {'; '.join(suggestion.persona_notes)}",
            (
                "Guardrails: ok"
                if not suggestion.guardrail_flags
                else f"Guardrails: {', '.join(suggestion.guardrail_flags)}"
            ),
            f"Риск: {suggestion.risk_label}",
            f"Уверенность: {round(suggestion.confidence * 100)}%",
            f"Стратегия: {suggestion.strategy}",
        ]
        if suggestion.alternative_action:
            lines.append(f"Вместо ответа: {suggestion.alternative_action}")
        return "\n".join(lines)
