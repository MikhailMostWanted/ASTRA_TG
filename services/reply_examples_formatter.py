from __future__ import annotations

from dataclasses import dataclass

from services.reply_examples_models import ReplyExamplesRebuildResult, ReplyExamplesRetrievalResult


@dataclass(slots=True)
class ReplyExamplesFormatter:
    def format_rebuild_result(self, result: ReplyExamplesRebuildResult) -> str:
        lines = [
            "Локальная база reply examples пересобрана.",
            f"Собрано reply examples: {result.examples_created}",
            f"Чатов: {result.chats_processed}",
            f"Просмотрено сообщений: {result.messages_scanned}",
        ]
        if result.scope_reference:
            lines.append(f"Скоуп: {result.scope_reference}")
        return "\n".join(lines)

    def format_matches(
        self,
        *,
        chat_title: str,
        chat_reference: str,
        retrieval_result: ReplyExamplesRetrievalResult,
    ) -> str:
        lines = [
            "Похожие прошлые ответы",
            f"Чат: {chat_title}",
            f"Источник: {chat_reference}",
            "",
        ]
        if not retrieval_result.matches:
            lines.append("Локальных похожих примеров не найдено.")
            return "\n".join(lines)

        lines.append(f"Найдено примеров: {retrieval_result.match_count}")
        for note in retrieval_result.notes:
            lines.append(f"- {note}")
        lines.append("")

        for index, match in enumerate(retrieval_result.matches, start=1):
            lines.extend(
                [
                    f"{index}. Сходство: {round(match.score * 100)}%",
                    f"Причины: {', '.join(match.reasons)}",
                    f"Чат примера: {match.chat_title}",
                    f"Входящий: {match.inbound_text}",
                    f"Ответ: {match.outbound_text}",
                    "",
                ]
            )

        return "\n".join(lines).rstrip()
