"""Tests for Stripe billing, checkout, customer portal, and webhooks."""

from __future__ import annotations

import json

from fastapi import status
from fastapi.testclient import TestClient


class TestBillingEndpoints:
    def _get_auth_headers(
        self, client: TestClient, email: str = "billingtest@mergex.ai"
    ) -> dict[str, str]:
        reg = client.post(
            "/api/v1/auth/register",
            json={
                "email": email,
                "password": "SecurePassword123!",
                "name": "Billing Tester",
            },
        )
        token = reg.json()["access_token"]
        return {"Authorization": f"Bearer {token}"}

    def test_get_billing_status_authenticated(self, client: TestClient) -> None:
        headers = self._get_auth_headers(client, "status_user@mergex.ai")
        response = client.get("/api/v1/billing/status", headers=headers)
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["tier"] == "free"
        assert data["monthly_scans_used"] == 0
        assert data["max_scans"] == 5
        assert data["has_active_subscription"] is False

    def test_create_checkout_session_simulated(self, client: TestClient) -> None:
        headers = self._get_auth_headers(client, "checkout_user@mergex.ai")
        response = client.post(
            "/api/v1/billing/checkout",
            json={"plan": "pro"},
            headers=headers,
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "checkout_url" in data
        assert "session_id" in data
        assert "gumroad" in data["checkout_url"] or "simulated=true" in data["checkout_url"]
        assert "checkout_user@mergex.ai" in data["checkout_url"]

    def test_create_portal_session_simulated(self, client: TestClient) -> None:
        headers = self._get_auth_headers(client, "portal_user@mergex.ai")
        response = client.post(
            "/api/v1/billing/portal",
            json={},
            headers=headers,
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "portal_url" in data
        assert "portal_simulated=true" in data["portal_url"]

    def test_gumroad_ping_endpoint(self, client: TestClient) -> None:
        # Register user first
        self._get_auth_headers(client, "gumroad_buyer@mergex.ai")
        # Send simulated Gumroad ping
        ping_payload = {
            "email": "gumroad_buyer@mergex.ai",
            "sale_id": "test_sale_12345",
            "product_name": "MergeX AI Developer Pro",
            "price": "2900",
        }
        response = client.post(
            "/api/v1/billing/gumroad-ping",
            json=ping_payload,
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json().get("received") is True

    def test_stripe_webhook_endpoint(self, client: TestClient) -> None:
        fake_event = {
            "type": "customer.subscription.deleted",
            "data": {"object": {"id": "sub_test123"}},
        }
        response = client.post(
            "/api/v1/billing/webhook",
            content=json.dumps(fake_event).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["status"] in ("ok", "ignored", "processed")
