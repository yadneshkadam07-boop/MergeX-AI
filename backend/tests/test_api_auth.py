"""Tests for authentication, JWT validation, and per-user resource isolation."""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

from fastapi import status
from fastapi.testclient import TestClient

from app.core.auth import create_access_token
from app.core.config import Settings


class TestAuthRegistration:
    def test_register_success(self, client: TestClient) -> None:
        response = client.post(
            "/api/v1/auth/register",
            json={
                "email": "newdev@mergex.ai",
                "password": "SecurePassword123!",
                "name": "Sarah Connor",
            },
        )
        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"
        assert data["user"]["email"] == "newdev@mergex.ai"
        assert data["user"]["name"] == "Sarah Connor"
        assert "id" in data["user"]

    def test_register_duplicate_email_returns_409(self, client: TestClient) -> None:
        # developer@mergex.ai is seeded in conftest
        response = client.post(
            "/api/v1/auth/register",
            json={
                "email": "developer@mergex.ai",
                "password": "Password123!",
                "name": "Duplicate Dev",
            },
        )
        assert response.status_code == status.HTTP_409_CONFLICT
        assert "already exists" in response.json()["detail"].lower()

    def test_register_invalid_email_returns_422(self, client: TestClient) -> None:
        response = client.post(
            "/api/v1/auth/register",
            json={
                "email": "not-an-email",
                "password": "Password123!",
            },
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    def test_register_short_password_returns_422(self, client: TestClient) -> None:
        response = client.post(
            "/api/v1/auth/register",
            json={
                "email": "valid@mergex.ai",
                "password": "123",
            },
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


class TestAuthLogin:
    def test_login_with_username_success(self, client: TestClient) -> None:
        # Seeded user developer@mergex.ai with password: secretpassword
        # In conftest, password hash is $2b$12$b.we3xq6ykEWvSq5rz2cpu.P/JfIxC5Gm7xfSynZUrr98sdqwKnCe (hash of 'SecretPassword123!')
        # Let's register a known user first to verify roundtrip
        reg = client.post(
            "/api/v1/auth/register",
            json={
                "email": "loginuser@mergex.ai",
                "password": "MySecretPassword1!",
                "name": "Login Tester",
            },
        )
        assert reg.status_code == status.HTTP_201_CREATED

        # Login with username field
        resp = client.post(
            "/api/v1/auth/token",
            json={
                "username": "loginuser@mergex.ai",
                "password": "MySecretPassword1!",
            },
        )
        assert resp.status_code == status.HTTP_200_OK
        data = resp.json()
        assert "access_token" in data
        assert data["user"]["email"] == "loginuser@mergex.ai"

        # Login with email field
        resp_email = client.post(
            "/api/v1/auth/token",
            json={
                "email": "loginuser@mergex.ai",
                "password": "MySecretPassword1!",
            },
        )
        assert resp_email.status_code == status.HTTP_200_OK

    def test_login_wrong_password_returns_401(self, client: TestClient) -> None:
        client.post(
            "/api/v1/auth/register",
            json={
                "email": "wrongpwd@mergex.ai",
                "password": "CorrectPassword1!",
            },
        )
        resp = client.post(
            "/api/v1/auth/token",
            json={
                "email": "wrongpwd@mergex.ai",
                "password": "IncorrectPassword!",
            },
        )
        assert resp.status_code == status.HTTP_401_UNAUTHORIZED
        assert "invalid email or password" in resp.json()["detail"].lower()

    def test_login_unknown_user_returns_401(self, client: TestClient) -> None:
        resp = client.post(
            "/api/v1/auth/token",
            json={
                "email": "nonexistent@mergex.ai",
                "password": "SomePassword123!",
            },
        )
        assert resp.status_code == status.HTTP_401_UNAUTHORIZED


class TestAuthProfile:
    def test_get_me_success(self, client: TestClient) -> None:
        reg = client.post(
            "/api/v1/auth/register",
            json={
                "email": "profile@mergex.ai",
                "password": "SecretPassword1!",
                "name": "Profile Tester",
            },
        )
        token = reg.json()["access_token"]

        resp = client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == status.HTTP_200_OK
        data = resp.json()
        assert data["email"] == "profile@mergex.ai"
        assert data["name"] == "Profile Tester"

    def test_get_me_invalid_token_returns_401(self, client: TestClient) -> None:
        resp = client.get(
            "/api/v1/auth/me",
            headers={"Authorization": "Bearer not-a-valid-jwt-token"},
        )
        assert resp.status_code == status.HTTP_401_UNAUTHORIZED

    def test_get_me_expired_token_returns_401(self, client: TestClient, settings: Settings) -> None:
        expired_token = create_access_token(
            data={"sub": str(uuid.uuid4()), "email": "expired@mergex.ai"},
            secret=settings.jwt_secret,
            algorithm=settings.jwt_algorithm,
            expires_delta=timedelta(seconds=-10),
        )
        resp = client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {expired_token}"},
        )
        assert resp.status_code == status.HTTP_401_UNAUTHORIZED
        assert "expired" in resp.json()["detail"].lower()

    def test_strict_unauthenticated_returns_401_when_anonymous_disabled(
        self, settings_factory: Any, app_factory: Any
    ) -> None:
        strict_settings = settings_factory(allow_anonymous_user=False)
        app = app_factory(strict_settings)
        with TestClient(app) as strict_client:
            resp = strict_client.get("/api/v1/auth/me")
            assert resp.status_code == status.HTTP_401_UNAUTHORIZED

            resp_projects = strict_client.get("/api/v1/projects")
            assert resp_projects.status_code == status.HTTP_401_UNAUTHORIZED


class TestUserResourceIsolation:
    def test_users_cannot_access_each_others_projects(self, client: TestClient) -> None:
        # Create User A and User B
        reg_a = client.post(
            "/api/v1/auth/register",
            json={"email": "usera@mergex.ai", "password": "PasswordA123!"},
        )
        token_a = reg_a.json()["access_token"]

        reg_b = client.post(
            "/api/v1/auth/register",
            json={"email": "userb@mergex.ai", "password": "PasswordB123!"},
        )
        token_b = reg_b.json()["access_token"]

        # User A creates a project via one-step analysis (or upload)
        headers_a = {"Authorization": f"Bearer {token_a}"}
        headers_b = {"Authorization": f"Bearer {token_b}"}

        import io
        import zipfile

        zip_buf = io.BytesIO()
        with zipfile.ZipFile(zip_buf, "w") as zf:
            zf.writestr("package.json", '{"name":"test"}')
        zip_bytes = zip_buf.getvalue()

        resp_create = client.post(
            "/api/v1/projects/upload",
            files={"file": ("project.zip", zip_bytes, "application/zip")},
            data={"name": "User A Private Project"},
            headers=headers_a,
        )
        assert resp_create.status_code == status.HTTP_201_CREATED
        project_id = resp_create.json()["project"]["id"]

        # User A can get it
        get_a = client.get(f"/api/v1/projects/{project_id}", headers=headers_a)
        assert get_a.status_code == status.HTTP_200_OK

        # User B gets 404 (not 403, preventing enumeration)
        get_b = client.get(f"/api/v1/projects/{project_id}", headers=headers_b)
        assert get_b.status_code == status.HTTP_404_NOT_FOUND

        # User B listing projects does not see User A's project
        list_b = client.get("/api/v1/projects", headers=headers_b)
        assert list_b.status_code == status.HTTP_200_OK
        assert not any(p["id"] == project_id for p in list_b.json()["items"])

    def test_settings_isolation_per_user(self, client: TestClient) -> None:
        reg_a = client.post(
            "/api/v1/auth/register",
            json={"email": "alice@mergex.ai", "password": "PasswordA123!", "name": "Alice"},
        )
        token_a = reg_a.json()["access_token"]

        reg_b = client.post(
            "/api/v1/auth/register",
            json={"email": "bob@mergex.ai", "password": "PasswordB123!", "name": "Bob"},
        )
        token_b = reg_b.json()["access_token"]

        headers_a = {"Authorization": f"Bearer {token_a}"}
        headers_b = {"Authorization": f"Bearer {token_b}"}

        # Alice saves settings
        put_a = client.put(
            "/api/v1/settings",
            json={"theme": "dark", "alertSeverity": "critical"},
            headers=headers_a,
        )
        assert put_a.status_code == status.HTTP_200_OK

        # Bob saves different settings
        put_b = client.put(
            "/api/v1/settings",
            json={"theme": "light", "alertSeverity": "low"},
            headers=headers_b,
        )
        assert put_b.status_code == status.HTTP_200_OK

        # Verify Alice's settings
        get_a = client.get("/api/v1/settings", headers=headers_a)
        assert get_a.json()["theme"] == "dark"
        assert get_a.json()["alertSeverity"] == "critical"

        # Verify Bob's settings
        get_b = client.get("/api/v1/settings", headers=headers_b)
        assert get_b.json()["theme"] == "light"
        assert get_b.json()["alertSeverity"] == "low"
