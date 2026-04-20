"""Добавить начальную схему хранения для MVP Astra AFT.

Revision ID: 20260420_01
Revises:
Create Date: 2026-04-20 22:15:00
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260420_01"
down_revision: str | None = None
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "chats",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("telegram_chat_id", sa.BigInteger(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("handle", sa.String(length=255), nullable=True),
        sa.Column("type", sa.String(length=50), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("category", sa.String(length=50), nullable=True),
        sa.Column("summary_schedule", sa.String(length=50), nullable=True),
        sa.Column(
            "reply_assist_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("auto_reply_mode", sa.String(length=50), nullable=True),
        sa.Column(
            "exclude_from_memory",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "exclude_from_digest",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("0"),
        ),
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
        sa.UniqueConstraint("telegram_chat_id", name="uq_chats_telegram_chat_id"),
    )

    op.create_table(
        "messages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("telegram_message_id", sa.BigInteger(), nullable=False),
        sa.Column("chat_id", sa.Integer(), nullable=False),
        sa.Column("sender_id", sa.BigInteger(), nullable=True),
        sa.Column("sender_name", sa.String(length=255), nullable=True),
        sa.Column("direction", sa.String(length=32), nullable=False),
        sa.Column("source_adapter", sa.String(length=64), nullable=False),
        sa.Column("source_type", sa.String(length=64), nullable=False),
        sa.Column(
            "sent_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("raw_text", sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.Column("normalized_text", sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.Column("reply_to_message_id", sa.Integer(), nullable=True),
        sa.Column("forward_info", sa.JSON(), nullable=True),
        sa.Column("has_media", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("media_type", sa.String(length=64), nullable=True),
        sa.Column("entities_json", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(["chat_id"], ["chats.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["reply_to_message_id"],
            ["messages.id"],
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint(
            "chat_id",
            "telegram_message_id",
            name="uq_messages_chat_id_telegram_message_id",
        ),
    )
    op.create_index(
        "ix_messages_chat_id_sent_at",
        "messages",
        ["chat_id", "sent_at"],
        unique=False,
    )

    op.create_table(
        "digests",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("chat_id", sa.Integer(), nullable=True),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("summary_short", sa.Text(), nullable=False),
        sa.Column("summary_long", sa.Text(), nullable=False),
        sa.Column("delivered_to_chat_id", sa.BigInteger(), nullable=True),
        sa.Column("delivered_message_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(["chat_id"], ["chats.id"], ondelete="SET NULL"),
    )
    op.create_index(
        "ix_digests_chat_id_window_end",
        "digests",
        ["chat_id", "window_end"],
        unique=False,
    )

    op.create_table(
        "people_memory",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("person_key", sa.String(length=255), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("relationship_label", sa.String(length=255), nullable=True),
        sa.Column("importance_score", sa.Float(), nullable=False, server_default=sa.text("0")),
        sa.Column("last_summary", sa.Text(), nullable=True),
        sa.Column("known_facts_json", sa.JSON(), nullable=True),
        sa.Column("sensitive_topics_json", sa.JSON(), nullable=True),
        sa.Column("open_loops_json", sa.JSON(), nullable=True),
        sa.Column("interaction_pattern", sa.Text(), nullable=True),
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
        sa.UniqueConstraint("person_key", name="uq_people_memory_person_key"),
    )

    op.create_table(
        "chat_memory",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("chat_id", sa.Integer(), nullable=False),
        sa.Column("chat_summary_short", sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.Column("chat_summary_long", sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.Column("current_state", sa.Text(), nullable=True),
        sa.Column("dominant_topics_json", sa.JSON(), nullable=True),
        sa.Column("recent_conflicts_json", sa.JSON(), nullable=True),
        sa.Column("pending_tasks_json", sa.JSON(), nullable=True),
        sa.Column("linked_people_json", sa.JSON(), nullable=True),
        sa.Column("last_digest_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(["chat_id"], ["chats.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("chat_id", name="uq_chat_memory_chat_id"),
    )

    op.create_table(
        "tasks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source_chat_id", sa.Integer(), nullable=True),
        sa.Column("source_message_id", sa.Integer(), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("suggested_remind_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column("confidence", sa.Float(), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "needs_user_confirmation",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("1"),
        ),
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
        sa.ForeignKeyConstraint(["source_chat_id"], ["chats.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["source_message_id"], ["messages.id"], ondelete="SET NULL"),
    )
    op.create_index(
        "ix_tasks_status_due_at",
        "tasks",
        ["status", "due_at"],
        unique=False,
    )

    op.create_table(
        "reminders",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("task_id", sa.Integer(), nullable=True),
        sa.Column("remind_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column("last_notification_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("payload_json", sa.JSON(), nullable=True),
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
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="SET NULL"),
    )
    op.create_index(
        "ix_reminders_status_remind_at",
        "reminders",
        ["status", "remind_at"],
        unique=False,
    )

    op.create_table(
        "settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("key", sa.String(length=255), nullable=False),
        sa.Column("value_json", sa.JSON(), nullable=True),
        sa.Column("value_text", sa.Text(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.UniqueConstraint("key", name="uq_settings_key"),
    )

    op.create_table(
        "digest_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("digest_id", sa.Integer(), nullable=False),
        sa.Column("source_chat_id", sa.Integer(), nullable=False),
        sa.Column("source_message_id", sa.Integer(), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("link", sa.Text(), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.ForeignKeyConstraint(["digest_id"], ["digests.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_chat_id"], ["chats.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["source_message_id"], ["messages.id"], ondelete="SET NULL"),
    )
    op.create_index(
        "ix_digest_items_digest_id_sort_order",
        "digest_items",
        ["digest_id", "sort_order"],
        unique=False,
    )

    op.execute(
        """
        CREATE VIRTUAL TABLE messages_fts
        USING fts5(
            raw_text,
            normalized_text,
            content='messages',
            content_rowid='id'
        )
        """
    )
    op.execute(
        """
        INSERT INTO messages_fts(rowid, raw_text, normalized_text)
        SELECT id, raw_text, normalized_text
        FROM messages
        """
    )
    op.execute(
        """
        CREATE TRIGGER messages_ai AFTER INSERT ON messages BEGIN
            INSERT INTO messages_fts(rowid, raw_text, normalized_text)
            VALUES (new.id, new.raw_text, new.normalized_text);
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER messages_au AFTER UPDATE ON messages BEGIN
            INSERT INTO messages_fts(messages_fts, rowid, raw_text, normalized_text)
            VALUES ('delete', old.id, old.raw_text, old.normalized_text);
            INSERT INTO messages_fts(rowid, raw_text, normalized_text)
            VALUES (new.id, new.raw_text, new.normalized_text);
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER messages_bu AFTER DELETE ON messages BEGIN
            INSERT INTO messages_fts(messages_fts, rowid, raw_text, normalized_text)
            VALUES ('delete', old.id, old.raw_text, old.normalized_text);
        END
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS messages_bu")
    op.execute("DROP TRIGGER IF EXISTS messages_au")
    op.execute("DROP TRIGGER IF EXISTS messages_ai")
    op.execute("DROP TABLE IF EXISTS messages_fts")

    op.drop_index("ix_digest_items_digest_id_sort_order", table_name="digest_items")
    op.drop_table("digest_items")

    op.drop_table("settings")

    op.drop_index("ix_reminders_status_remind_at", table_name="reminders")
    op.drop_table("reminders")

    op.drop_index("ix_tasks_status_due_at", table_name="tasks")
    op.drop_table("tasks")

    op.drop_table("chat_memory")
    op.drop_table("people_memory")

    op.drop_index("ix_digests_chat_id_window_end", table_name="digests")
    op.drop_table("digests")

    op.drop_index("ix_messages_chat_id_sent_at", table_name="messages")
    op.drop_table("messages")

    op.drop_table("chats")
