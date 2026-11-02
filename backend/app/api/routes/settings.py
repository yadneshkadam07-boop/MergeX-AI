"""User settings router for GET and PUT /settings."""

from __future__ import annotations

import uuid

from fastapi import APIRouter
from sqlalchemy import select

from app.api.dependencies import CurrentUserDep, SessionDep
from app.core.logging import get_logger
from app.models.settings import UserSettingsModel
from app.schemas.contract import UserSettingsChecks, UserSettingsOut, UserSettingsUpdate

router = APIRouter(prefix="/settings", tags=["settings"])
log = get_logger("app.api.settings")


def _to_out(model: UserSettingsModel) -> UserSettingsOut:
    checks_dict = model.checks or {}
    checks = UserSettingsChecks(
        integration=bool(checks_dict.get("integration", True)),
        security=bool(checks_dict.get("security", True)),
        dependencies=bool(checks_dict.get("dependencies", True)),
        deployment=bool(checks_dict.get("deployment", True)),
    )
    return UserSettingsOut(
        displayName=model.display_name,
        email=model.email,
        theme=model.theme,
        githubConnected=model.github_connected,
        githubUsername=model.github_username,
        checks=checks,
        alertSeverity=model.alert_severity,
    )


@router.get(
    "",
    response_model=UserSettingsOut,
    summary="Get user preferences and settings",
)
async def get_settings(
    session: SessionDep,
    current_user: CurrentUserDep,
) -> UserSettingsOut:
    """Return user preferences for the authenticated developer."""
    row = await session.scalar(
        select(UserSettingsModel).where(UserSettingsModel.user_id == current_user.id)
    )
    if row is None:
        return UserSettingsOut(
            displayName=current_user.display_name,
            email=current_user.email,
        )
    return _to_out(row)


@router.put(
    "",
    response_model=UserSettingsOut,
    summary="Save user preferences and settings",
)
async def update_settings(
    payload: UserSettingsUpdate,
    session: SessionDep,
    current_user: CurrentUserDep,
) -> UserSettingsOut:
    """Save or update user preferences and audit checks for the authenticated developer."""
    row = await session.scalar(
        select(UserSettingsModel).where(UserSettingsModel.user_id == current_user.id)
    )
    if row is None:
        row = UserSettingsModel(
            id=uuid.uuid4(),
            user_id=current_user.id,
            display_name=current_user.display_name,
            email=current_user.email,
        )
        session.add(row)

    if payload.display_name is not None:
        row.display_name = payload.display_name
    if payload.email is not None:
        row.email = payload.email
    if payload.theme is not None:
        row.theme = payload.theme
    if payload.github_connected is not None:
        row.github_connected = payload.github_connected
    if payload.github_username is not None:
        row.github_username = payload.github_username
    if payload.checks is not None:
        # Merge or replace checks dict
        existing_checks = dict(row.checks or {})
        existing_checks.update(payload.checks)
        row.checks = existing_checks
    if payload.alert_severity is not None:
        row.alert_severity = payload.alert_severity

    await session.commit()
    await session.refresh(row)

    log.info("user_settings_saved", user_id=str(current_user.id), user_email=row.email)
    return _to_out(row)
