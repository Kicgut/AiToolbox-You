import time
import json
import os

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.ai_workbench import router
from app.ai_workbench.execution.codex_runtime import ExecutionResult
from app.ai_workbench.execution.runtime_coordinator import RuntimeCoordinator
from app.ai_workbench.event_persistence import persist_event
from app.ai_workbench.composer import _request_hash
from app.ai_workbench.storage import connect_workbench_db


def _app(db_path, executor=None):
    app = FastAPI()
    app.include_router(router)
    app.state.ai_workbench_runtime = RuntimeCoordinator(db_path, executor=executor)
    return app


def _profile(db_path, root):
    with connect_workbench_db(db_path) as conn:
        conn.execute(
            "INSERT INTO tool_profiles(id,tool,display_name,config_root,session_root,discovery_source) VALUES('p','codex','p',?,?, 'test')",
            (str(root), str(root)),
        )
        conn.commit()


def _payload(cwd):
    return {"action": "new", "tool": "codex", "profile_id": "p", "cwd": str(cwd), "prompt": "read only"}


def test_runs_api_rejects_without_real_execution_gate(monkeypatch, tmp_path):
    db_path = tmp_path / "gate.db"
    monkeypatch.setenv("AI_WORKBENCH_DB_PATH", str(db_path))
    monkeypatch.delenv("AI_WORKBENCH_REAL_EXECUTION", raising=False)
    _profile(db_path, tmp_path)
    client = TestClient(_app(db_path))
    response = client.post("/api/ai-workbench/runs", json=_payload(tmp_path))
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "real_execution_disabled"
    with connect_workbench_db(db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 0


def test_runs_api_creates_clickable_run_with_fake_executor(monkeypatch, tmp_path):
    db_path = tmp_path / "fake.db"
    monkeypatch.setenv("AI_WORKBENCH_DB_PATH", str(db_path))
    _profile(db_path, tmp_path)
    app = _app(db_path, executor=lambda _run, _step: ExecutionResult(events=[
        {"event_type": "message.completed", "payload": {"text": "ok"}, "source_tool": "codex"},
    ]))
    client = TestClient(app)
    response = client.post("/api/ai-workbench/runs", json=_payload(tmp_path))
    assert response.status_code == 202
    run_id = response.json()["run"]["id"]
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        detail = client.get(f"/api/ai-workbench/runs/{run_id}").json()
        if detail["run"]["state"] == "succeeded":
            break
        time.sleep(0.02)
    assert detail["run"]["state"] == "succeeded"
    assert any(event["event_type"] == "message.completed" for event in detail["events"])
    app.state.ai_workbench_runtime.stop()


def test_run_artifact_download_is_scoped_to_its_run(monkeypatch, tmp_path):
    db_path = tmp_path / "artifacts.db"
    monkeypatch.setenv("AI_WORKBENCH_DB_PATH", str(db_path))
    with connect_workbench_db(db_path) as conn:
        conn.execute("INSERT INTO runs(id,tool,profile_id,mode,execution_path,permission_policy_json,budget_policy_json,state,created_at,config_snapshot_json) VALUES('r','codex','p','new','codex_exec','{}','{}','running','now','{}')")
        saved = persist_event(conn, {"event_id": "large", "run_id": "r", "source_tool": "codex", "event_type": "command.output", "payload": {"output": "x" * 70_000}}, broadcast=None)
        artifact_id = saved["payload"]["artifact"]["artifact_id"]
    client = TestClient(_app(db_path))
    response = client.get(f"/api/ai-workbench/runs/r/artifacts/{artifact_id}")
    assert response.status_code == 200 and len(response.content) > 70_000
    assert client.get(f"/api/ai-workbench/runs/not-r/artifacts/{artifact_id}").status_code == 404
    assert client.delete(f"/api/ai-workbench/runs/r/artifacts/{artifact_id}").json() == {"deleted": artifact_id}
    assert client.get(f"/api/ai-workbench/runs/r/artifacts/{artifact_id}").status_code == 404


def test_p3_10_gate_rejects_before_enqueue_and_consumes_matching_nonce(monkeypatch, tmp_path):
    db_path = tmp_path / "p3-10.db"
    monkeypatch.setenv("AI_WORKBENCH_DB_PATH", str(db_path))
    monkeypatch.setenv("AI_WORKBENCH_EXECUTION_MODE", "p3_10")
    _profile(db_path, tmp_path)
    payload = _payload(tmp_path)
    body_hash = _request_hash({
        "action": "new", "tool": "codex", "profile_id": "p", "session_copy_id": None,
        "cwd": os.path.normcase(os.path.realpath(str(tmp_path))), "model": None,
        "permission_policy": {}, "budget_policy": {}, "prompt": "read only",
    })
    approval = tmp_path / "approval.json"
    approval.write_text(json.dumps({
        "nonce": "gate-nonce", "request_body_hash": body_hash, "expires_at": "2099-01-01T00:00:00Z",
        "allowed_tools": ["codex"], "budget_policy": {}, "max_uses": 1,
    }), encoding="utf-8")
    monkeypatch.setenv("AI_WORKBENCH_P3_10_APPROVAL_FILE", str(approval))
    app = _app(db_path, executor=lambda _run, _step: ExecutionResult())
    client = TestClient(app)
    rejected = client.post("/api/ai-workbench/runs", json=payload)
    assert rejected.status_code == 409 and rejected.json()["detail"]["code"] == "authorization_required"
    with connect_workbench_db(db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 0
    accepted = client.post("/api/ai-workbench/runs", json={**payload, "authorization_nonce": "gate-nonce"})
    assert accepted.status_code == 202
    replay = client.post("/api/ai-workbench/runs", json={**payload, "authorization_nonce": "gate-nonce"})
    assert replay.status_code == 409 and replay.json()["detail"]["code"] == "authorization_consumed"
    app.state.ai_workbench_runtime.stop()
