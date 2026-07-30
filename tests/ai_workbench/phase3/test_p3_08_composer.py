import pytest

from app.ai_workbench.composer import ComposerError, compose_run, cancel_run, retry_failed_step
from app.ai_workbench.storage import connect_workbench_db


def test_composer_creates_one_turn_and_is_idempotent(tmp_path):
    with connect_workbench_db(tmp_path / "c.db") as conn:
        conn.execute("INSERT INTO tool_profiles(id,tool,display_name,config_root,session_root,discovery_source) VALUES('p','codex','p','x','x','test')")
        conn.commit()
        a = compose_run(conn, action="new", tool="codex", profile_id="p", cwd=str(tmp_path), prompt="one", client_request_id="req")
        b = compose_run(conn, action="new", tool="codex", profile_id="p", cwd=str(tmp_path), prompt="one", client_request_id="req")
        assert a["idempotent"] is False and b["idempotent"] is True
        assert conn.execute("SELECT count(*) FROM runs").fetchone()[0] == 1
        assert conn.execute("SELECT count(*) FROM run_steps WHERE run_id=?", (a["run"]["id"],)).fetchone()[0] == 1
        with pytest.raises(ComposerError, match="exactly one"):
            compose_run(conn, action="new", tool="codex", profile_id="p", cwd=str(tmp_path), prompts=["one", "two"])


def test_composer_rejects_profile_and_cwd_mismatch(tmp_path):
    with connect_workbench_db(tmp_path / "c.db") as conn:
        conn.execute("INSERT INTO tool_profiles(id,tool,display_name,config_root,session_root,discovery_source) VALUES('p','codex','p','x','x','test')")
        conn.commit()
        with pytest.raises(ComposerError, match="profile"):
            compose_run(conn, action="new", tool="claude", profile_id="p", cwd=str(tmp_path), prompt="x")
        with pytest.raises(ComposerError, match="cwd"):
            compose_run(conn, action="new", tool="codex", profile_id="p", cwd=str(tmp_path / "missing"), prompt="x")


def test_cancel_is_idempotent_and_retry_records_attempt(tmp_path):
    with connect_workbench_db(tmp_path / "c.db") as conn:
        conn.execute("INSERT INTO tool_profiles(id,tool,display_name,config_root,session_root,discovery_source) VALUES('p','codex','p','x','x','test')")
        conn.commit()
        result = compose_run(conn, action="new", tool="codex", profile_id="p", cwd=str(tmp_path), prompt="x")
        run_id = result["run"]["id"]
        step_id = conn.execute("SELECT id FROM run_steps WHERE run_id=?", (run_id,)).fetchone()[0]
        conn.execute("UPDATE runs SET state='failed' WHERE id=?", (run_id,))
        conn.execute("UPDATE run_steps SET state='failed' WHERE id=?", (step_id,))
        conn.commit()
        retried = retry_failed_step(conn, run_id, step_id)
        assert retried["run"]["id"] != run_id
        assert retried["step"]["state"] == "queued" and retried["step"]["attempt_no"] == 1
        assert retried["run"]["retry_of_run_id"] == run_id
        retry_id = retried["run"]["id"]
        assert cancel_run(conn, retry_id)["state"] == "cancelled"
        assert cancel_run(conn, retry_id)["state"] == "cancelled"
