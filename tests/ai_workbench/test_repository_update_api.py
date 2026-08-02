from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import ai_workbench


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(ai_workbench.router)
    return TestClient(app)


def test_repository_update_status_is_a_read_only_proxy(monkeypatch):
    expected = {"repository_available": True, "checked": True, "update_available": True, "can_apply": True}
    monkeypatch.setattr(ai_workbench, "check_for_updates", lambda *, refresh: {**expected, "checked": refresh})
    response = _client().get("/api/ai-workbench/repository-update?refresh=true")
    assert response.status_code == 200
    assert response.json() == expected


def test_repository_update_settings_round_trip(monkeypatch):
    saved: list[bool] = []
    monkeypatch.setattr(ai_workbench, "load_settings", lambda: {"auto_update_enabled": False})
    monkeypatch.setattr(ai_workbench, "save_settings", lambda *, auto_update_enabled: saved.append(auto_update_enabled) or {"auto_update_enabled": auto_update_enabled})
    client = _client()
    assert client.get("/api/ai-workbench/repository-update/settings").json() == {"auto_update_enabled": False}
    assert client.patch("/api/ai-workbench/repository-update/settings", json={"auto_update_enabled": True}).json() == {"auto_update_enabled": True}
    assert saved == [True]


def test_repository_update_apply_refuses_active_runs(monkeypatch):
    monkeypatch.setattr(ai_workbench, "_active_run_count", lambda: 1)
    response = _client().post("/api/ai-workbench/repository-update/apply")
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "active_runs"


def test_repository_update_apply_returns_restart_requirement(monkeypatch):
    monkeypatch.setattr(ai_workbench, "_active_run_count", lambda: 0)
    monkeypatch.setattr(ai_workbench, "apply_update", lambda: {"updated": True, "restart_required": True, "message": "restart"})
    response = _client().post("/api/ai-workbench/repository-update/apply")
    assert response.status_code == 202
    assert response.json()["restart_required"] is True
