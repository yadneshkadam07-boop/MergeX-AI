"""The bundled demo project.

The three fixture repositories under ``backend/fixtures/`` exist as analysis
input for the test suite. One of them doubles as the demo: a user who has no
repository to hand should still be able to see MergeX find something real.

This packs that fixture into a ZIP at request time and hands it to the
ordinary upload path, rather than adding a second way to import a project.
The demo therefore exercises exactly the code a real upload does, and the
fixture stays the single source of truth -- editing it changes the demo.
"""

from __future__ import annotations

import zipfile
from pathlib import Path
from typing import Final

from app.core.logging import get_logger

__all__ = ["DEMO_FIXTURE", "DemoUnavailableError", "demo_fixture_path", "pack_demo_archive"]

log = get_logger("app.demo")

# The mismatch fixture is the clearest demo: five API-contract findings, each
# one a defect a reader can verify in the source in seconds.
DEMO_FIXTURE: Final[str] = "react_fastapi_mismatch"

_FIXTURES_DIR: Final[Path] = Path(__file__).resolve().parent.parent.parent / "fixtures"

# The manifest is the test suite's contract, not part of the project.
_EXCLUDED_NAMES: Final[frozenset[str]] = frozenset({"expected_findings.json"})


class DemoUnavailableError(RuntimeError):
    """The bundled fixture is missing from this deployment."""


def demo_fixture_path(name: str = DEMO_FIXTURE) -> Path:
    """Locate a bundled fixture.

    Raises:
        DemoUnavailableError: the image was built without ``fixtures/``.
    """
    path = _FIXTURES_DIR / name
    if not path.is_dir():
        raise DemoUnavailableError("The bundled demo project is not available in this deployment.")
    return path


def pack_demo_archive(destination: Path, *, name: str = DEMO_FIXTURE) -> int:
    """Write the fixture to ``destination`` as a ZIP. Returns the file count.

    Synchronous and small (single-digit kilobytes); callers run it in a
    worker thread for consistency with the rest of the import path.
    """
    root = demo_fixture_path(name)
    written = 0

    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.name in _EXCLUDED_NAMES:
                continue
            archive.write(path, path.relative_to(root).as_posix())
            written += 1

    log.info("demo_archive_packed", fixture=name, files=written)
    return written
