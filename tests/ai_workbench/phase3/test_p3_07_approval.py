from app.ai_workbench.approval import create_approval, decide_approval, expire_approvals, record_approval_delivery
from app.ai_workbench.storage import connect_workbench_db


def _seed(conn):
    conn.execute("INSERT INTO runs (id,tool,profile_id,mode,execution_path,permission_policy_json,budget_policy_json,state,created_at,config_snapshot_json) VALUES ('r','codex','p','new','codex_exec','{}','{}','waiting_approval','now','{}')")
    conn.execute("INSERT INTO run_steps (id,run_id,ordinal,prompt_text,state) VALUES ('s','r',1,'x','waiting_approval')")
    conn.commit()


def test_approval_is_idempotent_and_offline_stays_pending(tmp_path):
    with connect_workbench_db(tmp_path / "a.db") as conn:
        _seed(conn)
        first = create_approval(conn, run_id="r", step_id="s", native_request_id="n", operation="command", target_summary="x", risk_level="high")
        again = create_approval(conn, run_id="r", step_id="s", native_request_id="n", operation="command", target_summary="x", risk_level="high")
        assert first["id"] == again["id"]
        assert first["state"] == "pending" and first["disconnect_policy"] == "wait"


def test_only_one_decision_wins_and_expiry_is_explicit(tmp_path):
    with connect_workbench_db(tmp_path / "a.db") as conn:
        _seed(conn)
        item = create_approval(conn, run_id="r", step_id="s", native_request_id="n", operation="file_write", target_summary="x", risk_level="high", expires_at="2020-01-01T00:00:00Z")
        assert expire_approvals(conn, now="2021-01-01T00:00:00Z") == 1
        assert decide_approval(conn, item["id"], decision="accept", decided_by="u")["conflict"] is True
        item2 = create_approval(conn, run_id="r", step_id="s", native_request_id="n2", operation="command", target_summary="x", risk_level="medium")
        assert decide_approval(conn, item2["id"], decision="accept", decided_by="u")["state"] == "responding"
        assert record_approval_delivery(conn, item2["id"], delivered=True)["state"] == "accepted"
        assert decide_approval(conn, item2["id"], decision="decline", decided_by="v")["conflict"] is True
