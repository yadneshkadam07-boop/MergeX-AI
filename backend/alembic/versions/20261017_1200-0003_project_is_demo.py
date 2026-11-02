"""Mark demo projects so they can be purged

The demo endpoint is unauthenticated, so the projects it creates are
disposable and are deleted on a retention schedule. A column rather than a
naming convention: deletion must not depend on a string a user can set, and
a stray project called "Demo" must never be eligible for automatic removal.

Backfilled to false, which is correct for every project that existed before
the demo endpoint did.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-17
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "projects",
        sa.Column(
            "is_demo",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    # Partial indexes are not portable to SQLite, which the test suite uses,
    # so this is a plain index. It is only read by the cleanup task.
    op.create_index("ix_projects_is_demo", "projects", ["is_demo"])


def downgrade() -> None:
    op.drop_index("ix_projects_is_demo", table_name="projects")
    op.drop_column("projects", "is_demo")
