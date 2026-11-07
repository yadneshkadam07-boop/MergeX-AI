"""Aggregate router for the versioned API.

Health endpoints are mounted separately at the root in ``app.main`` so probes
do not depend on the API version prefix.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.routes.analyses import analyses_router, project_analyses_router
from app.api.routes.auth import router as auth_router
from app.api.routes.billing import router as billing_router
from app.api.routes.projects import router as projects_router
from app.api.routes.settings import router as settings_router

api_router = APIRouter()

# Order matters: the nested `/projects/{id}/analyses` routes must be
# registered alongside `/projects`, and FastAPI resolves the more specific
# literal path first regardless of declaration order.
api_router.include_router(auth_router)
api_router.include_router(billing_router)
api_router.include_router(projects_router)
api_router.include_router(project_analyses_router)
api_router.include_router(analyses_router)
api_router.include_router(settings_router)
