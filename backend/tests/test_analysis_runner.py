"""The runner: one analysis, from a pending row to a persisted report.

The guarantee this module exists to assert is that **a run always reaches a
terminal state**. An analysis stuck on ``running`` is the worst possible
outcome -- the UI spins and the user cannot tell whether to wait -- so every
failure path is exercised: a clone that fails, a rule group that crashes, a
missing archive, an explainer that explodes, and an exception type the runner
has never seen.

The repository import is faked throughout. The real importer is tested in
``test_repo_importer.py``; here it only needs to hand over a directory.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.events import EventBus, EventStatus, Stage
from app.models.analysis import Analysis
from app.models.enums import AnalysisStatus, IssueCategory, Severity, SourceType
from app.models.issue import Issue
from app.models.project import Project
from app.services.analysis_runner import (
    AnalysisRunner,
    EventBusReporter,
    default_explainer_for,
)
from app.services.explanations import (
    Explanation,
    ExplanationResult,
    TemplateExplainer,
    TokenUsage,
)
from app.services.osv import StaticVulnerabilityClient
from app.services.repo_importer import ImportResult, RepoImportError
from tests.conftest import FIXTURE_CREDENTIALS

pytestmark = pytest.mark.anyio


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeImporter:
    """Hands over a directory that already exists, or fails on demand."""

    def __init__(
        self,
        root: Path | None = None,
        *,
        error: Exception | None = None,
        file_count: int = 12,
        commit_sha: str = "a1b2c3d4e5f60718293a4b5c6d7e8f9012345678",
    ) -> None:
        self.root = root
        self.error = error
        self.file_count = file_count
        self.commit_sha = commit_sha
        self.cleaned_up = False
        self.calls: list[str] = []

    @asynccontextmanager
    async def _yield(self, kind: str) -> AsyncGenerator[ImportResult, None]:
        self.calls.append(kind)
        if self.error is not None:
            raise self.error
        assert self.root is not None
        try:
            yield ImportResult(
                path=self.root,
                source_type=SourceType.GITHUB,
                file_count=self.file_count,
                size_bytes=4096,
                duration_ms=5,
                commit_sha=self.commit_sha,
            )
        finally:
            # The real importer removes the sandbox here; this records that the
            # runner left the context manager on every path.
            self.cleaned_up = True

    def import_github(self, repo: Any, *, token: str | None = None) -> Any:
        return self._yield("github")

    def import_zip(self, archive_path: Path) -> Any:
        return self._yield("zip")


class FakeExplainer:
    """A model-shaped explainer, so the persisted source reads ``gemini``."""

    async def explain(self, findings: Any) -> ExplanationResult:
        return ExplanationResult(
            explanations={
                f.fingerprint: Explanation(
                    fingerprint=f.fingerprint,
                    explanation=f"Why {f.rule_id} matters.",
                    suggested_fix=f"Change {f.primary_location}.",
                    source="gemini",
                    fix_before="before();",
                    fix_after="after();",
                )
                for f in findings
            },
            usage=TokenUsage(900, 300, 1200, 3),
        )


def no_vulnerabilities() -> StaticVulnerabilityClient:
    """The real client interface, answering from an empty table.

    Used rather than a hand-rolled stub so these tests exercise the same code
    path production uses, and so a change to the protocol breaks them loudly.
    """
    return StaticVulnerabilityClient()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def bus() -> EventBus:
    return EventBus()


@pytest.fixture
async def project(session: AsyncSession) -> Project:
    project = Project(
        id=uuid.uuid4(),
        name="demo",
        source_type=SourceType.GITHUB,
        source_url="https://github.com/acme/demo",
    )
    session.add(project)
    await session.flush()
    return project


@pytest.fixture
async def analysis(session: AsyncSession, project: Project) -> Analysis:
    analysis = Analysis(id=uuid.uuid4(), project_id=project.id, status=AnalysisStatus.PENDING)
    session.add(analysis)
    await session.flush()
    return analysis


def runner(
    settings: Settings,
    bus: EventBus,
    importer: FakeImporter,
    **kwargs: Any,
) -> AnalysisRunner:
    return AnalysisRunner(
        settings=settings,
        bus=bus,
        importer=importer,  # type: ignore[arg-type]
        vulnerability_client=kwargs.pop("vulnerability_client", no_vulnerabilities()),
        **kwargs,
    )


async def issues_of(session: AsyncSession, analysis_id: uuid.UUID) -> list[Issue]:
    return list(await session.scalars(select(Issue).where(Issue.analysis_id == analysis_id)))


# ---------------------------------------------------------------------------


class TestSuccessfulRun:
    async def test_the_analysis_succeeds_and_is_scored(
        self,
        session: AsyncSession,
        settings: Settings,
        bus: EventBus,
        analysis: Analysis,
        fixture_repo: Callable[[str], Path],
    ) -> None:
        importer = FakeImporter(fixture_repo("react_fastapi_mismatch"))

        await runner(settings, bus, importer).run(session, analysis.id)

        assert analysis.status is AnalysisStatus.SUCCEEDED
        assert analysis.stage is None
        assert analysis.health_score is not None
        assert 0 <= analysis.health_score < 100
        assert analysis.completed_at is not None
        assert analysis.duration_ms is not None and analysis.duration_ms >= 0
        assert analysis.error_message is None

    async def test_the_findings_are_persisted(
        self,
        session: AsyncSession,
        settings: Settings,
        bus: EventBus,
        analysis: Analysis,
        fixture_repo: Callable[[str], Path],
    ) -> None:
        importer = FakeImporter(fixture_repo("react_fastapi_mismatch"))

        await runner(settings, bus, importer).run(session, analysis.id)
        stored = await issues_of(session, analysis.id)

        assert stored
        for issue in stored:
            assert issue.detected_by.startswith("MX-")
            assert issue.file_path
            assert issue.line_start is not None
            assert issue.fingerprint
            assert 0.0 < issue.confidence <= 1.0

    async def test_the_explanation_is_persisted_with_its_source(
        self,
        session: AsyncSession,
        settings: Settings,
        bus: EventBus,
        analysis: Analysis,
        fixture_repo: Callable[[str], Path],
    ) -> None:
        importer = FakeImporter(fixture_repo("react_fastapi_mismatch"))

        await runner(settings, bus, importer, explainer=FakeExplainer()).run(session, analysis.id)
        stored = await issues_of(session, analysis.id)

        assert all(issue.explanation for issue in stored)
        assert all(issue.suggested_fix for issue in stored)
        assert {issue.explanation_source for issue in stored} == {"gemini"}
        assert all(issue.fix_before and issue.fix_after for issue in stored)
        assert analysis.ai_explanations_available is True

    async def test_the_offline_run_records_template_explanations(
        self,
        session: AsyncSession,
        settings: Settings,
        bus: EventBus,
        analysis: Analysis,
        fixture_repo: Callable[[str], Path],
    ) -> None:
        """No API key configured: the report is still complete."""
        importer = FakeImporter(fixture_repo("react_fastapi_mismatch"))

        await runner(settings, bus, importer, explainer=TemplateExplainer()).run(
            session, analysis.id
        )
        stored = await issues_of(session, analysis.id)

        assert {issue.explanation_source for issue in stored} == {"template"}
        assert all(issue.explanation for issue in stored)
        assert analysis.ai_explanations_available is False

    async def test_the_import_metadata_is_recorded(
        self,
        session: AsyncSession,
        settings: Settings,
        bus: EventBus,
        analysis: Analysis,
        fixture_repo: Callable[[str], Path],
    ) -> None:
        importer = FakeImporter(fixture_repo("react_fastapi_mismatch"), file_count=42)

        await runner(settings, bus, importer).run(session, analysis.id)

        assert analysis.file_count == 42
        assert analysis.commit_sha == importer.commit_sha

    async def test_the_stack_and_caveats_are_recorded(
        self,
        session: AsyncSession,
        settings: Settings,
        bus: EventBus,
        analysis: Analysis,
        fixture_repo: Callable[[str], Path],
    ) -> None:
        importer = FakeImporter(fixture_repo("react_fastapi_mismatch"))

        await runner(settings, bus, importer).run(session, analysis.id)

        stack = analysis.stack or {}
        assert "React" in (stack.get("frontend") or [])
        assert stack["counts"]["frontend_calls"] > 0
        assert isinstance(stack["notes"], list)
        assert stack["failed_groups"] == []
        assert stack["explanation_sources"]

    async def test_the_sub_scores_are_recorded(
        self,
        session: AsyncSession,
        settings: Settings,
        bus: EventBus,
        analysis: Analysis,
        fixture_repo: Callable[[str], Path],
    ) -> None:
        importer = FakeImporter(fixture_repo("react_fastapi_mismatch"))

        await runner(settings, bus, importer).run(session, analysis.id)

        scores = analysis.category_scores or {}
        assert scores["score"] == analysis.health_score
        assert "api_contract" in scores["categories"]

    async def test_the_sandbox_is_released(
        self,
        session: AsyncSession,
        settings: Settings,
        bus: EventBus,
        analysis: Analysis,
        fixture_repo: Callable[[str], Path],
    ) -> None:
        importer = FakeImporter(fixture_repo("react_fastapi_mismatch"))

        await runner(settings, bus, importer).run(session, analysis.id)

        assert importer.cleaned_up is True


class TestTerminalEvents:
    """Success and failure must both end the stream."""

    async def test_a_successful_run_emits_a_terminal_event(
        self,
        session: AsyncSession,
        settings: Settings,
        bus: EventBus,
        analysis: Analysis,
        fixture_repo: Callable[[str], Path],
    ) -> None:
        importer = FakeImporter(fixture_repo("react_fastapi_mismatch"))

        await runner(settings, bus, importer).run(session, analysis.id)

        events = bus.history(analysis.id)
        assert events[-1].stage is Stage.COMPLETE
        assert events[-1].status is EventStatus.COMPLETED
        assert events[-1].total_findings == len(await issues_of(session, analysis.id))
        assert events[-1].data["score"] == analysis.health_score
        assert bus.is_finished(analysis.id)

    async def test_a_failed_run_emits_a_terminal_event(
        self,
        session: AsyncSession,
        settings: Settings,
        bus: EventBus,
        analysis: Analysis,
    ) -> None:
        importer = FakeImporter(error=RepoImportError("Repository not found."))

        await runner(settings, bus, importer).run(session, analysis.id)

        events = bus.history(analysis.id)
        assert events[-1].stage is Stage.COMPLETE
        assert events[-1].status is EventStatus.FAILED
        assert "Repository not found." in events[-1].message
        assert bus.is_finished(analysis.id)

    async def test_every_stage_is_announced(
        self,
        session: AsyncSession,
        settings: Settings,
        bus: EventBus,
        analysis: Analysis,
        fixture_repo: Callable[[str], Path],
    ) -> None:
        importer = FakeImporter(fixture_repo("react_fastapi_mismatch"))

        await runner(settings, bus, importer).run(session, analysis.id)

        stages = {event.stage for event in bus.history(analysis.id)}
        assert {
            Stage.IMPORTING,
            Stage.STACK,
            Stage.API_CONTRACT,
            Stage.SCHEMA,
            Stage.SECURITY,
            Stage.SYNTHESIS,
            Stage.COMPLETE,
        } <= stages

    async def test_the_running_total_only_grows(
        self,
        session: AsyncSession,
        settings: Settings,
        bus: EventBus,
        analysis: Analysis,
        fixture_repo: Callable[[str], Path],
    ) -> None:
        """A stepper showing a shrinking total would look broken."""
        importer = FakeImporter(fixture_repo("react_fastapi_insecure"))

        await runner(settings, bus, importer).run(session, analysis.id)

        totals = [
            event.total_findings
            for event in bus.history(analysis.id)
            if event.total_findings is not None
        ]
        assert totals == sorted(totals)
        assert totals[-1] > 0

    async def test_a_stage_reports_its_own_finding_count(
        self,
        session: AsyncSession,
        settings: Settings,
        bus: EventBus,
        analysis: Analysis,
        fixture_repo: Callable[[str], Path],
    ) -> None:
        importer = FakeImporter(fixture_repo("react_fastapi_insecure"))

        await runner(settings, bus, importer).run(session, analysis.id)

        per_stage = {
            event.stage: event.finding_count
            for event in bus.history(analysis.id)
            if event.finding_count is not None
        }
        assert per_stage.get(Stage.SECURITY, 0) > 0


class TestFailurePaths:
    async def test_a_clone_failure_is_recorded_with_its_message(
        self,
        session: AsyncSession,
        settings: Settings,
        bus: EventBus,
        analysis: Analysis,
    ) -> None:
        importer = FakeImporter(error=RepoImportError("The repository exceeds the 100 MB limit."))

        await runner(settings, bus, importer).run(session, analysis.id)

        assert analysis.status is AnalysisStatus.FAILED
        assert analysis.stage is None
        assert analysis.error_message == "The repository exceeds the 100 MB limit."
        assert analysis.completed_at is not None

    async def test_a_missing_upload_is_explained(
        self,
        session: AsyncSession,
        settings: Settings,
        bus: EventBus,
        project: Project,
        tmp_path: Path,
    ) -> None:
        """An archive deleted since upload must say so, not fail obscurely."""
        project.source_type = SourceType.ZIP
        project.source_url = None
        project.upload_path = str(tmp_path / "gone.zip")
        analysis = Analysis(id=uuid.uuid4(), project_id=project.id, status=AnalysisStatus.PENDING)
        session.add(analysis)
        await session.flush()

        await runner(settings, bus, FakeImporter()).run(session, analysis.id)

        assert analysis.status is AnalysisStatus.FAILED
        assert "no longer available" in (analysis.error_message or "")

    async def test_an_unexpected_failure_does_not_leak_its_message(
        self,
        session: AsyncSession,
        settings: Settings,
        bus: EventBus,
        analysis: Analysis,
    ) -> None:
        """An arbitrary exception string can contain paths or credentials."""
        importer = FakeImporter(error=RuntimeError("psql: password=hunter2 host=10.0.0.4 failed"))

        await runner(settings, bus, importer).run(session, analysis.id)

        assert analysis.status is AnalysisStatus.FAILED
        assert "hunter2" not in (analysis.error_message or "")
        assert "RuntimeError" in (analysis.error_message or "")

    async def test_the_sandbox_is_released_on_failure(
        self,
        session: AsyncSession,
        settings: Settings,
        bus: EventBus,
        analysis: Analysis,
        fixture_repo: Callable[[str], Path],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A crash inside the analysis must not leave a clone on disk."""
        importer = FakeImporter(fixture_repo("react_fastapi_mismatch"))

        async def explode(*args: Any, **kwargs: Any) -> Any:
            raise RuntimeError("the workflow blew up")

        monkeypatch.setattr("app.services.analysis_runner.run_workflow", explode)

        await runner(settings, bus, importer).run(session, analysis.id)

        assert importer.cleaned_up is True
        assert analysis.status is AnalysisStatus.FAILED

    async def test_a_crashed_rule_group_still_succeeds(
        self,
        session: AsyncSession,
        settings: Settings,
        bus: EventBus,
        analysis: Analysis,
        fixture_repo: Callable[[str], Path],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A degraded analysis is a successful one that says what it missed."""
        importer = FakeImporter(fixture_repo("react_fastapi_insecure"))

        def explode(*args: Any, **kwargs: Any) -> Any:
            raise RuntimeError("the security rules are broken")

        monkeypatch.setattr("app.agents.graph.run_security_rules", explode)

        await runner(settings, bus, importer).run(session, analysis.id)

        assert analysis.status is AnalysisStatus.SUCCEEDED
        assert (analysis.stack or {})["failed_groups"] == ["security"]
        assert any("security analysis failed" in note for note in (analysis.stack or {})["notes"])

    async def test_an_explainer_crash_still_succeeds(
        self,
        session: AsyncSession,
        settings: Settings,
        bus: EventBus,
        analysis: Analysis,
        fixture_repo: Callable[[str], Path],
    ) -> None:
        class Exploding:
            async def explain(self, findings: Any) -> ExplanationResult:
                raise RuntimeError("no model today")

        importer = FakeImporter(fixture_repo("react_fastapi_mismatch"))

        await runner(settings, bus, importer, explainer=Exploding()).run(session, analysis.id)
        stored = await issues_of(session, analysis.id)

        assert analysis.status is AnalysisStatus.SUCCEEDED
        assert stored
        assert all(issue.explanation for issue in stored)

    async def test_a_missing_analysis_row_is_ignored(
        self, session: AsyncSession, settings: Settings, bus: EventBus
    ) -> None:
        """A deleted analysis must not raise out of a background task."""
        await runner(settings, bus, FakeImporter()).run(session, uuid.uuid4())

        assert bus.history(uuid.uuid4()) == []


class TestSecretsAreNotPersisted:
    async def test_the_stored_evidence_is_masked(
        self,
        session: AsyncSession,
        settings: Settings,
        bus: EventBus,
        analysis: Analysis,
        fixture_repo: Callable[[str], Path],
    ) -> None:
        """MergeX must not become a database of the secrets it finds."""
        importer = FakeImporter(fixture_repo("react_fastapi_insecure"))

        await runner(settings, bus, importer).run(session, analysis.id)
        stored = await issues_of(session, analysis.id)

        blob = "\n".join(
            " ".join(
                filter(
                    None,
                    [
                        issue.evidence,
                        issue.explanation,
                        issue.suggested_fix,
                        issue.fix_before,
                        issue.fix_after,
                        issue.actual,
                        issue.expected,
                    ],
                )
            )
            for issue in stored
        )
        leaked = [secret for secret in FIXTURE_CREDENTIALS if secret in blob]
        assert leaked == [], f"credentials persisted in the issue rows: {leaked}"

    async def test_the_secret_rules_still_fired(
        self,
        session: AsyncSession,
        settings: Settings,
        bus: EventBus,
        analysis: Analysis,
        fixture_repo: Callable[[str], Path],
    ) -> None:
        """Masking must not be achieved by failing to report the secrets."""
        importer = FakeImporter(fixture_repo("react_fastapi_insecure"))

        await runner(settings, bus, importer).run(session, analysis.id)
        stored = await issues_of(session, analysis.id)

        rules = {issue.detected_by for issue in stored}
        assert "MX-SEC-001" in rules
        assert "MX-SEC-004" in rules


class TestEventBusReporter:
    def test_the_total_accumulates_across_stages(self, bus: EventBus) -> None:
        reporter = EventBusReporter(bus, ANALYSIS_ID)

        reporter.completed("api", "api done", finding_count=3)
        reporter.completed("schema", "schema done", finding_count=2)

        assert [event.total_findings for event in bus.history(ANALYSIS_ID)] == [3, 5]

    def test_synthesis_does_not_double_count(self, bus: EventBus) -> None:
        """Synthesis reports the merged total, not new findings."""
        reporter = EventBusReporter(bus, ANALYSIS_ID)

        reporter.completed("api", "api done", finding_count=3)
        reporter.completed("synthesis", "scored", finding_count=3)

        assert bus.history(ANALYSIS_ID)[-1].total_findings == 3

    def test_a_failure_is_published_without_losing_the_total(self, bus: EventBus) -> None:
        reporter = EventBusReporter(bus, ANALYSIS_ID)

        reporter.completed("api", "api done", finding_count=4)
        reporter.failed("security", "RuntimeError: boom")

        last = bus.history(ANALYSIS_ID)[-1]
        assert last.status is EventStatus.FAILED
        assert last.stage is Stage.SECURITY
        assert last.total_findings == 4

    def test_a_skip_is_published(self, bus: EventBus) -> None:
        reporter = EventBusReporter(bus, ANALYSIS_ID)

        reporter.skipped("schema", "No migrations")

        assert bus.history(ANALYSIS_ID)[-1].status is EventStatus.SKIPPED

    def test_an_unknown_stage_does_not_raise(self, bus: EventBus) -> None:
        """A new workflow stage must not break progress reporting."""
        reporter = EventBusReporter(bus, ANALYSIS_ID)

        reporter.started("something_new", "working")

        assert bus.history(ANALYSIS_ID)[0].stage is Stage.STACK


ANALYSIS_ID = "33333333-3333-3333-3333-333333333333"


class TestExplainerSelection:
    def test_no_key_means_the_template_explainer(
        self, settings_factory: Callable[..., Settings]
    ) -> None:
        subject = default_explainer_for(settings_factory(gemini_api_key=None))

        assert isinstance(subject, TemplateExplainer)

    def test_a_blank_key_means_the_template_explainer(
        self, settings_factory: Callable[..., Settings]
    ) -> None:
        """A key set to whitespace in a .env must not count as configured."""
        subject = default_explainer_for(settings_factory(gemini_api_key="   "))

        assert isinstance(subject, TemplateExplainer)

    def test_a_key_selects_gemini(self, settings_factory: Callable[..., Settings]) -> None:
        from app.services.gemini import GeminiExplainer

        subject = default_explainer_for(settings_factory(gemini_api_key="AIza-not-real"))

        assert isinstance(subject, GeminiExplainer)


class TestIssueMapping:
    async def test_a_finding_maps_onto_an_issue_row(
        self,
        session: AsyncSession,
        settings: Settings,
        bus: EventBus,
        analysis: Analysis,
        fixture_repo: Callable[[str], Path],
    ) -> None:
        importer = FakeImporter(fixture_repo("react_fastapi_mismatch"))

        await runner(settings, bus, importer, explainer=FakeExplainer()).run(session, analysis.id)
        stored = sorted(await issues_of(session, analysis.id), key=lambda issue: issue.detected_by)

        first = stored[0]
        assert first.category in set(IssueCategory)
        assert first.severity in set(Severity)
        assert first.title and first.description
        assert first.analysis_id == analysis.id
        assert first.explanation_source == "gemini"

    async def test_fingerprints_are_unique_within_a_run(
        self,
        session: AsyncSession,
        settings: Settings,
        bus: EventBus,
        analysis: Analysis,
        fixture_repo: Callable[[str], Path],
    ) -> None:
        importer = FakeImporter(fixture_repo("react_fastapi_insecure"))

        await runner(settings, bus, importer).run(session, analysis.id)
        stored = await issues_of(session, analysis.id)

        fingerprints = [issue.fingerprint for issue in stored]
        assert len(fingerprints) == len(set(fingerprints))
