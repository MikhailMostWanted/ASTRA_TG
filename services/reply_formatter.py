from __future__ import annotations

from dataclasses import dataclass

from services.reply_models import ReplyResult


@dataclass(slots=True)
class ReplyFormatter:
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
        label = "Совет" if suggestion.strategy == "не отвечать" else "Черновик"
        lines = [
            f"Чат: {result.chat_title}",
            f"Источник: {result.chat_reference}",
            f"Ориентир: {result.source_message_preview or suggestion.source_message_preview}",
            "",
            f"{label}:",
            suggestion.reply_text,
            "",
            f"Почему: {suggestion.reason_short}",
            f"Риск: {suggestion.risk_label}",
            f"Уверенность: {round(suggestion.confidence * 100)}%",
            f"Стратегия: {suggestion.strategy}",
        ]
        if suggestion.alternative_action:
            lines.append(f"Вместо ответа: {suggestion.alternative_action}")
        return "\n".join(lines)
