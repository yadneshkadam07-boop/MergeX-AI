"""The LangGraph workflow, run against the real fixture repositories.

Two requirements are proved here, and both are properties of the graph rather
than of any one node:

**The model cannot change the finding set.** The same fixture is analysed with
the template explainer, with a Gemini-shaped explainer, and with an explainer
that returns nonsense, and all three produce byte-identical findings --- same
fingerprints, same order, same severities, same score. Only the attached prose
differs.

**A crashed rule group does not take the run down.** Each of the three groups
is made to raise in turn; the siblings still produce their findings, the
report names the failed category, and the score is computed from what did
work.
"""

from __future__ import annotations

import asyncio
import shutil
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import pytest

from app.agents import graph as graph_module
from app.agents.graph import build_graph, run_workflow
from app.agents.state import GroupError, ProgressReporter, initial_state
from app.analysis.findings import Finding
from app.models.enums import IssueCategory, Severity
from app.services.explanations import (
    Explanation,
    ExplanationResult,
    TemplateExplainer,
    TokenUsage,
)

pytestmark = pytest.mark.anyio

FIXTURES = ["react_fastapi_mismatch", "react_fastapi_schema_drift", "react_fastapi_insecure"]


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class RecordingReporter(ProgressReporter):
    """Captures the progress calls a run makes."""

    def __init__(self) -> None:
        self.events: list[tuple[str, str, int | None]] = []

    def started(self, stage: str, message: str) -> None:
        self.events.append(("started", stage, None))

    def completed(self, stage: str, message: str, finding_count: int | None = None) -> None:
        self.events.append(("completed", stage, finding_count))

    def failed(self, stage: str, message: str) -> None:
        self.events.append(("failed", stage, None))

    def skipped(self, stage: str, message: str) -> None:
        self.events.append(("skipped", stage, None))

    def stages(self, kind: str) -> list[str]:
        return [stage for event, stage, _ in self.events if event == kind]


class FakeGeminiExplainer:
    """Shaped exactly like Gemini's output, with none of the network.

    Returns an explanation for every finding, as a well-behaved model would.
    The point of testing with it is to show that even a *perfectly* behaved
    model leaves the findings untouched.
    """

    def __init__(self) -> None:
        self.seen: list[str] = []

    async def explain(self, findings: Sequence[Finding]) -> ExplanationResult:
        self.seen.extend(f.fingerprint for f in findings)
        return ExplanationResult(
            explanations={
                f.fingerprint: Explanation(
                    fingerprint=f.fingerprint,
                    explanation=f"Model prose for {f.rule_id}.",
                    suggested_fix=f"Model fix at {f.primary_location}.",
                    source="gemini",
                    fix_before="before",
                    fix_after="after",
                )
                for f in findings
            },
            usage=TokenUsage(500, 200, 700, 2),
        )


class HostileExplainer:
    """A model behaving as badly as the schema permits.

    It claims findings that do not exist, omits ones that do, and returns its
    answers in reverse. None of that may alter the report.
    """

    async def explain(self, findings: Sequence[Finding]) -> ExplanationResult:
        explanations = {
            "invented-fingerprint-1": Explanation(
                fingerprint="invented-fingerprint-1",
                explanation="A critical SQL injection nobody found.",
                suggested_fix="Panic.",
                source="gemini",
            ),
            "invented-fingerprint-2": Explanation(
                fingerprint="invented-fingerprint-2",
                explanation="Another invention.",
                suggested_fix="Panic more.",
                source="gemini",
            ),
        }
        for f in reversed(list(findings)[1:]):  # drops the first, reverses the rest
            explanations[f.fingerprint] = Explanation(
                fingerprint=f.fingerprint,
                explanation="Reordered.",
                suggested_fix="Reordered.",
                source="gemini",
            )
        return ExplanationResult(explanations=explanations)


class ExplodingExplainer:
    async def explain(self, findings: Sequence[Finding]) -> ExplanationResult:
        raise RuntimeError("the explainer itself is broken")


def identity(findings: Sequence[Finding]) -> list[tuple[str, str, Severity, str]]:
    """The part of a finding a model must never be able to influence."""
    return [(f.fingerprint, f.rule_id, f.severity, str(f.primary_location)) for f in findings]


# ---------------------------------------------------------------------------


@pytest.fixture
def mixed_repo(tmp_path: Path, fixture_repo: Callable[[str], Path]) -> Path:
    """A repository with defects in all three categories at once.

    Each seeded fixture deliberately exercises one category, which is right
    for rule tests but cannot show that a crash in one group leaves the other
    two intact. This merges the schema-drift repository with the insecure
    one's routes and secrets, so all three groups have real work to do.
    """
    root = tmp_path / "mixed"
    shutil.copytree(fixture_repo("react_fastapi_schema_drift"), root)
    (root / "expected_findings.json").unlink(missing_ok=True)

    insecure = fixture_repo("react_fastapi_insecure")
    for relative in (
        "frontend/src/api/config.ts",
        "backend/app/auth.py",
        "backend/app/main.py",
        "backend/app/routes.py",
        "backend/.env",
    ):
        destination = root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(insecure / relative, destination)
    return root


class TestTheModelCannotChangeTheFindings:
    """The central guarantee of the phase, asserted end to end."""

    @pytest.mark.parametrize("name", FIXTURES)
    async def test_findings_are_identical_with_and_without_gemini(
        self, name: str, fixture_repo: Callable[[str], Path]
    ) -> None:
        root = fixture_repo(name)

        offline = await run_workflow(root, explainer=TemplateExplainer())
        with_model = await run_workflow(root, explainer=FakeGeminiExplainer())

        assert identity(offline.findings) == identity(with_model.findings)
        assert offline.score.score == with_model.score.score
        assert offline.score.severity_counts == with_model.score.severity_counts

    @pytest.mark.parametrize("name", FIXTURES)
    async def test_a_hostile_model_changes_nothing(
        self, name: str, fixture_repo: Callable[[str], Path]
    ) -> None:
        """Inventing, dropping and reordering all fail to alter the report."""
        root = fixture_repo(name)

        offline = await run_workflow(root, explainer=TemplateExplainer())
        hostile = await run_workflow(root, explainer=HostileExplainer())

        assert identity(offline.findings) == identity(hostile.findings)
        assert offline.score.score == hostile.score.score

    async def test_an_invented_finding_never_reaches_the_report(
        self, fixture_repo: Callable[[str], Path]
    ) -> None:
        result = await run_workflow(
            fixture_repo("react_fastapi_insecure"), explainer=HostileExplainer()
        )

        prose = " ".join(str(f.metadata.get("explanation", "")) for f in result.findings)
        assert "SQL injection nobody found" not in prose
        assert all(not f.fingerprint.startswith("invented") for f in result.findings)

    async def test_the_model_only_adds_prose(self, fixture_repo: Callable[[str], Path]) -> None:
        root = fixture_repo("react_fastapi_mismatch")

        offline = await run_workflow(root, explainer=TemplateExplainer())
        with_model = await run_workflow(root, explainer=FakeGeminiExplainer())

        sources = {f.metadata["explanation_source"] for f in with_model.findings}
        assert sources == {"gemini"}
        assert {f.metadata["explanation_source"] for f in offline.findings} == {"template"}
        # Same findings, different prose.
        assert [f.fingerprint for f in offline.findings] == [
            f.fingerprint for f in with_model.findings
        ]

    async def test_every_finding_is_explained(self, fixture_repo: Callable[[str], Path]) -> None:
        result = await run_workflow(
            fixture_repo("react_fastapi_mismatch"), explainer=FakeGeminiExplainer()
        )

        assert result.findings
        assert all(f.metadata.get("explanation") for f in result.findings)
        assert all(f.metadata.get("suggested_fix") for f in result.findings)

    async def test_a_broken_explainer_does_not_fail_the_run(
        self, fixture_repo: Callable[[str], Path]
    ) -> None:
        """Two layers of fallback: the run must survive even this."""
        root = fixture_repo("react_fastapi_mismatch")

        offline = await run_workflow(root, explainer=TemplateExplainer())
        broken = await run_workflow(root, explainer=ExplodingExplainer())

        assert identity(offline.findings) == identity(broken.findings)
        assert all(f.metadata.get("explanation") for f in broken.findings)
        assert any("AI explanations were unavailable" in note for note in broken.notes)

    async def test_the_offline_path_needs_no_explainer_at_all(
        self, fixture_repo: Callable[[str], Path]
    ) -> None:
        """No argument, no API key, no network: still a complete report."""
        result = await run_workflow(fixture_repo("react_fastapi_mismatch"))

        assert result.findings
        assert result.score.score < 100
        assert all(f.metadata["explanation_source"] == "template" for f in result.findings)

    async def test_token_usage_is_reported(self, fixture_repo: Callable[[str], Path]) -> None:
        result = await run_workflow(
            fixture_repo("react_fastapi_mismatch"), explainer=FakeGeminiExplainer()
        )

        assert result.explanation_usage.total_tokens == 700
        assert result.explanation_usage.calls == 2
        assert result.explanation_sources == {"gemini": len(result.findings)}


class TestParallelism:
    async def test_the_three_groups_overlap_in_time(
        self, fixture_repo: Callable[[str], Path], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Proved by overlap, not by timing.

        Each group announces itself and then waits on a barrier that only
        releases once all three have arrived. If the graph ran them
        sequentially this would deadlock, so the timeout is the assertion.
        """
        arrived: list[str] = []
        barrier = asyncio.Barrier(3)

        def instrument(name: str, original: Any) -> Any:
            async def wrapper(state: Any) -> Any:
                arrived.append(name)
                async with asyncio.timeout(5):
                    await barrier.wait()
                return await original(state)

            return wrapper

        for name in ("api_contract_node", "schema_node", "security_node"):
            monkeypatch.setattr(graph_module, name, instrument(name, getattr(graph_module, name)))

        result = await asyncio.wait_for(
            run_workflow(fixture_repo("react_fastapi_mismatch")), timeout=30
        )

        assert sorted(arrived) == ["api_contract_node", "schema_node", "security_node"]
        assert result.score is not None

    async def test_the_synthesiser_waits_for_all_three(
        self, fixture_repo: Callable[[str], Path], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A fan-in that fires early would score an incomplete finding set."""
        order: list[str] = []

        for name, label in [
            ("api_contract_node", "api"),
            ("schema_node", "schema"),
            ("security_node", "security"),
        ]:
            original = getattr(graph_module, name)

            def instrument(label: str, original: Any) -> Any:
                async def wrapper(state: Any) -> Any:
                    update = await original(state)
                    order.append(label)
                    return update

                return wrapper

            monkeypatch.setattr(graph_module, name, instrument(label, original))

        original_factory = graph_module.make_synthesize_node

        def instrumented_factory(explainer: Any) -> Any:
            node = original_factory(explainer)

            async def wrapper(state: Any) -> Any:
                order.append("synthesis")
                return await node(state)

            return wrapper

        monkeypatch.setattr(graph_module, "make_synthesize_node", instrumented_factory)

        await run_workflow(fixture_repo("react_fastapi_mismatch"))

        assert order[-1] == "synthesis"
        assert sorted(order[:3]) == ["api", "schema", "security"]


class TestCrashIsolation:
    """A crash in one rule group must not cost the other two.

    The failure is injected into the *rule engine*, not into the node: the
    node is already wrapped by ``_guard``, so replacing the node would remove
    the very mechanism under test. A rule engine raising is also the realistic
    case -- it is where a parser bug on unusual input would surface.
    """

    GROUPS = [
        ("run_api_contract_rules", IssueCategory.API_CONTRACT, "api"),
        ("run_schema_rules", IssueCategory.SCHEMA, "schema"),
        ("run_security_rules", IssueCategory.SECURITY, "security"),
    ]

    @pytest.mark.parametrize("rule_engine,category,stage", GROUPS)
    async def test_one_group_crashing_leaves_the_others_working(
        self,
        rule_engine: str,
        category: IssueCategory,
        stage: str,
        mixed_repo: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        healthy = await run_workflow(mixed_repo)

        def explode(*args: Any, **kwargs: Any) -> Any:
            raise RuntimeError(f"{rule_engine} is broken")

        monkeypatch.setattr(graph_module, rule_engine, explode)
        reporter = RecordingReporter()

        degraded = await run_workflow(mixed_repo, reporter=reporter)

        # The run completed and produced a report.
        assert degraded.score is not None
        # The failure is named, not swallowed.
        assert [error.category for error in degraded.group_errors] == [category]
        assert degraded.group_errors[0].exception_type == "RuntimeError"
        assert stage in reporter.stages("failed")
        # The surviving groups produced exactly what a healthy run produces,
        # which is the whole point of isolating the failure.
        expected = [f.fingerprint for f in healthy.findings if f.category is not category]
        assert [f.fingerprint for f in degraded.findings] == expected
        assert expected, "the siblings produced nothing, so nothing was proved"
        # The siblings reached their own terminal state, and so did synthesis.
        assert {"api", "schema", "security"} - {stage} <= set(reporter.stages("completed"))
        assert "synthesis" in reporter.stages("completed")

    @pytest.mark.parametrize("rule_engine,category,stage", GROUPS)
    async def test_a_crashed_category_is_not_reported_as_clean(
        self,
        rule_engine: str,
        category: IssueCategory,
        stage: str,
        mixed_repo: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """ "We found nothing" and "we could not look" must never look alike."""

        def explode(*args: Any, **kwargs: Any) -> Any:
            raise RuntimeError("boom")

        monkeypatch.setattr(graph_module, rule_engine, explode)

        result = await run_workflow(mixed_repo)

        assert category in result.failed_categories
        assert any(category.value.replace("_", " ") in note for note in result.notes)
        assert result.is_complete is False
        sub_score = result.score.categories[category.value]
        assert (
            sub_score.analysed is False
        ), "a crashed category must not be scored as analysed and clean"

    async def test_two_groups_crashing_still_leaves_a_report(
        self, mixed_repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def explode(*args: Any, **kwargs: Any) -> Any:
            raise ValueError("boom")

        monkeypatch.setattr(graph_module, "run_schema_rules", explode)
        monkeypatch.setattr(graph_module, "run_security_rules", explode)

        result = await run_workflow(mixed_repo)

        assert {error.category for error in result.group_errors} == {
            IssueCategory.SCHEMA,
            IssueCategory.SECURITY,
        }
        assert result.score is not None
        assert any(f.category is IssueCategory.API_CONTRACT for f in result.findings)

    async def test_all_three_crashing_still_leaves_a_report(
        self, mixed_repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The worst case still produces a report that says what happened."""

        def explode(*args: Any, **kwargs: Any) -> Any:
            raise ValueError("boom")

        for name in (
            "run_api_contract_rules",
            "run_schema_rules",
            "run_security_rules",
        ):
            monkeypatch.setattr(graph_module, name, explode)

        result = await run_workflow(mixed_repo)

        assert result.findings == []
        assert len(result.group_errors) == 3
        assert len(result.notes) >= 3
        assert result.is_complete is False
        # An empty report with every category unanalysed must not read as clean.
        assert all(
            not sub.analysed for sub in result.score.categories.values() if sub.issue_count == 0
        )

    async def test_the_crash_message_is_truncated(
        self, mixed_repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An exception message can contain a lot of source code."""

        def explode(*args: Any, **kwargs: Any) -> Any:
            raise RuntimeError("x" * 5000)

        monkeypatch.setattr(graph_module, "run_security_rules", explode)

        result = await run_workflow(mixed_repo)

        assert len(result.group_errors[0].message) <= 300

    async def test_the_survivors_are_still_explained(
        self, mixed_repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def explode(*args: Any, **kwargs: Any) -> Any:
            raise RuntimeError("boom")

        monkeypatch.setattr(graph_module, "run_security_rules", explode)

        result = await run_workflow(mixed_repo, explainer=FakeGeminiExplainer())

        assert result.findings
        assert all(f.metadata.get("explanation") for f in result.findings)

    async def test_a_crash_in_extraction_is_not_isolated(
        self, mixed_repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Extraction feeds every branch; there is no partial report without it.

        This is deliberate: the three rule groups are isolated from each other,
        but a failure to read the repository at all is a failed analysis, and
        the runner reports it as one rather than publishing an empty report
        that would read as a clean bill of health.
        """

        def explode(*args: Any, **kwargs: Any) -> Any:
            raise OSError("the repository could not be read")

        monkeypatch.setattr(graph_module, "extract_frontend_api_calls", explode)

        with pytest.raises(OSError):
            await run_workflow(mixed_repo)


class TestProgressReporting:
    async def test_every_stage_is_announced(self, fixture_repo: Callable[[str], Path]) -> None:
        reporter = RecordingReporter()

        await run_workflow(fixture_repo("react_fastapi_mismatch"), reporter=reporter)

        started = reporter.stages("started")
        assert "stack" in started
        assert {"api", "schema", "security", "synthesis"} <= set(started)

    async def test_finding_counts_are_reported_per_stage(
        self, fixture_repo: Callable[[str], Path]
    ) -> None:
        """The SSE requirement: a status *and* a finding count per stage."""
        reporter = RecordingReporter()

        result = await run_workflow(fixture_repo("react_fastapi_mismatch"), reporter=reporter)

        counted = {
            stage: count
            for event, stage, count in reporter.events
            if event == "completed" and count is not None
        }
        assert counted.get("synthesis") == len(result.findings)
        assert "api" in counted

    async def test_a_skipped_stage_says_so(self, tmp_path: Path) -> None:
        """An empty repository is not a repository full of problems."""
        (tmp_path / "README.md").write_text("# nothing here\n", encoding="utf-8")
        reporter = RecordingReporter()

        result = await run_workflow(tmp_path, reporter=reporter)

        assert set(reporter.stages("skipped")) >= {"api", "schema"}
        assert result.findings == []
        assert result.score.score == 100
        assert result.notes, "a score of 100 on an empty repo needs an explanation"


class TestWorkflowResult:
    async def test_counts_describe_what_was_examined(
        self, fixture_repo: Callable[[str], Path]
    ) -> None:
        result = await run_workflow(fixture_repo("react_fastapi_mismatch"))

        assert result.counts["frontend_calls"] > 0
        assert result.counts["backend_routes"] > 0

    async def test_the_stack_is_detected(self, fixture_repo: Callable[[str], Path]) -> None:
        result = await run_workflow(fixture_repo("react_fastapi_mismatch"))

        assert "React" in result.stack.frontend
        assert "FastAPI" in result.stack.backend

    async def test_a_duration_is_recorded(self, fixture_repo: Callable[[str], Path]) -> None:
        result = await run_workflow(fixture_repo("react_fastapi_mismatch"))

        assert result.duration_ms >= 0

    async def test_a_clean_run_is_complete(self, tmp_path: Path) -> None:
        result = await run_workflow(tmp_path)

        assert result.group_errors == []

    async def test_findings_are_deduplicated_before_scoring(
        self, fixture_repo: Callable[[str], Path]
    ) -> None:
        result = await run_workflow(fixture_repo("react_fastapi_mismatch"))

        fingerprints = [f.fingerprint for f in result.findings]
        assert len(fingerprints) == len(set(fingerprints))

    async def test_the_graph_compiles_once_per_run(self) -> None:
        """A sanity check that the graph shape itself is valid."""
        compiled = build_graph(TemplateExplainer())

        assert compiled is not None

    async def test_the_initial_state_starts_empty(self, tmp_path: Path) -> None:
        state = initial_state(tmp_path)

        assert state["findings"] == []
        assert state["group_errors"] == []
        assert isinstance(state["reporter"], ProgressReporter)


class TestGroupError:
    def test_it_carries_the_category_and_the_type(self) -> None:
        error = GroupError(
            category=IssueCategory.SECURITY, message="boom", exception_type="ValueError"
        )

        assert error.category is IssueCategory.SECURITY
        assert error.exception_type == "ValueError"
