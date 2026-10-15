"""The migration must match the models.

This is the test that justifies the rest of the suite using
``Base.metadata.create_all`` instead of running Alembic: if the migration and
the models ever diverge, this fails, and until then they are interchangeable.

It also catches the classic drift where someone edits a model and forgets the
migration — which is, pointedly, one of the defect classes MergeX itself
detects.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.autogenerate import compare_metadata
from alembic.command import downgrade, upgrade
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory

from app.models import Base

BACKEND_DIR = Path(__file__).resolve().parent.parent


def _alembic_config(database_url: str) -> Config:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url)
    # The post-write hooks only matter when generating revisions.
    config.set_section_option("post_write_hooks", "hooks", "")
    return config


@pytest.fixture
def sqlite_url(tmp_path: Path) -> str:
    return f"sqlite:///{(tmp_path / 'migrated.db').as_posix()}"


def test_single_head() -> None:
    """Exactly one head: a branched history cannot be upgraded unattended."""
    script = ScriptDirectory(str(BACKEND_DIR / "alembic"))

    assert len(script.get_heads()) == 1


def test_upgrade_creates_every_table(sqlite_url: str) -> None:
    upgrade(_alembic_config(sqlite_url), "head")

    engine = sa.create_engine(sqlite_url)
    try:
        tables = set(sa.inspect(engine).get_table_names())
    finally:
        engine.dispose()

    assert {"projects", "analyses", "issues"} <= tables


def test_migration_matches_models(sqlite_url: str) -> None:
    """No pending autogenerate diffs after upgrading to head."""
    upgrade(_alembic_config(sqlite_url), "head")

    engine = sa.create_engine(sqlite_url)
    try:
        with engine.connect() as connection:
            diffs = compare_metadata(MigrationContext.configure(connection), Base.metadata)
    finally:
        engine.dispose()

    # SQLite does not report the *name* of a reflected UNIQUE constraint, so
    # Alembic proposes dropping and re-adding every named one. The constraint
    # is present and correctly named in the DDL (asserted below), so this
    # single class of false positive is filtered out rather than papered over
    # by relaxing the whole comparison.
    real_diffs = [diff for diff in diffs if not _is_sqlite_unique_name_artifact(diff)]

    assert real_diffs == [], f"Migration has drifted from the models: {real_diffs}"


def test_unique_constraint_is_named_in_the_database(sqlite_url: str) -> None:
    """Guards the filter applied in the test above."""
    upgrade(_alembic_config(sqlite_url), "head")

    engine = sa.create_engine(sqlite_url)
    try:
        with engine.connect() as connection:
            ddl: str = connection.exec_driver_sql(
                "SELECT sql FROM sqlite_master WHERE name = 'issues'"
            ).scalar_one()
    finally:
        engine.dispose()

    assert "CONSTRAINT uq_issues_analysis_id_fingerprint UNIQUE" in ddl


def test_downgrade_removes_every_table(sqlite_url: str) -> None:
    """A migration that cannot be rolled back is a migration you cannot ship."""
    config = _alembic_config(sqlite_url)
    upgrade(config, "head")
    downgrade(config, "base")

    engine = sa.create_engine(sqlite_url)
    try:
        tables = set(sa.inspect(engine).get_table_names())
    finally:
        engine.dispose()

    assert tables - {"alembic_version"} == set()


def _is_sqlite_unique_name_artifact(diff: object) -> bool:
    """True for the add/remove pair SQLite reflection invents for named uniques."""
    if not isinstance(diff, tuple) or len(diff) != 2:
        return False
    operation, constraint = diff
    if operation not in {"add_constraint", "remove_constraint"}:
        return False
    return isinstance(constraint, sa.UniqueConstraint)
