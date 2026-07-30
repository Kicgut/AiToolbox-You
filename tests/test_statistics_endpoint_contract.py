from fastapi.testclient import TestClient

from app.main import app


def test_statistics_page_dependencies_have_stable_contracts():
    client = TestClient(app)
    paths = [
        "/api/ai-workbench/statistics/overview",
        "/api/ai-workbench/statistics/timeseries",
        "/api/ai-workbench/statistics/breakdown",
        "/api/ai-workbench/statistics/reliability",
        "/api/ai-workbench/statistics/data-quality",
        "/api/ai-workbench/statistics/conflicts",
        "/api/ai-workbench/statistics/cc-switch/capabilities",
        "/api/ai-workbench/statistics/cc-switch/audit",
    ]
    responses = [client.get(path) for path in paths]
    assert all(response.status_code == 200 for response in responses)
    assert "metrics" in responses[0].json()
    assert isinstance(responses[1].json()["data"], list)
    assert isinstance(responses[5].json()["data"], list)


def test_statistics_filters_reject_unknown_source():
    assert TestClient(app).get("/api/ai-workbench/statistics/overview?source=secret").status_code == 400


def test_statistics_metrics_expose_unavailable_as_null_and_distinct_status():
    payload = TestClient(app).get("/api/ai-workbench/statistics/overview").json()
    assert all("availability" in metric and "quality" in metric and "source" in metric for metric in payload["metrics"].values())
    assert all(metric["value"] is None or isinstance(metric["value"], (int, float)) for metric in payload["metrics"].values())
