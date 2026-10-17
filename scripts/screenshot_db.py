"""Create a throwaway SQLite database for the screenshot harness.

The models are dialect-neutral (``app.models.base``) and
``tests/test_migrations.py`` asserts that the Alembic migration and the
models agree, so ``create_all`` is a legitimate shortcut here: it avoids
needing a Postgres service just to take pictures.

Usage: ``python scripts/screenshot_db.py <sqlite-file-path>``
"""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))

import sqlalchemy as sa  # noqa: E402

from app.models import Base  # noqa: E402


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2

    target = Path(sys.argv[1]).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.unlink(missing_ok=True)

    engine = sa.create_engine(f"sqlite:///{target.as_posix()}")
    try:
        Base.metadata.create_all(engine)
    finally:
        engine.dispose()

    print(f"created {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
