"""Authentication endpoints: register, login (token), and profile (me)."""

from __future__ import annotations

import secrets
import uuid

import httpx
from fastapi import APIRouter, HTTPException, status
from sqlalchemy import or_, select

from app.api.dependencies import AuthRateLimitDep, CurrentUserDep, SessionDep, SettingsDep
from app.core.auth import create_access_token, hash_password, verify_password
from app.core.logging import get_logger
from app.models.user import User
from app.schemas.auth import (
    GitHubOAuthRequest,
    TokenResponse,
    UserLoginRequest,
    UserProfileOut,
    UserRegisterRequest,
)
from app.schemas.common import CONFLICT_RESPONSE, UNPROCESSABLE_RESPONSE

log = get_logger("app.api.routes.auth")

router = APIRouter(prefix="/auth", tags=["auth"])


def _user_to_profile(user: User) -> UserProfileOut:
    return UserProfileOut(
        id=str(user.id),
        email=user.email,
        name=user.display_name,
        displayName=user.display_name,
        avatarUrl=user.avatar_url,
        githubUsername=user.github_username,
        tier=getattr(user, "tier", "free") or "free",
        monthlyScansUsed=getattr(user, "monthly_scans_used", 0) or 0,
        createdAt=user.created_at,
    )


@router.post(
    "/register",
    response_model=TokenResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new developer account",
    responses={**CONFLICT_RESPONSE, **UNPROCESSABLE_RESPONSE},
)
async def register(
    body: UserRegisterRequest,
    session: SessionDep,
    settings: SettingsDep,
    _: AuthRateLimitDep,
) -> TokenResponse:
    """Create a new user account, hash the password, and return an access token."""
    cleaned_email = body.email.strip().lower()

    # Check for existing account
    existing = await session.scalar(select(User).where(User.email == cleaned_email))
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"An account with email '{cleaned_email}' already exists.",
        )

    display_name = body.name or cleaned_email.split("@")[0] or "MergeX Developer"
    user = User(
        id=uuid.uuid4(),
        email=cleaned_email,
        password_hash=hash_password(body.password),
        display_name=display_name,
    )
    session.add(user)
    await session.flush()
    await session.refresh(user)

    token = create_access_token(
        data={"sub": str(user.id), "email": user.email},
        secret=settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
        expiry_minutes=settings.jwt_expiry_minutes,
    )

    return TokenResponse(
        access_token=token,
        token_type="bearer",
        user=_user_to_profile(user),
    )


@router.post(
    "/token",
    response_model=TokenResponse,
    summary="Obtain a JWT access token via email and password",
    responses={**UNPROCESSABLE_RESPONSE},
)
async def login_token(
    body: UserLoginRequest,
    session: SessionDep,
    settings: SettingsDep,
    _: AuthRateLimitDep,
) -> TokenResponse:
    """Authenticate with username or email and password, returning an access token."""
    account_email = body.account_email

    user = await session.scalar(select(User).where(User.email == account_email))
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = create_access_token(
        data={"sub": str(user.id), "email": user.email},
        secret=settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
        expiry_minutes=settings.jwt_expiry_minutes,
    )

    return TokenResponse(
        access_token=token,
        token_type="bearer",
        user=_user_to_profile(user),
    )


@router.post(
    "/github",
    response_model=TokenResponse,
    summary="Exchange GitHub OAuth code for a JWT access token",
    responses={**UNPROCESSABLE_RESPONSE},
)
async def login_github(
    body: GitHubOAuthRequest,
    session: SessionDep,
    settings: SettingsDep,
    _: AuthRateLimitDep,
) -> TokenResponse:
    """Exchange a temporary GitHub OAuth authorization code for user profile and issue JWT."""
    client_id = settings.github_client_id
    client_secret = (
        settings.github_client_secret.get_secret_value() if settings.github_client_secret else None
    )

    if not client_id or not client_secret:
        log.error("github_oauth_missing_credentials")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="GitHub OAuth is not configured on the server.",
        )

    async with httpx.AsyncClient(timeout=20.0) as client:
        token_payload = {
            "client_id": client_id,
            "client_secret": client_secret,
            "code": body.code,
        }
        if body.redirect_uri:
            token_payload["redirect_uri"] = body.redirect_uri

        token_resp = await client.post(
            "https://github.com/login/oauth/access_token",
            json=token_payload,
            headers={"Accept": "application/json", "User-Agent": "MergeX-AI"},
        )
        if token_resp.status_code != 200:
            log.warning("github_token_exchange_http_error", status_code=token_resp.status_code)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Failed to communicate with GitHub token service.",
            )

        token_data = token_resp.json()
        if "error" in token_data:
            log.warning("github_token_exchange_error", error=token_data.get("error"))
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=token_data.get("error_description", "Invalid or expired GitHub code."),
            )

        github_token = token_data.get("access_token")
        if not github_token:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="GitHub did not return an access token.",
            )

        gh_headers = {
            "Authorization": f"Bearer {github_token}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "MergeX-AI",
        }

        user_resp = await client.get("https://api.github.com/user", headers=gh_headers)
        if user_resp.status_code != 200:
            log.warning("github_fetch_user_failed", status_code=user_resp.status_code)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Failed to retrieve GitHub profile.",
            )

        gh_user = user_resp.json()
        gh_login = gh_user.get("login")
        if not gh_login:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="GitHub account has no valid username.",
            )

        gh_name = gh_user.get("name")
        gh_avatar = gh_user.get("avatar_url")
        gh_email = gh_user.get("email")

        if not gh_email:
            emails_resp = await client.get(
                "https://api.github.com/user/emails",
                headers=gh_headers,
            )
            if emails_resp.status_code == 200:
                emails_list = emails_resp.json()
                for item in emails_list:
                    if item.get("primary") and item.get("verified"):
                        gh_email = item.get("email")
                        break
                if not gh_email and emails_list:
                    gh_email = emails_list[0].get("email")

        if not gh_email:
            gh_email = f"{gh_login}@users.noreply.github.com"

    cleaned_email = gh_email.strip().lower()

    # Find existing user by github_username or email
    user = await session.scalar(
        select(User).where(or_(User.github_username == gh_login, User.email == cleaned_email))
    )

    if user is None:
        user = User(
            id=uuid.uuid4(),
            email=cleaned_email,
            password_hash=hash_password(secrets.token_urlsafe(32)),
            display_name=gh_name or gh_login or "MergeX Developer",
            avatar_url=gh_avatar,
            github_username=gh_login,
        )
        session.add(user)
    else:
        if not user.github_username:
            user.github_username = gh_login
        if gh_avatar and not user.avatar_url:
            user.avatar_url = gh_avatar
        if gh_name and (not user.display_name or user.display_name == "MergeX Developer"):
            user.display_name = gh_name

    await session.flush()
    await session.refresh(user)

    token = create_access_token(
        data={"sub": str(user.id), "email": user.email},
        secret=settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
        expiry_minutes=settings.jwt_expiry_minutes,
    )

    log.info("github_oauth_success", user_id=str(user.id), github_username=gh_login)
    return TokenResponse(
        access_token=token,
        token_type="bearer",
        user=_user_to_profile(user),
    )


@router.get(
    "/me",
    response_model=UserProfileOut,
    summary="Get currently authenticated developer profile",
)
async def get_current_user_profile(
    current_user: CurrentUserDep,
) -> UserProfileOut:
    """Return the profile of the user identified by the Bearer access token."""
    return _user_to_profile(current_user)
