import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_health_endpoint():
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["service"] == "CodeMate"


def test_dashboard_endpoint():
    response = client.get("/")
    assert response.status_code == 200
    assert "CodeMate" in response.text
    assert "Autonomous Repository Auditor" in response.text


def test_cancel_nonexistent_audit():
    response = client.post("/api/v1/audit/nonexistent-id/cancel")
    assert response.status_code == 404
