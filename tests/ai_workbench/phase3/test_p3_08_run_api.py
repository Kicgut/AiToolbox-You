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
from app.ai_workbench.approval import create_approval
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
    return {"action": "new", "tool": "codex", "profile_id": "p", "cwd": str(cwd), "cwd_confirmed": True, "prompt": "read only"}


def test_runs_api_rejects_without_real_execution_gate(monkeypatch, tmp_path):
    db_path = tmp_path / "gate.db"
    monkeypatch.setenv("AI_WORKBENCH_DB_PATH", str(db_path))
    monkeypatch.delenv("AI_WORKBENCH_REAL_EXECUTION", raising=False)
    _profile(db_path, tmp_path)
    client = TestClient(_app(db_path))
    response = client.post("/api/ai-workbench/runs", json=_payload(tmp_path))
    assert response.status_code == 409
    assert response.json()["code"] == "real_execution_disabled"


def test_profiles_api_exposes_observed_capability_baseline(monkeypatch, tmp_path):
    db_path = tmp_path / "profiles.db"
    monkeypatch.setenv("AI_WORKBENCH_DB_PATH", str(db_path))
    _profile(db_path, tmp_path)
    with connect_workbench_db(db_path) as conn:
        conn.execute(
            "INSERT INTO runtime_capability_baselines(observed_at,payload_json) VALUES(?,?)",
            ("2026-08-01T00:00:00Z", json.dumps({"codex": {"status": "missing", "features": {"app_server": False}}})),
        )
        conn.commit()
    response = TestClient(_app(db_path)).get("/api/ai-workbench/profiles")
    assert response.status_code == 200
    item = response.json()["data"][0]
    assert item["observed_capabilities"]["features"]["app_server"] is False
    assert item["observed_capabilities_at"] == "2026-08-01T00:00:00Z"
    with connect_workbench_db(db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 0


def test_run_api_errors_use_the_public_error_envelope(monkeypatch, tmp_path):
    db_path = tmp_path / "error-envelope.db"
    monkeypatch.setenv("AI_WORKBENCH_DB_PATH", str(db_path))
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    missing = client.get("/api/ai-workbench/runs/missing")
    unavailable = client.post("/api/ai-workbench/runs", json={
        "action": "new", "tool": "codex", "profile_id": "p", "cwd": str(tmp_path), "cwd_confirmed": True, "prompt": "read only",
    })
    for response in (missing, unavailable):
        assert set(response.json()) == {"code", "message", "details", "retryable"}
    assert missing.json()["code"] == "run_not_found"
    assert unavailable.status_code == 503 and unavailable.json()["code"] == "runtime_unavailable"


def test_run_api_validation_errors_use_the_public_error_envelope(monkeypatch, tmp_path):
    db_path = tmp_path / "validation-envelope.db"
    monkeypatch.setenv("AI_WORKBENCH_DB_PATH", str(db_path))
    response = TestClient(_app(db_path)).post("/api/ai-workbench/runs", json={"action": "invalid"})
    assert response.status_code == 422
    assert set(response.json()) == {"code", "message", "details", "retryable"}
    assert response.json()["code"] == "invalid_request" and response.json()["details"]["errors"]


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


def test_run_detail_returns_structured_approval_evidence(monkeypatch, tmp_path):
    db_path = tmp_path / "approval-detail.db"
    monkeypatch.setenv("AI_WORKBENCH_DB_PATH", str(db_path))
    with connect_workbench_db(db_path) as conn:
        conn.execute("INSERT INTO runs(id,tool,profile_id,mode,execution_path,permission_policy_json,budget_policy_json,state,created_at,config_snapshot_json) VALUES('r','codex','p','new','codex_exec','{}','{}','waiting_approval','now','{}')")
        conn.execute("INSERT INTO run_steps(id,run_id,ordinal,prompt_text,state) VALUES('s','r',1,'x','waiting_approval')")
        create_approval(conn, run_id="r", step_id="s", native_request_id="n", operation="command", target_summary="status", risk_level="high", command_argv=["git", "status", "--short"], cwd=str(tmp_path), affected_paths=["README.md"], expires_at="2099-01-01T00:00:00Z")
    detail = TestClient(_app(db_path)).get("/api/ai-workbench/runs/r").json()
    approval = detail["approvals"][0]
    assert approval["command_argv"] == ["git", "status", "--short"]
    assert approval["affected_paths"] == ["README.md"]
    assert "command_argv_json" not in approval and "affected_paths_json" not in approval


def test_approval_decision_rejects_a_run_without_native_approval(monkeypatch, tmp_path):
    db_path = tmp_path / "approval-capability.db"
    monkeypatch.setenv("AI_WORKBENCH_DB_PATH", str(db_path))
    with connect_workbench_db(db_path) as conn:
        conn.execute("INSERT INTO runs(id,tool,profile_id,mode,execution_path,permission_policy_json,budget_policy_json,capabilities_snapshot_json,state,created_at,config_snapshot_json) VALUES('r','claude','p','new','claude_step_process','{}','{}','{\"native_approval\":false}','waiting_approval','now','{}')")
        conn.execute("INSERT INTO run_steps(id,run_id,ordinal,prompt_text,state) VALUES('s','r',1,'x','waiting_approval')")
        request_id = create_approval(conn, run_id="r", step_id="s", native_request_id="n", operation="command", target_summary="x", risk_level="high")["id"]
    response = TestClient(_app(db_path)).post(f"/api/ai-workbench/approvals/{request_id}/decision", json={"decision": "accept", "decided_by": "ignored"})
    assert response.status_code == 409 and response.json()["code"] == "capability_not_supported"
    with connect_workbench_db(db_path) as conn:
        assert conn.execute("SELECT state FROM approval_requests WHERE id=?", (request_id,)).fetchone()[0] == "pending"


def test_runs_api_uses_stable_cursor_and_filters(monkeypatch, tmp_path):
    db_path = tmp_path / "runs-page.db"
    monkeypatch.setenv("AI_WORKBENCH_DB_PATH", str(db_path))
    with connect_workbench_db(db_path) as conn:
        for run_id, created_at, tool, profile_id in (
            ("r3", "2026-01-03T00:00:00Z", "codex", "p"),
            ("r2", "2026-01-02T00:00:00Z", "claude", "q"),
            ("r1", "2026-01-01T00:00:00Z", "codex", "p"),
        ):
            conn.execute("INSERT INTO runs(id,tool,profile_id,mode,execution_path,permission_policy_json,budget_policy_json,state,created_at,config_snapshot_json) VALUES(?,?,?,'new','codex_exec','{}','{}','queued',?,'{}')", (run_id, tool, profile_id, created_at))
        conn.execute("INSERT INTO run_events(event_id,run_id,sequence_no,event_type,timestamp,payload_json,source_tool,persisted_at) VALUES('latest','r3',1,'message.completed','2026-01-03T00:01:00Z','{}','codex','now')")
        conn.commit()
    client = TestClient(_app(db_path))
    first = client.get("/api/ai-workbench/runs?limit=1&tool=codex&profile_id=p").json()
    assert [row["id"] for row in first["data"]] == ["r3"] and first["next_cursor"]
    assert first["data"][0]["latest_event_type"] == "message.completed"
    second = client.get(f"/api/ai-workbench/runs?limit=1&tool=codex&profile_id=p&cursor={first['next_cursor']}").json()
    assert [row["id"] for row in second["data"]] == ["r1"] and second["next_cursor"] is None
    invalid = client.get("/api/ai-workbench/runs?cursor=not-a-cursor")
    assert invalid.status_code == 400 and invalid.json()["code"] == "invalid_cursor"


def test_run_api_exposes_budget_enforcement_strength(monkeypatch, tmp_path):
    db_path = tmp_path / "budget-strength.db"
    monkeypatch.setenv("AI_WORKBENCH_DB_PATH", str(db_path))
    with connect_workbench_db(db_path) as conn:
        conn.execute("INSERT INTO runs(id,tool,profile_id,mode,execution_path,permission_policy_json,budget_policy_json,state,created_at,config_snapshot_json) VALUES('r','codex','p','new','codex_exec','{}','{\"max_turns\":1,\"max_duration_seconds\":60,\"max_total_tokens_observed\":20}','queued','now','{}')")
        conn.commit()
    run = TestClient(_app(db_path)).get("/api/ai-workbench/runs/r").json()["run"]
    strengths = {item["name"]: item["strength"] for item in run["budget_limits"]}
    assert strengths == {"max_turns": "hard", "max_duration_seconds": "hard", "max_total_tokens_observed": "observed_only"}
    availability = {item["name"]: item["availability"] for item in run["budget_limits"]}
    assert availability == {"max_turns": "exact", "max_duration_seconds": "exact", "max_total_tokens_observed": "estimated"}


def test_p3_10_gate_rejects_before_enqueue_and_consumes_matching_nonce(monkeypatch, tmp_path):
    db_path = tmp_path / "p3-10.db"
    monkeypatch.setenv("AI_WORKBENCH_DB_PATH", str(db_path))
    monkeypatch.setenv("AI_WORKBENCH_EXECUTION_MODE", "p3_10")
    _profile(db_path, tmp_path)
    payload = _payload(tmp_path)
    body_hash = _request_hash({
        "action": "new", "tool": "codex", "profile_id": "p", "session_copy_id": None,
        "cwd": os.path.normcase(os.path.realpath(str(tmp_path))), "cwd_confirmed": True, "model": None,
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
    assert rejected.status_code == 409 and rejected.json()["code"] == "authorization_required"
    with connect_workbench_db(db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 0
    accepted = client.post("/api/ai-workbench/runs", json={**payload, "authorization_nonce": "gate-nonce"})
    assert accepted.status_code == 202
    replay = client.post("/api/ai-workbench/runs", json={**payload, "authorization_nonce": "gate-nonce"})
    assert replay.status_code == 409 and replay.json()["code"] == "authorization_consumed"
    app.state.ai_workbench_runtime.stop()
