from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.common import TimestampMixin
from storage.base import Base

if TYPE_CHECKING:
    from models.chat import Chat, Message


class Task(TimestampMixin, Base):
    __tablename__ = "tasks"
    __table_args__ = (
        Index("ix_tasks_status_due_at", "status", "due_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    source_chat_id: Mapped[int | None] = mapped_column(
        ForeignKey("chats.id", ondelete="SET NULL"),
        nullable=True,
    )
    source_message_id: Mapped[int | None] = mapped_column(
        ForeignKey("messages.id", ondelete="SET NULL"),
        nullable=True,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    summary: Mapped[str] = mapped_column(Text, default="", nullable=False)
    due_at: Mapped["datetime | None"] = mapped_column(DateTime(timezone=True), nullable=True)
    suggested_remind_at: Mapped["datetime | None"] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    needs_user_confirmation: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    source_chat: Mapped["Chat | None"] = relationship(back_populates="tasks")
    source_message: Mapped["Message | None"] = relationship()
    reminders: Mapped[list["Reminder"]] = relationship(back_populates="task")


class Reminder(TimestampMixin, Base):
    __tablename__ = "reminders"
    __table_args__ = (
        Index("ix_reminders_status_remind_at", "status", "remind_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int | None] = mapped_column(ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True)
    remind_at: Mapped["datetime"] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    last_notification_at: Mapped["datetime | None"] = mapped_column(DateTime(timezone=True), nullable=True)
    payload_json: Mapped[dict[str, Any] | list[Any] | None] = mapped_column(JSON, nullable=True)

    task: Mapped["Task | None"] = relationship(back_populates="reminders")
