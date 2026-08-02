import json
import os

import pytest

from app.ai_workbench.composer import ComposerError, compose_run, cancel_run, request_cancel, retry_failed_step
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
        snapshot = json.loads(a["run"]["capabilities_snapshot_json"])
        assert snapshot["sandbox"] == ["read-only"] and snapshot["tool_allow_deny_lists"] is False
        assert snapshot["limit_strengths"]["max_total_tokens_observed"] == "observed_only"
        config_snapshot = json.loads(a["run"]["config_snapshot_json"])
        assert config_snapshot["profile_environment"]["variable_names"] == ["CODEX_HOME"]
        assert config_snapshot["profile"]["config_root"] == os.path.normcase(os.path.realpath("x"))
        assert config_snapshot["profile"]["session_root"] == os.path.normcase(os.path.realpath("x"))
        assert "executable" in config_snapshot["profile"]
        assert str(tmp_path) not in json.dumps(config_snapshot["profile_environment"])
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


def test_composer_requires_confirmation_for_an_unregistered_cwd(tmp_path):
    with connect_workbench_db(tmp_path / "c.db") as conn:
        conn.execute("INSERT INTO tool_profiles(id,tool,display_name,config_root,session_root,discovery_source) VALUES('p','codex','p','x','x','test')")
        conn.commit()
        with pytest.raises(ComposerError) as error:
            compose_run(conn, action="new", tool="codex", profile_id="p", cwd=str(tmp_path), cwd_confirmed=False, prompt="x")
        assert error.value.code == "cwd_confirmation_required"
        conn.execute("INSERT INTO projects(id,cwd_canonical,exists_on_disk) VALUES('project',?,1)", (str(tmp_path),))
        conn.commit()
        assert compose_run(conn, action="new", tool="codex", profile_id="p", cwd=str(tmp_path), cwd_confirmed=False, prompt="x")["idempotent"] is False


def test_composer_rejects_unenforceable_codex_contracts(tmp_path):
    with connect_workbench_db(tmp_path / "c.db") as conn:
        conn.execute("INSERT INTO tool_profiles(id,tool,display_name,config_root,session_root,discovery_source) VALUES('p','codex','p','x','x','test')")
        conn.commit()
        with pytest.raises(ComposerError, match="cannot be guaranteed"):
            compose_run(conn, action="new", tool="codex", profile_id="p", cwd=str(tmp_path), prompt="x", permission_policy={"allowed_tools": ["read"]})
        with pytest.raises(ComposerError, match="max_budget_usd"):
            compose_run(conn, action="new", tool="codex", profile_id="p", cwd=str(tmp_path), prompt="x", budget_policy={"max_budget_usd": 1})


def test_composer_validates_model_against_capability_contract(tmp_path):
    with connect_workbench_db(tmp_path / "model.db") as conn:
        conn.execute("INSERT INTO tool_profiles(id,tool,display_name,config_root,session_root,discovery_source) VALUES('p','codex','p','x','x','test')")
        conn.commit()
        with pytest.raises(ComposerError, match="model must"):
            compose_run(conn, action="new", tool="codex", profile_id="p", cwd=str(tmp_path), prompt="x", model=" ")


def test_resume_source_lease_is_reserved_before_worker_spawn_and_released_on_queued_cancel(tmp_path):
    with connect_workbench_db(tmp_path / "lease.db") as conn:
        conn.execute("INSERT INTO tool_profiles(id,tool,display_name,config_root,session_root,discovery_source) VALUES('p','codex','p','x','x','test')")
        conn.execute("INSERT INTO conversation_families(id,tool,native_session_id,created_at,updated_at) VALUES('f','codex','thread',0,0)")
        conn.execute("INSERT INTO session_copies(id,family_id,tool,native_session_id,profile_id,transcript_path,transcript_kind,title,kind,created_at,updated_at,content_hash,head_event_hash,parse_version,index_status,event_count) VALUES('copy','f','codex','thread','p','x','jsonl','x','live',0,0,'h','h','v','indexed',0)")
        conn.commit()
        first = compose_run(conn, action="resume", tool="codex", profile_id="p", session_copy_id="copy", cwd=str(tmp_path), prompt="x")["run"]
        with pytest.raises(Exception, match="session_busy"):
            compose_run(conn, action="fork", tool="codex", profile_id="p", session_copy_id="copy", cwd=str(tmp_path), prompt="x")
        assert request_cancel(conn, first["id"])["state"] == "cancelled"
        second = compose_run(conn, action="fork", tool="codex", profile_id="p", session_copy_id="copy", cwd=str(tmp_path), prompt="x")["run"]
        assert second["id"] != first["id"]


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


def test_cancel_returns_a_terminal_fact_when_completion_wins_the_race(tmp_path, monkeypatch):
    with connect_workbench_db(tmp_path / "c.db") as conn:
        conn.execute("INSERT INTO tool_profiles(id,tool,display_name,config_root,session_root,discovery_source) VALUES('p','codex','p','x','x','test')")
        conn.commit()
        run = compose_run(conn, action="new", tool="codex", profile_id="p", cwd=str(tmp_path), prompt="x")["run"]
        conn.execute("UPDATE runs SET state='running' WHERE id=?", (run["id"],)); conn.commit()

        def completion_wins(target, **_kwargs):
            target.execute("UPDATE runs SET state='succeeded' WHERE id=?", (run["id"],)); target.commit()
            raise ValueError("illegal run state transition: succeeded -> cancel_requested")

        monkeypatch.setattr("app.ai_workbench.event_persistence.persist_status_change", completion_wins)
        # request_cancel imports its helper lazily, so patch the package-level
        # implementation it resolves at call time.
        assert request_cancel(conn, run["id"])["state"] == "succeeded"


def test_composer_rejects_unknown_tool_via_capability_contract(tmp_path):
    with connect_workbench_db(tmp_path / "c.db") as conn:
        conn.execute("INSERT INTO tool_profiles(id,tool,display_name,config_root,session_root,discovery_source) VALUES('p','unknown','p','x','x','test')")
        conn.commit()
        with pytest.raises(ComposerError, match="not supported"):
            compose_run(conn, action="new", tool="unknown", profile_id="p", cwd=str(tmp_path), prompt="x")


def test_composer_uses_observed_baseline_to_reject_unavailable_cli_and_fork(tmp_path):
    with connect_workbench_db(tmp_path / "observed.db") as conn:
        conn.execute("INSERT INTO tool_profiles(id,tool,display_name,config_root,session_root,discovery_source) VALUES('p','codex','p','x','x','test')")
        conn.execute("INSERT INTO runtime_capability_baselines(observed_at,payload_json) VALUES('now', ?)", (json.dumps({"codex": {"status": "missing", "features": {"app_server": False}}}),))
        conn.commit()
        with pytest.raises(ComposerError, match="not available"):
            compose_run(conn, action="new", tool="codex", profile_id="p", cwd=str(tmp_path), prompt="x")


def test_composer_rejects_fork_when_observed_app_server_is_unavailable(tmp_path):
    with connect_workbench_db(tmp_path / "fork-observed.db") as conn:
        conn.execute("INSERT INTO tool_profiles(id,tool,display_name,config_root,session_root,discovery_source) VALUES('p','codex','p','x','x','test')")
        conn.execute("INSERT INTO conversation_families(id,tool,native_session_id,created_at,updated_at) VALUES('f','codex','thread',0,0)")
        conn.execute("INSERT INTO session_copies(id,family_id,tool,native_session_id,profile_id,transcript_path,transcript_kind,title,kind,created_at,updated_at,content_hash,head_event_hash,parse_version,index_status,event_count) VALUES('copy','f','codex','thread','p','x','jsonl','x','live',0,0,'h','h','v','indexed',0)")
        conn.execute("INSERT INTO runtime_capability_baselines(observed_at,payload_json) VALUES('now', ?)", (json.dumps({"codex": {"status": "available", "features": {"app_server": False}}}),))
        conn.commit()
        with pytest.raises(ComposerError, match="App Server"):
            compose_run(conn, action="fork", tool="codex", profile_id="p", session_copy_id="copy", cwd=str(tmp_path), prompt="x")
