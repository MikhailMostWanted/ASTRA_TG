"""Добавить локальный few-shot слой reply examples.

Revision ID: 20260421_01
Revises: 20260420_02
Create Date: 2026-04-21 10:40:00
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260421_01"
down_revision: str | None = "20260420_02"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "reply_examples",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("chat_id", sa.Integer(), nullable=False),
        sa.Column("inbound_message_id", sa.Integer(), nullable=True),
        sa.Column("outbound_message_id", sa.Integer(), nullable=True),
        sa.Column("inbound_text", sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.Column("outbound_text", sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.Column("inbound_normalized", sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.Column("outbound_normalized", sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.Column("context_before_json", sa.JSON(), nullable=True),
        sa.Column(
            "example_type",
            sa.String(length=64),
            nullable=False,
            server_default=sa.text("'soft_reply'"),
        ),
        sa.Column(
            "source_person_key",
            sa.String(length=255),
            nullable=True,
        ),
        sa.Column(
            "quality_score",
            sa.Float(),
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
        sa.ForeignKeyConstraint(["chat_id"], ["chats.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["inbound_message_id"], ["messages.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["outbound_message_id"], ["messages.id"], ondelete="SET NULL"),
        sa.UniqueConstraint(
            "inbound_message_id",
            "outbound_message_id",
            name="uq_reply_examples_message_pair",
        ),
    )
    op.create_index(
        "ix_reply_examples_chat_id_created_at",
        "reply_examples",
        ["chat_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_reply_examples_quality_score",
        "reply_examples",
        ["quality_score"],
        unique=False,
    )
    op.create_index(
        "ix_reply_examples_source_person_key",
        "reply_examples",
        ["source_person_key"],
        unique=False,
    )

    op.execute(
        """
        CREATE VIRTUAL TABLE reply_examples_fts
        USING fts5(
            inbound_text,
            inbound_normalized,
            content='reply_examples',
            content_rowid='id'
        )
        """
    )
    op.execute(
        """
        INSERT INTO reply_examples_fts(rowid, inbound_text, inbound_normalized)
        SELECT id, inbound_text, inbound_normalized
        FROM reply_examples
        """
    )
    op.execute(
        """
        CREATE TRIGGER reply_examples_ai AFTER INSERT ON reply_examples BEGIN
            INSERT INTO reply_examples_fts(rowid, inbound_text, inbound_normalized)
            VALUES (new.id, new.inbound_text, new.inbound_normalized);
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER reply_examples_au AFTER UPDATE ON reply_examples BEGIN
            INSERT INTO reply_examples_fts(reply_examples_fts, rowid, inbound_text, inbound_normalized)
            VALUES ('delete', old.id, old.inbound_text, old.inbound_normalized);
            INSERT INTO reply_examples_fts(rowid, inbound_text, inbound_normalized)
            VALUES (new.id, new.inbound_text, new.inbound_normalized);
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER reply_examples_bu AFTER DELETE ON reply_examples BEGIN
            INSERT INTO reply_examples_fts(reply_examples_fts, rowid, inbound_text, inbound_normalized)
            VALUES ('delete', old.id, old.inbound_text, old.inbound_normalized);
        END
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS reply_examples_bu")
    op.execute("DROP TRIGGER IF EXISTS reply_examples_au")
    op.execute("DROP TRIGGER IF EXISTS reply_examples_ai")
    op.execute("DROP TABLE IF EXISTS reply_examples_fts")

    op.drop_index("ix_reply_examples_source_person_key", table_name="reply_examples")
    op.drop_index("ix_reply_examples_quality_score", table_name="reply_examples")
    op.drop_index("ix_reply_examples_chat_id_created_at", table_name="reply_examples")
    op.drop_table("reply_examples")
