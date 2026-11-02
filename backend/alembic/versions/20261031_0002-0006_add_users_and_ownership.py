"""Add users table and project/settings ownership

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-31
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DEFAULT_USER_ID = uuid.UUID("00000000-0000-4000-a000-000000000001")
DEFAULT_PASSWORD_HASH = "$2b$12$b.we3xq6ykEWvSq5rz2cpu.P/JfIxC5Gm7xfSynZUrr98sdqwKnCe"


def upgrade() -> None:
    # 1. Create users table
    users_table = op.create_table(
        "users",
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
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("display_name", sa.String(length=100), nullable=False),
        sa.Column("avatar_url", sa.String(length=500), nullable=True),
        sa.Column("github_username", sa.String(length=100), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
    )
    op.create_index(op.f("ix_users_email"), "users", ["email"], unique=True)

    # 2. Seed default user so existing projects and settings have an owner
    op.bulk_insert(
        users_table,
        [
            {
                "id": DEFAULT_USER_ID,
                "email": "developer@mergex.ai",
                "password_hash": DEFAULT_PASSWORD_HASH,
                "display_name": "Alex Vance",
                "avatar_url": None,
                "github_username": "alex-vance",
            }
        ],
    )

    # 3. Add user_id to projects with default fallback and foreign key
    with op.batch_alter_table("projects") as batch_op:
        batch_op.add_column(
            sa.Column(
                "user_id",
                sa.Uuid(),
                nullable=False,
                server_default=str(DEFAULT_USER_ID),
            )
        )
        batch_op.create_foreign_key(
            op.f("fk_projects_user_id_users"),
            "users",
            ["user_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch_op.create_index(op.f("ix_projects_user_id"), ["user_id"], unique=False)

    # 4. Add user_id to user_settings with default fallback, unique index, and foreign key
    with op.batch_alter_table("user_settings") as batch_op:
        batch_op.add_column(
            sa.Column(
                "user_id",
                sa.Uuid(),
                nullable=False,
                server_default=str(DEFAULT_USER_ID),
            )
        )
        batch_op.create_foreign_key(
            op.f("fk_user_settings_user_id_users"),
            "users",
            ["user_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch_op.create_index(op.f("ix_user_settings_user_id"), ["user_id"], unique=True)


def downgrade() -> None:
    with op.batch_alter_table("user_settings") as batch_op:
        batch_op.drop_index(op.f("ix_user_settings_user_id"))
        batch_op.drop_constraint(op.f("fk_user_settings_user_id_users"), type_="foreignkey")
        batch_op.drop_column("user_id")

    with op.batch_alter_table("projects") as batch_op:
        batch_op.drop_index(op.f("ix_projects_user_id"))
        batch_op.drop_constraint(op.f("fk_projects_user_id_users"), type_="foreignkey")
        batch_op.drop_column("user_id")

    op.drop_index(op.f("ix_users_email"), table_name="users")
    op.drop_table("users")
