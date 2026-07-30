import threading
import time

import pytest

from app.ai_workbench.composer import compose_run, request_cancel
from app.ai_workbench.execution.codex_runtime import ExecutionResult
from app.ai_workbench.execution.runtime_coordinator import RuntimeCoordinator
from app.ai_workbench.storage import connect_workbench_db
from app.ai_workbench.storage import SessionBusyError
from app.ai_workbench.approval import decide_approval


def _wait_for(db_path, run_id, states, timeout=3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with connect_workbench_db(db_path) as conn:
            row = conn.execute("SELECT state FROM runs WHERE id=?", (run_id,)).fetchone()
            if row and row["state"] in states:
                return row["state"]
        time.sleep(0.02)
    raise AssertionError(f"run {run_id} did not reach {states}")


def _create_run(db_path, cwd):
    with connect_workbench_db(db_path) as conn:
        conn.execute(
            "INSERT INTO tool_profiles(id,tool,display_name,config_root,session_root,discovery_source) "
            "VALUES('p','codex','p',?,?, 'test')",
            (str(cwd), str(cwd)),
        )
        conn.commit()
        return compose_run(conn, action="new", tool="codex", profile_id="p", cwd=str(cwd), prompt="read only")["run"]


def test_coordinator_persists_visible_lifecycle_and_output(tmp_path):
    db_path = tmp_path / "runtime.db"
    run = _create_run(db_path, tmp_path)

    def executor(_run, _step):
        return ExecutionResult(events=[
            {"event_type": "message.delta", "payload": {"text_delta": "hello"}, "source_tool": "codex"},
            {"event_type": "message.completed", "payload": {"text": "hello"}, "source_tool": "codex"},
        ])

    coordinator = RuntimeCoordinator(db_path, executor=executor)
    coordinator.enqueue(run["id"])
    assert _wait_for(db_path, run["id"], {"succeeded"}) == "succeeded"
    coordinator.stop()

    with connect_workbench_db(db_path) as conn:
        events = conn.execute("SELECT event_type FROM run_events WHERE run_id=? ORDER BY sequence_no", (run["id"],)).fetchall()
        assert [event["event_type"] for event in events] == [
            "run.status_changed", "run.status_changed", "message.delta", "message.completed", "run.status_changed",
        ]


def test_coordinator_finishes_a_requested_cancellation(tmp_path):
    db_path = tmp_path / "cancel.db"
    run = _create_run(db_path, tmp_path)
    entered, release = threading.Event(), threading.Event()

    def executor(_run, _step):
        entered.set()
        assert release.wait(2.0)
        return ExecutionResult(events=[])

    coordinator = RuntimeCoordinator(db_path, executor=executor)
    coordinator.enqueue(run["id"])
    assert entered.wait(2.0)
    with connect_workbench_db(db_path) as conn:
        request_cancel(conn, run["id"])
    assert _wait_for(db_path, run["id"], {"cancel_requested"}) == "cancel_requested"
    release.set()
    assert _wait_for(db_path, run["id"], {"cancelled"}) == "cancelled"
    coordinator.stop()


def test_coordinator_native_approval_waits_and_returns_one_shot_decision(tmp_path):
    db_path = tmp_path / "approval.db"
    created = _create_run(db_path, tmp_path)
    with connect_workbench_db(db_path) as conn:
        conn.execute("UPDATE runs SET state='running' WHERE id=?", (created["id"],))
        conn.execute("UPDATE run_steps SET state='running' WHERE run_id=?", (created["id"],))
        conn.commit()
        run = dict(conn.execute("SELECT r.*,p.config_root,p.session_root FROM runs r JOIN tool_profiles p ON p.id=r.profile_id WHERE r.id=?", (created["id"],)).fetchone())
        step = dict(conn.execute("SELECT * FROM run_steps WHERE run_id=?", (created["id"],)).fetchone())

    coordinator = RuntimeCoordinator(db_path)
    result = {}
    worker = threading.Thread(
        target=lambda: result.setdefault("value", coordinator._await_native_approval(run, step, {
            "id": 7, "method": "item/commandExecution/requestApproval",
            "params": {"command": "git status --short", "cwd": str(tmp_path)},
        })),
    )
    worker.start()
    deadline = time.monotonic() + 2
    approval_id = None
    while time.monotonic() < deadline:
        with connect_workbench_db(db_path) as conn:
            row = conn.execute("SELECT id FROM approval_requests WHERE run_id=?", (created["id"],)).fetchone()
            if row:
                approval_id = row["id"]
                assert conn.execute("SELECT state FROM runs WHERE id=?", (created["id"],)).fetchone()["state"] == "waiting_approval"
                break
        time.sleep(0.02)
    assert approval_id
    with connect_workbench_db(db_path) as conn:
        assert decide_approval(conn, approval_id, decision="accept", decided_by="test")["state"] == "responding"
    assert coordinator.resolve_approval(approval_id, "accept") is True
    worker.join(2.0)
    assert result["value"] == {"decision": "accept"}
    coordinator._record_native_approval_delivery(run, step, "7", "accept", True)
    assert _wait_for(db_path, created["id"], {"running"}) == "running"


def test_timeout_request_is_durable_before_process_termination(tmp_path):
    db_path = tmp_path / "timeout.db"
    created = _create_run(db_path, tmp_path)
    with connect_workbench_db(db_path) as conn:
        conn.execute("UPDATE runs SET state='running' WHERE id=?", (created["id"],))
        conn.execute("UPDATE run_steps SET state='running' WHERE run_id=?", (created["id"],))
        conn.commit()
    coordinator = RuntimeCoordinator(db_path)
    coordinator._timeout_run(created["id"], "codex")
    with connect_workbench_db(db_path) as conn:
        run = conn.execute("SELECT state,failure_code FROM runs WHERE id=?", (created["id"],)).fetchone()
        assert (run["state"], run["failure_code"]) == ("cancel_requested", "timeout")


def test_resume_lease_blocks_another_runtime_and_releases(tmp_path):
    db_path = tmp_path / "lease.db"
    run = {"id": "r1", "tool": "codex", "profile_id": "p", "source_native_session_id": "thread-1"}
    first, second = RuntimeCoordinator(db_path), RuntimeCoordinator(db_path)
    lease = first._acquire_source_lease(run)
    with pytest.raises(SessionBusyError):
        second._acquire_source_lease({**run, "id": "r2"})
    first._release_lease("r1", lease)
    second_lease = second._acquire_source_lease({**run, "id": "r2"})
    second._release_lease("r2", second_lease)
