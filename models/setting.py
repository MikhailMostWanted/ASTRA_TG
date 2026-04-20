from __future__ import annotations

from typing import Any

from sqlalchemy import JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from models.common import UpdatedAtMixin
from storage.base import Base


class Setting(UpdatedAtMixin, Base):
    __tablename__ = "settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    value_json: Mapped[dict[str, Any] | list[Any] | None] = mapped_column(JSON, nullable=True)
    value_text: Mapped[str | None] = mapped_column(Text, nullable=True)
