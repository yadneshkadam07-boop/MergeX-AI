"""Add subscription tier and Stripe columns to users table

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-07
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "tier",
            sa.String(length=20),
            server_default="free",
            nullable=False,
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "stripe_customer_id",
            sa.String(length=100),
            nullable=True,
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "stripe_subscription_id",
            sa.String(length=100),
            nullable=True,
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "monthly_scans_used",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
    )
    op.create_index(
        op.f("ix_users_stripe_customer_id"),
        "users",
        ["stripe_customer_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_users_stripe_customer_id"), table_name="users")
    op.drop_column("users", "monthly_scans_used")
    op.drop_column("users", "stripe_subscription_id")
    op.drop_column("users", "stripe_customer_id")
    op.drop_column("users", "tier")
