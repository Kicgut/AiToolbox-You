import threading
import time
from datetime import datetime, timedelta, timezone

import pytest

from app.ai_workbench.composer import compose_run, request_cancel
from app.ai_workbench.execution.codex_runtime import ExecutionResult
from app.ai_workbench.execution.codex_runtime import BusinessError
from app.ai_workbench.execution.runtime_coordinator import RuntimeCoordinator
from app.ai_workbench.storage import acquire_writer_lease, connect_workbench_db
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
        return ExecutionResult(stderr="harmless diagnostic", events=[
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
        assert conn.execute("SELECT failure_message FROM runs WHERE id=?", (run["id"],)).fetchone()["failure_message"] is None


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


def test_unconfirmed_registered_process_becomes_interrupted_not_cancelled(tmp_path):
    db_path = tmp_path / "unconfirmed-cancel.db"
    run = _create_run(db_path, tmp_path)
    with connect_workbench_db(db_path) as conn:
        conn.execute("UPDATE runs SET state='cancel_requested' WHERE id=?", (run["id"],))
        conn.execute("UPDATE run_steps SET state='cancel_requested' WHERE run_id=?", (run["id"],))
        conn.commit()
        step_id = conn.execute("SELECT id FROM run_steps WHERE run_id=?", (run["id"],)).fetchone()[0]
        run_data = dict(conn.execute("SELECT * FROM runs WHERE id=?", (run["id"],)).fetchone())

    class StillAlive:
        def poll(self): return None

    coordinator = RuntimeCoordinator(db_path)
    coordinator._processes[run["id"]] = StillAlive()
    coordinator._persist_result(run["id"], step_id, run_data, ExecutionResult(events=[]))
    with connect_workbench_db(db_path) as conn:
        row = conn.execute("SELECT state,failure_code FROM runs WHERE id=?", (run["id"],)).fetchone()
    assert tuple(row) == ("interrupted", "termination_unconfirmed")


def test_coordinator_terminates_a_registered_process_only_once(monkeypatch, tmp_path):
    coordinator = RuntimeCoordinator(tmp_path / "once.db")
    process = object()
    coordinator._processes["r"] = process
    calls = []
    monkeypatch.setattr("app.ai_workbench.execution.runtime_coordinator.terminate_process_tree", lambda item: calls.append(item) or True)
    assert coordinator.request_cancel("r") is True
    assert coordinator.request_cancel("r") is False
    assert calls == [process]


def test_coordinator_owns_adapter_cleanup_for_its_registered_process(monkeypatch, tmp_path):
    coordinator = RuntimeCoordinator(tmp_path / "cleanup.db")
    process = object()
    coordinator._processes["r"] = process
    calls = []
    monkeypatch.setattr("app.ai_workbench.execution.runtime_coordinator.terminate_process_tree", lambda item: calls.append(item) or True)
    assert coordinator._cleanup_registered_process("r", process) is True
    assert calls == [process]
    assert "r" in coordinator._termination_requested


def test_registering_a_process_attaches_a_coordinator_owned_job(monkeypatch, tmp_path):
    db_path = tmp_path / "job.db"
    created = _create_run(db_path, tmp_path)
    coordinator = RuntimeCoordinator(db_path)
    process, job = object(), object()
    monkeypatch.setattr("app.ai_workbench.execution.runtime_coordinator.attach_process_to_job", lambda item: job)
    coordinator._register_process(created["id"], process, "codex")
    assert coordinator._processes[created["id"]] is process
    assert coordinator._process_jobs[created["id"]] is job
    registration = coordinator._registry[created["id"]]
    assert registration.process is process and registration.job is job


def test_registry_tracks_adapter_session_lease_and_interrupt(tmp_path):
    coordinator = RuntimeCoordinator(tmp_path / "registry.db")
    run = {"id": "r", "source_native_session_id": "source"}
    adapter = object()
    coordinator._register_run(run)
    coordinator._set_adapter("r", adapter)
    coordinator._register_interrupt("r", lambda: True)
    registration = coordinator._registry["r"]
    assert registration.adapter is adapter and registration.session_id == "source" and registration.interrupt


def test_codex_execution_path_choice_is_persisted_for_audit(monkeypatch, tmp_path):
    coordinator = RuntimeCoordinator(tmp_path / "path.db")
    recorded = []
    monkeypatch.setattr(
        "app.ai_workbench.execution.runtime_coordinator.execute_with_fallback",
        lambda *args, **kwargs: ExecutionResult(execution_path="codex_exec"),
    )
    monkeypatch.setattr(coordinator, "_persist_live_event", lambda run, step, event: recorded.append(event))
    result = coordinator._execute_real(
        {"id": "r", "tool": "codex", "cwd": str(tmp_path), "config_root": str(tmp_path), "permission_policy_json": "{}", "budget_policy_json": "{}", "mode": "new", "source_native_session_id": None, "model": None},
        {"id": "s", "prompt_text": "fixture", "timeout_ms": None},
    )
    assert result.execution_path == "codex_exec"
    assert recorded == [{
        "event_type": "run.execution_path_selected",
        "payload": {"execution_path": "codex_exec"},
        "source_tool": "codex",
        "source_event_type": "execution_path_selected",
        "execution_path": "codex_exec",
    }]


def test_app_server_turn_submission_is_persisted_only_after_acceptance(tmp_path):
    db_path = tmp_path / "turn-submitted.db"
    created = _create_run(db_path, tmp_path)
    coordinator = RuntimeCoordinator(db_path)
    with connect_workbench_db(db_path) as conn:
        step_id = conn.execute("SELECT id FROM run_steps WHERE run_id=?", (created["id"],)).fetchone()[0]
        assert conn.execute("SELECT dispatch_state FROM runs WHERE id=?", (created["id"],)).fetchone()[0] == "not_started"
    coordinator._mark_turn_submitted(created["id"], step_id, "thread-1", "turn-1")
    with connect_workbench_db(db_path) as conn:
        row = conn.execute("SELECT dispatch_state,native_thread_id FROM runs WHERE id=?", (created["id"],)).fetchone()
        event = conn.execute("SELECT event_type,payload_json FROM run_events WHERE run_id=?", (created["id"],)).fetchone()
    assert tuple(row) == ("submitted", "thread-1")
    assert tuple(event) == ("run.dispatch_submitted", '{"thread_id": "thread-1", "turn_id": "turn-1"}')


def test_lost_lease_stops_event_writes_and_interrupts_run(monkeypatch, tmp_path):
    db_path = tmp_path / "lease-lost.db"
    created = _create_run(db_path, tmp_path)
    coordinator = RuntimeCoordinator(db_path)
    with connect_workbench_db(db_path) as conn:
        conn.execute("UPDATE runs SET state='running' WHERE id=?", (created["id"],))
        conn.execute("UPDATE run_steps SET state='running' WHERE run_id=?", (created["id"],))
        conn.commit()
        run = dict(conn.execute("SELECT * FROM runs WHERE id=?", (created["id"],)).fetchone())
        step = dict(conn.execute("SELECT * FROM run_steps WHERE run_id=?", (created["id"],)).fetchone())
    run.update(_lease_key="codex:p:thread", lease_generation=1)
    monkeypatch.setattr(coordinator, "_heartbeat_lease", lambda *_args: (_ for _ in ()).throw(SessionBusyError("lease lost")))
    with pytest.raises(SessionBusyError):
        coordinator._persist_live_event(run, step, {"event_type": "message.delta", "source_tool": "codex", "payload": {"text_delta": "must not write"}})
    with connect_workbench_db(db_path) as conn:
        assert conn.execute("SELECT count(*) FROM run_events WHERE run_id=?", (created["id"],)).fetchone()[0] == 0
    coordinator._fail(created["id"], step["id"], "codex", "session_busy", "lease lost")
    with connect_workbench_db(db_path) as conn:
        assert conn.execute("SELECT state FROM runs WHERE id=?", (created["id"],)).fetchone()[0] == "interrupted"


def test_registering_after_a_cancel_immediately_terminates_the_process(monkeypatch, tmp_path):
    db_path = tmp_path / "cancel-before-spawn.db"
    created = _create_run(db_path, tmp_path)
    with connect_workbench_db(db_path) as conn:
        conn.execute("UPDATE runs SET state='cancel_requested' WHERE id=?", (created["id"],))
        conn.commit()
    coordinator = RuntimeCoordinator(db_path)
    process, job = object(), object()
    calls = []
    monkeypatch.setattr("app.ai_workbench.execution.runtime_coordinator.attach_process_to_job", lambda item: job)
    monkeypatch.setattr("app.ai_workbench.execution.runtime_coordinator.terminate_process_job", lambda item: calls.append(("job", item)))
    monkeypatch.setattr("app.ai_workbench.execution.runtime_coordinator.terminate_process_tree", lambda item: calls.append(("process", item)) or True)
    coordinator._register_process(created["id"], process, "codex")
    assert calls == [("job", job), ("process", process)]


def test_new_run_converts_to_a_lease_for_its_first_native_session_id(tmp_path):
    db_path = tmp_path / "new-native-lease.db"
    created = _create_run(db_path, tmp_path)
    coordinator = RuntimeCoordinator(db_path)
    with connect_workbench_db(db_path) as conn:
        run = dict(conn.execute("SELECT * FROM runs WHERE id=?", (created["id"],)).fetchone())
        step = dict(conn.execute("SELECT * FROM run_steps WHERE run_id=?", (created["id"],)).fetchone())
    coordinator._persist_live_event(run, step, {"event_type": "run.started", "source_tool": "codex", "payload": {"thread_id": "new-thread"}})
    with connect_workbench_db(db_path) as conn:
        lease = conn.execute("SELECT physical_session_key,run_id FROM session_writer_leases").fetchone()
    assert tuple(lease) == (f"codex:{run['profile_id']}:new-thread", created["id"])
    coordinator._release_lease(created["id"], (run["_lease_key"], run["lease_generation"]))


def test_resume_and_fork_native_session_identity_are_checked_before_persisting():
    with pytest.raises(BusinessError, match="resume returned"):
        RuntimeCoordinator._validate_native_session_identity({"mode": "resume", "source_native_session_id": "source"}, "other")
    with pytest.raises(BusinessError, match="fork did not"):
        RuntimeCoordinator._validate_native_session_identity({"mode": "fork", "source_native_session_id": "source"}, "source")
    RuntimeCoordinator._validate_native_session_identity({"mode": "resume", "source_native_session_id": "source"}, "source")
    RuntimeCoordinator._validate_native_session_identity({"mode": "fork", "source_native_session_id": "source"}, "forked")


def test_stopped_coordinator_refuses_new_runs(tmp_path):
    db_path = tmp_path / "stopped.db"
    _create_run(db_path, tmp_path)
    coordinator = RuntimeCoordinator(db_path, executor=lambda _run, _step: ExecutionResult(events=[]))
    assert coordinator.execution_available is True
    coordinator.stop()
    assert coordinator.execution_available is False
    with pytest.raises(RuntimeError, match="stopping"):
        coordinator.enqueue("new-run")


def test_coordinator_assigns_a_structured_code_to_native_failure(tmp_path):
    db_path = tmp_path / "failure.db"
    run = _create_run(db_path, tmp_path)
    coordinator = RuntimeCoordinator(
        db_path,
        executor=lambda _run, _step: ExecutionResult(state="failed", stderr="fixture failed", events=[]),
    )
    coordinator.enqueue(run["id"])
    assert _wait_for(db_path, run["id"], {"failed"}) == "failed"
    with connect_workbench_db(db_path) as conn:
        row = conn.execute("SELECT failure_code,failure_message FROM runs WHERE id=?", (run["id"],)).fetchone()
        assert dict(row) == {"failure_code": "native_process_failed", "failure_message": "fixture failed"}
    coordinator.stop()


def test_coordinator_native_approval_waits_and_returns_one_shot_decision(tmp_path):
    db_path = tmp_path / "approval.db"
    created = _create_run(db_path, tmp_path)
    with connect_workbench_db(db_path) as conn:
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        expires = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat().replace("+00:00", "Z")
        generation = acquire_writer_lease(conn, physical_session_key="codex:p:test-native", run_id=created["id"], owner_id="test", now=now, expires_at=expires)
        conn.execute("UPDATE runs SET state='running' WHERE id=?", (created["id"],))
        conn.execute("UPDATE run_steps SET state='running' WHERE run_id=?", (created["id"],))
        conn.commit()
        run = dict(conn.execute("SELECT r.*,p.config_root,p.session_root FROM runs r JOIN tool_profiles p ON p.id=r.profile_id WHERE r.id=?", (created["id"],)).fetchone())
        run["_lease_key"] = "codex:p:test-native"
        run["lease_generation"] = generation
        step = dict(conn.execute("SELECT * FROM run_steps WHERE run_id=?", (created["id"],)).fetchone())

    coordinator = RuntimeCoordinator(db_path)
    result = {}
    worker = threading.Thread(
        target=lambda: result.setdefault("value", coordinator._await_native_approval(run, step, {
            "id": 7, "method": "item/commandExecution/requestApproval",
            "params": {"command": "git status --short", "cwd": str(tmp_path), "paths": ["README.md"], "networkTargets": ["https://api.example.test"]},
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
    with connect_workbench_db(db_path) as conn:
        approval = conn.execute("SELECT command_argv_json,affected_paths_json,network_targets_json,risk_level FROM approval_requests WHERE id=?", (approval_id,)).fetchone()
        assert dict(approval) == {"command_argv_json": '["git", "status", "--short"]', "affected_paths_json": '["README.md"]', "network_targets_json": '["https://api.example.test"]', "risk_level": "high"}


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
