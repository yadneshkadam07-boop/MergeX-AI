"""The ``user_settings`` table: global user preferences and scan configuration."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import Boolean, ForeignKey, String, false as sa_false
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, JSONType, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    import uuid

    from app.models.user import User


class UserSettingsModel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Stores user preferences, UI theme, checks toggle, and alert severity thresholds."""

    __tablename__ = "user_settings"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    user: Mapped[User] = relationship("User", back_populates="settings")

    display_name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        default="Alex Vance",
        server_default="Alex Vance",
    )
    email: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        default="developer@mergex.ai",
        server_default="developer@mergex.ai",
    )
    theme: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="system",
        server_default="system",
    )
    github_connected: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=sa_false(),
    )
    github_username: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )
    checks: Mapped[dict[str, Any]] = mapped_column(
        JSONType,
        nullable=False,
        default=lambda: {
            "integration": True,
            "security": True,
            "dependencies": True,
            "deployment": True,
        },
    )
    alert_severity: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="high",
        server_default="high",
    )
