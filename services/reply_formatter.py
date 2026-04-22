from __future__ import annotations

from dataclasses import dataclass, field

from services.reply_models import ReplyResult
from services.render_cards import (
    MARKER_OFF,
    MARKER_OK,
    MARKER_WARN,
    compact_text,
    format_status_line,
    state_shell_lines,
)
from services.style_formatter import StyleFormatter


@dataclass(slots=True)
class ReplyFormatter:
    style_formatter: StyleFormatter = field(default_factory=StyleFormatter)

    def format_result(self, result: ReplyResult) -> str:
        title = _reply_title(result)
        if result.kind != "suggestion" or result.suggestion is None:
            return "\n".join([title, "", *_reply_error_lines(result)])

        suggestion = result.suggestion
        lines = [
            title,
            "",
            *_reply_success_lines(result),
        ]
        lines.extend(self._final_reply_block(result))
        lines.extend(_why_and_details(result))
        return "\n".join(lines)

    def format_inline_result(self, result: ReplyResult) -> str:
        if result.kind != "suggestion" or result.suggestion is None:
            return "\n".join(_reply_error_lines(result))

        lines = _reply_success_lines(result)
        lines.extend(self._final_reply_block(result))
        lines.extend(_why_and_details(result))
        return "\n".join(lines)

    def _final_reply_block(self, result: ReplyResult) -> list[str]:
        suggestion = result.suggestion
        if suggestion is None:
            return []
        return [
            "",
            "Готовый вариант ответа",
            *self.style_formatter.format_reply_messages(
                suggestion.final_reply_messages or suggestion.reply_messages
            ),
        ]


def _reply_title(result: ReplyResult) -> str:
    chat_label = result.chat_title or result.chat_reference or "чат"
    return f"💬 Ответ / {chat_label}"


def _reply_error_lines(result: ReplyResult) -> list[str]:
    return state_shell_lines(
        marker=MARKER_WARN,
        status="Ответ не собран",
        meaning=result.error_message or "Подсказку сейчас собрать не получилось.",
        next_step="/reply <chat_id|@username>",
    )


def _reply_success_lines(result: ReplyResult) -> list[str]:
    suggestion = result.suggestion
    if suggestion is None:
        return []
    return [
        "Фокус ответа",
        compact_text(
            result.source_message_preview or suggestion.source_message_preview or "нет превью",
            limit=220,
        ),
        format_status_line(
            MARKER_OK,
            "Почему выбран",
            compact_text(suggestion.focus_reason, limit=160),
        ),
    ]


def _why_and_details(result: ReplyResult) -> list[str]:
    suggestion = result.suggestion
    if suggestion is None:
        return []

    style_source = "ручной" if suggestion.style_source == "override" else "авто"
    few_shot_detail = (
        f"{suggestion.few_shot_match_count} прим."
        if suggestion.few_shot_found
        else "нет"
    )
    guardrails_marker = MARKER_OK if not suggestion.guardrail_flags else MARKER_WARN
    guardrails_detail = (
        "без замечаний" if not suggestion.guardrail_flags else ", ".join(suggestion.guardrail_flags)
    )
    llm_lines: list[str] = []
    if suggestion.llm_refine_requested:
        llm_detail = (
            suggestion.llm_refine_provider or "применён"
            if suggestion.llm_refine_applied
            else "резервный режим"
        )
        if suggestion.llm_refine_notes:
            llm_detail = f"{llm_detail}: {compact_text(suggestion.llm_refine_notes[0], limit=90)}"
        llm_lines.append(
            format_status_line(
                MARKER_OK if suggestion.llm_refine_applied else MARKER_WARN,
                "LLM",
                llm_detail,
            )
        )
    lines = [
        "",
        "Почему именно так",
        compact_text(suggestion.reason_short, limit=140),
        format_status_line(MARKER_OK, "Повод сейчас", compact_text(suggestion.reply_opportunity_reason, limit=110)),
        "",
        "Тех. детали",
        format_status_line(MARKER_OK, "Стиль", f"{suggestion.style_profile_key} ({style_source})"),
        format_status_line(MARKER_OK if suggestion.persona_applied else MARKER_OFF, "Персона", "да" if suggestion.persona_applied else "нет"),
        format_status_line(MARKER_OK if suggestion.few_shot_found else MARKER_OFF, "Похожие примеры", few_shot_detail),
        *llm_lines,
        format_status_line(guardrails_marker, "Ограничители", guardrails_detail),
        format_status_line(MARKER_OK, "Риск", f"{suggestion.risk_label}; уверенность {round(suggestion.confidence * 100)}%"),
        format_status_line(MARKER_OK, "Стратегия", suggestion.strategy),
    ]
    if suggestion.alternative_action:
        lines.append(format_status_line(MARKER_WARN, "Вместо ответа", suggestion.alternative_action))
    return lines
