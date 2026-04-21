from __future__ import annotations

from typing import Any

from sqlalchemy import Float, ForeignKey, Index, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.common import TimestampMixin
from storage.base import Base


class ReplyExample(TimestampMixin, Base):
    __tablename__ = "reply_examples"
    __table_args__ = (
        UniqueConstraint(
            "inbound_message_id",
            "outbound_message_id",
            name="uq_reply_examples_message_pair",
        ),
        Index("ix_reply_examples_chat_id_created_at", "chat_id", "created_at"),
        Index("ix_reply_examples_quality_score", "quality_score"),
        Index("ix_reply_examples_source_person_key", "source_person_key"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    chat_id: Mapped[int] = mapped_column(
        ForeignKey("chats.id", ondelete="CASCADE"),
        nullable=False,
    )
    inbound_message_id: Mapped[int | None] = mapped_column(
        ForeignKey("messages.id", ondelete="SET NULL"),
        nullable=True,
    )
    outbound_message_id: Mapped[int | None] = mapped_column(
        ForeignKey("messages.id", ondelete="SET NULL"),
        nullable=True,
    )
    inbound_text: Mapped[str] = mapped_column(Text, default="", nullable=False)
    outbound_text: Mapped[str] = mapped_column(Text, default="", nullable=False)
    inbound_normalized: Mapped[str] = mapped_column(Text, default="", nullable=False)
    outbound_normalized: Mapped[str] = mapped_column(Text, default="", nullable=False)
    context_before_json: Mapped[dict[str, Any] | list[Any] | None] = mapped_column(
        JSON,
        nullable=True,
    )
    example_type: Mapped[str] = mapped_column(String(64), default="soft_reply", nullable=False)
    source_person_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    quality_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    chat = relationship("Chat")
    inbound_message = relationship("Message", foreign_keys=[inbound_message_id])
    outbound_message = relationship("Message", foreign_keys=[outbound_message_id])
