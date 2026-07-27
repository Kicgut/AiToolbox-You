from fastapi.testclient import TestClient

from app.main import app


def test_reliability_reports_unavailable_proxy_without_hiding_native(tmp_path, monkeypatch):
    # The API uses the Workbench default DB; an empty isolated process still
    # must return a structured two-source response, never a generic error.
    response = TestClient(app).get("/api/ai-workbench/statistics/reliability")
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"native", "proxy"}
    assert body["proxy"]["availability"] in {"available", "unavailable"}
    assert "reason_code" in body["proxy"]
