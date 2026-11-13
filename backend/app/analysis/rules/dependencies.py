"""Dependency vulnerability rule (``MX-DEP-001``).

**Only exactly-pinned versions are checked.** A range such as ``^1.6.0``
resolves to whatever npm installed, which without a lockfile this analysis
cannot know. Reporting the range's lower bound would flag projects that are
already patched -- a false positive on correct code, which is the one failure
mode this engine refuses. Ranges are counted and reported as *skipped* so the
number is visible rather than silently missing.

The lookup goes through :class:`app.services.osv.VulnerabilityClient`, so a
degraded or unreachable OSV produces a clear note and no findings, never an
exception.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from app.analysis.findings import Finding, make_finding
from app.core.logging import get_logger
from app.models.enums import Severity
from app.services.osv import PackageQuery, Vulnerability, VulnerabilityClient
from app.services.parsers.base import SourceFile, SourceLocation, iter_source_files

__all__ = [
    "DependencyInput",
    "PinnedDependency",
    "parse_dependency_manifests",
    "run_dependency_rules",
]

log = get_logger("app.analysis.dependencies")

_MANIFEST_SUFFIXES: Final[frozenset[str]] = frozenset({".txt", ".json"})
_REQUIREMENTS_NAMES: Final[tuple[str, ...]] = ("requirements", "requirements-dev", "constraints")

# `package==1.2.3`, with optional extras and trailing comment.
_PINNED_REQUIREMENT_RE: Final[re.Pattern[str]] = re.compile(
    r"^\s*(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)"
    r"(?:\[[^\]]*\])?"
    r"\s*==\s*"
    r"(?P<version>[A-Za-z0-9][A-Za-z0-9.\-+!]*)"
    r"\s*(?:[;#].*)?$"
)
# A requirement with any other operator: a range, not a pin.
_RANGED_REQUIREMENT_RE: Final[re.Pattern[str]] = re.compile(
    r"^\s*[A-Za-z0-9][A-Za-z0-9._-]*(?:\[[^\]]*\])?\s*(?:>=|<=|~=|>|<|!=)"
)
# An npm version that is an exact pin rather than a range.
_EXACT_NPM_VERSION_RE: Final[re.Pattern[str]] = re.compile(r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.\-]+)?$")


@dataclass(frozen=True, slots=True)
class PinnedDependency:
    """One exactly-pinned dependency, with where it is declared."""

    ecosystem: str
    name: str
    version: str
    location: SourceLocation

    @property
    def query(self) -> PackageQuery:
        return PackageQuery(ecosystem=self.ecosystem, name=self.name, version=self.version)


@dataclass(slots=True)
class DependencyInput:
    """Everything the dependency rule needs."""

    root: Path
    client: VulnerabilityClient
    subdirectories: tuple[str, ...] = ()


_LOCKFILES: Final[frozenset[str]] = frozenset(
    {
        "package-lock.json",
        "npm-shrinkwrap.json",
        "yarn.lock",
        "pnpm-lock.yaml",
        "bun.lockb",
        "bun.lock",
    }
)


@dataclass(slots=True)
class _ManifestScan:
    pinned: list[PinnedDependency] = field(default_factory=list)
    ranged_count: int = 0
    manifests: list[str] = field(default_factory=list)
    manifest_sources: list[tuple[SourceFile, str]] = field(default_factory=list)


async def run_dependency_rules(data: DependencyInput) -> tuple[list[Finding], str | None]:
    """Run the dependency rules (MX-DEP-001 and MX-DEP-002).

    Returns:
        ``(findings, note)``. ``note`` is a human-readable caveat when the
        check could not be completed -- an unreachable OSV, ranges that could
        not be resolved -- and None when it ran cleanly. The caller surfaces
        it rather than letting an incomplete check look like a clean one.
    """
    scan = parse_dependency_manifests(data.root, subdirectories=data.subdirectories)
    findings: list[Finding] = []

    # MX-DEP-002: Missing lockfile check
    findings.extend(_check_missing_lockfiles(data.root, scan.manifest_sources))

    notes: list[str] = []

    if scan.pinned:
        report = await data.client.query([dependency.query for dependency in scan.pinned])
        if report.degraded and not report.findings:
            notes.append(
                f"Dependency vulnerability lookup unavailable ({report.degraded_reason}). "
                f"{len(scan.pinned)} pinned dependencies were not checked."
            )
        else:
            for dependency in scan.pinned:
                vulnerabilities = report.for_package(dependency.query)
                if vulnerabilities:
                    findings.append(_dependency_finding(dependency, vulnerabilities))
            if report.degraded:
                notes.append(f"the lookup was incomplete ({report.degraded_reason})")
    elif scan.ranged_count:
        notes.append(
            f"No exactly-pinned dependencies to check: {scan.ranged_count} use "
            f"version ranges, which cannot be resolved without a lockfile"
        )

    if scan.ranged_count and scan.pinned:
        notes.append(
            f"{scan.ranged_count} dependencies use version ranges and were skipped; "
            f"commit a lockfile to have them checked"
        )

    log.info(
        "dependency_rules_complete",
        pinned=len(scan.pinned),
        ranged=scan.ranged_count,
        vulnerable=len(findings),
    )
    return (findings, "; ".join(notes).capitalize() + "." if notes else None)


def _check_missing_lockfiles(
    root: Path, manifest_sources: list[tuple[SourceFile, str]]
) -> list[Finding]:
    """Flag manifests that declare dependencies but lack a lockfile (MX-DEP-002)."""
    findings: list[Finding] = []
    for source, manifest_type in manifest_sources:
        if manifest_type == "npm":
            manifest_path = root / source.relative_path
            curr_dir = manifest_path.parent
            has_lock = False
            while True:
                if any((curr_dir / lock).is_file() for lock in _LOCKFILES):
                    has_lock = True
                    break
                if curr_dir == root or curr_dir.parent == curr_dir:
                    break
                curr_dir = curr_dir.parent

            if not has_lock:
                findings.append(
                    make_finding(
                        "MX-DEP-002",
                        identity=("npm", source.relative_path, "missing_lockfile"),
                        locations=[source.location(1)],
                        title=f"Package manifest {source.relative_path} is missing a lockfile",
                        description=(
                            f"{source.relative_path} declares dependencies but no lockfile "
                            f"(package-lock.json, yarn.lock, pnpm-lock.yaml) exists in its directory or repository root. "
                            f"Without a lockfile, CI/CD installs resolve floating versions nondeterministically."
                        ),
                        expected="package-lock.json, yarn.lock, or pnpm-lock.yaml committed alongside package.json",
                        actual=f"No lockfile present for {source.relative_path}",
                        severity=Severity.HIGH,
                        metadata={"manifest": source.relative_path, "ecosystem": "npm"},
                    )
                )
    return findings


def _dependency_finding(
    dependency: PinnedDependency, vulnerabilities: tuple[Vulnerability, ...]
) -> Finding:
    """One finding per vulnerable package, listing every advisory against it."""
    worst = _worst_severity(vulnerabilities)
    identifiers = [vulnerability.best_identifier for vulnerability in vulnerabilities]
    fixes = sorted(
        {version for vulnerability in vulnerabilities for version in vulnerability.fixed_versions}
    )
    partial = [v for v in vulnerabilities if not v.details_available]

    advisory_list = ", ".join(identifiers[:6])
    if len(identifiers) > 6:
        advisory_list += f" and {len(identifiers) - 6} more"

    summary = next(
        (v.summary for v in vulnerabilities if v.details_available and v.summary),
        "See the advisory for details.",
    )
    fix_text = (
        f" Fixed in {', '.join(fixes[:4])}." if fixes else " No fixed version is published yet."
    )
    caveat = (
        f" Details could not be retrieved for {len(partial)} of these advisories, so "
        f"their severity is assumed rather than read."
        if partial
        else ""
    )

    return make_finding(
        "MX-DEP-001",
        identity=(dependency.ecosystem, dependency.name.lower(), dependency.version),
        locations=[dependency.location],
        title=f"{dependency.name} {dependency.version} has a known vulnerability",
        description=(
            f"{dependency.name} is pinned to {dependency.version}, which has "
            f"{len(vulnerabilities)} published "
            f"{'advisory' if len(vulnerabilities) == 1 else 'advisories'} "
            f"({advisory_list}). {summary}{fix_text}{caveat}"
        ),
        expected=(
            f"{dependency.name}=={fixes[0]} or later"
            if fixes
            else f"A patched release of {dependency.name}"
        ),
        actual=f"{dependency.name}=={dependency.version}",
        severity=worst,
        metadata={
            "ecosystem": dependency.ecosystem,
            "package": dependency.name,
            "version": dependency.version,
            "advisories": identifiers,
            "osv_ids": [vulnerability.id for vulnerability in vulnerabilities],
            "fixed_versions": fixes,
            "details_incomplete": bool(partial),
        },
    )


def _worst_severity(vulnerabilities: tuple[Vulnerability, ...]) -> Severity:
    rank = {
        Severity.CRITICAL: 0,
        Severity.HIGH: 1,
        Severity.MEDIUM: 2,
        Severity.LOW: 3,
    }
    return min((v.severity for v in vulnerabilities), key=lambda s: rank[s])


# ---------------------------------------------------------------------------
# Manifest parsing
# ---------------------------------------------------------------------------


def parse_dependency_manifests(
    root: Path, *, subdirectories: tuple[str, ...] = ()
) -> _ManifestScan:
    """Find exactly-pinned dependencies under ``root``.

    Kept here rather than in ``app.services.extractors`` because it exists
    solely to feed this rule and has no other consumer; splitting it out would
    add a module without adding a seam.
    """
    scan = _ManifestScan()
    search_roots = [root / sub for sub in subdirectories] if subdirectories else [root]

    sources: list[SourceFile] = []
    for search_root in search_roots:
        if not search_root.is_dir():
            continue
        for source in iter_source_files(search_root, _MANIFEST_SUFFIXES):
            sources.append(_rebase(source, root, search_root))

    for source in sorted(sources, key=lambda item: item.relative_path):
        stem = Path(source.relative_path).stem
        name = Path(source.relative_path).name

        if source.suffix == ".txt" and stem in _REQUIREMENTS_NAMES:
            scan.manifests.append(source.relative_path)
            _parse_requirements(source, scan)
        elif name == "package.json":
            scan.manifests.append(source.relative_path)
            _parse_package_json(source, scan)

    log.info(
        "dependency_manifests_parsed",
        manifests=len(scan.manifests),
        pinned=len(scan.pinned),
        ranged=scan.ranged_count,
    )
    return scan


def _rebase(source: SourceFile, root: Path, search_root: Path) -> SourceFile:
    if search_root == root:
        return source
    try:
        prefix = search_root.relative_to(root).as_posix()
    except ValueError:  # pragma: no cover - defensive
        return source
    return SourceFile(
        relative_path=f"{prefix}/{source.relative_path}",
        text=source.text,
        lines=source.lines,
    )


def _parse_requirements(source: SourceFile, scan: _ManifestScan) -> None:
    for index, raw in enumerate(source.lines, start=1):
        line = raw.strip()
        if not line or line.startswith(("#", "-", "git+", "http")):
            continue

        pinned = _PINNED_REQUIREMENT_RE.match(line)
        if pinned is not None:
            scan.pinned.append(
                PinnedDependency(
                    ecosystem="PyPI",
                    name=pinned.group("name"),
                    version=pinned.group("version"),
                    location=source.location(index),
                )
            )
            continue

        if _RANGED_REQUIREMENT_RE.match(line):
            scan.ranged_count += 1


def _parse_package_json(source: SourceFile, scan: _ManifestScan) -> None:
    try:
        payload = json.loads(source.text)
    except json.JSONDecodeError:
        log.debug("package_json_unparseable", file=source.relative_path)
        return
    if not isinstance(payload, dict):
        return

    has_any_deps = False
    for section in ("dependencies", "devDependencies", "optionalDependencies"):
        block = payload.get(section)
        if not isinstance(block, dict):
            continue
        for name, raw_version in sorted(block.items()):
            if not isinstance(name, str) or not isinstance(raw_version, str):
                continue
            has_any_deps = True
            if _EXACT_NPM_VERSION_RE.match(raw_version.strip()):
                scan.pinned.append(
                    PinnedDependency(
                        ecosystem="npm",
                        name=name,
                        version=raw_version.strip(),
                        location=source.location(_line_of(source, name)),
                    )
                )
            else:
                scan.ranged_count += 1

    if has_any_deps:
        scan.manifest_sources.append((source, "npm"))


def _line_of(source: SourceFile, package_name: str) -> int:
    """The line a package is declared on, for the finding's location.

    Matches the *key* form ``"name":``. Searching for ``"name"`` alone matches
    a script body too -- ``"dev": "vite"`` is a value, not the declaration of
    the ``vite`` dependency -- and would point the finding at the wrong line.
    """
    needle = f'"{package_name}":'
    for index, line in enumerate(source.lines, start=1):
        if needle in line:
            return index
    return 1
