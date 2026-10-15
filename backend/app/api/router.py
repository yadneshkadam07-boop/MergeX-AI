"""Aggregate router for the versioned API.

Resource routers (projects, analyses, issues) are registered here as they land
in later phases. Health endpoints are mounted separately at the root so probes
do not depend on the API version prefix.
"""

from __future__ import annotations

from fastapi import APIRouter

api_router = APIRouter()
