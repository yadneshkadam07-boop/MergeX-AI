"""Declarative base, shared column types and mixins.

The naming convention matters: without it, Alembic autogenerate produces
migrations that try to drop and recreate unnamed constraints, because the names
the database invented do not match what the metadata expects.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any, TypeVar

from sqlalchemy import DateTime, Enum, MetaData, func
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import JSON, TypeEngine

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

# JSONB on PostgreSQL (indexable, typed), plain JSON elsewhere so the test
# suite can run on SQLite.
JSONType: TypeEngine[Any] = JSON().with_variant(postgresql.JSONB(), "postgresql")

_E = TypeVar("_E", bound=StrEnum)


def enum_column(python_enum: type[_E], name: str) -> Enum:
    """Build a ``VARCHAR`` + ``CHECK`` column type for a :class:`StrEnum`.

    ``values_callable`` is essential: without it SQLAlchemy persists the enum
    *member name* (``CRITICAL``) rather than its value (``critical``), which
    would not match what the API emits.
    """
    return Enum(
        python_enum,
        name=name,
        native_enum=False,
        validate_strings=True,
        values_callable=lambda enum_cls: [member.value for member in enum_cls],
    )


class Base(DeclarativeBase):
    """Declarative base for every MergeX model."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)

    type_annotation_map = {  # noqa: RUF012
        dict[str, Any]: JSONType,
        list[Any]: JSONType,
    }

    def __repr__(self) -> str:
        identifier = getattr(self, "id", None)
        return f"<{type(self).__name__} id={identifier}>"


class UUIDPrimaryKeyMixin:
    """A client-generatable UUID primary key.

    UUIDs rather than serials so an analysis id can be minted before the row
    is written (useful for the SSE stream URL) and so ids are not guessable.
    """

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)


class TimestampMixin:
    """``created_at`` / ``updated_at``, maintained by the database."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
