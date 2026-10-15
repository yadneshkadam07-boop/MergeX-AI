"""Shared response envelopes and error shapes."""

from __future__ import annotations

from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

ItemT = TypeVar("ItemT")

# Pagination bounds. The default is deliberately small: the dashboard pages.
DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100


class Page(BaseModel, Generic[ItemT]):
    """A slice of a collection, with enough metadata to drive a pager."""

    model_config = ConfigDict(extra="forbid")

    items: list[ItemT]
    total: int = Field(ge=0, description="Total rows matching the query.")
    limit: int = Field(ge=1, le=MAX_PAGE_SIZE)
    offset: int = Field(ge=0)

    @property
    def has_more(self) -> bool:
        return self.offset + len(self.items) < self.total


class ErrorResponse(BaseModel):
    """The shape every non-2xx response takes.

    Mirrors what the exception handlers in ``app.main`` emit, so the generated
    OpenAPI schema is accurate and the frontend has one error type to handle.
    """

    model_config = ConfigDict(extra="forbid")

    error: str = Field(description="Stable machine-readable error code.")
    detail: str | None = Field(default=None, description="Human-readable explanation.")


# Reusable OpenAPI response declarations. The annotation matches FastAPI's
# `responses` parameter, which is invariant in its value type.
OpenApiResponses = dict[int | str, dict[str, Any]]

NOT_FOUND_RESPONSE: OpenApiResponses = {
    404: {"model": ErrorResponse, "description": "Resource does not exist."}
}
CONFLICT_RESPONSE: OpenApiResponses = {
    409: {"model": ErrorResponse, "description": "Conflicts with current state."}
}
RATE_LIMITED_RESPONSE: OpenApiResponses = {
    429: {"model": ErrorResponse, "description": "Rate limit exceeded."}
}
UNPROCESSABLE_RESPONSE: OpenApiResponses = {
    422: {"model": ErrorResponse, "description": "Request failed validation."}
}
