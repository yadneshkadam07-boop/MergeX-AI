"""One real call to Gemini. Skipped by default.

Everything else in the suite fakes the transport, which proves the plumbing
but not that the model can actually fill the schema with useful prose. This
runs the real pipeline over ``react_fastapi_mismatch`` and asserts the three
properties that cost real money to verify: the response validates against the
schema, the finding set is unchanged, and no credential was sent.

Run it with::

    MERGEX_LIVE_LLM=1 GEMINI_API_KEY=... pytest -m llm tests/test_gemini_live.py -s

``-s`` prints the model's output, which is the point of running it at all.
"""

from __future__ import annotations

import json
import os
import textwrap
from collections.abc import Callable
from pathlib import Path

import pytest

from app.agents.graph import run_workflow
from app.services.explanations import TemplateExplainer, build_batch_prompt
from app.services.gemini import GeminiExplainer, GeminiSettings
from tests.conftest import FIXTURE_CREDENTIALS

pytestmark = [
    pytest.mark.llm,
    pytest.mark.anyio,
    pytest.mark.skipif(
        os.getenv("MERGEX_LIVE_LLM") != "1" or not os.getenv("GEMINI_API_KEY"),
        reason=(
            "Live Gemini test. Set MERGEX_LIVE_LLM=1 and GEMINI_API_KEY to run it; "
            "it makes a real, billable API call."
        ),
    ),
]


def live_explainer() -> GeminiExplainer:
    return GeminiExplainer(
        GeminiSettings(
            api_key=os.environ["GEMINI_API_KEY"],
            model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
            timeout_seconds=90.0,
        )
    )


def show(title: str, body: str) -> None:
    print(f"\n{'=' * 78}\n{title}\n{'=' * 78}\n{body}")


class TestLiveGemini:
    async def test_the_model_explains_the_fixture(
        self, fixture_repo: Callable[[str], Path]
    ) -> None:
        root = fixture_repo("react_fastapi_mismatch")

        offline = await run_workflow(root, explainer=TemplateExplainer())
        live = await run_workflow(root, explainer=live_explainer())

        show(
            "PROMPT (first batch, as actually sent)",
            build_batch_prompt(offline.findings),
        )
        for finding in live.findings:
            show(
                f"{finding.rule_id}  {finding.severity.value}  " f"{finding.primary_location}",
                textwrap.dedent(
                    f"""\
                    source:      {finding.metadata.get("explanation_source")}
                    title:       {finding.title}

                    explanation: {finding.metadata.get("explanation")}

                    fix:         {finding.metadata.get("suggested_fix")}

                    before:      {finding.metadata.get("fix_before")}
                    after:       {finding.metadata.get("fix_after")}"""
                ),
            )
        usage = live.explanation_usage
        show(
            "TOKEN USAGE",
            json.dumps(
                {
                    "calls": usage.calls,
                    "prompt_tokens": usage.prompt_tokens,
                    "output_tokens": usage.output_tokens,
                    "total_tokens": usage.total_tokens,
                    "sources": live.explanation_sources,
                },
                indent=2,
            ),
        )

        # 1. The finding set is identical to the offline run.
        assert [f.fingerprint for f in live.findings] == [f.fingerprint for f in offline.findings]
        assert [f.severity for f in live.findings] == [f.severity for f in offline.findings]
        assert live.score.score == offline.score.score

        # 2. The model, not the template, produced the prose.
        assert (
            live.explanation_sources.get("gemini", 0) > 0
        ), f"Gemini returned nothing usable: {live.notes}"

        # 3. Every explanation is substantive and names its own file.
        for finding in live.findings:
            if finding.metadata.get("explanation_source") != "gemini":
                continue
            explanation = str(finding.metadata.get("explanation", ""))
            fix = str(finding.metadata.get("suggested_fix", ""))
            assert len(explanation) > 60, f"{finding.rule_id}: explanation is a stub"
            assert (
                finding.primary_location.file_path in fix
            ), f"{finding.rule_id}: the fix does not name the file it applies to"

        # 4. Tokens were accounted for.
        assert usage.calls > 0
        assert usage.total_tokens > 0

    async def test_no_credential_is_sent_to_the_real_api(
        self, fixture_repo: Callable[[str], Path]
    ) -> None:
        """The insecure fixture, against the real endpoint."""
        root = fixture_repo("react_fastapi_insecure")

        result = await run_workflow(root, explainer=live_explainer())

        returned = json.dumps(
            [
                {
                    "explanation": f.metadata.get("explanation"),
                    "fix": f.metadata.get("suggested_fix"),
                    "before": f.metadata.get("fix_before"),
                    "after": f.metadata.get("fix_after"),
                }
                for f in result.findings
            ]
        )
        show("INSECURE FIXTURE, LIVE OUTPUT", returned)

        leaked = [secret for secret in FIXTURE_CREDENTIALS if secret in returned]
        assert leaked == [], f"the model echoed credentials back: {leaked}"
