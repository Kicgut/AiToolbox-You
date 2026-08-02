import threading
import time

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.ai_workbench import router
from app.ai_workbench.execution.codex_runtime import ExecutionResult
from app.ai_workbench.execution.runtime_coordinator import RuntimeCoordinator
from app.ai_workbench.storage import connect_workbench_db


def _app(db_path, executor):
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


def test_run_stream_replays_then_delivers_live_events(monkeypatch, tmp_path):
    db_path = tmp_path / "stream.db"
    monkeypatch.setenv("AI_WORKBENCH_DB_PATH", str(db_path))
    _profile(db_path, tmp_path)
    entered, release = threading.Event(), threading.Event()

    def executor(_run, _step):
        entered.set()
        assert release.wait(2.0)
        return ExecutionResult(events=[{"event_type": "message.completed", "payload": {"text": "done"}, "source_tool": "codex"}])

    app = _app(db_path, executor)
    client = TestClient(app)
    created = client.post("/api/ai-workbench/runs", json={
        "action": "new", "tool": "codex", "profile_id": "p", "cwd": str(tmp_path), "cwd_confirmed": True, "prompt": "read only",
    }).json()["run"]
    assert entered.wait(2.0)
    with client.websocket_connect(f"/api/ai-workbench/runs/{created['id']}/stream?last_sequence_no=0") as socket:
        snapshot = socket.receive_json()
        assert snapshot["type"] == "hello"
        assert snapshot["connection_id"] and snapshot["high_watermark"] >= 1
        assert snapshot["events"]
        cursor = max(event["sequence_no"] for event in snapshot["events"])
        release.set()
        received = []
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            message = socket.receive_json()
            received.extend(message.get("events", []))
            if any(event["event_type"] == "message.completed" for event in received):
                break
        assert any(event["event_type"] == "message.completed" for event in received)
    detail = client.get(f"/api/ai-workbench/runs/{created['id']}?last_sequence_no={cursor}").json()
    assert detail["run"]["state"] == "succeeded"
    assert all(event["sequence_no"] > cursor for event in detail["events"])
    app.state.ai_workbench_runtime.stop()


def test_run_events_endpoint_pages_history(monkeypatch, tmp_path):
    db_path = tmp_path / "history.db"
    monkeypatch.setenv("AI_WORKBENCH_DB_PATH", str(db_path))
    _profile(db_path, tmp_path)
    app = _app(db_path, lambda _run, _step: ExecutionResult(events=[]))
    client = TestClient(app)
    created = client.post("/api/ai-workbench/runs", json={
        "action": "new", "tool": "codex", "profile_id": "p", "cwd": str(tmp_path), "cwd_confirmed": True, "prompt": "read only",
    }).json()["run"]
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        detail = client.get(f"/api/ai-workbench/runs/{created['id']}").json()
        if detail["run"]["state"] == "succeeded":
            break
        time.sleep(0.02)
    response = client.get(f"/api/ai-workbench/runs/{created['id']}/events?after_sequence=0&limit=1")
    assert response.status_code == 200
    payload = response.json()
    assert len(payload["events"]) == 1
    assert payload["has_more"] is True
    app.state.ai_workbench_runtime.stop()
