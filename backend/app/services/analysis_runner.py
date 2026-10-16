"""Runs one analysis end to end and records what happened.

Import the repository, run the workflow, persist the findings and the score,
and publish progress throughout. This is the layer that turns the pure
analysis pipeline into something a user watches in a browser.

Two guarantees it exists to provide:

**A run always reaches a terminal state.** Whatever fails — the clone, a rule
group, the database — the analysis row ends as ``succeeded`` or ``failed`` and
a terminal SSE event is emitted. An analysis stuck on ``running`` forever is
the worst outcome, because the UI spins and the user cannot tell whether to
wait.

**The sandbox is always cleaned up.** The import context manager owns the
working tree, so it is removed on every path out, including a crash.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.graph import run_workflow
from app.agents.state import ProgressReporter, WorkflowResult
from app.analysis.findings import Finding
from app.core.config import Settings
from app.core.events import EventBus, EventStatus, Stage
from app.core.logging import get_logger
from app.models.analysis import Analysis
from app.models.enums import AnalysisStage, AnalysisStatus, SourceType
from app.models.issue import Issue
from app.models.project import Project
from app.services.explanations import Explainer, TemplateExplainer
from app.services.gemini import build_explainer
from app.services.github import parse_github_url
from app.services.osv import OsvClient, VulnerabilityClient
from app.services.repo_importer import RepoImporter

__all__ = ["AnalysisRunner", "EventBusReporter"]

log = get_logger("app.analysis_runner")

# Maps a workflow stage name onto the SSE stage the UI renders.
_STAGE_BY_NAME = {
    "stack": Stage.STACK,
    "api": Stage.API_CONTRACT,
    "schema": Stage.SCHEMA,
    "security": Stage.SECURITY,
    "synthesis": Stage.SYNTHESIS,
}

# Mirrors the SSE stage onto the analysis row, so a client polling instead of
# streaming can still see progress.
_DB_STAGE_BY_NAME = {
    "stack": AnalysisStage.DETECTING_STACK,
    "api": AnalysisStage.API_CONTRACT,
    "schema": AnalysisStage.SCHEMA,
    "security": AnalysisStage.SECURITY,
    "synthesis": AnalysisStage.SYNTHESIZING,
}


class EventBusReporter(ProgressReporter):
    """Publishes workflow progress to the SSE bus.

    Counts are accumulated so each event can carry the running total as well
    as the stage's own contribution; a stepper showing "security: 6 issues"
    next to "24 so far" is much more informative than either alone.
    """

    def __init__(self, bus: EventBus, analysis_id: uuid.UUID | str) -> None:
        self._bus = bus
        self._analysis_id = str(analysis_id)
        self._total = 0

    def started(self, stage: str, message: str) -> None:
        self._bus.publish(
            self._analysis_id,
            _STAGE_BY_NAME.get(stage, Stage.STACK),
            EventStatus.STARTED,
            message,
            total_findings=self._total,
        )

    def completed(self, stage: str, message: str, finding_count: int | None = None) -> None:
        if finding_count and stage != "synthesis":
            self._total += finding_count
        self._bus.publish(
            self._analysis_id,
            _STAGE_BY_NAME.get(stage, Stage.STACK),
            EventStatus.COMPLETED,
            message,
            finding_count=finding_count,
            total_findings=self._total,
        )

    def failed(self, stage: str, message: str) -> None:
        self._bus.publish(
            self._analysis_id,
            _STAGE_BY_NAME.get(stage, Stage.STACK),
            EventStatus.FAILED,
            message,
            total_findings=self._total,
        )

    def skipped(self, stage: str, message: str) -> None:
        self._bus.publish(
            self._analysis_id,
            _STAGE_BY_NAME.get(stage, Stage.STACK),
            EventStatus.SKIPPED,
            message,
            total_findings=self._total,
        )


@dataclass(slots=True)
class AnalysisRunner:
    """Executes an analysis for one persisted :class:`Analysis` row."""

    settings: Settings
    bus: EventBus
    explainer: Explainer | None = None
    vulnerability_client: VulnerabilityClient | None = None
    importer: RepoImporter | None = None

    async def run(self, session: AsyncSession, analysis_id: uuid.UUID) -> None:
        """Run the analysis, recording the outcome whatever happens."""
        analysis = await session.get(Analysis, analysis_id)
        if analysis is None:
            log.warning("analysis_missing", analysis_id=str(analysis_id))
            return

        project = await session.get(Project, analysis.project_id)
        if project is None:  # pragma: no cover - cascade makes this unreachable
            await self._fail(session, analysis, "The project no longer exists.")
            return

        reporter = EventBusReporter(self.bus, analysis_id)
        started = time.perf_counter()

        analysis.status = AnalysisStatus.RUNNING
        analysis.stage = AnalysisStage.IMPORTING
        analysis.started_at = datetime.now(UTC)
        await session.flush()

        self.bus.publish(
            analysis_id,
            Stage.IMPORTING,
            EventStatus.STARTED,
            f"Importing {project.name}",
        )

        try:
            async with self._import(project) as imported:
                self.bus.publish(
                    analysis_id,
                    Stage.IMPORTING,
                    EventStatus.COMPLETED,
                    f"Imported {imported.file_count} files",
                    data={"file_count": imported.file_count},
                )
                analysis.commit_sha = imported.commit_sha
                analysis.file_count = imported.file_count

                result = await run_workflow(
                    imported.path,
                    explainer=self.explainer or self._default_explainer(),
                    vulnerability_client=self.vulnerability_client
                    or self._default_vulnerability_client(),
                    reporter=reporter,
                )
        except Exception as exc:  # noqa: BLE001 - every failure must be recorded
            log.exception("analysis_failed", analysis_id=str(analysis_id))
            await self._fail(session, analysis, _user_message(exc))
            return

        await self._persist(session, analysis, result, started)

    # -- persistence --------------------------------------------------------

    async def _persist(
        self,
        session: AsyncSession,
        analysis: Analysis,
        result: WorkflowResult,
        started: float,
    ) -> None:
        for finding in result.findings:
            session.add(_to_issue(analysis.id, finding))

        analysis.status = AnalysisStatus.SUCCEEDED
        analysis.stage = None
        analysis.health_score = result.score.score
        analysis.category_scores = result.score.to_dict()
        analysis.stack = {
            **result.stack.to_dict(),
            "notes": result.notes,
            "counts": result.counts,
            "failed_groups": [error.category.value for error in result.group_errors],
            "explanation_sources": result.explanation_sources,
        }
        analysis.completed_at = datetime.now(UTC)
        analysis.duration_ms = int((time.perf_counter() - started) * 1000)
        analysis.ai_explanations_available = result.explanation_sources.get("gemini", 0) > 0
        await session.flush()

        usage = result.explanation_usage
        log.info(
            "analysis_succeeded",
            analysis_id=str(analysis.id),
            findings=len(result.findings),
            score=result.score.score,
            duration_ms=analysis.duration_ms,
            explanation_sources=result.explanation_sources,
            total_tokens=getattr(usage, "total_tokens", 0),
            llm_calls=getattr(usage, "calls", 0),
        )

        self.bus.publish(
            analysis.id,
            Stage.COMPLETE,
            EventStatus.COMPLETED,
            f"Analysis complete: {len(result.findings)} issues, score {result.score.score}",
            total_findings=len(result.findings),
            data={
                "score": result.score.score,
                "failed_groups": [error.category.value for error in result.group_errors],
                "notes": result.notes,
            },
        )

    async def _fail(self, session: AsyncSession, analysis: Analysis, message: str) -> None:
        analysis.status = AnalysisStatus.FAILED
        analysis.stage = None
        analysis.error_message = message
        analysis.completed_at = datetime.now(UTC)
        await session.flush()

        # A terminal event on failure too: a stream that simply stops is
        # indistinguishable from a slow one, and the UI would spin forever.
        self.bus.publish(
            analysis.id,
            Stage.COMPLETE,
            EventStatus.FAILED,
            message,
            data={"error": message},
        )

    # -- dependencies -------------------------------------------------------

    def _import(self, project: Project) -> Any:
        """Open the project's working tree as a context manager."""
        importer = self.importer or RepoImporter(self.settings)
        if project.source_type is SourceType.GITHUB:
            if not project.source_url:  # pragma: no cover - guarded by a CHECK
                raise ValueError("The project has no source URL to import from.")
            token = (
                self.settings.github_token.get_secret_value()
                if self.settings.github_token
                else None
            )
            repo = parse_github_url(project.source_url, ref=project.source_ref)
            return importer.import_github(repo, token=token)

        if not project.upload_path or not Path(project.upload_path).is_file():
            raise FileNotFoundError(
                "The uploaded archive for this project is no longer available. "
                "Re-upload it to analyse the project again."
            )
        return importer.import_zip(Path(project.upload_path))

    def _default_explainer(self) -> Explainer:
        key = (
            self.settings.gemini_api_key.get_secret_value()
            if self.settings.gemini_api_key
            else None
        )
        explainer: Explainer = build_explainer(
            api_key=key,
            model=self.settings.gemini_model,
            timeout_seconds=float(self.settings.gemini_timeout_seconds),
            max_retries=self.settings.gemini_max_retries,
        )
        return explainer

    def _default_vulnerability_client(self) -> VulnerabilityClient:
        return OsvClient(
            api_url=self.settings.osv_api_url,
            timeout=float(self.settings.gemini_timeout_seconds),
        )


def _to_issue(analysis_id: uuid.UUID, finding: Finding) -> Issue:
    """Map a finding onto a persisted issue row."""
    location = finding.primary_location
    metadata = finding.metadata
    return Issue(
        id=uuid.uuid4(),
        analysis_id=analysis_id,
        category=finding.category,
        severity=finding.severity,
        title=finding.title,
        description=finding.description,
        file_path=location.file_path,
        line_start=location.line_start,
        line_end=location.line_end,
        evidence=finding.evidence or None,
        expected=finding.expected,
        actual=finding.actual,
        detected_by=finding.rule_id,
        confidence=finding.confidence,
        fingerprint=finding.fingerprint,
        explanation=metadata.get("explanation"),
        suggested_fix=metadata.get("suggested_fix"),
        explanation_source=metadata.get("explanation_source"),
        fix_before=metadata.get("fix_before"),
        fix_after=metadata.get("fix_after"),
    )


def _user_message(exc: BaseException) -> str:
    """A message safe and useful to show a user.

    Import failures already carry actionable text; anything else is reported
    by type only, because an arbitrary exception string can contain paths,
    queries or credentials.
    """
    from app.services.repo_importer import RepoImportError

    if isinstance(exc, (RepoImportError, FileNotFoundError, ValueError)):
        return str(exc)[:500]
    return f"The analysis failed unexpectedly ({type(exc).__name__})."


def default_explainer_for(settings: Settings) -> Explainer:
    """The explainer a run would use, without constructing a runner.

    Used by the report endpoint to describe the configuration, and by tests.
    """
    if not settings.ai_explanations_enabled:
        return TemplateExplainer()
    key = settings.gemini_api_key.get_secret_value() if settings.gemini_api_key else None
    explainer: Explainer = build_explainer(
        api_key=key,
        model=settings.gemini_model,
        timeout_seconds=float(settings.gemini_timeout_seconds),
        max_retries=settings.gemini_max_retries,
    )
    return explainer
