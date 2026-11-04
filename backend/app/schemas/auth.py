"""Schemas for authentication, user profiles, and JWT tokens."""

from __future__ import annotations

import re
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def _validate_email(email_str: str) -> str:
    cleaned = email_str.strip().lower()
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", cleaned):
        raise ValueError("Invalid email format.")
    return cleaned


class UserRegisterRequest(BaseModel):
    """Payload to register a new user account."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    email: str = Field(description="User's email address.")
    password: str = Field(min_length=6, description="Password (at least 6 characters).")
    name: str | None = Field(default=None, alias="displayName", description="Display name.")

    @field_validator("email")
    @classmethod
    def _check_email(cls, v: str) -> str:
        return _validate_email(v)

    @field_validator("name")
    @classmethod
    def _clean_name(cls, v: str | None) -> str | None:
        if v is not None:
            v = v.strip()
            return v or None
        return None


class UserLoginRequest(BaseModel):
    """Payload to authenticate and acquire a JWT."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    username: str | None = Field(default=None, description="Username or email.")
    email: str | None = Field(default=None, description="Email address.")
    password: str = Field(min_length=1, description="Account password.")

    @model_validator(mode="after")
    def _resolve_identity(self) -> UserLoginRequest:
        identity = self.username or self.email
        if not identity or not identity.strip():
            raise ValueError("Either 'username' or 'email' must be provided.")
        return self

    @property
    def account_email(self) -> str:
        ident = self.username or self.email or ""
        return ident.strip().lower()


class GitHubOAuthRequest(BaseModel):
    """Payload containing the GitHub OAuth temporary authorization code."""

    model_config = ConfigDict(extra="ignore")

    code: str = Field(min_length=1, description="GitHub OAuth authorization code.")
    redirect_uri: str | None = Field(
        default=None,
        description="OAuth redirect URI matching the authorization request.",
    )


class UserProfileOut(BaseModel):
    """Authenticated user profile representation."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    id: str = Field(description="User ID.")
    email: str = Field(description="User email address.")
    name: str = Field(description="User display name.")
    displayName: str = Field(description="User display name alias.")
    avatarUrl: str | None = Field(default=None, description="Avatar image URL.")
    githubUsername: str | None = Field(default=None, description="GitHub username.")
    createdAt: datetime | None = Field(default=None, description="Creation timestamp.")


class TokenResponse(BaseModel):
    """Token response returned upon successful authentication."""

    model_config = ConfigDict(extra="ignore")

    access_token: str = Field(description="Signed JWT access token.")
    token_type: str = Field(default="bearer", description="Token type, always bearer.")
    user: UserProfileOut = Field(description="User profile metadata.")
