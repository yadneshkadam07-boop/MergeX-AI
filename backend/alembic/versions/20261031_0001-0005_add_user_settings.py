"""Add user_settings table

Stores global user preferences, theme, check toggles, and alert thresholds.
Works portably across PostgreSQL and SQLite.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-31
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON_TYPE = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "user_settings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "display_name", sa.String(length=100), server_default="Alex Vance", nullable=False
        ),
        sa.Column(
            "email", sa.String(length=255), server_default="developer@mergex.ai", nullable=False
        ),
        sa.Column("theme", sa.String(length=20), server_default="system", nullable=False),
        sa.Column("github_connected", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("github_username", sa.String(length=100), nullable=True),
        sa.Column("checks", JSON_TYPE, nullable=False),
        sa.Column("alert_severity", sa.String(length=20), server_default="high", nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_user_settings"),
    )


def downgrade() -> None:
    op.drop_table("user_settings")
