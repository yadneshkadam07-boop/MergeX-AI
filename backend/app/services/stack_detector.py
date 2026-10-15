"""Deterministic framework and tooling detection.

Every conclusion is backed by a specific file and a specific line of evidence,
recorded on the :class:`Signal` that produced it. Nothing here guesses, and
nothing here calls a language model: the downstream agents need to know *which
file* proved that a project uses FastAPI so they know where to look for route
definitions.

Detection is layered:

1. **Manifests** (``package.json``, ``requirements.txt``, ``pyproject.toml``,
   ``go.mod``, ``composer.json``) -- a declared dependency is the strongest
   signal available.
2. **Marker files** (``next.config.js``, ``prisma/schema.prisma``,
   ``alembic.ini``, ``vite.config.ts``) -- present when a manifest is absent
   or when a tool is configured without a direct dependency entry.
3. **File extensions** -- language mix, and the fallback when a project has no
   manifest at all.
"""

from __future__ import annotations

import json
import re
import tomllib
from collections import Counter
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Any

from app.core.logging import get_logger
from app.services.archive import is_ignored_path

__all__ = [
    "Layer",
    "Signal",
    "StackReport",
    "detect_stack",
]

log = get_logger("app.stack_detector")

# How deep to search for manifests. A monorepo keeps them in packages/*/ or
# apps/*/; nothing legitimate buries package.json six levels down.
_MAX_MANIFEST_DEPTH = 4


class Layer(StrEnum):
    """Which part of the architecture a technology belongs to."""

    FRONTEND = "frontend"
    BACKEND = "backend"
    DATABASE = "database"
    BUILD = "build"
    PACKAGE_MANAGER = "package_manager"


@dataclass(frozen=True, slots=True)
class Signal:
    """One piece of evidence for one technology."""

    technology: str
    layer: Layer
    source_file: str
    evidence: str
    confidence: float = 1.0


@dataclass(slots=True)
class StackReport:
    """Everything detection concluded about a project."""

    frontend: list[str] = field(default_factory=list)
    backend: list[str] = field(default_factory=list)
    database: list[str] = field(default_factory=list)
    build: list[str] = field(default_factory=list)
    package_managers: list[str] = field(default_factory=list)
    languages: dict[str, int] = field(default_factory=dict)
    is_monorepo: bool = False
    # Directories that root each layer, e.g. ["frontend"] and ["backend"].
    # Phase 2 uses these to decide where to look for API calls versus route
    # definitions, instead of scanning the whole tree for both.
    frontend_roots: list[str] = field(default_factory=list)
    backend_roots: list[str] = field(default_factory=list)
    manifest_paths: list[str] = field(default_factory=list)
    signals: list[Signal] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """JSON-serialisable form, as persisted on the project row."""
        return {
            "frontend": self.frontend,
            "backend": self.backend,
            "database": self.database,
            "build": self.build,
            "package_managers": self.package_managers,
            "languages": self.languages,
            "is_monorepo": self.is_monorepo,
            "frontend_roots": self.frontend_roots,
            "backend_roots": self.backend_roots,
            "manifest_paths": self.manifest_paths,
            "signals": [
                {
                    "technology": signal.technology,
                    "layer": signal.layer.value,
                    "source_file": signal.source_file,
                    "evidence": signal.evidence,
                    "confidence": signal.confidence,
                }
                for signal in self.signals
            ],
        }

    @property
    def is_empty(self) -> bool:
        """True when nothing recognisable was found."""
        return not (self.frontend or self.backend or self.database)


# -- Dependency tables --------------------------------------------------------
# npm package name -> (display name, layer). Checked against the union of
# dependencies, devDependencies and peerDependencies.
_NPM_PACKAGES: dict[str, tuple[str, Layer]] = {
    # frontend frameworks
    "react": ("React", Layer.FRONTEND),
    "react-dom": ("React", Layer.FRONTEND),
    "next": ("Next.js", Layer.FRONTEND),
    "vue": ("Vue", Layer.FRONTEND),
    "nuxt": ("Nuxt", Layer.FRONTEND),
    "svelte": ("Svelte", Layer.FRONTEND),
    "@sveltejs/kit": ("SvelteKit", Layer.FRONTEND),
    "@angular/core": ("Angular", Layer.FRONTEND),
    "solid-js": ("SolidJS", Layer.FRONTEND),
    "preact": ("Preact", Layer.FRONTEND),
    "@remix-run/react": ("Remix", Layer.FRONTEND),
    "astro": ("Astro", Layer.FRONTEND),
    # node backends
    "express": ("Express", Layer.BACKEND),
    "fastify": ("Fastify", Layer.BACKEND),
    "koa": ("Koa", Layer.BACKEND),
    "@nestjs/core": ("NestJS", Layer.BACKEND),
    "hapi": ("hapi", Layer.BACKEND),
    "@hapi/hapi": ("hapi", Layer.BACKEND),
    "hono": ("Hono", Layer.BACKEND),
    # data layer
    "prisma": ("Prisma", Layer.DATABASE),
    "@prisma/client": ("Prisma", Layer.DATABASE),
    "drizzle-orm": ("Drizzle", Layer.DATABASE),
    "typeorm": ("TypeORM", Layer.DATABASE),
    "sequelize": ("Sequelize", Layer.DATABASE),
    "mongoose": ("Mongoose", Layer.DATABASE),
    "knex": ("Knex", Layer.DATABASE),
    "@supabase/supabase-js": ("Supabase", Layer.DATABASE),
    "pg": ("PostgreSQL", Layer.DATABASE),
    "mysql2": ("MySQL", Layer.DATABASE),
    "better-sqlite3": ("SQLite", Layer.DATABASE),
    "redis": ("Redis", Layer.DATABASE),
    "ioredis": ("Redis", Layer.DATABASE),
    # build tooling
    "vite": ("Vite", Layer.BUILD),
    "webpack": ("Webpack", Layer.BUILD),
    "parcel": ("Parcel", Layer.BUILD),
    "rollup": ("Rollup", Layer.BUILD),
    "esbuild": ("esbuild", Layer.BUILD),
    "typescript": ("TypeScript", Layer.BUILD),
    "tailwindcss": ("Tailwind CSS", Layer.BUILD),
}

# PyPI distribution name -> (display name, layer).
_PYTHON_PACKAGES: dict[str, tuple[str, Layer]] = {
    "fastapi": ("FastAPI", Layer.BACKEND),
    "django": ("Django", Layer.BACKEND),
    "flask": ("Flask", Layer.BACKEND),
    "starlette": ("Starlette", Layer.BACKEND),
    "litestar": ("Litestar", Layer.BACKEND),
    "sanic": ("Sanic", Layer.BACKEND),
    "tornado": ("Tornado", Layer.BACKEND),
    "aiohttp": ("aiohttp", Layer.BACKEND),
    "sqlalchemy": ("SQLAlchemy", Layer.DATABASE),
    "alembic": ("Alembic", Layer.DATABASE),
    "tortoise-orm": ("Tortoise ORM", Layer.DATABASE),
    "peewee": ("Peewee", Layer.DATABASE),
    "psycopg": ("PostgreSQL", Layer.DATABASE),
    "psycopg2": ("PostgreSQL", Layer.DATABASE),
    "psycopg2-binary": ("PostgreSQL", Layer.DATABASE),
    "asyncpg": ("PostgreSQL", Layer.DATABASE),
    "pymongo": ("MongoDB", Layer.DATABASE),
    "motor": ("MongoDB", Layer.DATABASE),
    "redis": ("Redis", Layer.DATABASE),
    "supabase": ("Supabase", Layer.DATABASE),
    "django-rest-framework": ("Django REST Framework", Layer.BACKEND),
    "djangorestframework": ("Django REST Framework", Layer.BACKEND),
}

# Marker file (matched on the relative POSIX path) -> (display name, layer).
_MARKER_FILES: dict[str, tuple[str, Layer]] = {
    "next.config.js": ("Next.js", Layer.FRONTEND),
    "next.config.mjs": ("Next.js", Layer.FRONTEND),
    "next.config.ts": ("Next.js", Layer.FRONTEND),
    "nuxt.config.ts": ("Nuxt", Layer.FRONTEND),
    "svelte.config.js": ("Svelte", Layer.FRONTEND),
    "angular.json": ("Angular", Layer.FRONTEND),
    "vite.config.ts": ("Vite", Layer.BUILD),
    "vite.config.js": ("Vite", Layer.BUILD),
    "tailwind.config.js": ("Tailwind CSS", Layer.BUILD),
    "tailwind.config.ts": ("Tailwind CSS", Layer.BUILD),
    "tsconfig.json": ("TypeScript", Layer.BUILD),
    "prisma/schema.prisma": ("Prisma", Layer.DATABASE),
    "alembic.ini": ("Alembic", Layer.DATABASE),
    "manage.py": ("Django", Layer.BACKEND),
    "drizzle.config.ts": ("Drizzle", Layer.DATABASE),
    "supabase/config.toml": ("Supabase", Layer.DATABASE),
    "docker-compose.yml": ("Docker Compose", Layer.BUILD),
    "docker-compose.yaml": ("Docker Compose", Layer.BUILD),
    "Dockerfile": ("Docker", Layer.BUILD),
}

# Lockfile -> package manager.
_LOCKFILES: dict[str, str] = {
    "package-lock.json": "npm",
    "yarn.lock": "yarn",
    "pnpm-lock.yaml": "pnpm",
    "bun.lockb": "bun",
    "poetry.lock": "poetry",
    "Pipfile.lock": "pipenv",
    "uv.lock": "uv",
    "requirements.txt": "pip",
    "pdm.lock": "pdm",
}

# File extension -> language label.
_LANGUAGE_EXTENSIONS: dict[str, str] = {
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".mts": "TypeScript",
    ".cts": "TypeScript",
    ".js": "JavaScript",
    ".jsx": "JavaScript",
    ".mjs": "JavaScript",
    ".cjs": "JavaScript",
    ".py": "Python",
    ".pyi": "Python",
    ".go": "Go",
    ".rs": "Rust",
    ".rb": "Ruby",
    ".php": "PHP",
    ".java": "Java",
    ".kt": "Kotlin",
    ".cs": "C#",
    ".swift": "Swift",
    ".vue": "Vue",
    ".svelte": "Svelte",
    ".sql": "SQL",
    ".css": "CSS",
    ".scss": "CSS",
    ".html": "HTML",
    ".sh": "Shell",
}

# `package==1.2.3`, `package>=1.0`, `package[extra]~=2.0`, `package`
_REQUIREMENT_RE = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)\s*(?:\[[^\]]*\])?")
# Lines in requirements.txt that are directives, not dependencies.
_REQUIREMENT_SKIP = ("-r", "-c", "--", "#", "git+", "http://", "https://", ".")


def detect_stack(root: Path) -> StackReport:
    """Identify the frameworks, data layer and tooling used under ``root``.

    Args:
        root: An imported working tree.

    Returns:
        A report whose lists are sorted and de-duplicated, with the raw
        evidence retained in :attr:`StackReport.signals`.
    """
    signals: list[Signal] = []
    manifests: list[str] = []
    package_managers: set[str] = set()

    files = _collect_files(root)

    for relative, absolute in files.items():
        name = Path(relative).name

        if name in _LOCKFILES:
            package_managers.add(_LOCKFILES[name])

        marker = _MARKER_FILES.get(relative) or _MARKER_FILES.get(name)
        if marker is not None:
            display, layer = marker
            signals.append(
                Signal(
                    technology=display,
                    layer=layer,
                    source_file=relative,
                    evidence=f"{name} is present",
                    # A marker file is good evidence, but weaker than a
                    # declared dependency: it may be a leftover.
                    confidence=0.8,
                )
            )

        if name == "package.json":
            manifests.append(relative)
            signals.extend(_from_package_json(absolute, relative))
        elif name == "requirements.txt":
            manifests.append(relative)
            signals.extend(_from_requirements(absolute, relative))
        elif name == "pyproject.toml":
            manifests.append(relative)
            signals.extend(_from_pyproject(absolute, relative))

    # A package.json with no JS lockfile still means an npm-family project;
    # the lockfile is simply not committed (common in AI-generated repos).
    if any(Path(path).name == "package.json" for path in manifests) and not (
        package_managers & {"npm", "yarn", "pnpm", "bun"}
    ):
        package_managers.add("npm")

    report = StackReport(
        frontend=_collect(signals, Layer.FRONTEND),
        backend=_collect(signals, Layer.BACKEND),
        database=_collect(signals, Layer.DATABASE),
        build=_collect(signals, Layer.BUILD),
        package_managers=sorted(package_managers),
        languages=_count_languages(files),
        is_monorepo=_looks_like_monorepo(files, signals),
        frontend_roots=_layer_roots(signals, Layer.FRONTEND),
        backend_roots=_layer_roots(signals, Layer.BACKEND),
        manifest_paths=sorted(manifests),
        signals=sorted(signals, key=lambda s: (s.layer.value, s.technology, s.source_file)),
    )

    log.info(
        "stack_detected",
        frontend=report.frontend,
        backend=report.backend,
        database=report.database,
        monorepo=report.is_monorepo,
    )
    return report


def _collect_files(root: Path) -> dict[str, Path]:
    """Map relative POSIX paths to absolute paths, skipping ignored trees."""
    found: dict[str, Path] = {}
    stack = [(root, 0)]

    while stack:
        current, depth = stack.pop()
        try:
            entries = list(current.iterdir())
        except OSError:
            continue

        for entry in entries:
            if entry.is_symlink():
                continue
            try:
                relative = entry.relative_to(root).as_posix()
            except ValueError:  # pragma: no cover - defensive
                continue
            if entry.is_dir():
                if depth < _MAX_MANIFEST_DEPTH and not is_ignored_path(f"{relative}/"):
                    stack.append((entry, depth + 1))
                continue
            if not is_ignored_path(relative):
                found[relative] = entry

    return found


def _from_package_json(path: Path, relative: str) -> list[Signal]:
    """Signals from an npm manifest's declared dependencies."""
    data = _read_json(path)
    if data is None:
        return []

    declared: dict[str, str] = {}
    for section in ("dependencies", "devDependencies", "peerDependencies"):
        block = data.get(section)
        if isinstance(block, dict):
            for key, value in block.items():
                if isinstance(key, str):
                    declared[key] = str(value)

    signals = [
        Signal(
            technology=_NPM_PACKAGES[name][0],
            layer=_NPM_PACKAGES[name][1],
            source_file=relative,
            evidence=f'"{name}": "{version}"',
        )
        for name, version in sorted(declared.items())
        if name in _NPM_PACKAGES
    ]

    # `"workspaces"` is the npm/yarn/bun monorepo marker.
    if isinstance(data.get("workspaces"), (list, dict)):  # noqa: UP038
        signals.append(
            Signal(
                technology="Workspaces",
                layer=Layer.BUILD,
                source_file=relative,
                evidence='"workspaces" is declared',
            )
        )
    return signals


def _from_requirements(path: Path, relative: str) -> list[Signal]:
    """Signals from a pip requirements file."""
    text = _read_text(path)
    if text is None:
        return []

    signals: list[Signal] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith(_REQUIREMENT_SKIP):
            continue
        match = _REQUIREMENT_RE.match(line)
        if match is None:
            continue
        normalised = _normalise_distribution(match.group(1))
        entry = _PYTHON_PACKAGES.get(normalised)
        if entry is not None:
            signals.append(
                Signal(
                    technology=entry[0],
                    layer=entry[1],
                    source_file=relative,
                    evidence=line,
                )
            )
    return signals


def _from_pyproject(path: Path, relative: str) -> list[Signal]:
    """Signals from PEP 621 dependencies and from Poetry's table."""
    text = _read_text(path)
    if text is None:
        return []
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        log.warning("manifest_unparseable", file=relative)
        return []

    requirement_lines: list[str] = []

    project = data.get("project")
    if isinstance(project, dict):
        for value in project.get("dependencies", []) or []:
            if isinstance(value, str):
                requirement_lines.append(value)
        optional = project.get("optional-dependencies")
        if isinstance(optional, dict):
            for group in optional.values():
                requirement_lines.extend(v for v in group or [] if isinstance(v, str))

    poetry = data.get("tool", {})
    if isinstance(poetry, dict):
        poetry_block = poetry.get("poetry")
        if isinstance(poetry_block, dict):
            deps = poetry_block.get("dependencies")
            if isinstance(deps, dict):
                requirement_lines.extend(str(name) for name in deps)

    signals: list[Signal] = []
    seen: set[tuple[str, str]] = set()
    for line in requirement_lines:
        match = _REQUIREMENT_RE.match(line)
        if match is None:
            continue
        normalised = _normalise_distribution(match.group(1))
        entry = _PYTHON_PACKAGES.get(normalised)
        if entry is None:
            continue
        key = (entry[0], relative)
        if key in seen:
            continue
        seen.add(key)
        signals.append(
            Signal(
                technology=entry[0],
                layer=entry[1],
                source_file=relative,
                evidence=line,
            )
        )
    return signals


def _normalise_distribution(name: str) -> str:
    """PEP 503 normalisation: ``Flask_SQLAlchemy`` and ``flask-sqlalchemy``
    are the same distribution."""
    return re.sub(r"[-_.]+", "-", name).lower()


def _collect(signals: list[Signal], layer: Layer) -> list[str]:
    """Distinct technologies detected for one layer, in a stable order."""
    return sorted({signal.technology for signal in signals if signal.layer is layer})


def _count_languages(files: dict[str, Path]) -> dict[str, int]:
    """File counts per language, most common first."""
    counter: Counter[str] = Counter()
    for relative in files:
        language = _LANGUAGE_EXTENSIONS.get(Path(relative).suffix.lower())
        if language is not None:
            counter[language] += 1
    return dict(counter.most_common())


def _layer_roots(signals: list[Signal], layer: Layer) -> list[str]:
    """Directories that root a layer, derived from where its evidence was found.

    ``frontend/package.json`` declaring React makes ``frontend`` a frontend
    root; a manifest at the top level makes the root ``"."``.
    """
    roots = set()
    for signal in signals:
        if signal.layer is not layer:
            continue
        parent = PurePosixPath(signal.source_file).parent.as_posix()
        roots.add("." if parent in {"", "."} else parent)
    return sorted(roots)


def _looks_like_monorepo(files: dict[str, Path], signals: list[Signal]) -> bool:
    """True only on an explicit workspace declaration.

    Deliberately *not* inferred from "there are two manifests": a
    ``frontend/`` + ``backend/`` split is the single most common shape for the
    projects MergeX targets, and calling that a monorepo would be wrong and
    would mislead the agents about how to pair layers. Layer locations are
    reported separately via :attr:`StackReport.frontend_roots`.
    """
    if any(signal.technology == "Workspaces" for signal in signals):
        return True
    return any(
        path in files
        for path in ("pnpm-workspace.yaml", "lerna.json", "turbo.json", "nx.json", "rush.json")
    )


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _read_json(path: Path) -> dict[str, Any] | None:
    text = _read_text(path)
    if text is None:
        return None
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        # An AI-generated project with a malformed manifest is exactly the
        # case MergeX exists for; note it and carry on with other evidence.
        log.warning("manifest_unparseable", file=str(path))
        return None
    return parsed if isinstance(parsed, dict) else None
