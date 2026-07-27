from fastapi.testclient import TestClient

from app.main import app


def test_rebuild_contract_rejects_unknown_parser_and_timezone():
    client = TestClient(app)
    assert client.post("/api/ai-workbench/statistics/rebuild", json={"parser_version": "future"}).status_code == 400
    assert client.post("/api/ai-workbench/statistics/rebuild", json={"timezone": "No/SuchZone"}).status_code == 400


def test_rebuild_contract_returns_persisted_options():
    client = TestClient(app)
    response = client.post("/api/ai-workbench/statistics/rebuild", json={"timezone": "America/Los_Angeles", "parser_version": "current", "include_pricing_estimates": False})
    assert response.status_code == 200
    assert response.json()["options"]["timezone"] == "America/Los_Angeles"
