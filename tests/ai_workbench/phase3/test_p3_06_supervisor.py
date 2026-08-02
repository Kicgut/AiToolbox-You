import subprocess
import sys
import time

import psutil

from app.ai_workbench.execution.supervisor import EventRingBuffer, RunState, reconcile_stale_runs, run_process, terminate_process_tree
from app.ai_workbench.storage import connect_workbench_db


def _tree_script(tmp_path, exit_now=False):
    child = tmp_path / "child.py"
    child.write_text("import time; time.sleep(30)", encoding="utf-8")
    parent = tmp_path / "parent.py"
    parent.write_text(
        "import subprocess,sys,time\n"
        "p=subprocess.Popen([sys.executable, sys.argv[1]])\n"
        "open(sys.argv[2],'w').write(str(p.pid))\n"
        f"{'raise SystemExit' if exit_now else 'time.sleep(30)'}\n",
        encoding="utf-8",
    )
    return parent, child


def test_p3_06_timeout_kills_real_parent_and_child(tmp_path):
    parent, _ = _tree_script(tmp_path)
    pid_file = tmp_path / "child.pid"
    result = run_process((sys.executable, str(parent), str(tmp_path / "child.py"), str(pid_file)), timeout_seconds=0.3, grace_seconds=0.05)
    assert result.status == "timeout"
    child_pid = int(pid_file.read_text())
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline and psutil.pid_exists(child_pid):
        time.sleep(0.05)
    assert not psutil.pid_exists(child_pid)


def test_p3_06_registered_process_cancel_kills_real_tree(tmp_path):
    parent, _ = _tree_script(tmp_path)
    pid_file = tmp_path / "child.pid"
    process = subprocess.Popen(
        [sys.executable, str(parent), str(tmp_path / "child.py"), str(pid_file)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline and not pid_file.exists():
        time.sleep(0.02)
    assert pid_file.exists()
    child_pid = int(pid_file.read_text())
    assert terminate_process_tree(process) is True
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline and psutil.pid_exists(child_pid):
        time.sleep(0.05)
    assert not psutil.pid_exists(child_pid)


def test_p3_06_grace_and_timeout_state_are_deterministic(tmp_path):
    parent, _ = _tree_script(tmp_path)
    started = time.monotonic()
    result = run_process((sys.executable, str(parent), str(tmp_path / "child.py"), str(tmp_path / "child.pid")), timeout_seconds=0.2, grace_seconds=0.15)
    assert result.status == "timeout"
    assert time.monotonic() - started >= 0.2
    state = RunState()
    assert state.request_cancel() is True
    assert state.request_cancel() is False
    assert state.begin_termination() is True
    assert state.begin_termination() is False
    assert state.finish("cancelled") is True
    assert state.finish("cancelled") is False


def test_p3_06_natural_exit_wins_cancel_race(tmp_path):
    parent, _ = _tree_script(tmp_path, exit_now=True)
    result = run_process((sys.executable, str(parent), str(tmp_path / "child.py"), str(tmp_path / "child.pid")), timeout_seconds=2)
    assert result.status == "completed"
    state = RunState()
    assert state.finish("succeeded") is True
    assert state.request_cancel() is False


def test_p3_06_restart_reconciles_stale_run(tmp_path):
    with connect_workbench_db(tmp_path / "runs.db") as conn:
        conn.execute("INSERT INTO runs (id,tool,profile_id,mode,execution_path,permission_policy_json,budget_policy_json,state,created_at,config_snapshot_json) VALUES ('queued','codex','p','new','codex_exec','{}','{}','queued','now','{}')")
        conn.execute("INSERT INTO runs (id,tool,profile_id,mode,execution_path,permission_policy_json,budget_policy_json,state,created_at,config_snapshot_json) VALUES ('stale','codex','p','new','codex_exec','{}','{}','running','now','{}')")
        conn.execute("INSERT INTO runs (id,tool,profile_id,mode,execution_path,permission_policy_json,budget_policy_json,state,created_at,config_snapshot_json) VALUES ('approval','codex','p','new','codex_exec','{}','{}','waiting_approval','now','{}')")
        assert reconcile_stale_runs(conn) == 2
        assert conn.execute("SELECT state FROM runs WHERE id='stale'").fetchone()[0] == "interrupted"
        assert conn.execute("SELECT state FROM runs WHERE id='approval'").fetchone()[0] == "interrupted"
        assert conn.execute("SELECT state FROM runs WHERE id='queued'").fetchone()[0] == "queued"
        assert conn.execute("SELECT failure_code FROM runs WHERE id='queued'").fetchone()[0] is None


def test_p3_06_backpressure_preserves_critical_events_and_gaps():
    ring = EventRingBuffer(capacity=3)
    for i in range(10):
        ring.append({"event_type": "message.delta", "sequence_no": i, "payload": {"message_id": "m", "text_delta": "x"}}, consumer_blocked=True)
    ring.append({"event_type": "tool.started", "sequence_no": 10, "payload": {}})
    ring.append({"event_type": "usage.updated", "sequence_no": 11, "payload": {}})
    ring.append({"event_type": "error", "sequence_no": 12, "payload": {}})
    events = ring.drain()
    kinds = [event["event_type"] for event in events]
    assert "stream_gap" in kinds
    assert {"tool.started", "usage.updated", "error"} <= set(kinds)
    assert "stream_gap" in kinds  # deltas are reconstructable from SQLite after the gap
