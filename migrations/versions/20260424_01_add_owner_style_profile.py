"""Добавить owner style profile для reply quality.

Revision ID: 20260424_01
Revises: 20260421_01
Create Date: 2026-04-24 12:00:00
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260424_01"
down_revision: str | None = "20260421_01"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


OWNER_STYLE_PROFILE = {
    "key": "owner_style",
    "title": "Мой стиль",
    "description": "Короткий живой Telegram-ритм владельца: каскады, прямота, минимум пунктуации.",
    "sort_order": 5,
    "traits_json": {
        "message_mode": "series",
        "target_message_count": 3,
        "max_message_count": 4,
        "avg_length_hint": "short",
        "punctuation_level": "low",
        "profanity_level": "functional",
        "warmth_level": "medium",
        "directness_level": "high",
        "explanation_pattern": [
            "короткий заход",
            "уточнить смысл",
            "сказать прямо",
            "добить мысль без канцелярита",
        ],
        "preferred_openers": [
            "ну",
            "да",
            "не",
            "не не",
            "а",
            "слушай",
            "смотри",
            "короче",
            "типо",
            "щас",
        ],
        "preferred_closers": [
            "если что скажу",
            "дальше уже по факту",
        ],
        "avoid_patterns": [
            "я бы ответил",
            "можно написать",
            "вариант ответа",
            "с учётом контекста",
            "длинный абзац",
            "markdown",
            "карикатурный мат",
        ],
        "casing_mode": "mostly_lower",
        "rhythm_mode": "telegram_cascade",
    },
}


def upgrade() -> None:
    style_profiles_table = sa.table(
        "style_profiles",
        sa.column("key", sa.String(length=64)),
        sa.column("title", sa.String(length=255)),
        sa.column("description", sa.Text()),
        sa.column("sort_order", sa.Integer()),
        sa.column("traits_json", sa.JSON()),
        sa.column("is_builtin", sa.Boolean()),
    )
    connection = op.get_bind()
    exists = connection.execute(
        sa.text("SELECT 1 FROM style_profiles WHERE key = :key LIMIT 1"),
        {"key": OWNER_STYLE_PROFILE["key"]},
    ).fetchone()
    if exists is None:
        op.bulk_insert(
            style_profiles_table,
            [
                {
                    **OWNER_STYLE_PROFILE,
                    "is_builtin": True,
                }
            ],
        )


def downgrade() -> None:
    op.execute("DELETE FROM style_profiles WHERE key = 'owner_style'")
