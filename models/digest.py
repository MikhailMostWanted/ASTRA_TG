from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.common import CreatedAtMixin
from storage.base import Base

if TYPE_CHECKING:
    from models.chat import Chat, Message


class Digest(CreatedAtMixin, Base):
    __tablename__ = "digests"
    __table_args__ = (
        Index("ix_digests_chat_id_window_end", "chat_id", "window_end"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    chat_id: Mapped[int | None] = mapped_column(ForeignKey("chats.id", ondelete="SET NULL"), nullable=True)
    window_start: Mapped["datetime"] = mapped_column(DateTime(timezone=True), nullable=False)
    window_end: Mapped["datetime"] = mapped_column(DateTime(timezone=True), nullable=False)
    summary_short: Mapped[str] = mapped_column(Text, nullable=False)
    summary_long: Mapped[str] = mapped_column(Text, nullable=False)
    delivered_to_chat_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    delivered_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    chat: Mapped["Chat | None"] = relationship(back_populates="digests")
    items: Mapped[list["DigestItem"]] = relationship(
        back_populates="digest",
        cascade="all, delete-orphan",
        order_by="DigestItem.sort_order",
    )


class DigestItem(Base):
    __tablename__ = "digest_items"
    __table_args__ = (
        Index("ix_digest_items_digest_id_sort_order", "digest_id", "sort_order"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    digest_id: Mapped[int] = mapped_column(ForeignKey("digests.id", ondelete="CASCADE"), nullable=False)
    source_chat_id: Mapped[int] = mapped_column(ForeignKey("chats.id", ondelete="RESTRICT"), nullable=False)
    source_message_id: Mapped[int | None] = mapped_column(
        ForeignKey("messages.id", ondelete="SET NULL"),
        nullable=True,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    link: Mapped[str | None] = mapped_column(Text, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    digest: Mapped["Digest"] = relationship(back_populates="items")
    source_chat: Mapped["Chat"] = relationship()
    source_message: Mapped["Message | None"] = relationship()
