"""The Gemini client, exercised entirely against a fake transport.

Three things matter here and are each asserted directly:

1. **Structured output or nothing.** A response that does not validate as
   :class:`ExplanationBatch` is never salvaged; it is retried once and then
   replaced by the template for that batch.
2. **The analysis never fails.** Timeouts, 429s, 5xxs, a malformed body, even
   an arbitrary exception from the SDK, all end in explanations being present.
3. **No credential ever reaches the wire.** Every prompt the fake client
   receives is checked against the six credentials seeded in the fixtures.

The fake client records every prompt, which is what makes (3) testable: the
assertion is made on what was actually sent, not on what `redact_prompt` is
believed to do.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from google.genai import errors as genai_errors

from app.agents.graph import run_workflow
from app.analysis.findings import Finding, make_finding
from app.services.explanations import (
    ExplanationBatch,
    ExplanationItem,
    TemplateExplainer,
)
from app.services.gemini import (
    GeminiExplainer,
    GeminiSettings,
    build_explainer,
)
from app.services.parsers.base import SourceLocation
from tests.conftest import FIXTURE_CREDENTIALS

pytestmark = pytest.mark.anyio


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


@dataclass
class FakeUsage:
    prompt_token_count: int = 100
    candidates_token_count: int = 40
    total_token_count: int = 140


@dataclass
class FakeResponse:
    """Stands in for ``types.GenerateContentResponse``.

    Only the three attributes the client reads are provided, deliberately: if
    the client starts depending on something else, these tests should fail.
    """

    parsed: Any = None
    text: str | None = None
    usage_metadata: FakeUsage | None = field(default_factory=FakeUsage)


class FakeModels:
    def __init__(self, outcomes: list[Any]) -> None:
        self._outcomes = list(outcomes)
        self.prompts: list[str] = []
        self.configs: list[Any] = []
        self.models: list[str] = []

    async def generate_content(self, *, model: str, contents: str, config: Any) -> FakeResponse:
        self.prompts.append(contents)
        self.configs.append(config)
        self.models.append(model)
        outcome = self._outcomes.pop(0) if self._outcomes else FakeResponse()
        if isinstance(outcome, BaseException):
            raise outcome
        if callable(outcome):
            return await outcome()  # type: ignore[no-any-return]
        return outcome


class FakeAio:
    def __init__(self, models: FakeModels) -> None:
        self.models = models


class FakeClient:
    """``client.aio.models.generate_content`` is the whole surface used."""

    def __init__(self, *outcomes: Any) -> None:
        self.aio = FakeAio(FakeModels(list(outcomes)))

    @property
    def calls(self) -> int:
        return len(self.aio.models.prompts)

    @property
    def prompts(self) -> list[str]:
        return self.aio.models.prompts


@pytest.fixture(autouse=True)
def no_real_sleeping(monkeypatch: pytest.MonkeyPatch) -> None:
    """Backoff is asserted on separately; nothing else should wait for it."""

    async def instant(_seconds: float) -> None:
        return None

    monkeypatch.setattr(asyncio, "sleep", instant)


def explainer(client: FakeClient, **kwargs: Any) -> GeminiExplainer:
    return GeminiExplainer(
        GeminiSettings(api_key="test-key", timeout_seconds=5.0, **kwargs),
        client=client,  # type: ignore[arg-type]
    )


def finding(
    rule_id: str = "MX-API-001",
    *,
    identity: tuple[Any, ...] = ("GET", "/api/user"),
    snippet: str = 'api.get("/api/user/${id}");',
    metadata: dict[str, Any] | None = None,
) -> Finding:
    return make_finding(
        rule_id,
        identity=identity,
        locations=[
            SourceLocation(
                file_path="frontend/src/api.ts",
                line_start=12,
                line_end=12,
                snippet=snippet,
            )
        ],
        description="The call has no matching backend route.",
        expected="GET /api/users/{id}",
        actual="GET /api/user/{id}",
        metadata=metadata or {"method": "GET", "path": "/api/user/{id}"},
    )


def batch_for(*findings: Finding, **overrides: str) -> FakeResponse:
    """A well-formed response covering exactly the findings given."""
    return FakeResponse(
        parsed=ExplanationBatch(
            items=[
                ExplanationItem(
                    finding_id=f.fingerprint,
                    explanation=overrides.get("explanation", "The path is misspelt."),
                    suggested_fix=overrides.get(
                        "suggested_fix", "At frontend/src/api.ts:12, use /api/users."
                    ),
                    fix_before='api.get("/api/user/${id}");',
                    fix_after='api.get("/api/users/${id}");',
                )
                for f in findings
            ]
        )
    )


# ---------------------------------------------------------------------------


class TestStructuredOutput:
    async def test_the_schema_is_requested(self) -> None:
        """Structured output is a request parameter, not a prompt instruction."""
        target = finding()
        client = FakeClient(batch_for(target))

        await explainer(client).explain([target])

        config = client.aio.models.configs[0]
        assert config.response_schema is ExplanationBatch
        assert config.response_mime_type == "application/json"
        assert config.system_instruction

    async def test_a_parsed_batch_is_used(self) -> None:
        target = finding()
        client = FakeClient(batch_for(target))

        result = await explainer(client).explain([target])

        explanation = result.explanations[target.fingerprint]
        assert explanation.source == "gemini"
        assert explanation.explanation == "The path is misspelt."
        assert explanation.fix_after == 'api.get("/api/users/${id}");'
        assert result.degraded is False

    async def test_raw_json_text_is_validated_and_accepted(self) -> None:
        """Some responses arrive as text the SDK did not coerce."""
        target = finding()
        payload = ExplanationBatch(
            items=[
                ExplanationItem(
                    finding_id=target.fingerprint,
                    explanation="From raw JSON.",
                    suggested_fix="Fix it at frontend/src/api.ts:12.",
                )
            ]
        ).model_dump_json()
        client = FakeClient(FakeResponse(text=payload))

        result = await explainer(client).explain([target])

        assert result.explanations[target.fingerprint].explanation == "From raw JSON."
        assert result.explanations[target.fingerprint].source == "gemini"

    async def test_prose_is_rejected_not_salvaged(self) -> None:
        """A chatty model must not produce a half-parsed explanation."""
        target = finding()
        client = FakeClient(
            FakeResponse(text="Sure! Here is the problem: the path is wrong."),
            FakeResponse(text="Still not JSON."),
        )

        result = await explainer(client).explain([target])

        assert result.explanations[target.fingerprint].source == "template"

    async def test_json_of_the_wrong_shape_is_rejected(self) -> None:
        target = finding()
        client = FakeClient(
            FakeResponse(text='{"explanations": ["a", "b"]}'),
            FakeResponse(text='{"explanations": ["a", "b"]}'),
        )

        result = await explainer(client).explain([target])

        assert result.degraded is True
        assert result.explanations[target.fingerprint].source == "template"

    async def test_an_invented_finding_id_is_dropped(self) -> None:
        """The model cannot add a finding by inventing an id for it."""
        target = finding()
        client = FakeClient(
            FakeResponse(
                parsed=ExplanationBatch(
                    items=[
                        ExplanationItem(
                            finding_id="not-a-real-fingerprint",
                            explanation="An invented finding.",
                            suggested_fix="Do something.",
                        ),
                        ExplanationItem(
                            finding_id=target.fingerprint,
                            explanation="The real one.",
                            suggested_fix="Fix the real one.",
                        ),
                    ]
                )
            )
        )

        result = await explainer(client).explain([target])

        assert set(result.explanations) == {target.fingerprint}

    async def test_an_empty_explanation_falls_back(self) -> None:
        target = finding()
        client = FakeClient(
            FakeResponse(
                parsed=ExplanationBatch(
                    items=[
                        ExplanationItem(
                            finding_id=target.fingerprint,
                            explanation="   ",
                            suggested_fix="",
                        )
                    ]
                )
            )
        )

        result = await explainer(client).explain([target])

        assert result.explanations[target.fingerprint].source == "template"


class TestRetryAndFallback:
    async def test_one_retry_then_the_template(self) -> None:
        """Exactly one retry: two calls, then the template."""
        target = finding()
        client = FakeClient(FakeResponse(text="not json"), FakeResponse(text="still not json"))

        result = await explainer(client).explain([target])

        assert client.calls == 2
        assert result.explanations[target.fingerprint].source == "template"

    async def test_the_retry_succeeds(self) -> None:
        target = finding()
        client = FakeClient(FakeResponse(text="not json"), batch_for(target))

        result = await explainer(client).explain([target])

        assert client.calls == 2
        assert result.explanations[target.fingerprint].source == "gemini"
        assert result.degraded is False

    async def test_a_429_is_retried_with_backoff(self, monkeypatch: pytest.MonkeyPatch) -> None:
        slept: list[float] = []

        async def record(seconds: float) -> None:
            slept.append(seconds)

        monkeypatch.setattr(asyncio, "sleep", record)
        target = finding()
        client = FakeClient(
            genai_errors.ClientError(429, {"error": {"status": "RESOURCE_EXHAUSTED"}}),
            batch_for(target),
        )

        result = await explainer(client).explain([target])

        assert client.calls == 2
        assert len(slept) == 1 and slept[0] > 0, "a 429 must wait before retrying"
        assert result.explanations[target.fingerprint].source == "gemini"

    async def test_a_429_that_persists_falls_back(self) -> None:
        target = finding()
        error = genai_errors.ClientError(429, {"error": {"status": "RESOURCE_EXHAUSTED"}})
        client = FakeClient(error, error)

        result = await explainer(client).explain([target])

        assert result.degraded is True
        assert "429" in (result.degraded_reason or "")
        assert result.explanations[target.fingerprint].source == "template"

    async def test_a_5xx_is_retried(self) -> None:
        target = finding()
        client = FakeClient(
            genai_errors.ServerError(503, {"error": {"status": "UNAVAILABLE"}}),
            batch_for(target),
        )

        result = await explainer(client).explain([target])

        assert client.calls == 2
        assert result.explanations[target.fingerprint].source == "gemini"

    async def test_a_bad_api_key_is_not_retried(self) -> None:
        """A 401 will not fix itself; retrying only adds latency."""
        target = finding()
        client = FakeClient(
            genai_errors.ClientError(401, {"error": {"status": "UNAUTHENTICATED"}}),
            batch_for(target),
        )

        result = await explainer(client).explain([target])

        assert client.calls == 1, "a non-retryable status must fail fast"
        assert result.explanations[target.fingerprint].source == "template"

    async def test_a_timeout_falls_back(self) -> None:
        target = finding()
        client = FakeClient(TimeoutError("deadline exceeded"), TimeoutError("again"))

        result = await explainer(client).explain([target])

        assert "timeout" in (result.degraded_reason or "")
        assert result.explanations[target.fingerprint].source == "template"

    async def test_a_slow_response_is_cut_off_by_the_timeout(self) -> None:
        """The timeout is enforced by the client, not trusted to the SDK.

        The call waits on an event nobody sets, rather than sleeping: this
        module patches ``asyncio.sleep`` to be instant, and a sleep that
        returns immediately would let the test pass without the timeout ever
        firing.
        """
        target = finding()

        async def never_returns() -> FakeResponse:
            await asyncio.Event().wait()
            raise AssertionError("should have been cancelled")

        client = FakeClient(never_returns, never_returns)
        subject = GeminiExplainer(
            GeminiSettings(api_key="k", timeout_seconds=0.05),
            client=client,  # type: ignore[arg-type]
        )

        result = await subject.explain([target])

        assert result.explanations[target.fingerprint].source == "template"
        assert result.degraded is True
        assert "timeout" in (result.degraded_reason or "")

    async def test_an_arbitrary_sdk_exception_falls_back(self) -> None:
        """Anything at all. The analysis must not fail because of the model."""
        target = finding()
        client = FakeClient(RuntimeError("the SDK changed"), RuntimeError("again"))

        result = await explainer(client).explain([target])

        assert result.explanations[target.fingerprint].source == "template"
        assert "RuntimeError" in (result.degraded_reason or "")

    async def test_every_finding_is_explained_however_badly_it_goes(self) -> None:
        findings = [finding(identity=("GET", f"/p{i}")) for i in range(9)]
        client = FakeClient(*[RuntimeError("down")] * 20)

        result = await explainer(client).explain(findings)

        assert {f.fingerprint for f in findings} == set(result.explanations)
        assert all(e.source == "template" for e in result.explanations.values())

    async def test_a_good_batch_survives_a_bad_one(self) -> None:
        """Fallback is per batch, so one failure does not discard good work."""
        findings = [finding(identity=("GET", f"/p{i}")) for i in range(8)]
        first, second = findings[:6], findings[6:]
        client = FakeClient(
            batch_for(*first),
            RuntimeError("down"),
            RuntimeError("down"),
        )

        result = await explainer(client).explain(findings)

        assert all(result.explanations[f.fingerprint].source == "gemini" for f in first)
        assert all(result.explanations[f.fingerprint].source == "template" for f in second)

    async def test_a_partial_batch_is_topped_up(self) -> None:
        """A model answering four of six leaves no finding unexplained."""
        findings = [finding(identity=("GET", f"/p{i}")) for i in range(6)]
        client = FakeClient(batch_for(*findings[:4]))

        result = await explainer(client).explain(findings)

        assert len(result.explanations) == 6
        assert sum(1 for e in result.explanations.values() if e.source == "template") == 2


class TestNoSecretsInPrompts:
    """The requirement: no fixture credential may appear in any prompt.

    Asserted against what the fake client *received*, so this covers the whole
    path from finding construction through batching to prompt building.
    """

    CREDENTIALS = list(FIXTURE_CREDENTIALS)

    @pytest.mark.parametrize("credential", CREDENTIALS)
    async def test_the_credential_never_reaches_the_model(self, credential: str) -> None:
        leaky = finding(
            "MX-SEC-001",
            snippet=f'const KEY = "{credential}";',
            metadata={"variable": "KEY", "secret_kind": "api key", "value": credential},
        )
        client = FakeClient(batch_for(leaky))

        await explainer(client).explain([leaky])

        assert client.prompts, "no prompt was sent"
        for prompt in client.prompts:
            assert credential not in prompt, f"{credential} leaked into the prompt"

    async def test_all_six_at_once(self) -> None:
        findings = [
            finding(
                "MX-SEC-001",
                identity=("MX-SEC-001", str(i)),
                snippet=f'KEY_{i} = "{credential}"',
                metadata={"variable": f"KEY_{i}", "value": credential},
            )
            for i, credential in enumerate(self.CREDENTIALS)
        ]
        client = FakeClient(batch_for(*findings))

        await explainer(client).explain(findings)

        sent = "\n".join(client.prompts)
        leaked = [c for c in self.CREDENTIALS if c in sent]
        assert leaked == [], f"leaked credentials: {leaked}"

    async def test_a_connection_string_password_is_masked(self) -> None:
        url = "postgresql://admin:sup3rs3cretpw@db.example.com:5432/app"
        leaky = finding(
            "MX-SEC-001",
            snippet=f'DATABASE_URL = "{url}"',
            metadata={"variable": "DATABASE_URL", "value": url},
        )
        client = FakeClient(batch_for(leaky))

        await explainer(client).explain([leaky])

        assert "sup3rs3cretpw" not in "\n".join(client.prompts)

    async def test_the_prompt_is_still_useful_after_redaction(self) -> None:
        """Masking must not strip the context the model needs."""
        leaky = finding(
            "MX-SEC-001",
            snippet=f'const STRIPE_KEY = "{self.CREDENTIALS[0]}";',
            metadata={"variable": "STRIPE_KEY"},
        )
        client = FakeClient(batch_for(leaky))

        await explainer(client).explain([leaky])

        prompt = client.prompts[0]
        assert "STRIPE_KEY" in prompt
        assert "frontend/src/api.ts" in prompt
        assert "MX-SEC-001" in prompt


class TestNoSecretsFromTheRealFixture:
    """The same requirement, end to end.

    The class above builds findings by hand, which proves the redaction works
    but not that the pipeline routes every snippet through it. This runs the
    real workflow over the insecure fixture -- the one seeded with live-looking
    credentials -- with the transport faked, and asserts on exactly what the
    client was handed.
    """

    async def test_no_fixture_credential_reaches_the_model(
        self, fixture_repo: Callable[[str], Path]
    ) -> None:
        client = FakeClient(*[FakeResponse(text="not json")] * 40)
        subject = GeminiExplainer(
            GeminiSettings(api_key="k", timeout_seconds=5.0),
            client=client,  # type: ignore[arg-type]
        )

        result = await run_workflow(fixture_repo("react_fastapi_insecure"), explainer=subject)

        assert result.findings, "nothing was analysed, so nothing was proved"
        assert client.prompts, "no prompt was built, so nothing was proved"
        sent = "\n".join(client.prompts)
        leaked = [secret for secret in FIXTURE_CREDENTIALS if secret in sent]
        assert leaked == [], f"credentials sent to the model: {leaked}"

    async def test_the_prompts_still_describe_the_findings(
        self, fixture_repo: Callable[[str], Path]
    ) -> None:
        """Redaction must not have emptied the prompt of its content."""
        client = FakeClient(*[FakeResponse(text="not json")] * 40)
        subject = GeminiExplainer(
            GeminiSettings(api_key="k", timeout_seconds=5.0),
            client=client,  # type: ignore[arg-type]
        )

        await run_workflow(fixture_repo("react_fastapi_insecure"), explainer=subject)

        sent = "\n".join(client.prompts)
        assert "MX-SEC-001" in sent
        assert "STRIPE_SECRET_KEY" in sent, "the variable name is what makes it fixable"
        assert "config.ts" in sent

    async def test_the_report_is_complete_even_though_the_model_failed(
        self, fixture_repo: Callable[[str], Path]
    ) -> None:
        client = FakeClient(*[FakeResponse(text="not json")] * 40)
        subject = GeminiExplainer(
            GeminiSettings(api_key="k", timeout_seconds=5.0),
            client=client,  # type: ignore[arg-type]
        )

        result = await run_workflow(fixture_repo("react_fastapi_insecure"), explainer=subject)

        assert all(f.metadata.get("explanation") for f in result.findings)
        assert all(f.metadata["explanation_source"] == "template" for f in result.findings)


class TestTokenAccounting:
    async def test_usage_is_recorded(self) -> None:
        target = finding()
        client = FakeClient(batch_for(target))

        result = await explainer(client).explain([target])

        assert result.usage.calls == 1
        assert result.usage.prompt_tokens == 100
        assert result.usage.output_tokens == 40
        assert result.usage.total_tokens == 140

    async def test_usage_accumulates_across_batches(self) -> None:
        findings = [finding(identity=("GET", f"/p{i}")) for i in range(12)]
        client = FakeClient(batch_for(*findings[:6]), batch_for(*findings[6:]))

        result = await explainer(client).explain(findings)

        assert result.usage.calls == 2
        assert result.usage.total_tokens == 280

    async def test_a_failed_attempt_still_counts_its_tokens(self) -> None:
        """A rejected response was still paid for and must be visible."""
        target = finding()
        client = FakeClient(FakeResponse(text="not json"), batch_for(target))

        result = await explainer(client).explain([target])

        assert result.usage.calls == 2
        assert result.usage.total_tokens == 280

    async def test_missing_usage_metadata_is_tolerated(self) -> None:
        target = finding()
        client = FakeClient(batch_for(target))
        client.aio.models._outcomes[0].usage_metadata = None

        result = await explainer(client).explain([target])

        assert result.usage.calls == 1
        assert result.usage.total_tokens == 0

    async def test_no_findings_means_no_call(self) -> None:
        client = FakeClient()

        result = await explainer(client).explain([])

        assert client.calls == 0
        assert result.usage.calls == 0


class TestBuildExplainer:
    def test_no_key_means_templates(self) -> None:
        """This is what makes the product work offline."""
        subject = build_explainer(
            api_key=None, model="gemini-2.5-flash", timeout_seconds=60.0, max_retries=1
        )

        assert isinstance(subject, TemplateExplainer)

    @pytest.mark.parametrize("key", ["", "   "])
    def test_a_blank_key_means_templates(self, key: str) -> None:
        subject = build_explainer(
            api_key=key, model="gemini-2.5-flash", timeout_seconds=60.0, max_retries=1
        )

        assert isinstance(subject, TemplateExplainer)

    def test_a_key_means_gemini(self) -> None:
        subject = build_explainer(
            api_key="AIza-not-a-real-key",
            model="gemini-2.5-flash",
            timeout_seconds=30.0,
            max_retries=1,
        )

        assert isinstance(subject, GeminiExplainer)

    async def test_the_offline_explainer_explains_everything(self) -> None:
        findings = [finding(identity=("GET", f"/p{i}")) for i in range(5)]
        subject = build_explainer(api_key=None, model="m", timeout_seconds=1.0, max_retries=0)

        result = await subject.explain(findings)

        assert len(result.explanations) == 5
        assert all(e.explanation for e in result.explanations.values())
