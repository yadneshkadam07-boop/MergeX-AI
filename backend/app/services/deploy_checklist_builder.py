"""Deployment readiness checklist builder for GET /api/v1/projects/{id}/deploy-checklist.

Evaluates project findings against the four core deployment checklist items:
1. Environment Variables & Secrets Segregation (chk_env_secrets)
2. Container Healthcheck Directives (chk_docker_healthcheck)
3. Cross-Origin Resource Sharing (CORS) Isolation (chk_cors_strict)
4. Database Connection Pool Limits (chk_db_pool)
"""

from __future__ import annotations

from app.models.analysis import Analysis
from app.models.enums import AnalysisStatus, Severity
from app.models.issue import Issue
from app.models.project import Project
from app.schemas.contract import ChecklistItemOut


def build_deploy_checklist(
    _project: Project,
    analysis: Analysis | None,
    issues: list[Issue],
) -> list[ChecklistItemOut]:
    """Derive deployment readiness checklist items from analysis findings."""
    if analysis is None or analysis.status != AnalysisStatus.SUCCEEDED:
        return [
            ChecklistItemOut(
                id="chk_env_secrets",
                label="Environment Variables & Secrets Segregation",
                status="warn",
                detail="Awaiting project analysis run to inspect repository secrets.",
            ),
            ChecklistItemOut(
                id="chk_docker_healthcheck",
                label="Container Healthcheck Directives",
                status="warn",
                detail="Awaiting project analysis run to assess container configuration.",
            ),
            ChecklistItemOut(
                id="chk_cors_strict",
                label="Cross-Origin Resource Sharing (CORS) Isolation",
                status="warn",
                detail="Awaiting project analysis run to verify CORS policies.",
            ),
            ChecklistItemOut(
                id="chk_db_pool",
                label="Database Connection Pool Limits",
                status="warn",
                detail="Awaiting project analysis run to verify database pooling parameters.",
            ),
        ]

    # 1. chk_env_secrets
    secrets_issue = next(
        (
            i
            for i in issues
            if any(
                term in (i.title + " " + i.description).lower()
                for term in ("secret", "api_key", "password", "token", "credential")
            )
        ),
        None,
    )
    if secrets_issue:
        secrets_item = ChecklistItemOut(
            id="chk_env_secrets",
            label="Environment Variables & Secrets Segregation",
            status=(
                "fail" if secrets_issue.severity in (Severity.CRITICAL, Severity.HIGH) else "warn"
            ),
            detail=f"{secrets_issue.title} in {secrets_issue.file_path or 'project tree'}.",
        )
    else:
        secrets_item = ChecklistItemOut(
            id="chk_env_secrets",
            label="Environment Variables & Secrets Segregation",
            status="pass",
            detail="No hardcoded API keys found in repository history or configuration files.",
        )

    # 2. chk_docker_healthcheck
    docker_issue = next(
        (
            i
            for i in issues
            if any(
                term in (i.title + " " + i.description).lower()
                for term in ("healthcheck", "docker", "liveness", "container")
            )
        ),
        None,
    )
    if docker_issue:
        docker_item = ChecklistItemOut(
            id="chk_docker_healthcheck",
            label="Container Healthcheck Directives",
            status="warn",
            detail=docker_issue.description
            or "Dockerfile does not declare a HEALTHCHECK instruction.",
        )
    else:
        docker_item = ChecklistItemOut(
            id="chk_docker_healthcheck",
            label="Container Healthcheck Directives",
            status="pass",
            detail="Container manifests specify automated healthcheck and liveness inspection.",
        )

    # 3. chk_cors_strict
    cors_issue = next(
        (
            i
            for i in issues
            if any(
                term in (i.title + " " + i.description).lower()
                for term in ("cors", "allow_origins", "wildcard origin", "cross-origin")
            )
        ),
        None,
    )
    if cors_issue:
        cors_item = ChecklistItemOut(
            id="chk_cors_strict",
            label="Cross-Origin Resource Sharing (CORS) Isolation",
            status="fail" if cors_issue.severity in (Severity.CRITICAL, Severity.HIGH) else "warn",
            detail=cors_issue.description
            or "CORS policy permits open wildcard '*' access on authenticated routes.",
        )
    else:
        cors_item = ChecklistItemOut(
            id="chk_cors_strict",
            label="Cross-Origin Resource Sharing (CORS) Isolation",
            status="pass",
            detail="CORS policies restrict access to explicit origins without wildcard grants.",
        )

    # 4. chk_db_pool
    pool_issue = next(
        (
            i
            for i in issues
            if any(
                term in (i.title + " " + i.description).lower()
                for term in ("pool", "connection limit", "max_connections", "pool_size")
            )
        ),
        None,
    )
    if pool_issue:
        pool_item = ChecklistItemOut(
            id="chk_db_pool",
            label="Database Connection Pool Limits",
            status="warn",
            detail=pool_issue.description
            or "Database engine does not specify max pool limits or connection timeouts.",
        )
    else:
        pool_item = ChecklistItemOut(
            id="chk_db_pool",
            label="Database Connection Pool Limits",
            status="pass",
            detail="Database engine specifies max pool size and timeout limits.",
        )

    return [secrets_item, docker_item, cors_item, pool_item]
