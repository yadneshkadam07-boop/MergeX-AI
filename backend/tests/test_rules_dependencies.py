"""Dependency vulnerability rule and manifest parsing.

The precision decision under test: only *exactly-pinned* versions are checked.
A range like ``^1.6.0`` resolves to whatever was installed, which this
analysis cannot know, and reporting the range's lower bound would flag
projects that are already patched.

The degradation tests matter as much: an unreachable OSV must produce a clear
note and no findings, never an exception and never a silently clean result.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.analysis.rules.dependencies import (
    DependencyInput,
    parse_dependency_manifests,
    run_dependency_rules,
)
from app.models.enums import Severity
from app.services.osv import StaticVulnerabilityClient, Vulnerability

PYYAML_ADVISORY = Vulnerability(
    id="GHSA-8q59-q68h-6hv4",
    summary="Arbitrary code execution via full_load.",
    severity=Severity.CRITICAL,
    aliases=("CVE-2020-14343",),
    fixed_versions=("5.4",),
)


def write(root: Path, files: dict[str, str]) -> Path:
    for relative, content in files.items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return root


def client(**kwargs: object) -> StaticVulnerabilityClient:
    return StaticVulnerabilityClient(
        {("PyPI", "pyyaml", "5.3.1"): (PYYAML_ADVISORY,)},
        **kwargs,  # type: ignore[arg-type]
    )


class TestManifestParsing:
    def test_reads_pinned_requirements(self, tmp_path: Path) -> None:
        write(tmp_path, {"requirements.txt": "fastapi==0.111.0\nPyYAML==5.3.1\n"})

        scan = parse_dependency_manifests(tmp_path)

        assert [(d.name, d.version) for d in scan.pinned] == [
            ("fastapi", "0.111.0"),
            ("PyYAML", "5.3.1"),
        ]

    def test_records_the_line_of_each_pin(self, tmp_path: Path) -> None:
        write(tmp_path, {"requirements.txt": "# header\nfastapi==0.111.0\n\nPyYAML==5.3.1\n"})

        scan = parse_dependency_manifests(tmp_path)

        assert [d.location.line_start for d in scan.pinned] == [2, 4]

    def test_handles_extras_and_comments(self, tmp_path: Path) -> None:
        write(tmp_path, {"requirements.txt": "uvicorn[standard]==0.30.1  # server\n"})

        scan = parse_dependency_manifests(tmp_path)

        assert [(d.name, d.version) for d in scan.pinned] == [("uvicorn", "0.30.1")]

    @pytest.mark.parametrize(
        "line",
        ["fastapi>=0.100", "fastapi<=1.0", "fastapi~=0.111", "fastapi>0.1", "fastapi!=0.5"],
    )
    def test_ranges_are_counted_not_pinned(self, tmp_path: Path, line: str) -> None:
        """A range cannot be resolved without a lockfile."""
        write(tmp_path, {"requirements.txt": f"{line}\n"})

        scan = parse_dependency_manifests(tmp_path)

        assert scan.pinned == []
        assert scan.ranged_count == 1

    def test_skips_directives_and_urls(self, tmp_path: Path) -> None:
        write(
            tmp_path,
            {
                "requirements.txt": (
                    "-r base.txt\n"
                    "--index-url https://pypi.org/simple\n"
                    "git+https://github.com/org/repo.git\n"
                    "# a comment\n"
                    "PyYAML==5.3.1\n"
                )
            },
        )

        scan = parse_dependency_manifests(tmp_path)

        assert len(scan.pinned) == 1

    def test_reads_exact_npm_pins(self, tmp_path: Path) -> None:
        write(
            tmp_path,
            {
                "package.json": (
                    '{"dependencies": {"axios": "1.6.0", "react": "^18.3.1"},'
                    ' "devDependencies": {"vite": "4.5.2"}}'
                )
            },
        )

        scan = parse_dependency_manifests(tmp_path)

        assert sorted((d.name, d.version) for d in scan.pinned) == [
            ("axios", "1.6.0"),
            ("vite", "4.5.2"),
        ]
        assert scan.ranged_count == 1

    def test_npm_pins_report_their_declaration_line(self, tmp_path: Path) -> None:
        """Not the line of a script that merely mentions the package name."""
        write(
            tmp_path,
            {
                "package.json": (
                    "{\n"
                    '  "scripts": { "dev": "vite", "build": "vite build" },\n'
                    '  "devDependencies": {\n'
                    '    "vite": "4.5.2"\n'
                    "  }\n"
                    "}\n"
                )
            },
        )

        scan = parse_dependency_manifests(tmp_path)

        assert scan.pinned[0].location.line_start == 4

    def test_an_unparseable_package_json_is_skipped(self, tmp_path: Path) -> None:
        write(tmp_path, {"package.json": "{ not json"})

        assert parse_dependency_manifests(tmp_path).pinned == []

    def test_unrelated_text_files_are_ignored(self, tmp_path: Path) -> None:
        write(tmp_path, {"notes.txt": "fastapi==0.111.0\n"})

        assert parse_dependency_manifests(tmp_path).pinned == []

    def test_ecosystems_are_labelled(self, tmp_path: Path) -> None:
        write(
            tmp_path,
            {
                "requirements.txt": "PyYAML==5.3.1\n",
                "package.json": '{"dependencies": {"axios": "1.6.0"}}',
            },
        )

        scan = parse_dependency_manifests(tmp_path)

        assert {d.ecosystem for d in scan.pinned} == {"PyPI", "npm"}


class TestVulnerabilityFindings:
    async def test_reports_a_vulnerable_pin(self, tmp_path: Path) -> None:
        write(tmp_path, {"requirements.txt": "PyYAML==5.3.1\n"})

        findings, note = await run_dependency_rules(DependencyInput(root=tmp_path, client=client()))

        assert [finding.rule_id for finding in findings] == ["MX-DEP-001"]
        assert note is None

    async def test_severity_comes_from_the_advisory(self, tmp_path: Path) -> None:
        write(tmp_path, {"requirements.txt": "PyYAML==5.3.1\n"})

        findings, _ = await run_dependency_rules(DependencyInput(root=tmp_path, client=client()))

        assert findings[0].severity is Severity.CRITICAL

    async def test_the_finding_names_the_cve_and_the_fix(self, tmp_path: Path) -> None:
        write(tmp_path, {"requirements.txt": "PyYAML==5.3.1\n"})

        findings, _ = await run_dependency_rules(DependencyInput(root=tmp_path, client=client()))
        finding = findings[0]

        assert "CVE-2020-14343" in finding.description
        assert finding.expected == "PyYAML==5.4 or later"
        assert finding.actual == "PyYAML==5.3.1"
        assert finding.metadata["fixed_versions"] == ["5.4"]

    async def test_the_finding_points_at_the_manifest_line(self, tmp_path: Path) -> None:
        write(tmp_path, {"requirements.txt": "fastapi==0.111.0\nPyYAML==5.3.1\n"})

        findings, _ = await run_dependency_rules(DependencyInput(root=tmp_path, client=client()))

        assert findings[0].primary_location.line_start == 2
        assert "PyYAML" in findings[0].primary_location.snippet

    async def test_a_clean_pin_is_silent(self, tmp_path: Path) -> None:
        write(tmp_path, {"requirements.txt": "sqlalchemy==2.0.31\n"})

        findings, note = await run_dependency_rules(DependencyInput(root=tmp_path, client=client()))

        assert findings == []
        assert note is None

    async def test_ranges_produce_a_note(self, tmp_path: Path) -> None:
        write(tmp_path, {"requirements.txt": "PyYAML==5.3.1\nflask>=2.0\n"})

        _, note = await run_dependency_rules(DependencyInput(root=tmp_path, client=client()))

        assert note is not None
        assert "version ranges" in note

    async def test_only_ranges_produces_a_note_and_no_findings(self, tmp_path: Path) -> None:
        write(tmp_path, {"requirements.txt": "flask>=2.0\n"})

        findings, note = await run_dependency_rules(DependencyInput(root=tmp_path, client=client()))

        assert findings == []
        assert note is not None
        assert "lockfile" in note

    async def test_no_manifests_is_quiet(self, tmp_path: Path) -> None:
        findings, note = await run_dependency_rules(DependencyInput(root=tmp_path, client=client()))

        assert findings == []
        assert note is None

    async def test_one_finding_per_package_not_per_advisory(self, tmp_path: Path) -> None:
        """Two advisories against one pin are one upgrade, so one finding."""
        second = Vulnerability(id="GHSA-other", summary="Another issue.", severity=Severity.MEDIUM)
        multi = StaticVulnerabilityClient({("PyPI", "pyyaml", "5.3.1"): (PYYAML_ADVISORY, second)})
        write(tmp_path, {"requirements.txt": "PyYAML==5.3.1\n"})

        findings, _ = await run_dependency_rules(DependencyInput(root=tmp_path, client=multi))

        assert len(findings) == 1
        assert len(findings[0].metadata["advisories"]) == 2
        # The worst severity wins.
        assert findings[0].severity is Severity.CRITICAL


class TestGracefulDegradation:
    async def test_an_unreachable_lookup_produces_a_note_not_an_error(self, tmp_path: Path) -> None:
        write(tmp_path, {"requirements.txt": "PyYAML==5.3.1\n"})
        offline = StaticVulnerabilityClient(
            degraded=True, degraded_reason="ConnectError: name resolution failed"
        )

        findings, note = await run_dependency_rules(DependencyInput(root=tmp_path, client=offline))

        assert findings == []
        assert note is not None
        assert "unavailable" in note
        assert "name resolution failed" in note

    async def test_the_note_says_how_many_went_unchecked(self, tmp_path: Path) -> None:
        """A silently clean result would be a lie."""
        write(tmp_path, {"requirements.txt": "PyYAML==5.3.1\nflask==2.0.0\n"})
        offline = StaticVulnerabilityClient(degraded=True, degraded_reason="timeout")

        _, note = await run_dependency_rules(DependencyInput(root=tmp_path, client=offline))

        assert note is not None
        assert "2 pinned dependencies were not checked" in note

    async def test_an_advisory_with_no_details_is_still_reported(self, tmp_path: Path) -> None:
        partial = Vulnerability(
            id="GHSA-partial",
            summary="Advisory details could not be retrieved.",
            severity=Severity.HIGH,
            details_available=False,
        )
        write(tmp_path, {"requirements.txt": "PyYAML==5.3.1\n"})

        findings, _ = await run_dependency_rules(
            DependencyInput(
                root=tmp_path,
                client=StaticVulnerabilityClient({("PyPI", "pyyaml", "5.3.1"): (partial,)}),
            )
        )

        assert len(findings) == 1
        assert findings[0].metadata["details_incomplete"] is True
        assert "assumed rather than read" in findings[0].description


class TestFindingShape:
    async def test_the_finding_carries_everything_the_schema_needs(self, tmp_path: Path) -> None:
        write(tmp_path, {"requirements.txt": "PyYAML==5.3.1\n"})

        findings, _ = await run_dependency_rules(DependencyInput(root=tmp_path, client=client()))
        finding = findings[0]

        assert finding.primary_location.file_path == "requirements.txt"
        assert finding.evidence.strip()
        assert finding.expected and finding.actual
        assert finding.fingerprint
        assert 0.0 < finding.confidence <= 1.0

    async def test_the_fingerprint_is_the_package_version(self, tmp_path: Path) -> None:
        """So the same vulnerable pin in two manifests is one finding."""
        write(
            tmp_path,
            {
                "a/requirements.txt": "PyYAML==5.3.1\n",
                "b/requirements.txt": "PyYAML==5.3.1\n",
            },
        )

        findings, _ = await run_dependency_rules(DependencyInput(root=tmp_path, client=client()))

        assert len({finding.fingerprint for finding in findings}) == 1

    def test_the_rule_is_registered(self) -> None:
        from app.analysis.taxonomy import REGISTRY

        assert "MX-DEP-001" in REGISTRY
