from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, Float, ForeignKey, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.common import TimestampMixin, UpdatedAtMixin
from storage.base import Base

if TYPE_CHECKING:
    from models.chat import Chat


class PersonMemory(TimestampMixin, Base):
    __tablename__ = "people_memory"

    id: Mapped[int] = mapped_column(primary_key=True)
    person_key: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    relationship_label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    importance_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    last_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    known_facts_json: Mapped[dict[str, Any] | list[Any] | None] = mapped_column(JSON, nullable=True)
    sensitive_topics_json: Mapped[dict[str, Any] | list[Any] | None] = mapped_column(JSON, nullable=True)
    open_loops_json: Mapped[dict[str, Any] | list[Any] | None] = mapped_column(JSON, nullable=True)
    interaction_pattern: Mapped[str | None] = mapped_column(Text, nullable=True)


class ChatMemory(UpdatedAtMixin, Base):
    __tablename__ = "chat_memory"

    id: Mapped[int] = mapped_column(primary_key=True)
    chat_id: Mapped[int] = mapped_column(ForeignKey("chats.id", ondelete="CASCADE"), unique=True, nullable=False)
    chat_summary_short: Mapped[str] = mapped_column(Text, default="", nullable=False)
    chat_summary_long: Mapped[str] = mapped_column(Text, default="", nullable=False)
    current_state: Mapped[str | None] = mapped_column(Text, nullable=True)
    dominant_topics_json: Mapped[dict[str, Any] | list[Any] | None] = mapped_column(JSON, nullable=True)
    recent_conflicts_json: Mapped[dict[str, Any] | list[Any] | None] = mapped_column(JSON, nullable=True)
    pending_tasks_json: Mapped[dict[str, Any] | list[Any] | None] = mapped_column(JSON, nullable=True)
    linked_people_json: Mapped[dict[str, Any] | list[Any] | None] = mapped_column(JSON, nullable=True)
    last_digest_at: Mapped["datetime | None"] = mapped_column(DateTime(timezone=True), nullable=True)

    chat: Mapped["Chat"] = relationship(back_populates="memory")
