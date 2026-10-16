"""Gemini explanation client.

The model is an *enhancement layer*. Everything about this module is built so
that its failure is invisible to the user:

* a malformed response is retried once, then falls back to the template for
  that batch only -- good batches are kept;
* a timeout, a 429 or a 5xx falls back the same way, after backoff;
* a missing API key means the client is never constructed at all;
* every finding is guaranteed an explanation, because the template explainer
  fills whatever Gemini did not return.

Nothing here can change the finding set. The client is handed findings and
returns explanations keyed by fingerprint; the caller matches them back. An
invented ``finding_id`` matches nothing and is dropped.

Token usage is accumulated per analysis and logged, because an LLM feature
with no cost visibility is one nobody can run in production.
"""

from __future__ import annotations

import asyncio
import random
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Final

from google import genai
from google.genai import errors as genai_errors, types

from app.analysis.findings import Finding
from app.core.logging import get_logger
from app.services.explanations import (
    SYSTEM_INSTRUCTION,
    Explanation,
    ExplanationBatch,
    ExplanationResult,
    TemplateExplainer,
    TokenUsage,
    batch_findings,
    build_batch_prompt,
    estimate_tokens,
)

__all__ = ["GeminiExplainer", "GeminiSettings"]

log = get_logger("app.gemini")

SOURCE: Final[str] = "gemini"

# One retry, as specified: a malformed or failed response is usually transient
# or a one-off formatting slip, and a second failure means the template is the
# better answer than a third attempt's latency.
_ATTEMPTS: Final[int] = 2
_BACKOFF_BASE_SECONDS: Final[float] = 1.5
_BACKOFF_MAX_SECONDS: Final[float] = 20.0

# HTTP statuses worth waiting and retrying for, as opposed to failing fast.
_RETRYABLE_STATUSES: Final[frozenset[int]] = frozenset({408, 429, 500, 502, 503, 504})


@dataclass(frozen=True, slots=True)
class GeminiSettings:
    """Everything the client needs, pulled out so tests can vary it."""

    api_key: str
    model: str = "gemini-2.5-flash"
    timeout_seconds: float = 60.0
    max_retries: int = 1
    temperature: float = 0.2
    max_output_tokens: int = 4096


class GeminiExplainer:
    """Explains findings with Gemini, falling back to templates.

    Args:
        settings: Model and transport configuration.
        client: An existing ``genai.Client``; supplied by tests.
        fallback: Used for any batch Gemini could not answer. Defaults to the
            template explainer, which never fails.
    """

    def __init__(
        self,
        settings: GeminiSettings,
        *,
        client: genai.Client | None = None,
        fallback: TemplateExplainer | None = None,
    ) -> None:
        self._settings = settings
        self._fallback = fallback or TemplateExplainer()
        self._client = client or genai.Client(
            api_key=settings.api_key,
            http_options=types.HttpOptions(timeout=int(settings.timeout_seconds * 1000)),
        )

    async def explain(self, findings: Sequence[Finding]) -> ExplanationResult:
        """Explain every finding, guaranteeing one explanation each."""
        if not findings:
            return ExplanationResult()

        result = ExplanationResult()
        batches = batch_findings(list(findings))
        failures: list[str] = []

        for batch in batches:
            explanations, usage, error = await self._explain_batch(batch)
            result.usage = result.usage.plus(usage)

            if error is not None:
                failures.append(error)
                fallback = await self._fallback.explain(batch)
                result.explanations.update(fallback.explanations)
                continue

            # Keep only explanations that match a finding in this batch. An
            # id the model invented refers to nothing and is discarded.
            wanted = {finding.fingerprint for finding in batch}
            matched = {
                fingerprint: explanation
                for fingerprint, explanation in explanations.items()
                if fingerprint in wanted
            }
            result.explanations.update(matched)

            missing = [finding for finding in batch if finding.fingerprint not in matched]
            if missing:
                log.warning(
                    "gemini_incomplete_batch",
                    requested=len(batch),
                    returned=len(matched),
                    missing=len(missing),
                )
                fallback = await self._fallback.explain(missing)
                result.explanations.update(fallback.explanations)

        if failures:
            result.degraded = True
            result.degraded_reason = failures[0]

        log.info(
            "gemini_explanations_complete",
            findings=len(findings),
            batches=len(batches),
            calls=result.usage.calls,
            prompt_tokens=result.usage.prompt_tokens,
            output_tokens=result.usage.output_tokens,
            total_tokens=result.usage.total_tokens,
            sources=result.source_counts,
            degraded=result.degraded,
        )
        return result

    async def _explain_batch(
        self, batch: Sequence[Finding]
    ) -> tuple[dict[str, Explanation], TokenUsage, str | None]:
        """One batch, with a single retry. Never raises."""
        prompt = build_batch_prompt(batch)
        usage = TokenUsage()
        last_error = "unknown error"

        for attempt in range(_ATTEMPTS):
            if attempt:
                await self._sleep_before_retry(attempt)

            try:
                response = await self._generate(prompt)
            except genai_errors.APIError as exc:
                last_error = f"{type(exc).__name__}: {_describe(exc)}"
                status = getattr(exc, "code", None) or getattr(exc, "status_code", None)
                log.warning(
                    "gemini_call_failed", attempt=attempt + 1, status=status, error=last_error
                )
                if status is not None and int(status) not in _RETRYABLE_STATUSES:
                    # A bad key or a rejected request will not be fixed by
                    # trying again; fall back immediately.
                    break
                continue
            except TimeoutError as exc:
                last_error = f"timeout after {self._settings.timeout_seconds:.0f}s"
                log.warning("gemini_timeout", attempt=attempt + 1, error=str(exc))
                continue
            except Exception as exc:  # noqa: BLE001 - the analysis must survive anything
                last_error = f"{type(exc).__name__}: {exc}"
                log.warning("gemini_unexpected_error", attempt=attempt + 1, error=last_error)
                continue

            usage = usage.plus(_usage_of(response))

            parsed = _parse_response(response)
            if parsed is None:
                last_error = "response did not match the expected JSON schema"
                log.warning("gemini_invalid_output", attempt=attempt + 1)
                continue

            return (_to_explanations(parsed), usage, None)

        return ({}, usage, last_error)

    async def _generate(self, prompt: str) -> types.GenerateContentResponse:
        """Issue one request with a structured-output schema and a timeout."""
        config = types.GenerateContentConfig(
            system_instruction=SYSTEM_INSTRUCTION,
            response_mime_type="application/json",
            response_schema=ExplanationBatch,
            temperature=self._settings.temperature,
            max_output_tokens=self._settings.max_output_tokens,
        )
        log.debug(
            "gemini_request",
            model=self._settings.model,
            estimated_prompt_tokens=estimate_tokens(prompt),
        )
        return await asyncio.wait_for(
            self._client.aio.models.generate_content(
                model=self._settings.model, contents=prompt, config=config
            ),
            timeout=self._settings.timeout_seconds,
        )

    async def _sleep_before_retry(self, attempt: int) -> None:
        """Exponential backoff with jitter.

        Jitter matters for 429s specifically: several analyses retrying in
        lockstep would re-create the burst that triggered the limit.
        """
        delay = min(_BACKOFF_BASE_SECONDS * (2 ** (attempt - 1)), _BACKOFF_MAX_SECONDS)
        delay *= 0.5 + random.random()  # noqa: S311 - jitter, not cryptography
        log.debug("gemini_backoff", attempt=attempt + 1, seconds=round(delay, 2))
        await asyncio.sleep(delay)


def _describe(exc: BaseException) -> str:
    """A short, safe description of an API error.

    Deliberately truncated: a provider error body can echo part of the request
    back, and the request contains source code.
    """
    return str(exc)[:200]


def _usage_of(response: types.GenerateContentResponse) -> TokenUsage:
    metadata = getattr(response, "usage_metadata", None)
    if metadata is None:
        return TokenUsage(calls=1)
    return TokenUsage(
        prompt_tokens=int(getattr(metadata, "prompt_token_count", 0) or 0),
        output_tokens=int(getattr(metadata, "candidates_token_count", 0) or 0),
        total_tokens=int(getattr(metadata, "total_token_count", 0) or 0),
        calls=1,
    )


def _parse_response(response: types.GenerateContentResponse) -> ExplanationBatch | None:
    """Validate the response against the schema.

    The SDK populates ``parsed`` when the response matches ``response_schema``.
    Falling back to parsing ``text`` covers the case where the model returns
    valid JSON that the SDK did not coerce -- but anything that does not
    validate as :class:`ExplanationBatch` is rejected rather than salvaged.
    """
    parsed = getattr(response, "parsed", None)
    if isinstance(parsed, ExplanationBatch):
        return parsed
    if isinstance(parsed, dict):
        try:
            return ExplanationBatch.model_validate(parsed)
        except Exception:  # noqa: BLE001 - any validation failure means fall back
            return None

    text = getattr(response, "text", None)
    if not text:
        return None
    try:
        return ExplanationBatch.model_validate_json(text)
    except Exception:  # noqa: BLE001
        return None


def _to_explanations(batch: ExplanationBatch) -> dict[str, Explanation]:
    """Convert validated items into explanations, dropping empty ones."""
    explanations: dict[str, Explanation] = {}
    for item in batch.items:
        if not item.finding_id or not item.explanation.strip():
            continue
        explanations[item.finding_id] = Explanation(
            fingerprint=item.finding_id,
            explanation=item.explanation.strip(),
            suggested_fix=item.suggested_fix.strip(),
            source=SOURCE,
            fix_before=item.fix_before.strip() or None,
            fix_after=item.fix_after.strip() or None,
        )
    return explanations


def build_explainer(
    *,
    api_key: str | None,
    model: str,
    timeout_seconds: float,
    max_retries: int,
) -> Any:
    """Choose an explainer for the configured environment.

    Returns the template explainer when no key is set, which is what makes the
    product work offline rather than merely degrade.
    """
    if not api_key or not api_key.strip():
        log.info("explainer_selected", explainer="template", reason="no_api_key")
        return TemplateExplainer()

    log.info("explainer_selected", explainer="gemini", model=model)
    return GeminiExplainer(
        GeminiSettings(
            api_key=api_key,
            model=model,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
        )
    )
