"""Project request and response models."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.enums import SourceType
from app.services.github import InvalidGitHubUrlError, parse_github_url

ProjectName = Annotated[str, Field(min_length=1, max_length=200)]


class ProjectCreateFromGitHub(BaseModel):
    """Import a public (or token-accessible) GitHub repository."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {"source_url": "https://github.com/tiangolo/fastapi", "source_ref": "master"}
            ]
        },
    )

    source_url: str = Field(
        description="GitHub repository URL. Only github.com is accepted.",
        examples=["https://github.com/owner/repo"],
    )
    source_ref: str | None = Field(
        default=None,
        description="Branch, tag or commit. Defaults to the repository's default branch.",
        max_length=255,
    )
    name: ProjectName | None = Field(
        default=None,
        description="Display name. Defaults to the repository name.",
    )

    @field_validator("source_url")
    @classmethod
    def _validate_github_url(cls, value: str) -> str:
        """Reject non-GitHub and malformed URLs with a 422 rather than a
        failed clone several seconds later."""
        try:
            return parse_github_url(value).canonical_url
        except InvalidGitHubUrlError as exc:
            raise ValueError(str(exc)) from exc

    @field_validator("source_ref")
    @classmethod
    def _blank_ref_is_none(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


class ProjectUpdate(BaseModel):
    """Rename a project. Sources are immutable: re-import instead."""

    model_config = ConfigDict(extra="forbid")

    name: ProjectName


class DetectedStack(BaseModel):
    """Frameworks and tooling identified in the imported tree.

    Mirrors ``app.services.stack_detector.StackReport``. Declared separately so
    the HTTP contract does not shift whenever the detector's internals change.
    """

    model_config = ConfigDict(extra="allow")

    frontend: list[str] = Field(default_factory=list)
    backend: list[str] = Field(default_factory=list)
    database: list[str] = Field(default_factory=list)
    languages: dict[str, int] = Field(
        default_factory=dict,
        description="Source file count per language.",
    )
    package_managers: list[str] = Field(default_factory=list)
    is_monorepo: bool = False


class ProjectRead(BaseModel):
    """A project as the API returns it."""

    model_config = ConfigDict(from_attributes=True, extra="forbid")

    id: uuid.UUID
    name: str
    source_type: SourceType
    source_url: str | None
    source_ref: str | None
    upload_filename: str | None

    detected_stack: dict[str, Any] | None
    commit_sha: str | None
    file_count: int | None
    size_bytes: int | None
    last_imported_at: datetime | None
    import_error: str | None

    created_at: datetime
    updated_at: datetime


class ProjectImportSummary(BaseModel):
    """What a successful import found, returned alongside the project."""

    model_config = ConfigDict(extra="forbid")

    file_count: int = Field(ge=0)
    size_bytes: int = Field(ge=0)
    commit_sha: str | None = None
    duration_ms: int = Field(ge=0)
    skipped_paths: int = Field(
        default=0,
        ge=0,
        description="Archive members rejected as unsafe or ignored by policy.",
    )


class ProjectCreateResponse(BaseModel):
    """Result of a create-and-import request."""

    model_config = ConfigDict(extra="forbid")

    project: ProjectRead
    import_summary: ProjectImportSummary
