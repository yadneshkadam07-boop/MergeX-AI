"""Add explanation-source and concrete-fix columns to issues

Phase 4 produces a before/after code edit for every finding. Keeping the two
sides in their own columns lets the UI render a diff and offer a copy button
without parsing prose out of `suggested_fix`.

`explanation_source` records whether the prose came from Gemini or from the
rule's offline template, which the UI shows and which makes a drop in model
quality visible rather than silent.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-17
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("issues", sa.Column("explanation_source", sa.String(length=20), nullable=True))
    op.add_column("issues", sa.Column("fix_before", sa.Text(), nullable=True))
    op.add_column("issues", sa.Column("fix_after", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("issues", "fix_after")
    op.drop_column("issues", "fix_before")
    op.drop_column("issues", "explanation_source")
