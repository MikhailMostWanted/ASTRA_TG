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
            (
                f"Few-shot support: найден ({suggestion.few_shot_match_count} примера)"
                if suggestion.few_shot_found
                else "Few-shot support: не найден"
            ),
        ]
        if suggestion.llm_refine_requested:
            lines.append(
                (
                    f"LLM-refine: применён ({suggestion.llm_refine_provider or 'provider'})"
                    if suggestion.llm_refine_applied
                    else "LLM-refine: fallback"
                )
            )
        lines.extend(
            [
                "Итоговая серия:",
                *self.style_formatter.format_reply_messages(
                    suggestion.final_reply_messages or suggestion.reply_messages
                ),
                "",
                f"Почему: {suggestion.reason_short}",
                f"Что сделал few-shot-слой: {'; '.join(suggestion.few_shot_notes)}",
                f"Что сделал style-слой: {'; '.join(suggestion.style_notes)}",
                f"Что сделал persona-слой: {'; '.join(suggestion.persona_notes)}",
            ]
        )
        if suggestion.llm_refine_requested:
            lines.extend(
                [
                    f"Что сделал LLM-слой: {'; '.join(suggestion.llm_refine_notes)}",
                    (
                        "LLM-guardrails: ok"
                        if not suggestion.llm_refine_guardrail_flags
                        else (
                            "LLM-guardrails: "
                            + ", ".join(suggestion.llm_refine_guardrail_flags)
                        )
                    ),
                ]
            )
        lines.extend(
            [
                (
                    "Guardrails: ok"
                    if not suggestion.guardrail_flags
                    else f"Guardrails: {', '.join(suggestion.guardrail_flags)}"
                ),
                f"Риск: {suggestion.risk_label}",
                f"Уверенность: {round(suggestion.confidence * 100)}%",
                f"Стратегия: {suggestion.strategy}",
            ]
        )
        if suggestion.alternative_action:
            lines.append(f"Вместо ответа: {suggestion.alternative_action}")
        return "\n".join(lines)

    def format_inline_result(self, result: ReplyResult) -> str:
        if result.kind != "suggestion" or result.suggestion is None:
            lines = [
                f"Чат: {result.chat_title or 'не определён'}",
                f"Источник: {result.chat_reference or 'не определён'}",
                "",
                result.error_message or "Подсказку пока не получилось собрать.",
            ]
            return "\n".join(lines)

        suggestion = result.suggestion
        style_source = "ручной" if suggestion.style_source == "override" else "авто"
        few_shot_label = (
            f"few-shot: {suggestion.few_shot_match_count}"
            if suggestion.few_shot_found
            else "few-shot: нет"
        )
        llm_label = ""
        if suggestion.llm_refine_requested:
            llm_label = (
                f", LLM: {suggestion.llm_refine_provider or 'провайдер'}"
                if suggestion.llm_refine_applied
                else ", LLM: резервный режим"
            )
        lines = [
            f"Чат: {result.chat_title}",
            f"Источник: {result.chat_reference}",
            "",
            "Сообщение-ориентир",
            result.source_message_preview or suggestion.source_message_preview,
            "",
            "Итоговая серия",
            *self.style_formatter.format_reply_messages(
                suggestion.final_reply_messages or suggestion.reply_messages
            ),
            "",
            f"Почему: {suggestion.reason_short}",
            f"Риск / уверенность: {suggestion.risk_label} / {round(suggestion.confidence * 100)}%",
            (
                f"Style / persona / few-shot: {suggestion.style_profile_key} ({style_source}), "
                f"persona: {'да' if suggestion.persona_applied else 'нет'}, {few_shot_label}{llm_label}"
            ),
        ]
        if suggestion.alternative_action:
            lines.append(f"Вместо ответа: {suggestion.alternative_action}")
        return "\n".join(lines)
