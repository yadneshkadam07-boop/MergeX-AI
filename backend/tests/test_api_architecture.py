"""Tests for GET /api/v1/projects/{project_id}/architecture."""

from __future__ import annotations

import io
import json
import uuid
import zipfile

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.models.enums import AnalysisStatus, IssueCategory, Severity

SAMPLE_TREE = {
    "package.json": json.dumps({"dependencies": {"react": "^18.3.1"}}),
    "backend/requirements.txt": "fastapi==0.111.0\n",
}
MISSING_ID = "0ad4b1a6-0000-4000-8000-000000000000"


def make_zip(members: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in members.items():
            archive.writestr(name, content)
    return buffer.getvalue()


@pytest.fixture
def project_id(client: TestClient) -> str:
    response = client.post(
        "/api/v1/projects/upload",
        files={"file": ("app.zip", make_zip(SAMPLE_TREE), "application/zip")},
    )
    assert response.status_code == 201
    return str(response.json()["project"]["id"])


class TestProjectArchitecture:
    def test_missing_project_returns_404(self, client: TestClient) -> None:
        response = client.get(f"/api/v1/projects/{MISSING_ID}/architecture")
        assert response.status_code == 404

    def test_returns_synthesized_nodes_and_edges(self, client: TestClient, project_id: str) -> None:
        response = client.get(f"/api/v1/projects/{project_id}/architecture")
        assert response.status_code == 200
        data = response.json()
        assert "nodes" in data
        assert "edges" in data

        node_ids = [n["id"] for n in data["nodes"]]
        assert "node_web" in node_ids
        assert "node_api" in node_ids
        assert "node_db" in node_ids

        edge_ids = [e["id"] for e in data["edges"]]
        assert "edge_client_api" in edge_ids
        assert "edge_api_db" in edge_ids

    def test_attaches_issue_ids_and_updates_edge_status(
        self, client: TestClient, project_id: str, settings: Settings
    ) -> None:
        engine = sa.create_engine(settings.database_url.replace("+aiosqlite", ""))
        analysis_id = str(uuid.uuid4()).replace("-", "")
        issue_id = str(uuid.uuid4())
        try:
            with engine.begin() as conn:
                conn.execute(
                    sa.text(
                        "INSERT INTO analyses (id, project_id, status, created_at, updated_at, completed_at, health_score, ai_explanations_available)"
                        " VALUES (:id, :project_id, :status, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 70, 0)"
                    ),
                    {
                        "id": analysis_id,
                        "project_id": project_id.replace("-", ""),
                        "status": AnalysisStatus.SUCCEEDED.value,
                    },
                )
                conn.execute(
                    sa.text(
                        "INSERT INTO issues (id, analysis_id, created_at, updated_at,"
                        " category, severity, status, title, description, detected_by,"
                        " confidence, fingerprint, file_path, line_start)"
                        " VALUES (:id, :analysis_id, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP,"
                        " :category, :severity, :status, :title, :description, :detected_by,"
                        " :confidence, :fingerprint, :file_path, :line_start)"
                    ),
                    {
                        "id": issue_id.replace("-", ""),
                        "analysis_id": analysis_id,
                        "category": IssueCategory.API_CONTRACT.value,
                        "severity": Severity.CRITICAL.value,
                        "status": "open",
                        "title": "API route mismatch",
                        "description": "Endpoint path mismatch between client and server.",
                        "detected_by": "MX-API-001",
                        "confidence": 1.0,
                        "fingerprint": "fp-arch-1",
                        "file_path": "src/lib/api.ts",
                        "line_start": 10,
                    },
                )
        finally:
            engine.dispose()

        response = client.get(f"/api/v1/projects/{project_id}/architecture")
        assert response.status_code == 200
        data = response.json()

        # Web node and API edge should have the issue tagged
        edge_client_api = next(e for e in data["edges"] if e["id"] == "edge_client_api")
        assert issue_id in edge_client_api["issueIds"]
        assert edge_client_api["status"] == "broken"

    def test_synthesizes_chatbot_nlp_architecture(self, client: TestClient) -> None:
        chatbot_tree = {
            "app.py": "from flask import Flask\nimport nltk\napp = Flask(__name__)\n",
            "intents.json": '{"intents": [{"tag": "greeting", "patterns": ["hello"]}]}',
            "requirements.txt": "flask==3.0.0\nnltk==3.8.1\ntorch==2.2.0\n",
        }
        response = client.post(
            "/api/v1/projects/upload",
            files={"file": ("Health-Care-Chatbot.zip", make_zip(chatbot_tree), "application/zip")},
        )
        assert response.status_code == 201
        pid = response.json()["project"]["id"]

        res = client.get(f"/api/v1/projects/{pid}/architecture")
        assert res.status_code == 200
        arch = res.json()

        labels = [n["label"] for n in arch["nodes"]]
        assert any("Chatbot" in l for l in labels)
        assert any("Dialogue" in l or "Server" in l for l in labels)
        assert any("NLP" in l or "Intent" in l for l in labels)
        assert any("Corpus" in l or "Knowledge" in l for l in labels)

    def test_synthesizes_ecommerce_marketplace_architecture(self, client: TestClient) -> None:
        ecommerce_tree = {
            "package.json": json.dumps({
                "name": "fullstack-ecommerce-platform",
                "dependencies": {
                    "react": "^18.2.0",
                    "express": "^4.18.2",
                    "mongoose": "^8.0.0",
                    "stripe": "^14.0.0",
                },
            }),
            "server/models/product.js": "const mongoose = require('mongoose');\n",
        }
        response = client.post(
            "/api/v1/projects/upload",
            files={"file": ("fullstack-ecommerce.zip", make_zip(ecommerce_tree), "application/zip")},
        )
        assert response.status_code == 201
        pid = response.json()["project"]["id"]

        res = client.get(f"/api/v1/projects/{pid}/architecture")
        assert res.status_code == 200
        arch = res.json()

        node_map = {n["id"]: n for n in arch["nodes"]}
        assert "node_web" in node_map
        assert "node_api" in node_map
        assert "node_auth" in node_map
        assert "node_db" in node_map
        assert "node_external" in node_map

        assert "MongoDB" in node_map["node_db"]["tech"]
        assert "Stripe" in node_map["node_external"]["label"]

