"""Vulnerability lookup against OSV.dev, behind an interface.

Three requirements shape this module:

**It must never fail an analysis.** OSV is a third-party service on the public
internet. If it is slow, rate-limiting, returning garbage or simply down, the
analysis continues and reports every other finding; the dependency check
reports itself as *degraded* with a reason the user can read. An outage at
osv.dev must not turn into "MergeX is broken".

**It must be substitutable.** :class:`VulnerabilityClient` is a protocol, so
tests inject a recorded response and never touch the network, and a future
offline mode can supply a local database.

**It must not over-claim.** OSV's ``querybatch`` returns only advisory *IDs*;
details need a second request per advisory. Both stages are bounded, and
whatever could not be fetched is reported as degraded rather than silently
treated as "no vulnerabilities".
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Final, Protocol

import httpx

from app.core.logging import get_logger
from app.models.enums import Severity

__all__ = [
    "OsvClient",
    "PackageQuery",
    "StaticVulnerabilityClient",
    "Vulnerability",
    "VulnerabilityClient",
    "VulnerabilityReport",
]

log = get_logger("app.osv")

# OSV accepts large batches, but a smaller one fails more gracefully and keeps
# any single request short.
_BATCH_SIZE: Final[int] = 100
# Advisories to fetch details for. A project with more than this many distinct
# advisories has a dependency problem the exact details will not change.
_MAX_DETAIL_FETCHES: Final[int] = 60
_DETAIL_CONCURRENCY: Final[int] = 8

# GitHub advisory severities, which OSV passes through in database_specific.
_GHSA_SEVERITIES: Final[dict[str, Severity]] = {
    "CRITICAL": Severity.CRITICAL,
    "HIGH": Severity.HIGH,
    "MODERATE": Severity.MEDIUM,
    "MEDIUM": Severity.MEDIUM,
    "LOW": Severity.LOW,
}


@dataclass(frozen=True, slots=True)
class PackageQuery:
    """One package version to look up."""

    ecosystem: str
    """OSV ecosystem name: ``PyPI``, ``npm``, ``Go``, …"""
    name: str
    version: str

    def as_payload(self) -> dict[str, Any]:
        return {
            "package": {"name": self.name, "ecosystem": self.ecosystem},
            "version": self.version,
        }

    def __str__(self) -> str:
        return f"{self.name}@{self.version} ({self.ecosystem})"


@dataclass(frozen=True, slots=True)
class Vulnerability:
    """One advisory affecting a package version."""

    id: str
    summary: str
    severity: Severity
    aliases: tuple[str, ...] = ()
    fixed_versions: tuple[str, ...] = ()
    reference_url: str | None = None
    details_available: bool = True
    """False when only the ID was retrieved.

    The advisory is still real -- it came from OSV -- but its summary and
    severity could not be fetched, so the rule should not claim them.
    """

    @property
    def best_identifier(self) -> str:
        """A CVE where one exists, else the OSV ID.

        Users recognise CVEs; ``GHSA-xxxx-xxxx-xxxx`` means less to most
        people even though it is often the more precise record.
        """
        for alias in self.aliases:
            if alias.startswith("CVE-"):
                return alias
        return self.id


@dataclass(slots=True)
class VulnerabilityReport:
    """The result of a lookup, including whether it was complete."""

    findings: dict[PackageQuery, tuple[Vulnerability, ...]] = field(default_factory=dict)
    degraded: bool = False
    degraded_reason: str | None = None
    queried_count: int = 0

    @property
    def vulnerable_count(self) -> int:
        return sum(1 for vulns in self.findings.values() if vulns)

    def for_package(self, query: PackageQuery) -> tuple[Vulnerability, ...]:
        return self.findings.get(query, ())


class VulnerabilityClient(Protocol):
    """How vulnerabilities get looked up.

    A protocol so the rule engine never depends on HTTP, OSV, or the network
    being reachable.
    """

    async def query(self, packages: Sequence[PackageQuery]) -> VulnerabilityReport: ...


class StaticVulnerabilityClient:
    """A client that answers from a fixed table. For tests and offline runs.

    Using this in tests rather than patching ``httpx`` means the tests
    exercise the same code path the rule uses in production, and they cannot
    accidentally hit the network.
    """

    def __init__(
        self,
        table: Mapping[tuple[str, str, str], tuple[Vulnerability, ...]] | None = None,
        *,
        degraded: bool = False,
        degraded_reason: str | None = None,
    ) -> None:
        self._table: Mapping[tuple[str, str, str], tuple[Vulnerability, ...]] = table or {}
        self._degraded = degraded
        self._degraded_reason = degraded_reason
        self.calls: list[list[PackageQuery]] = []

    async def query(self, packages: Sequence[PackageQuery]) -> VulnerabilityReport:
        self.calls.append(list(packages))
        if self._degraded:
            return VulnerabilityReport(
                degraded=True,
                degraded_reason=self._degraded_reason or "lookup unavailable",
                queried_count=len(packages),
            )
        return VulnerabilityReport(
            findings={
                package: self._table.get(
                    (package.ecosystem, package.name.lower(), package.version), ()
                )
                for package in packages
            },
            queried_count=len(packages),
        )


class OsvClient:
    """Queries https://osv.dev.

    Args:
        api_url: The ``querybatch`` endpoint.
        timeout: Per-request timeout in seconds.
        client: An existing ``httpx.AsyncClient`` to reuse. When omitted one
            is created per call, which is fine for a single analysis run.
    """

    def __init__(
        self,
        *,
        api_url: str = "https://api.osv.dev/v1/querybatch",
        timeout: float = 20.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._api_url = api_url
        self._timeout = timeout
        self._client = client
        self._details_url = api_url.rsplit("/", 1)[0] + "/vulns"

    async def query(self, packages: Sequence[PackageQuery]) -> VulnerabilityReport:
        """Look up every package, degrading rather than raising.

        Returns:
            A report. ``degraded`` is True if any part of the lookup failed;
            whatever *was* retrieved is still included, because partial
            results are more useful than none.
        """
        unique = list(dict.fromkeys(packages))
        if not unique:
            return VulnerabilityReport(queried_count=0)

        own_client = self._client is None
        client = self._client or httpx.AsyncClient(timeout=self._timeout)
        try:
            return await self._query_with(client, unique)
        finally:
            if own_client:
                await client.aclose()

    async def _query_with(
        self, client: httpx.AsyncClient, packages: list[PackageQuery]
    ) -> VulnerabilityReport:
        report = VulnerabilityReport(queried_count=len(packages))
        ids_by_package: dict[PackageQuery, list[str]] = {}

        for start in range(0, len(packages), _BATCH_SIZE):
            batch = packages[start : start + _BATCH_SIZE]
            try:
                response = await client.post(
                    self._api_url,
                    json={"queries": [package.as_payload() for package in batch]},
                )
                response.raise_for_status()
                payload = response.json()
            except (httpx.HTTPError, ValueError) as exc:
                _degrade(report, f"{type(exc).__name__}: {exc}", self._api_url)
                continue

            results = payload.get("results")
            if not isinstance(results, list) or len(results) != len(batch):
                _degrade(report, "unexpected response shape from OSV", self._api_url)
                continue

            for package, result in zip(batch, results, strict=True):
                vulns = (result or {}).get("vulns") or []
                ids_by_package[package] = [
                    str(entry["id"])
                    for entry in vulns
                    if isinstance(entry, dict) and entry.get("id")
                ]

        details = await self._fetch_details(
            client, {vuln_id for ids in ids_by_package.values() for vuln_id in ids}, report
        )

        for package in packages:
            report.findings[package] = tuple(
                details.get(vuln_id, _placeholder(vuln_id))
                for vuln_id in ids_by_package.get(package, [])
            )

        log.info(
            "osv_lookup_complete",
            queried=len(packages),
            vulnerable=report.vulnerable_count,
            degraded=report.degraded,
        )
        return report

    async def _fetch_details(
        self,
        client: httpx.AsyncClient,
        vuln_ids: set[str],
        report: VulnerabilityReport,
    ) -> dict[str, Vulnerability]:
        """Fetch each advisory's details, bounded in count and concurrency."""
        ordered = sorted(vuln_ids)
        if len(ordered) > _MAX_DETAIL_FETCHES:
            _degrade(
                report,
                f"{len(ordered)} advisories found; details fetched for the first "
                f"{_MAX_DETAIL_FETCHES}",
                self._details_url,
            )
            ordered = ordered[:_MAX_DETAIL_FETCHES]

        semaphore = asyncio.Semaphore(_DETAIL_CONCURRENCY)
        details: dict[str, Vulnerability] = {}

        async def fetch(vuln_id: str) -> None:
            async with semaphore:
                try:
                    response = await client.get(f"{self._details_url}/{vuln_id}")
                    response.raise_for_status()
                    details[vuln_id] = _parse_vulnerability(response.json())
                except (httpx.HTTPError, ValueError, KeyError) as exc:
                    log.debug("osv_detail_failed", vuln_id=vuln_id, error=str(exc)[:200])

        if ordered:
            await asyncio.gather(*(fetch(vuln_id) for vuln_id in ordered))

        missing = len(ordered) - len(details)
        if missing > 0:
            _degrade(
                report,
                f"details could not be retrieved for {missing} of {len(ordered)} advisories",
                self._details_url,
            )
        return details


def _degrade(report: VulnerabilityReport, reason: str, url: str) -> None:
    """Mark a report degraded, keeping the first reason.

    The first failure is the most informative; later ones are usually the same
    cause repeating.
    """
    log.warning("osv_lookup_degraded", reason=reason, url=url)
    report.degraded = True
    if report.degraded_reason is None:
        report.degraded_reason = reason


def _placeholder(vuln_id: str) -> Vulnerability:
    """An advisory whose ID is known but whose details were not retrieved."""
    return Vulnerability(
        id=vuln_id,
        summary="Advisory details could not be retrieved.",
        severity=Severity.HIGH,
        details_available=False,
    )


def _parse_vulnerability(payload: dict[str, Any]) -> Vulnerability:
    """Build a :class:`Vulnerability` from an OSV advisory document."""
    aliases = tuple(str(alias) for alias in payload.get("aliases", []) if isinstance(alias, str))
    references = [
        str(reference.get("url"))
        for reference in payload.get("references", [])
        if isinstance(reference, dict) and reference.get("url")
    ]

    return Vulnerability(
        id=str(payload.get("id", "UNKNOWN")),
        summary=_summary_of(payload),
        severity=_severity_of(payload),
        aliases=aliases,
        fixed_versions=_fixed_versions(payload),
        reference_url=references[0] if references else None,
    )


def _summary_of(payload: dict[str, Any]) -> str:
    summary = payload.get("summary")
    if isinstance(summary, str) and summary.strip():
        return summary.strip()
    details = payload.get("details")
    if isinstance(details, str) and details.strip():
        # `details` is long-form markdown; the first sentence is enough.
        first = details.strip().split("\n")[0]
        return first[:300]
    return "No summary provided by the advisory."


def _severity_of(payload: dict[str, Any]) -> Severity:
    """Map an advisory's severity onto MergeX's scale.

    Taken from ``database_specific.severity``, which GitHub advisories supply
    as a word. CVSS vectors are *not* decoded: computing a base score from a
    vector string is a specification unto itself, and getting it subtly wrong
    would mis-rank findings. Absent a usable severity the rule's default is
    used, which the finding states.
    """
    database_specific = payload.get("database_specific")
    if isinstance(database_specific, dict):
        raw = database_specific.get("severity")
        if isinstance(raw, str) and raw.upper() in _GHSA_SEVERITIES:
            return _GHSA_SEVERITIES[raw.upper()]

    for entry in payload.get("severity", []) or []:
        if not isinstance(entry, dict):
            continue
        score = entry.get("score")
        # Some ecosystems supply a bare numeric score rather than a vector.
        if isinstance(score, (int, float)):
            return _from_cvss_score(float(score))
        if isinstance(score, str):
            try:
                return _from_cvss_score(float(score))
            except ValueError:
                continue

    return Severity.HIGH


def _from_cvss_score(score: float) -> Severity:
    if score >= 9.0:
        return Severity.CRITICAL
    if score >= 7.0:
        return Severity.HIGH
    if score >= 4.0:
        return Severity.MEDIUM
    return Severity.LOW


def _fixed_versions(payload: dict[str, Any]) -> tuple[str, ...]:
    """Versions that resolve the advisory, for the suggested fix."""
    fixed: list[str] = []
    for affected in payload.get("affected", []) or []:
        if not isinstance(affected, dict):
            continue
        for entry in affected.get("ranges", []) or []:
            if not isinstance(entry, dict):
                continue
            for event in entry.get("events", []) or []:
                if isinstance(event, dict) and event.get("fixed"):
                    fixed.append(str(event["fixed"]))
    return tuple(dict.fromkeys(fixed))
