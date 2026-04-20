from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.common import CreatedAtMixin, TimestampMixin, utcnow
from storage.base import Base

if TYPE_CHECKING:
    from models.digest import Digest
    from models.memory import ChatMemory
    from models.task import Task


class Chat(TimestampMixin, Base):
    __tablename__ = "chats"

    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_chat_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    handle: Mapped[str | None] = mapped_column(String(255), nullable=True)
    type: Mapped[str] = mapped_column(String(50), nullable=False)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    category: Mapped[str | None] = mapped_column(String(50), nullable=True)
    summary_schedule: Mapped[str | None] = mapped_column(String(50), nullable=True)
    reply_assist_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    auto_reply_mode: Mapped[str | None] = mapped_column(String(50), nullable=True)
    exclude_from_memory: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    exclude_from_digest: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    messages: Mapped[list["Message"]] = relationship(back_populates="chat")
    digests: Mapped[list["Digest"]] = relationship(back_populates="chat")
    memory: Mapped["ChatMemory | None"] = relationship(back_populates="chat", uselist=False)
    tasks: Mapped[list["Task"]] = relationship(back_populates="source_chat")


class Message(CreatedAtMixin, Base):
    __tablename__ = "messages"
    __table_args__ = (
        UniqueConstraint(
            "chat_id",
            "telegram_message_id",
            name="uq_messages_chat_id_telegram_message_id",
        ),
        Index("ix_messages_chat_id_sent_at", "chat_id", "sent_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_message_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    chat_id: Mapped[int] = mapped_column(ForeignKey("chats.id", ondelete="CASCADE"), nullable=False)
    sender_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    sender_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    direction: Mapped[str] = mapped_column(String(32), nullable=False)
    source_adapter: Mapped[str] = mapped_column(String(64), nullable=False)
    source_type: Mapped[str] = mapped_column(String(64), nullable=False)
    sent_at: Mapped["datetime"] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    raw_text: Mapped[str] = mapped_column(Text, default="", nullable=False)
    normalized_text: Mapped[str] = mapped_column(Text, default="", nullable=False)
    reply_to_message_id: Mapped[int | None] = mapped_column(
        ForeignKey("messages.id", ondelete="SET NULL"),
        nullable=True,
    )
    forward_info: Mapped[dict[str, Any] | list[Any] | None] = mapped_column(JSON, nullable=True)
    has_media: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    media_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    entities_json: Mapped[dict[str, Any] | list[Any] | None] = mapped_column(JSON, nullable=True)

    chat: Mapped["Chat"] = relationship(back_populates="messages")
    reply_to_message: Mapped["Message | None"] = relationship(
        remote_side="Message.id",
        foreign_keys=[reply_to_message_id],
    )
