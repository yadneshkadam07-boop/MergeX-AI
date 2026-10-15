"""Health and readiness response models."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ComponentStatus = Literal["ok", "degraded", "unavailable", "not_configured"]


class LivenessResponse(BaseModel):
    """Answer to 'is the process up?'. Never touches dependencies."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["ok"] = "ok"
    app: str = Field(description="Human-readable application name.")
    version: str = Field(description="Backend package version.")
    environment: str = Field(description="Deployment environment.")
    uptime_seconds: float = Field(ge=0, description="Seconds since process start.")


class ComponentHealth(BaseModel):
    """Health of one dependency."""

    model_config = ConfigDict(extra="forbid")

    status: ComponentStatus
    detail: str | None = Field(default=None, description="Why it is not 'ok'.")


class ReadinessResponse(BaseModel):
    """Answer to 'can this instance serve traffic?'. Probes dependencies."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["ok", "degraded", "unavailable"]
    components: dict[str, ComponentHealth]
