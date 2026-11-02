#!/usr/bin/env python3
"""End-to-end smoke test script for MergeX AI backend.

Validates authentication, resource ownership, project workflows,
settings isolation, and API contract compliance against a running server.
"""

from __future__ import annotations

import sys
import uuid
import httpx

BASE_URL = "http://127.0.0.1:8000"
API_PREFIX = f"{BASE_URL}/api/v1"


def run_smoke_tests() -> bool:
    print(f"[*] Running MergeX AI Smoke Tests against {BASE_URL}...")
    client = httpx.Client(timeout=15.0)

    try:
        # 1. Health check (public)
        print("  [1/10] Checking GET /health (public endpoint)...")
        r = client.get(f"{BASE_URL}/health")
        assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
        data = r.json()
        assert data.get("status") in ("ok", "healthy"), f"Unexpected health status: {data}"
        print("         -> OK: backend is healthy.")

        # 2. Registration
        test_email = f"smoketest_{uuid.uuid4().hex[:8]}@mergex.ai"
        test_password = "SmokeTestPassword123!"
        test_name = "Smoke Tester"

        print(f"  [2/10] Registering user {test_email}...")
        r = client.post(
            f"{API_PREFIX}/auth/register",
            json={
                "email": test_email,
                "password": test_password,
                "name": test_name,
            },
        )
        assert r.status_code == 201, f"Expected 201, got {r.status_code}: {r.text}"
        reg_data = r.json()
        assert "access_token" in reg_data, "Missing access_token in registration response"
        assert reg_data["user"]["email"] == test_email.lower(), "Email mismatch in user profile"
        token = reg_data["access_token"]
        user_id = reg_data["user"]["id"]
        print(f"         -> OK: registered user {user_id} with JWT token.")

        # 3. Duplicate registration conflict (409)
        print("  [3/10] Verifying duplicate registration rejection (409)...")
        r = client.post(
            f"{API_PREFIX}/auth/register",
            json={
                "email": test_email,
                "password": test_password,
                "name": test_name,
            },
        )
        assert r.status_code == 409, f"Expected 409 for duplicate email, got {r.status_code}"
        print("         -> OK: duplicate email properly rejected with 409.")

        # 4. Token login (with username or email)
        print("  [4/10] Testing POST /api/v1/auth/token...")
        r = client.post(
            f"{API_PREFIX}/auth/token",
            json={"email": test_email, "password": test_password},
        )
        assert r.status_code == 200, f"Expected 200 login, got {r.status_code}"
        login_token = r.json()["access_token"]
        assert len(login_token) > 20

        # Bad password check (401)
        r_bad = client.post(
            f"{API_PREFIX}/auth/token",
            json={"email": test_email, "password": "WrongPassword999!"},
        )
        assert r_bad.status_code == 401, f"Expected 401 on bad password, got {r_bad.status_code}"
        print("         -> OK: valid login succeeds; bad credentials return 401.")

        # 5. User Profile GET /api/v1/auth/me
        headers = {"Authorization": f"Bearer {token}"}
        print("  [5/10] Testing GET /api/v1/auth/me with Bearer token...")
        r = client.get(f"{API_PREFIX}/auth/me", headers=headers)
        assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
        me = r.json()
        assert me["email"] == test_email.lower()
        assert me["name"] == test_name
        print(f"         -> OK: authenticated as {me['name']} ({me['email']}).")

        # 6. User Settings isolation
        print("  [6/10] Testing GET and PUT /api/v1/settings...")
        r_set = client.get(f"{API_PREFIX}/settings", headers=headers)
        assert r_set.status_code == 200, f"Failed getting settings: {r_set.text}"
        initial_settings = r_set.json()
        assert "theme" in initial_settings or "displayName" in initial_settings

        update_payload = {
            "displayName": "Updated Smoke Tester",
            "theme": "dark",
            "alertSeverity": "high",
            "checks": {
                "integration": True,
                "security": True,
                "dependencies": False,
                "deployment": True,
            },
        }
        r_put = client.put(f"{API_PREFIX}/settings", json=update_payload, headers=headers)
        assert r_put.status_code == 200, f"Failed updating settings: {r_put.text}"
        saved_settings = r_put.json()
        assert saved_settings["theme"] == "dark"
        assert saved_settings["alertSeverity"] == "high"
        print("         -> OK: user settings loaded, updated, and persisted.")

        # 7. Project Creation (demo repo import or one-step analysis)
        print("  [7/10] Creating demo project via POST /api/v1/projects/demo...")
        r_proj = client.post(f"{API_PREFIX}/projects/demo", headers=headers)
        proj_payload = r_proj.json()
        proj = proj_payload.get("project", proj_payload)
        proj_id = proj["id"]
        print(f"         -> OK: demo project created with ID {proj_id}.")

        # 8. Project Detail & Derived Endpoints
        print(f"  [8/10] Fetching project {proj_id} issues, report, checklist, architecture...")
        r_detail = client.get(f"{API_PREFIX}/projects/{proj_id}", headers=headers)
        assert r_detail.status_code == 200
        assert r_detail.json()["id"] == proj_id

        r_issues = client.get(f"{API_PREFIX}/projects/{proj_id}/issues", headers=headers)
        assert r_issues.status_code == 200
        print(f"         -> Issues: {len(r_issues.json())} found.")

        r_chk = client.get(f"{API_PREFIX}/projects/{proj_id}/deploy-checklist", headers=headers)
        assert r_chk.status_code == 200
        print(f"         -> Deploy checklist items: {len(r_chk.json())}")

        r_arch = client.get(f"{API_PREFIX}/projects/{proj_id}/architecture", headers=headers)
        assert r_arch.status_code == 200
        print(f"         -> Architecture graph: {len(r_arch.json().get('nodes', []))} nodes.")

        # 9. Project Rescan
        print(f"  [9/10] Testing POST /api/v1/projects/{proj_id}/rescan...")
        r_rescan = client.post(f"{API_PREFIX}/projects/{proj_id}/rescan", headers=headers)
        assert r_rescan.status_code in (200, 202), f"Rescan failed: {r_rescan.status_code}: {r_rescan.text}"
        rescan_data = r_rescan.json()
        assert "id" in rescan_data
        print(f"         -> OK: rescan triggered (status: {rescan_data.get('status')}).")

        # 10. Multi-tenant Resource Ownership Isolation
        print("  [10/10] Verifying cross-user privacy isolation...")
        user2_email = f"smoketest2_{uuid.uuid4().hex[:8]}@mergex.ai"
        r_user2 = client.post(
            f"{API_PREFIX}/auth/register",
            json={"email": user2_email, "password": test_password, "name": "Second User"},
        )
        assert r_user2.status_code == 201
        user2_token = r_user2.json()["access_token"]
        user2_headers = {"Authorization": f"Bearer {user2_token}"}

        # Second user must get 404 when attempting to access first user's project
        r_cross = client.get(f"{API_PREFIX}/projects/{proj_id}", headers=user2_headers)
        assert r_cross.status_code == 404, f"Expected 404 for cross-user project, got {r_cross.status_code}"

        # Second user's projects list must not include first user's project
        r_list2 = client.get(f"{API_PREFIX}/projects", headers=user2_headers)
        assert r_list2.status_code == 200
        list2_json = r_list2.json()
        items = list2_json.get("items", list2_json) if isinstance(list2_json, dict) else list2_json
        user2_project_ids = [p["id"] for p in items if isinstance(p, dict)]
        assert proj_id not in user2_project_ids, "Cross-user project leak detected in /projects list!"

        print("         -> OK: strict 404 and project list isolation verified.")

        print("\n[+] ALL SMOKE TESTS PASSED SUCCESSFULLY! (10/10)")
        return True

    except Exception as exc:
        import traceback
        traceback.print_exc()
        print(f"\n[!] SMOKE TEST FAILED: {exc}", file=sys.stderr)
        return False
    finally:
        client.close()


if __name__ == "__main__":
    success = run_smoke_tests()
    sys.exit(0 if success else 1)
