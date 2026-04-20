"""Добавить style profiles и chat-specific overrides для reply layer.

Revision ID: 20260420_02
Revises: 20260420_01
Create Date: 2026-04-20 23:10:00
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260420_02"
down_revision: str | None = "20260420_01"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


STYLE_PROFILES = [
    {
        "key": "base",
        "title": "Базовый телеграмный",
        "description": "Короткая серия спокойных живых сообщений без карикатуры.",
        "sort_order": 10,
        "traits_json": {
            "message_mode": "series",
            "target_message_count": 2,
            "max_message_count": 4,
            "avg_length_hint": "short",
            "punctuation_level": "low",
            "profanity_level": "low",
            "warmth_level": "medium",
            "directness_level": "medium",
            "explanation_pattern": ["поправить", "упростить", "приземлить", "добить"],
            "preferred_openers": ["ну", "да", "это"],
            "preferred_closers": ["если что добью дальше"],
            "avoid_patterns": ["!!!", "брат", "короче короче"],
            "casing_mode": "mostly_lower",
            "rhythm_mode": "telegram_bursts",
        },
    },
    {
        "key": "friend_hard",
        "title": "Жёсткий дружеский",
        "description": "Прямой и короткий дружеский режим без тупого хамства.",
        "sort_order": 20,
        "traits_json": {
            "message_mode": "series",
            "target_message_count": 2,
            "max_message_count": 3,
            "avg_length_hint": "short",
            "punctuation_level": "low",
            "profanity_level": "functional",
            "warmth_level": "low",
            "directness_level": "high",
            "explanation_pattern": ["поправить", "сказать прямо", "закрыть хвост"],
            "preferred_openers": ["да", "не", "ну"],
            "preferred_closers": ["дальше уже добью по факту"],
            "avoid_patterns": ["брат", "!!!", "гоп-цирк"],
            "casing_mode": "mostly_lower",
            "rhythm_mode": "telegram_bursts",
        },
    },
    {
        "key": "friend_explain",
        "title": "Дружеский объясняющий",
        "description": "Пояснить по-человечески, кусочно и без длинных абзацев.",
        "sort_order": 30,
        "traits_json": {
            "message_mode": "series",
            "target_message_count": 3,
            "max_message_count": 4,
            "avg_length_hint": "short",
            "punctuation_level": "low",
            "profanity_level": "low",
            "warmth_level": "medium",
            "directness_level": "medium",
            "explanation_pattern": ["поправить", "упростить", "приземлить", "добить"],
            "preferred_openers": ["ну", "да", "а"],
            "preferred_closers": ["если что потом докручу"],
            "avoid_patterns": ["длинный абзац", "слишком литературно", "!!!"],
            "casing_mode": "mostly_lower",
            "rhythm_mode": "telegram_bursts",
        },
    },
    {
        "key": "practical_short",
        "title": "Практичный короткий",
        "description": "Максимально коротко и по делу, без лишней эмоциональности.",
        "sort_order": 40,
        "traits_json": {
            "message_mode": "series",
            "target_message_count": 1,
            "max_message_count": 2,
            "avg_length_hint": "short",
            "punctuation_level": "low",
            "profanity_level": "none",
            "warmth_level": "low",
            "directness_level": "high",
            "explanation_pattern": ["сказать по делу", "дать следующий шаг"],
            "preferred_openers": ["да", "это"],
            "preferred_closers": ["дальше скину отдельно"],
            "avoid_patterns": ["вода", "длинные абзацы", "!!!"],
            "casing_mode": "mostly_lower",
            "rhythm_mode": "telegram_bursts",
        },
    },
    {
        "key": "romantic_soft",
        "title": "Мягкий романтический",
        "description": "Тёплый и мягкий режим без сахара и карикатуры.",
        "sort_order": 50,
        "traits_json": {
            "message_mode": "series",
            "target_message_count": 2,
            "max_message_count": 3,
            "avg_length_hint": "short",
            "punctuation_level": "low",
            "profanity_level": "none",
            "warmth_level": "high",
            "directness_level": "low",
            "explanation_pattern": ["снять тревогу", "упростить", "мягко добить"],
            "preferred_openers": ["я", "не", "да"],
            "preferred_closers": ["я рядом"],
            "avoid_patterns": ["слишком сладко", "!!!", "литературщина"],
            "casing_mode": "mostly_lower",
            "rhythm_mode": "telegram_bursts",
        },
    },
    {
        "key": "tension_soft",
        "title": "Мягкое снятие напряжения",
        "description": "Сначала успокоить тон, потом коротко вернуть разговор в дело.",
        "sort_order": 60,
        "traits_json": {
            "message_mode": "series",
            "target_message_count": 3,
            "max_message_count": 4,
            "avg_length_hint": "short",
            "punctuation_level": "low",
            "profanity_level": "none",
            "warmth_level": "medium",
            "directness_level": "medium",
            "explanation_pattern": ["снять напряжение", "приземлить", "дать следующий шаг"],
            "preferred_openers": ["да", "ну", "я"],
            "preferred_closers": ["дальше уже по факту скажу"],
            "avoid_patterns": ["эскалация", "!!!", "хамство"],
            "casing_mode": "mostly_lower",
            "rhythm_mode": "telegram_bursts",
        },
    },
]


def upgrade() -> None:
    op.create_table(
        "style_profiles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("traits_json", sa.JSON(), nullable=False),
        sa.Column("is_builtin", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.UniqueConstraint("key", name="uq_style_profiles_key"),
    )

    op.create_table(
        "chat_style_overrides",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("chat_id", sa.Integer(), nullable=False),
        sa.Column("style_profile_id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(["chat_id"], ["chats.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["style_profile_id"], ["style_profiles.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("chat_id", name="uq_chat_style_overrides_chat_id"),
    )

    style_profiles_table = sa.table(
        "style_profiles",
        sa.column("key", sa.String(length=64)),
        sa.column("title", sa.String(length=255)),
        sa.column("description", sa.Text()),
        sa.column("sort_order", sa.Integer()),
        sa.column("traits_json", sa.JSON()),
        sa.column("is_builtin", sa.Boolean()),
    )
    op.bulk_insert(style_profiles_table, STYLE_PROFILES)


def downgrade() -> None:
    op.drop_table("chat_style_overrides")
    op.drop_table("style_profiles")
