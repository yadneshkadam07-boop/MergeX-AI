"""OSV vulnerability lookup.

Unit tests use a mock HTTP transport, so they exercise the real client code
without touching the network. The degradation tests matter most: OSV is a
third-party service on the public internet, and an outage there must never
fail a MergeX analysis.

One live test exists and is excluded from the default run. Run it with
``pytest -m network``.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from app.models.enums import Severity
from app.services.osv import (
    OsvClient,
    PackageQuery,
    StaticVulnerabilityClient,
    Vulnerability,
    VulnerabilityReport,
)

PYYAML = PackageQuery(ecosystem="PyPI", name="PyYAML", version="5.3.1")
REQUESTS = PackageQuery(ecosystem="PyPI", name="requests", version="2.19.1")
SAFE = PackageQuery(ecosystem="PyPI", name="sqlalchemy", version="2.0.31")

# A recorded-shape advisory document, trimmed to the fields the client reads.
PYYAML_ADVISORY: dict[str, Any] = {
    "id": "GHSA-8q59-q68h-6hv4",
    "summary": "Improper Input Validation in PyYAML",
    "details": "A vulnerability in PyYAML allows arbitrary code execution.",
    "aliases": ["CVE-2020-14343"],
    "database_specific": {"severity": "CRITICAL"},
    "affected": [
        {
            "package": {"name": "pyyaml", "ecosystem": "PyPI"},
            "ranges": [
                {
                    "type": "ECOSYSTEM",
                    "events": [{"introduced": "0"}, {"fixed": "5.4"}],
                }
            ],
        }
    ],
    "references": [{"type": "ADVISORY", "url": "https://nvd.nist.gov/vuln/CVE-2020-14343"}],
}


def transport(
    *,
    batch_payload: dict[str, Any] | None = None,
    advisories: dict[str, dict[str, Any]] | None = None,
    batch_status: int = 200,
    detail_status: int = 200,
    batch_body: str | None = None,
) -> httpx.MockTransport:
    """A transport serving the querybatch endpoint and advisory details."""
    advisories = advisories or {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/querybatch"):
            if batch_body is not None:
                return httpx.Response(batch_status, text=batch_body)
            return httpx.Response(batch_status, json=batch_payload or {"results": []})
        vuln_id = request.url.path.rsplit("/", 1)[-1]
        if detail_status != 200 or vuln_id not in advisories:
            return httpx.Response(detail_status if detail_status != 200 else 404, json={})
        return httpx.Response(200, json=advisories[vuln_id])

    return httpx.MockTransport(handler)


def client_with(mock: httpx.MockTransport) -> tuple[OsvClient, httpx.AsyncClient]:
    http = httpx.AsyncClient(transport=mock, base_url="https://api.osv.dev")
    return (OsvClient(client=http), http)


class TestSuccessfulLookup:
    async def test_reports_a_vulnerable_package(self) -> None:
        mock = transport(
            batch_payload={"results": [{"vulns": [{"id": "GHSA-8q59-q68h-6hv4"}]}]},
            advisories={"GHSA-8q59-q68h-6hv4": PYYAML_ADVISORY},
        )
        osv, http = client_with(mock)
        try:
            report = await osv.query([PYYAML])
        finally:
            await http.aclose()

        vulnerabilities = report.for_package(PYYAML)
        assert len(vulnerabilities) == 1
        assert vulnerabilities[0].id == "GHSA-8q59-q68h-6hv4"
        assert vulnerabilities[0].severity is Severity.CRITICAL
        assert vulnerabilities[0].fixed_versions == ("5.4",)
        assert not report.degraded

    async def test_prefers_a_cve_as_the_identifier(self) -> None:
        """Users recognise CVEs; GHSA ids mean less to most people."""
        mock = transport(
            batch_payload={"results": [{"vulns": [{"id": "GHSA-8q59-q68h-6hv4"}]}]},
            advisories={"GHSA-8q59-q68h-6hv4": PYYAML_ADVISORY},
        )
        osv, http = client_with(mock)
        try:
            report = await osv.query([PYYAML])
        finally:
            await http.aclose()

        assert report.for_package(PYYAML)[0].best_identifier == "CVE-2020-14343"

    async def test_reports_a_clean_package_as_clean(self) -> None:
        mock = transport(batch_payload={"results": [{}]})
        osv, http = client_with(mock)
        try:
            report = await osv.query([SAFE])
        finally:
            await http.aclose()

        assert report.for_package(SAFE) == ()
        assert report.vulnerable_count == 0
        assert not report.degraded

    async def test_handles_several_packages(self) -> None:
        mock = transport(
            batch_payload={
                "results": [
                    {"vulns": [{"id": "GHSA-8q59-q68h-6hv4"}]},
                    {},
                ]
            },
            advisories={"GHSA-8q59-q68h-6hv4": PYYAML_ADVISORY},
        )
        osv, http = client_with(mock)
        try:
            report = await osv.query([PYYAML, SAFE])
        finally:
            await http.aclose()

        assert report.queried_count == 2
        assert report.vulnerable_count == 1

    async def test_an_empty_query_makes_no_request(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
            raise AssertionError("no request should be made")

        osv = OsvClient(client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))

        report = await osv.query([])

        assert report.queried_count == 0

    async def test_duplicate_packages_are_queried_once(self) -> None:
        requests_made: list[int] = []

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/querybatch"):
                payload = json.loads(request.content)
                requests_made.append(len(payload["queries"]))
            return httpx.Response(200, json={"results": [{}]})

        osv = OsvClient(client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))

        await osv.query([PYYAML, PYYAML, PYYAML])

        assert requests_made == [1]


class TestGracefulDegradation:
    """An OSV outage must never fail an analysis."""

    async def test_a_server_error_degrades_rather_than_raising(self) -> None:
        osv, http = client_with(transport(batch_status=500))
        try:
            report = await osv.query([PYYAML])
        finally:
            await http.aclose()

        assert report.degraded
        assert report.degraded_reason
        assert report.for_package(PYYAML) == ()

    async def test_a_timeout_degrades_rather_than_raising(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("timed out", request=request)

        osv = OsvClient(client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))

        report = await osv.query([PYYAML])

        assert report.degraded
        assert "ReadTimeout" in (report.degraded_reason or "")

    async def test_a_connection_failure_degrades(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("name resolution failed", request=request)

        osv = OsvClient(client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))

        report = await osv.query([PYYAML])

        assert report.degraded
        assert "ConnectError" in (report.degraded_reason or "")

    async def test_malformed_json_degrades(self) -> None:
        osv, http = client_with(transport(batch_body="this is not json"))
        try:
            report = await osv.query([PYYAML])
        finally:
            await http.aclose()

        assert report.degraded

    async def test_a_wrong_length_response_degrades(self) -> None:
        """A results array that does not line up with the queries is unusable."""
        osv, http = client_with(transport(batch_payload={"results": [{}]}))
        try:
            report = await osv.query([PYYAML, REQUESTS])
        finally:
            await http.aclose()

        assert report.degraded
        assert "unexpected response shape" in (report.degraded_reason or "")

    async def test_a_missing_results_key_degrades(self) -> None:
        osv, http = client_with(transport(batch_payload={"nope": []}))
        try:
            report = await osv.query([PYYAML])
        finally:
            await http.aclose()

        assert report.degraded

    async def test_advisory_ids_survive_a_detail_failure(self) -> None:
        """The advisory is still real even when its details cannot be fetched."""
        mock = transport(
            batch_payload={"results": [{"vulns": [{"id": "GHSA-8q59-q68h-6hv4"}]}]},
            detail_status=503,
        )
        osv, http = client_with(mock)
        try:
            report = await osv.query([PYYAML])
        finally:
            await http.aclose()

        vulnerabilities = report.for_package(PYYAML)
        assert len(vulnerabilities) == 1
        assert vulnerabilities[0].details_available is False
        assert report.degraded
        assert "details could not be retrieved" in (report.degraded_reason or "")

    async def test_the_first_reason_is_kept(self) -> None:
        """Later failures are usually the same cause repeating."""
        report = VulnerabilityReport()
        from app.services.osv import _degrade

        _degrade(report, "first", "url")
        _degrade(report, "second", "url")

        assert report.degraded_reason == "first"


class TestSeverityMapping:
    @pytest.mark.parametrize(
        ("word", "expected"),
        [
            ("CRITICAL", Severity.CRITICAL),
            ("HIGH", Severity.HIGH),
            ("MODERATE", Severity.MEDIUM),
            ("MEDIUM", Severity.MEDIUM),
            ("LOW", Severity.LOW),
        ],
    )
    def test_maps_github_advisory_severities(self, word: str, expected: Severity) -> None:
        from app.services.osv import _severity_of

        assert _severity_of({"database_specific": {"severity": word}}) is expected

    @pytest.mark.parametrize(
        ("score", "expected"),
        [
            (9.8, Severity.CRITICAL),
            (7.5, Severity.HIGH),
            (5.0, Severity.MEDIUM),
            (2.1, Severity.LOW),
        ],
    )
    def test_maps_a_numeric_score(self, score: float, expected: Severity) -> None:
        from app.services.osv import _severity_of

        assert _severity_of({"severity": [{"type": "CVSS_V3", "score": score}]}) is expected

    def test_a_cvss_vector_falls_back_to_the_default(self) -> None:
        """Decoding a vector is a specification unto itself; guessing it would
        mis-rank findings, so an undecodable severity defaults to high."""
        from app.services.osv import _severity_of

        vector = {"severity": [{"type": "CVSS_V3", "score": "CVSS:3.1/AV:N/AC:L"}]}

        assert _severity_of(vector) is Severity.HIGH

    def test_no_severity_information_defaults_to_high(self) -> None:
        from app.services.osv import _severity_of

        assert _severity_of({}) is Severity.HIGH


class TestAdvisoryParsing:
    def test_reads_the_summary(self) -> None:
        from app.services.osv import _parse_vulnerability

        parsed = _parse_vulnerability(PYYAML_ADVISORY)

        assert parsed.summary == "Improper Input Validation in PyYAML"

    def test_falls_back_to_details_when_there_is_no_summary(self) -> None:
        from app.services.osv import _parse_vulnerability

        payload = {**PYYAML_ADVISORY, "summary": ""}

        assert "arbitrary code execution" in _parse_vulnerability(payload).summary

    def test_handles_an_advisory_with_nothing_useful(self) -> None:
        from app.services.osv import _parse_vulnerability

        parsed = _parse_vulnerability({"id": "X"})

        assert parsed.id == "X"
        assert parsed.summary
        assert parsed.fixed_versions == ()

    def test_collects_fixed_versions(self) -> None:
        from app.services.osv import _parse_vulnerability

        assert _parse_vulnerability(PYYAML_ADVISORY).fixed_versions == ("5.4",)

    def test_keeps_the_first_reference(self) -> None:
        from app.services.osv import _parse_vulnerability

        parsed = _parse_vulnerability(PYYAML_ADVISORY)

        assert parsed.reference_url is not None
        assert "CVE-2020-14343" in parsed.reference_url


class TestStaticClient:
    """The in-process client used by the rule tests."""

    async def test_answers_from_its_table(self) -> None:
        vulnerability = Vulnerability(id="X", summary="s", severity=Severity.HIGH)
        client = StaticVulnerabilityClient({("PyPI", "pyyaml", "5.3.1"): (vulnerability,)})

        report = await client.query([PYYAML])

        assert report.for_package(PYYAML) == (vulnerability,)

    async def test_is_case_insensitive_on_the_package_name(self) -> None:
        """PyYAML, pyyaml and PyYaml are one distribution."""
        vulnerability = Vulnerability(id="X", summary="s", severity=Severity.HIGH)
        client = StaticVulnerabilityClient({("PyPI", "pyyaml", "5.3.1"): (vulnerability,)})

        report = await client.query([PackageQuery("PyPI", "PyYAML", "5.3.1")])

        assert report.for_package(PackageQuery("PyPI", "PyYAML", "5.3.1")) == (vulnerability,)

    async def test_unknown_packages_come_back_clean(self) -> None:
        client = StaticVulnerabilityClient({})

        assert (await client.query([SAFE])).for_package(SAFE) == ()

    async def test_can_simulate_an_outage(self) -> None:
        client = StaticVulnerabilityClient(degraded=True, degraded_reason="offline")

        report = await client.query([PYYAML])

        assert report.degraded
        assert report.degraded_reason == "offline"

    async def test_records_its_calls(self) -> None:
        client = StaticVulnerabilityClient({})

        await client.query([PYYAML, SAFE])

        assert client.calls == [[PYYAML, SAFE]]


@pytest.mark.network
class TestLiveOsv:
    """Real requests to osv.dev. Excluded from the default run.

    Run with: ``pytest -m network tests/test_services_osv.py``
    """

    async def test_the_five_cve_pinned_fixture_dependencies_are_flagged(self) -> None:
        pinned = [
            PackageQuery("PyPI", "PyYAML", "5.3.1"),
            PackageQuery("PyPI", "requests", "2.19.1"),
            PackageQuery("PyPI", "GitPython", "3.1.29"),
            PackageQuery("PyPI", "jinja2", "2.11.2"),
            PackageQuery("PyPI", "fastapi", "0.65.1"),
        ]

        report = await OsvClient().query(pinned)

        if report.degraded and report.vulnerable_count == 0:
            pytest.skip(f"OSV unreachable: {report.degraded_reason}")

        clean = [str(package) for package in pinned if not report.for_package(package)]
        assert (
            clean == []
        ), f"These fixture pins are expected to have advisories but returned none: {clean}"

    async def test_a_current_version_is_clean(self) -> None:
        current = PackageQuery("PyPI", "sqlalchemy", "2.0.31")

        report = await OsvClient().query([current])

        if report.degraded:
            pytest.skip(f"OSV unreachable: {report.degraded_reason}")
        assert report.for_package(current) == ()
