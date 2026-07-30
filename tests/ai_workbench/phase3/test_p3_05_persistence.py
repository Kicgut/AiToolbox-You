from app.ai_workbench.event_persistence import persist_event, record_live_usage, resync_events
from app.ai_workbench.indexing.scanner import _persist_usage
from app.ai_workbench.storage import connect_workbench_db


def _run(conn):
    conn.execute("INSERT INTO runs(id,tool,profile_id,mode,execution_path,permission_policy_json,budget_policy_json,state,created_at,config_snapshot_json) VALUES('r','codex','p','new','codex_exec','{}','{}','running','now','{}')")


def _event(n="e", **payload):
    return {"event_id": n, "run_id": "r", "session_id": "s", "source_tool": "codex", "event_type": "usage.updated", "payload": {"request_id": "q", "input_tokens": 10, "output_tokens": 2, **payload}}


def _db(tmp_path, name):
    return connect_workbench_db(tmp_path / f"{name}-v2.sqlite")

def test_persist_before_broadcast_and_sequence(tmp_path):
    conn = _db(tmp_path, "ordering"); _run(conn); seen = []
    persist_event(conn, {**_event("e1"), "event_type": "message.delta"}, broadcast=lambda e: seen.append(conn.execute("SELECT COUNT(*) FROM run_events").fetchone()[0]))
    persist_event(conn, {**_event("e2"), "event_type": "message.delta"}, broadcast=lambda e: seen.append(conn.execute("SELECT last_sequence_no FROM runs WHERE id='r'").fetchone()[0]))
    assert seen == [1, 2]
    assert [r["sequence_no"] for r in conn.execute("SELECT * FROM run_events ORDER BY sequence_no")] == [1, 2]


def test_resync_detects_gap_and_returns_tail(tmp_path):
    conn = _db(tmp_path, "resync"); _run(conn)
    for n in ("e1", "e2", "e3"):
        persist_event(conn, {**_event(n), "event_type": "message.delta"})
    conn.execute("DELETE FROM run_events WHERE sequence_no=2"); conn.commit()
    result = resync_events(conn, "r", 1)
    assert result["resync_required"] is True
    assert [e["sequence_no"] for e in result["events"]] == [3]


def test_large_event_payload_is_redacted_and_referenced_by_artifact(tmp_path):
    conn = _db(tmp_path, "artifact"); _run(conn)
    saved = persist_event(conn, {
        "event_id": "large", "run_id": "r", "source_tool": "codex",
        "event_type": "command.output", "payload": {"token": "must-not-persist", "output": "x" * 70_000},
    }, broadcast=None)
    reference = saved["payload"]["artifact"]
    row = conn.execute("SELECT * FROM run_artifacts WHERE id=?", (reference["artifact_id"],)).fetchone()
    assert row and row["relative_path"].startswith("run-artifacts/r/") and row["expires_at"]
    content = (tmp_path / "run-artifacts" / "r" / f"{row['id']}.json").read_text(encoding="utf-8")
    assert "must-not-persist" not in content and '"[redacted]"' in content
    stored = conn.execute("SELECT payload_json,raw_json FROM run_events WHERE event_id='large'").fetchone()
    assert len(stored["payload_json"]) < 2048 and len(stored["raw_json"]) < 2048


def _native(conn):
    conn.execute("INSERT INTO observations(id,observation_kind,source,native_session_id,native_turn_id,request_id,tool,observed_at,payload_hash,quality,parser_version,parse_status,created_at) VALUES('native','session','codex_jsonl','s','t','q','codex','now','h','exact','v','parsed','now')")
    conn.execute("INSERT INTO usage_records(id,observation_id,dedup_key,event_kind,input_tokens,output_tokens,counter_scope,recorded_at,source,quality,parser_version,merge_status,created_at) VALUES('nu','native','native-key','request_delta',10,2,'request','now','codex_jsonl','exact','v','primary','now')"); conn.commit()


def test_live_then_native_exact_identity_has_one_primary(tmp_path):
    conn = _db(tmp_path, "live-native"); _run(conn)
    live = _event("live"); record_live_usage(conn, live)
    _persist_usage(conn, "codex", str(tmp_path / "native.jsonl"), "s", ['{"request_id":"q","turn_id":"t","input_tokens":10,"output_tokens":2}'])
    assert conn.execute("SELECT COUNT(*) FROM observations WHERE request_id='q'").fetchone()[0] == 2
    assert conn.execute("SELECT COUNT(*) FROM usage_records WHERE merge_status='primary'").fetchone()[0] == 1


def test_native_then_live_exact_identity_has_one_primary(tmp_path):
    conn = _db(tmp_path, "native-live"); _run(conn); _native(conn)
    assert record_live_usage(conn, _event("live")) == "duplicate"
    assert conn.execute("SELECT COUNT(*) FROM observations WHERE request_id='q'").fetchone()[0] == 2
    assert conn.execute("SELECT COUNT(*) FROM usage_records WHERE merge_status='primary'").fetchone()[0] == 1
