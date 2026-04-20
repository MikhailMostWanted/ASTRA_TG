from __future__ import annotations

from typing import Any

from sqlalchemy import Boolean, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.common import TimestampMixin
from storage.base import Base


class StyleProfile(TimestampMixin, Base):
    __tablename__ = "style_profiles"
    __table_args__ = (
        UniqueConstraint("key", name="uq_style_profiles_key"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    traits_json: Mapped[dict[str, Any] | list[Any]] = mapped_column(JSON, nullable=False)
    is_builtin: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class ChatStyleOverride(TimestampMixin, Base):
    __tablename__ = "chat_style_overrides"
    __table_args__ = (
        UniqueConstraint("chat_id", name="uq_chat_style_overrides_chat_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    chat_id: Mapped[int] = mapped_column(
        ForeignKey("chats.id", ondelete="CASCADE"),
        nullable=False,
    )
    style_profile_id: Mapped[int] = mapped_column(
        ForeignKey("style_profiles.id", ondelete="CASCADE"),
        nullable=False,
    )

    chat = relationship("Chat")
    style_profile = relationship("StyleProfile")
