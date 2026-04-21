from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from services.digest_builder import DigestBuildResult, DigestSourceSummary
from services.digest_window import format_window_range


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
        title = "Digest Astra AFT"
        intro_sections = [
            f"Окно: {format_window_range(result.window)}",
            "",
            "Что произошло:",
            *result.overview_lines,
            "",
            "Ключевые источники:",
            *(result.key_source_lines or ["- Пока нет содержательных источников."]),
            "",
            "Подробнее по источникам:",
        ]
        detail_sections = [self._format_source_section(source) for source in result.source_summaries]
        stats_section = "\n".join(
            [
                "Статистика:",
                f"- Сообщений в окне: {result.total_messages}",
                f"- Источников с активностью: {result.source_count}",
                f"- Окно digest: {result.window.label}",
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

    def format_inline_result(
        self,
        *,
        plan: DigestExecutionPlan,
        notice: str | None,
    ) -> str:
        target_label = plan.target.label or (
            str(plan.target.chat_id) if plan.target.chat_id is not None else "не задан"
        )
        lines = [
            f"Окно: {format_window_range(plan.window)}",
            f"Цель: {target_label}",
            f"Сводка: {plan.summary_short}",
        ]
        if plan.has_digest:
            lines.extend(
                [
                    "",
                    "Что произошло:",
                    f"• Digest сохранён: #{plan.digest_id}",
                    f"• Сообщений в окне: {plan.message_count}",
                    f"• Источников с активностью: {plan.source_count}",
                ]
            )
        else:
            lines.extend(["", "Что произошло:", "• Новых данных для digest в этом окне не нашлось."])
        if plan.llm_refine_requested:
            lines.append(
                "• LLM-улучшение: применено."
                if plan.llm_refine_applied
                else "• LLM-улучшение: fallback, показан базовый digest."
            )
        if notice:
            lines.append(f"• Публикация: {notice}")
        return "\n".join(lines)

    def _format_source_section(self, source: DigestSourceSummary) -> str:
        lines = [
            source.display_title,
            f"{source.message_count} сообщений за окно.",
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

    window_line = intro.splitlines()[0] if intro else ""
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
