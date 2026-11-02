"""Authentication endpoints: register, login (token), and profile (me)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.api.dependencies import AuthRateLimitDep, CurrentUserDep, SessionDep, SettingsDep
from app.core.auth import create_access_token, hash_password, verify_password
from app.models.user import User
from app.schemas.auth import TokenResponse, UserLoginRequest, UserProfileOut, UserRegisterRequest
from app.schemas.common import CONFLICT_RESPONSE, UNPROCESSABLE_RESPONSE

router = APIRouter(prefix="/auth", tags=["auth"])


def _user_to_profile(user: User) -> UserProfileOut:
    return UserProfileOut(
        id=str(user.id),
        email=user.email,
        name=user.display_name,
        displayName=user.display_name,
        avatarUrl=user.avatar_url,
        githubUsername=user.github_username,
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
