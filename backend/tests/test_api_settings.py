"""Tests for GET and PUT /api/v1/settings."""

from __future__ import annotations

from fastapi.testclient import TestClient


class TestUserSettings:
    def test_get_settings_default_values(self, client: TestClient) -> None:
        response = client.get("/api/v1/settings")
        assert response.status_code == 200
        data = response.json()
        assert data["displayName"] == "Alex Vance"
        assert data["email"] == "developer@mergex.ai"
        assert data["theme"] == "system"
        assert data["githubConnected"] is False
        assert data["alertSeverity"] == "high"
        assert data["checks"] == {
            "integration": True,
            "security": True,
            "dependencies": True,
            "deployment": True,
        }

    def test_put_settings_updates_and_persists(self, client: TestClient) -> None:
        payload = {
            "displayName": "Sarah Connor",
            "email": "sarah@cyberdyne.io",
            "theme": "dark",
            "githubConnected": True,
            "githubUsername": "sarah-c",
            "checks": {
                "integration": True,
                "security": True,
                "dependencies": False,
                "deployment": True,
            },
            "alertSeverity": "critical",
        }
        res = client.put("/api/v1/settings", json=payload)
        assert res.status_code == 200
        saved = res.json()
        assert saved["displayName"] == "Sarah Connor"
        assert saved["email"] == "sarah@cyberdyne.io"
        assert saved["theme"] == "dark"
        assert saved["githubConnected"] is True
        assert saved["githubUsername"] == "sarah-c"
        assert saved["checks"]["dependencies"] is False
        assert saved["alertSeverity"] == "critical"

        # Verify persisted via subsequent GET
        get_res = client.get("/api/v1/settings")
        assert get_res.status_code == 200
        get_data = get_res.json()
        assert get_data["displayName"] == "Sarah Connor"
        assert get_data["theme"] == "dark"
        assert get_data["checks"]["dependencies"] is False

    def test_partial_put_settings_updates_only_provided_fields(self, client: TestClient) -> None:
        res = client.put("/api/v1/settings", json={"theme": "light"})
        assert res.status_code == 200
        assert res.json()["theme"] == "light"
        # Other fields should stay intact
        assert res.json()["email"] is not None
