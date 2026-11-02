"""Add status column to issues table

Enables issue tracking (open, resolved, ignored) from the project workspace.
Defaults to 'open'. Works on both PostgreSQL and SQLite.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-31
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ISSUE_STATUS = sa.Enum(
    "open",
    "resolved",
    "ignored",
    name="issue_status",
    native_enum=False,
)


def upgrade() -> None:
    op.add_column(
        "issues",
        sa.Column(
            "status",
            ISSUE_STATUS,
            nullable=False,
            server_default="open",
        ),
    )
    op.create_index("ix_issues_status", "issues", ["status"])
    op.create_index("ix_issues_analysis_id_status", "issues", ["analysis_id", "status"])


def downgrade() -> None:
    op.drop_index("ix_issues_analysis_id_status", table_name="issues")
    op.drop_index("ix_issues_status", table_name="issues")
    op.drop_column("issues", "status")
