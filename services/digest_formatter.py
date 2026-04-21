from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from services.digest_builder import DigestBuildResult, DigestSourceSummary
from services.digest_window import format_window_range
from services.render_cards import (
    MARKER_OFF,
    MARKER_OK,
    MARKER_WARN,
    format_status_line,
    state_shell_lines,
)


if TYPE_CHECKING:
    from services.digest_engine import DigestExecutionPlan


@dataclass(frozen=True, slots=True)
class RenderedDigest:
    full_text: str
    chunks: list[str]


@dataclass(slots=True)
class DigestFormatter:
    max_message_length: int = 3500

    def format(self, result: DigestBuildResult) -> RenderedDigest:
        title = "Astra AFT / Digest"
        intro_sections = [
            "Сводка",
            format_status_line(MARKER_OK, "Окно", format_window_range(result.window)),
            format_status_line(MARKER_OK, "Сообщений", str(result.total_messages)),
            format_status_line(MARKER_OK, "Источников", str(result.source_count)),
            "",
            "Обзор",
            *result.overview_lines,
            "",
            "Ключевые темы и источники",
            *(result.key_source_lines or [f"{MARKER_OFF} Пока нет содержательных источников."]),
            "",
            "Источники",
        ]
        detail_sections = [self._format_source_section(source) for source in result.source_summaries]
        stats_section = "\n".join(
            [
                "Детали",
                format_status_line(MARKER_OK, "Сообщений в окне", str(result.total_messages)),
                format_status_line(MARKER_OK, "Источников с активностью", str(result.source_count)),
                format_status_line(MARKER_OK, "Окно digest", result.window.label),
            ]
        )
        chunks = _chunk_rendered_digest(
            title=title,
            intro="\n".join(intro_sections),
            sections=detail_sections,
            stats_section=stats_section,
            max_message_length=self.max_message_length,
        )
        return RenderedDigest(full_text="\n\n".join(chunks), chunks=chunks)

    def format_empty_window(self, *, window_label: str) -> RenderedDigest:
        lines = [
            "Astra AFT / Digest",
            "",
            *state_shell_lines(
                marker=MARKER_WARN,
                status="Данных для дайджеста нет",
                meaning=f"За {window_label} по активным digest-источникам сообщений не найдено.",
                next_step="Подожди новых сообщений или проверь Sources.",
            ),
        ]
        text = "\n".join(lines)
        return RenderedDigest(full_text=text, chunks=[text])

    def format_inline_result(
        self,
        *,
        plan: DigestExecutionPlan,
        notice: str | None,
    ) -> str:
        target_label = plan.target.label or (
            str(plan.target.chat_id) if plan.target.chat_id is not None else "не задан"
        )
        if not plan.has_digest:
            lines = state_shell_lines(
                marker=MARKER_WARN,
                status="Дайджест не собран",
                meaning="В выбранном окне не нашлось новых данных.",
                next_step="Попробуй окно 24h или проверь Sources.",
            )
            lines.extend(
                [
                    "",
                    "Детали",
                    format_status_line(MARKER_OK, "Окно", format_window_range(plan.window)),
                    format_status_line(MARKER_OFF, "Получатель", target_label),
                ]
            )
            return "\n".join(lines)

        lines = [
            "Сводка",
            format_status_line(MARKER_OK, "Дайджест", "собран"),
            plan.summary_short,
            "",
            "Ключевые параметры",
            format_status_line(MARKER_OK, "Окно", format_window_range(plan.window)),
            format_status_line(MARKER_OK, "Получатель", target_label),
            format_status_line(MARKER_OK, "Сообщений", str(plan.message_count)),
            format_status_line(MARKER_OK, "Источников", str(plan.source_count)),
        ]
        lines.extend(["", "Детали", format_status_line(MARKER_OK, "Digest ID", f"#{plan.digest_id}")])
        if plan.llm_refine_requested:
            lines.append(
                format_status_line(MARKER_OK, "LLM-улучшение", "применено")
                if plan.llm_refine_applied
                else format_status_line(MARKER_WARN, "LLM-улучшение", "резервный базовый digest")
            )
        if notice:
            lines.append(format_status_line(MARKER_OK, "Публикация", notice))
        return "\n".join(lines)

    def _format_source_section(self, source: DigestSourceSummary) -> str:
        lines = [
            format_status_line(MARKER_OK, source.display_title, f"{source.message_count} сообщений"),
        ]
        lines.extend(f"- {point.text}" for point in source.points)
        return "\n".join(lines)


def _chunk_rendered_digest(
    *,
    title: str,
    intro: str,
    sections: list[str],
    stats_section: str,
    max_message_length: int,
) -> list[str]:
    if not sections:
        return [f"{title}\n\n{intro}\n\n{stats_section}"]

    window_line = next((line for line in intro.splitlines() if "Окно:" in line), "")
    primary_header = f"{title}\n\n{intro}"
    continuation_header = (
        f"{title} (продолжение)\n\n{window_line}"
        if window_line
        else f"{title} (продолжение)"
    )
    chunks: list[str] = []
    current_sections: list[str] = []
    current_header = primary_header

    for section in [*sections, stats_section]:
        candidate = _render_chunk(current_header=current_header, sections=[*current_sections, section])
        if len(candidate) > max_message_length and current_sections:
            chunks.append(_render_chunk(current_header=current_header, sections=current_sections))
            current_header = continuation_header
            current_sections = [section]
            continue

        current_sections.append(section)

    if current_sections:
        chunks.append(_render_chunk(current_header=current_header, sections=current_sections))

    return chunks


def _render_chunk(*, current_header: str, sections: list[str]) -> str:
    return "\n\n".join([current_header, *sections])
