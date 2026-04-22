from datetime import datetime, timezone

from services.digest_builder import DigestBuildResult, DigestSourcePoint, DigestSourceSummary
from services.digest_formatter import DigestFormatter
from services.digest_window import parse_digest_window
from services.render_cards import MARKER_WARN, render_overview_card, render_text_card, state_shell_lines


def test_state_shell_uses_single_status_meaning_next_step_structure() -> None:
    lines = state_shell_lines(
        marker=MARKER_WARN,
        status="Данных нет",
        meaning="Локальная БД пока пустая.",
        next_step="/source_add <chat_id|@username>",
    )

    assert lines == [
        "[WARN] Данных нет",
        "",
        "Что это значит",
        "Локальная БД пока пустая.",
        "",
        "Что делать дальше",
        "/source_add <chat_id|@username>",
    ]


def test_overview_and_result_cards_keep_utility_buttons_last() -> None:
    overview = render_overview_card(
        title="Astra AFT / Status",
        summary_lines=["Готово: 2/9"],
        detail_lines=["[WARN] Источники: нет"],
        next_step="/source_add <chat_id|@username>",
        rows=[[("Чеклист", "ux:checklist")]],
        back_screen="home",
        current_screen="status",
    )
    result = render_text_card(
        title="Astra AFT / Reply / Команда",
        lines=["Итоговая серия", "1. Да, понял."],
        rows=[[("Похожие", "ux:reply:examples:team")]],
        back_screen="reply_pick",
        current_screen="reply_pick",
    )

    assert _keyboard_rows(overview.reply_markup)[-1] == ["Назад", "Домой", "Обновить"]
    assert _keyboard_rows(result.reply_markup)[0] == ["Похожие"]
    assert _keyboard_rows(result.reply_markup)[-1] == ["Назад", "Домой", "Обновить"]


def test_digest_chunking_keeps_summary_first_and_continuation_context() -> None:
    window = parse_digest_window(
        "24h",
        now=datetime(2026, 4, 21, 12, 0, tzinfo=timezone.utc),
    )
    result = DigestBuildResult(
        window=window,
        total_messages=12,
        source_count=4,
        summary_short="За 24h: 12 сообщений из 4 источников.",
        overview_lines=[
            "- Всего сообщений в окне: 12.",
            "- Самые активные источники: Команда, Новости.",
        ],
        key_source_lines=[
            "- Команда: 6 сообщ., 3 ключевых пункта.",
            "- Новости: 4 сообщ., 2 ключевых пункта.",
        ],
        source_summaries=[
            _source_summary(index=1, title="Команда продукта"),
            _source_summary(index=2, title="Новости релизов"),
            _source_summary(index=3, title="Поддержка"),
            _source_summary(index=4, title="Продажи"),
        ],
    )

    rendered = DigestFormatter(max_message_length=900).format(result)

    assert len(rendered.chunks) > 1
    assert rendered.chunks[0].startswith("📰 Дайджест\n\nКоротко")
    assert "Сводка" in rendered.chunks[0]
    assert "Темы и источники" in rendered.chunks[0]
    assert rendered.chunks[1].startswith("📰 Дайджест (продолжение)\n\n[OK] Окно:")
    assert "Тех. детали" in rendered.chunks[-1]


def _source_summary(*, index: int, title: str) -> DigestSourceSummary:
    return DigestSourceSummary(
        chat_id=index,
        telegram_chat_id=-1000 - index,
        title=title,
        handle=None,
        message_count=3,
        points=[
            DigestSourcePoint(
                source_message_id=index * 10 + point,
                text=(
                    f"{title}: важный пункт {point} с достаточно подробным текстом "
                    "для проверки разбиения длинной карточки."
                ),
                score=1.0,
            )
            for point in range(1, 4)
        ],
        representative_message_id=index * 10,
    )


def _keyboard_rows(reply_markup) -> list[list[str]]:
    return [[button.text for button in row] for row in reply_markup.inline_keyboard]
