"""Stack detection.

Two halves: synthetic trees that pin down individual rules, and the three
seeded-bug fixtures, whose `expected_findings.json` manifests are the contract
the rest of the pipeline is built against.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest

from app.services.stack_detector import Layer, detect_stack

FIXTURE_NAMES = [
    "react_fastapi_mismatch",
    "react_fastapi_schema_drift",
    "react_fastapi_insecure",
]


def write(root: Path, files: dict[str, str]) -> Path:
    for relative, content in files.items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return root


class TestNpmManifests:
    def test_detects_react_from_dependencies(self, tmp_path: Path) -> None:
        write(tmp_path, {"package.json": json.dumps({"dependencies": {"react": "^18.3.1"}})})

        assert "React" in detect_stack(tmp_path).frontend

    def test_detects_from_dev_dependencies(self, tmp_path: Path) -> None:
        write(tmp_path, {"package.json": json.dumps({"devDependencies": {"vite": "^5.0.0"}})})

        assert "Vite" in detect_stack(tmp_path).build

    @pytest.mark.parametrize(
        ("package", "expected", "layer"),
        [
            ("next", "Next.js", Layer.FRONTEND),
            ("vue", "Vue", Layer.FRONTEND),
            ("@angular/core", "Angular", Layer.FRONTEND),
            ("svelte", "Svelte", Layer.FRONTEND),
            ("express", "Express", Layer.BACKEND),
            ("@nestjs/core", "NestJS", Layer.BACKEND),
            ("fastify", "Fastify", Layer.BACKEND),
            ("@prisma/client", "Prisma", Layer.DATABASE),
            ("drizzle-orm", "Drizzle", Layer.DATABASE),
            ("mongoose", "Mongoose", Layer.DATABASE),
            ("@supabase/supabase-js", "Supabase", Layer.DATABASE),
        ],
    )
    def test_recognises_known_packages(
        self, tmp_path: Path, package: str, expected: str, layer: Layer
    ) -> None:
        write(tmp_path, {"package.json": json.dumps({"dependencies": {package: "1.0.0"}})})
        report = detect_stack(tmp_path)

        bucket = {
            Layer.FRONTEND: report.frontend,
            Layer.BACKEND: report.backend,
            Layer.DATABASE: report.database,
        }[layer]
        assert expected in bucket

    def test_unparseable_manifest_does_not_crash(self, tmp_path: Path) -> None:
        """A malformed manifest is exactly what MergeX exists to analyse."""
        write(tmp_path, {"package.json": "{ this is not json", "vite.config.ts": "export {};"})

        report = detect_stack(tmp_path)

        # Other evidence still contributes.
        assert "Vite" in report.build

    def test_a_manifest_with_no_known_packages_yields_nothing(self, tmp_path: Path) -> None:
        write(tmp_path, {"package.json": json.dumps({"dependencies": {"lodash": "^4"}})})

        assert detect_stack(tmp_path).is_empty


class TestPythonManifests:
    @pytest.mark.parametrize(
        ("line", "expected"),
        [
            ("fastapi==0.111.0", "FastAPI"),
            ("fastapi>=0.100,<1.0", "FastAPI"),
            ("Django==5.0", "Django"),
            ("flask", "Flask"),
            ("uvicorn[standard]==0.30.1", None),
            ("SQLAlchemy==2.0.31", "SQLAlchemy"),
            ("psycopg2-binary==2.9.9", "PostgreSQL"),
        ],
    )
    def test_parses_requirements_lines(
        self, tmp_path: Path, line: str, expected: str | None
    ) -> None:
        write(tmp_path, {"requirements.txt": f"{line}\n"})
        report = detect_stack(tmp_path)

        detected = set(report.backend) | set(report.database)
        if expected is None:
            assert detected == set()
        else:
            assert expected in detected

    def test_ignores_requirements_directives(self, tmp_path: Path) -> None:
        write(
            tmp_path,
            {"requirements.txt": "-r base.txt\n# a comment\n--index-url https://x\nflask\n"},
        )

        assert detect_stack(tmp_path).backend == ["Flask"]

    @pytest.mark.parametrize(
        "spelling",
        ["psycopg2-binary", "psycopg2_binary", "PSYCOPG2.BINARY", "Psycopg2-Binary"],
    )
    def test_normalises_distribution_names(self, tmp_path: Path, spelling: str) -> None:
        """PEP 503 folds runs of -, _ and . and lowercases.

        Note this does *not* make `SQL_Alchemy` equal to `SQLAlchemy`: those
        normalise to different names and are different distributions.
        """
        write(tmp_path, {"requirements.txt": f"{spelling}==2.9.9\n"})

        assert "PostgreSQL" in detect_stack(tmp_path).database

    def test_reads_pep621_dependencies(self, tmp_path: Path) -> None:
        write(
            tmp_path,
            {
                "pyproject.toml": (
                    '[project]\nname = "svc"\ndependencies = ["fastapi>=0.111", "asyncpg"]\n'
                )
            },
        )
        report = detect_stack(tmp_path)

        assert "FastAPI" in report.backend
        assert "PostgreSQL" in report.database

    def test_reads_poetry_dependencies(self, tmp_path: Path) -> None:
        write(
            tmp_path,
            {"pyproject.toml": ('[tool.poetry.dependencies]\npython = "^3.11"\ndjango = "^5.0"\n')},
        )

        assert "Django" in detect_stack(tmp_path).backend

    def test_unparseable_pyproject_does_not_crash(self, tmp_path: Path) -> None:
        write(tmp_path, {"pyproject.toml": "[project\nbroken", "manage.py": "pass\n"})

        assert "Django" in detect_stack(tmp_path).backend


class TestMarkerFiles:
    @pytest.mark.parametrize(
        ("marker", "expected"),
        [
            ("next.config.js", "Next.js"),
            ("angular.json", "Angular"),
            ("prisma/schema.prisma", "Prisma"),
            ("alembic.ini", "Alembic"),
            ("manage.py", "Django"),
            ("drizzle.config.ts", "Drizzle"),
            ("supabase/config.toml", "Supabase"),
        ],
    )
    def test_detects_from_marker_files_alone(
        self, tmp_path: Path, marker: str, expected: str
    ) -> None:
        """A project with no manifest is still identifiable."""
        write(tmp_path, {marker: "// marker\n"})
        report = detect_stack(tmp_path)

        detected = set(report.frontend) | set(report.backend) | set(report.database)
        assert expected in detected

    def test_marker_evidence_is_lower_confidence_than_a_dependency(self, tmp_path: Path) -> None:
        write(tmp_path, {"next.config.js": "module.exports = {};"})

        marker_signal = next(s for s in detect_stack(tmp_path).signals if s.technology == "Next.js")

        assert marker_signal.confidence < 1.0


class TestPackageManagers:
    @pytest.mark.parametrize(
        ("lockfile", "expected"),
        [
            ("package-lock.json", "npm"),
            ("yarn.lock", "yarn"),
            ("pnpm-lock.yaml", "pnpm"),
            ("poetry.lock", "poetry"),
            ("uv.lock", "uv"),
            ("requirements.txt", "pip"),
        ],
    )
    def test_detects_from_lockfiles(self, tmp_path: Path, lockfile: str, expected: str) -> None:
        write(tmp_path, {lockfile: ""})

        assert expected in detect_stack(tmp_path).package_managers

    def test_assumes_npm_when_a_manifest_has_no_lockfile(self, tmp_path: Path) -> None:
        """Common in AI-generated repos, where the lockfile is never committed."""
        write(tmp_path, {"package.json": json.dumps({"dependencies": {"react": "^18"}})})

        assert detect_stack(tmp_path).package_managers == ["npm"]

    def test_a_real_lockfile_wins_over_the_assumption(self, tmp_path: Path) -> None:
        write(
            tmp_path,
            {
                "package.json": json.dumps({"dependencies": {"react": "^18"}}),
                "pnpm-lock.yaml": "",
            },
        )

        assert detect_stack(tmp_path).package_managers == ["pnpm"]


class TestMonorepoAndLayout:
    def test_a_frontend_backend_split_is_not_a_monorepo(self, tmp_path: Path) -> None:
        """The most common shape MergeX sees. Calling it a monorepo is wrong."""
        write(
            tmp_path,
            {
                "frontend/package.json": json.dumps({"dependencies": {"react": "^18"}}),
                "backend/requirements.txt": "fastapi==0.111.0\n",
            },
        )
        report = detect_stack(tmp_path)

        assert report.is_monorepo is False
        assert report.frontend_roots == ["frontend"]
        assert report.backend_roots == ["backend"]

    def test_declared_workspaces_make_it_a_monorepo(self, tmp_path: Path) -> None:
        write(tmp_path, {"package.json": json.dumps({"workspaces": ["packages/*"]})})

        assert detect_stack(tmp_path).is_monorepo is True

    @pytest.mark.parametrize("marker", ["pnpm-workspace.yaml", "turbo.json", "nx.json"])
    def test_workspace_markers_make_it_a_monorepo(self, tmp_path: Path, marker: str) -> None:
        write(tmp_path, {marker: "{}"})

        assert detect_stack(tmp_path).is_monorepo is True

    def test_root_level_manifest_reports_dot_as_its_root(self, tmp_path: Path) -> None:
        write(tmp_path, {"package.json": json.dumps({"dependencies": {"react": "^18"}})})

        assert detect_stack(tmp_path).frontend_roots == ["."]


class TestLanguagesAndPruning:
    def test_counts_languages_by_extension(self, tmp_path: Path) -> None:
        write(
            tmp_path,
            {
                "a.ts": "",
                "b.tsx": "",
                "c.py": "",
                "d.sql": "",
                "e.unknown": "",
            },
        )

        languages = detect_stack(tmp_path).languages

        assert languages["TypeScript"] == 2
        assert languages["Python"] == 1
        assert languages["SQL"] == 1
        assert "e.unknown" not in languages

    def test_ignores_dependency_directories(self, tmp_path: Path) -> None:
        """node_modules would otherwise dominate both counts and detection."""
        write(
            tmp_path,
            {
                "src/app.ts": "",
                "node_modules/express/index.js": "",
                "node_modules/express/package.json": json.dumps({"dependencies": {"express": "4"}}),
                ".venv/lib/django/__init__.py": "",
            },
        )
        report = detect_stack(tmp_path)

        # Express lives only in node_modules, so it must not be reported.
        assert report.backend == []
        assert report.languages.get("TypeScript") == 1

    def test_an_empty_tree_is_empty(self, tmp_path: Path) -> None:
        report = detect_stack(tmp_path)

        assert report.is_empty
        assert report.languages == {}


class TestSerialisation:
    def test_to_dict_round_trips_as_json(self, tmp_path: Path) -> None:
        write(tmp_path, {"package.json": json.dumps({"dependencies": {"react": "^18"}})})

        payload = detect_stack(tmp_path).to_dict()

        assert json.loads(json.dumps(payload)) == payload

    def test_to_dict_retains_evidence(self, tmp_path: Path) -> None:
        """Phase 2 needs to know which file proved each conclusion."""
        write(tmp_path, {"package.json": json.dumps({"dependencies": {"react": "^18.3.1"}})})

        signals = detect_stack(tmp_path).to_dict()["signals"]
        react = next(s for s in signals if s["technology"] == "React")

        assert react["source_file"] == "package.json"
        assert "react" in react["evidence"]


class TestSeededFixtures:
    """The three fixture repos must be identified exactly as their manifests say."""

    @pytest.mark.parametrize("name", FIXTURE_NAMES)
    def test_matches_the_fixture_manifest(
        self, name: str, fixture_repo: Callable[[str], Path]
    ) -> None:
        root = fixture_repo(name)
        expected = json.loads((root / "expected_findings.json").read_text(encoding="utf-8"))[
            "stack"
        ]

        report = detect_stack(root)

        assert report.frontend == expected["frontend"]
        assert report.backend == expected["backend"]
        assert report.database == expected["database"]
        assert report.package_managers == expected["package_managers"]
        assert report.frontend_roots == expected["frontend_roots"]
        assert report.backend_roots == expected["backend_roots"]
        assert report.is_monorepo == expected["is_monorepo"]
        for language in expected["languages_include"]:
            assert language in report.languages, f"{language} not detected in {name}"

    @pytest.mark.parametrize("name", FIXTURE_NAMES)
    def test_every_conclusion_cites_a_real_file(
        self, name: str, fixture_repo: Callable[[str], Path]
    ) -> None:
        """No finding may cite evidence that does not exist on disk."""
        root = fixture_repo(name)

        for signal in detect_stack(root).signals:
            assert (root / signal.source_file).is_file(), signal
