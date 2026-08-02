import sqlite3
import threading

import pytest

from app.ai_workbench.storage import (
    RunTransitionConflict,
    SessionBusyError,
    acquire_writer_lease,
    compare_and_set_run_state,
    connect_workbench_db,
    release_writer_lease,
    validate_run_transition,
)


def test_p3_01_creates_execution_tables(tmp_path):
    with connect_workbench_db(tmp_path / "workbench.db") as conn:
        names = {row["name"] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
    assert {"runs", "run_steps", "approval_requests", "run_events",
            "run_stream_cursors", "session_writer_leases"} <= names


def test_p3_01_illegal_run_transition_does_not_mutate_state(tmp_path):
    with connect_workbench_db(tmp_path / "workbench.db") as conn:
        conn.execute("INSERT INTO runs (id, tool, profile_id, mode, execution_path, "
                     "permission_policy_json, budget_policy_json, state, created_at, config_snapshot_json) "
                     "VALUES ('r1','codex','p1','new','codex_exec','{}','{}','running','now','{}')")
        with pytest.raises(ValueError, match="running -> starting"):
            validate_run_transition("running", "starting")
        assert conn.execute("SELECT state FROM runs WHERE id='r1'").fetchone()[0] == "running"


def test_p3_01_state_compare_and_set_rejects_a_stale_writer(tmp_path):
    with connect_workbench_db(tmp_path / "workbench.db") as conn:
        conn.execute("INSERT INTO runs (id, tool, profile_id, mode, execution_path, permission_policy_json, budget_policy_json, state, created_at, config_snapshot_json) VALUES ('r1','codex','p1','new','codex_exec','{}','{}','running','now','{}')")
        compare_and_set_run_state(conn, run_id="r1", expected_state="running", proposed_state="succeeded", updates={"updated_at": "later"})
        with pytest.raises(RunTransitionConflict):
            compare_and_set_run_state(conn, run_id="r1", expected_state="running", proposed_state="cancel_requested", updates={"updated_at": "later"})


def test_p3_01_expired_lease_takeover_and_live_lease_busy(tmp_path):
    db = tmp_path / "workbench.db"
    with connect_workbench_db(db) as conn:
        first = acquire_writer_lease(conn, physical_session_key="codex|p|s", run_id="r1",
                                     owner_id="o1", now="2026-01-01T00:00:00Z",
                                     expires_at="2026-01-01T00:01:00Z")
        with pytest.raises(SessionBusyError, match="session_busy"):
            acquire_writer_lease(conn, physical_session_key="codex|p|s", run_id="r2",
                                 owner_id="o2", now="2026-01-01T00:00:30Z",
                                 expires_at="2026-01-01T00:02:00Z")
        second = acquire_writer_lease(conn, physical_session_key="codex|p|s", run_id="r2",
                                      owner_id="o2", now="2026-01-01T00:02:00Z",
                                      expires_at="2026-01-01T00:03:00Z")
        assert second == first + 1


def test_p3_01_release_reports_stale_generation_without_deleting_current_lease(tmp_path):
    with connect_workbench_db(tmp_path / "workbench.db") as conn:
        acquire_writer_lease(conn, physical_session_key="codex|p|s", run_id="r1", owner_id="o1", now="2026-01-01T00:00:00Z", expires_at="2026-01-01T00:01:00Z")
        assert release_writer_lease(conn, physical_session_key="codex|p|s", run_id="r1", lease_generation=99) is False
        assert conn.execute("SELECT run_id, lease_generation FROM session_writer_leases WHERE physical_session_key='codex|p|s'").fetchone()["lease_generation"] == 1
        assert release_writer_lease(conn, physical_session_key="codex|p|s", run_id="r1", lease_generation=1) is True


def test_p3_01_concurrent_lease_acquisition_has_one_winner(tmp_path):
    db = tmp_path / "workbench.db"
    with connect_workbench_db(db):
        pass
    barrier = threading.Barrier(2)
    results = []

    def attempt(run_id):
        conn = connect_workbench_db(db)
        try:
            barrier.wait()
            acquire_writer_lease(conn, physical_session_key="codex|p|s", run_id=run_id,
                                 owner_id=run_id, now="2026-01-01T00:00:00Z",
                                 expires_at="2026-01-01T00:01:00Z")
            results.append("won")
        except SessionBusyError:
            results.append("session_busy")
        finally:
            conn.close()

    threads = [threading.Thread(target=attempt, args=(f"r{i}",)) for i in (1, 2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(results) == ["session_busy", "won"]


def test_p3_01_run_events_sequence_unique_constraint(tmp_path):
    with connect_workbench_db(tmp_path / "workbench.db") as conn:
        conn.execute("INSERT INTO runs (id, tool, profile_id, mode, execution_path, "
                     "permission_policy_json, budget_policy_json, state, created_at, config_snapshot_json) "
                     "VALUES ('r1','codex','p1','new','codex_exec','{}','{}','starting','now','{}')")
        values = ("e1", "r1", 1, "message", "2026-01-01T00:00:00Z", "{}", "codex", "now")
        conn.execute("INSERT INTO run_events (event_id, run_id, sequence_no, event_type, timestamp, "
                     "payload_json, source_tool, persisted_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", values)
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO run_events (event_id, run_id, sequence_no, event_type, timestamp, "
                         "payload_json, source_tool, persisted_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                         ("e2", "r1", 1, "message", "2026-01-01T00:00:01Z", "{}", "codex", "now"))
