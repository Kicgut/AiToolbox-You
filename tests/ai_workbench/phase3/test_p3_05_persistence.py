import json

from app.ai_workbench.event_persistence import cleanup_expired_artifacts, list_events_before, persist_event, persist_status_change, record_live_usage, resync_events
from app.ai_workbench.indexing.scanner import _persist_usage
from app.ai_workbench.merge import merge_decision
from app.ai_workbench.storage import connect_workbench_db


def _run(conn):
    conn.execute("INSERT INTO runs(id,tool,profile_id,mode,execution_path,permission_policy_json,budget_policy_json,state,created_at,config_snapshot_json) VALUES('r','codex','p','new','codex_exec','{}','{}','running','now','{}')")


def _event(n="e", **payload):
    return {"event_id": n, "run_id": "r", "profile_id": "p", "session_id": "s", "source_tool": "codex", "event_type": "usage.updated", "payload": {"request_id": "q", "input_tokens": 10, "output_tokens": 2, **payload}}


def _db(tmp_path, name):
    return connect_workbench_db(tmp_path / f"{name}-v2.sqlite")

def test_persist_before_broadcast_and_sequence(tmp_path):
    conn = _db(tmp_path, "ordering"); _run(conn); seen = []
    persist_event(conn, {**_event("e1"), "event_type": "message.delta"}, broadcast=lambda e: seen.append(conn.execute("SELECT COUNT(*) FROM run_events").fetchone()[0]))
    persist_event(conn, {**_event("e2"), "event_type": "message.delta"}, broadcast=lambda e: seen.append(conn.execute("SELECT last_sequence_no FROM runs WHERE id='r'").fetchone()[0]))
    assert seen == [1, 2]
    assert [r["sequence_no"] for r in conn.execute("SELECT * FROM run_events ORDER BY sequence_no")] == [1, 2]


def test_status_event_run_state_and_cursor_commit_or_roll_back_together(tmp_path):
    conn = _db(tmp_path, "status-atomic"); _run(conn)
    saved = persist_status_change(conn, run_id="r", step_id=None, state="succeeded", source_tool="codex", broadcast=None)
    assert saved["sequence_no"] == 1
    assert tuple(conn.execute("SELECT state,last_sequence_no FROM runs WHERE id='r'").fetchone()) == ("succeeded", 1)
    assert conn.execute("SELECT last_persisted_sequence_no FROM run_stream_cursors WHERE run_id='r'").fetchone()[0] == 1
    assert conn.execute("SELECT count(*) FROM run_events WHERE run_id='r'").fetchone()[0] == 1
    try:
        persist_status_change(conn, run_id="r", step_id=None, state="running", source_tool="codex", broadcast=None)
    except ValueError as error:
        assert "illegal run state transition" in str(error)
    else:
        raise AssertionError("illegal state transition must fail")
    assert tuple(conn.execute("SELECT state,last_sequence_no FROM runs WHERE id='r'").fetchone()) == ("succeeded", 1)
    assert conn.execute("SELECT last_persisted_sequence_no FROM run_stream_cursors WHERE run_id='r'").fetchone()[0] == 1
    assert conn.execute("SELECT count(*) FROM run_events WHERE run_id='r'").fetchone()[0] == 1


def test_broadcast_cursor_advances_only_after_successful_fanout(tmp_path):
    conn = _db(tmp_path, "broadcast-cursor"); _run(conn)
    persist_event(conn, {**_event("ok"), "event_type": "message.delta"}, broadcast=lambda _event: None)
    assert conn.execute("SELECT last_broadcast_sequence_no FROM run_stream_cursors WHERE run_id='r'").fetchone()[0] == 1
    persist_event(conn, {**_event("failed"), "event_type": "message.delta"}, broadcast=lambda _event: (_ for _ in ()).throw(RuntimeError("fanout down")))
    row = conn.execute("SELECT last_persisted_sequence_no,last_broadcast_sequence_no FROM run_stream_cursors WHERE run_id='r'").fetchone()
    assert tuple(row) == (2, 1)


def test_resync_detects_gap_and_returns_tail(tmp_path):
    conn = _db(tmp_path, "resync"); _run(conn)
    for n in ("e1", "e2", "e3"):
        persist_event(conn, {**_event(n), "event_type": "message.delta"})
    conn.execute("DELETE FROM run_events WHERE sequence_no=2"); conn.commit()
    result = resync_events(conn, "r", 1)
    assert result["resync_required"] is True
    assert [e["sequence_no"] for e in result["events"]] == [3]


def test_event_history_is_bounded_and_can_be_paged_backwards(tmp_path):
    conn = _db(tmp_path, "history"); _run(conn)
    for index in range(1, 7):
        persist_event(conn, {**_event(f"e{index}"), "event_type": "message.delta"}, broadcast=None)
    replay = resync_events(conn, "r", 0, limit=2)
    assert [event["sequence_no"] for event in replay["events"]] == [1, 2]
    assert replay["has_more"] is True
    older = list_events_before(conn, "r", 5, limit=2)
    assert [event["sequence_no"] for event in older["events"]] == [3, 4]
    assert older["has_more"] is True


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


def test_event_payload_does_not_persist_environment_values(tmp_path):
    conn = _db(tmp_path, "event-environment-redaction"); _run(conn)
    saved = persist_event(conn, {
        "event_id": "env", "run_id": "r", "source_tool": "codex",
        "event_type": "command.output",
        "payload": {"env": {"API_KEY": "must-not-persist"}, "environment": {"HOME": "must-not-persist"}},
    }, broadcast=None)
    assert saved["payload"] == {"env": "[redacted]", "environment": "[redacted]"}
    stored = conn.execute("SELECT payload_json,raw_json FROM run_events WHERE event_id='env'").fetchone()
    assert "must-not-persist" not in stored["payload_json"] + stored["raw_json"]


def test_command_and_diff_text_redact_inline_credentials_before_storage(tmp_path):
    conn = _db(tmp_path, "inline-secret-redaction"); _run(conn)
    saved = persist_event(conn, {
        "event_id": "diff-secret", "run_id": "r", "source_tool": "codex",
        "event_type": "file.changed",
        "payload": {"diff": "+ Authorization: Bearer super-secret-token\n+ api_key=another-secret"},
    }, broadcast=None)
    assert "super-secret-token" not in json.dumps(saved)
    assert "another-secret" not in json.dumps(saved)
    assert "[redacted]" in saved["payload"]["diff"]


def test_expired_artifact_cleanup_is_scoped_and_idempotent(tmp_path):
    conn = _db(tmp_path, "artifact-cleanup"); _run(conn)
    saved = persist_event(conn, {
        "event_id": "large", "run_id": "r", "source_tool": "codex",
        "event_type": "command.output", "payload": {"output": "x" * 70_000},
    }, broadcast=None)
    artifact_id = saved["payload"]["artifact"]["artifact_id"]
    row = conn.execute("SELECT relative_path FROM run_artifacts WHERE id=?", (artifact_id,)).fetchone()
    artifact_path = tmp_path / row["relative_path"]
    conn.execute("UPDATE run_artifacts SET expires_at='2000-01-01T00:00:00Z' WHERE id=?", (artifact_id,))
    outside = tmp_path / "must-not-delete.txt"; outside.write_text("keep", encoding="utf-8")
    conn.execute("INSERT INTO run_artifacts(id,run_id,kind,relative_path,sha256,size_bytes,mime_type,redaction_state,created_at,expires_at) VALUES('unsafe','r','event_payload','../must-not-delete.txt','x',1,'text/plain','redacted','now','2000-01-01T00:00:00Z')")
    conn.commit()
    assert cleanup_expired_artifacts(conn, now="2001-01-01T00:00:00Z") == {"removed": 1, "missing": 0, "unsafe": 1}
    assert not artifact_path.exists() and outside.read_text(encoding="utf-8") == "keep"
    assert conn.execute("SELECT 1 FROM run_artifacts WHERE id=?", (artifact_id,)).fetchone() is None
    assert conn.execute("SELECT 1 FROM run_artifacts WHERE id='unsafe'").fetchone() is not None
    assert cleanup_expired_artifacts(conn, now="2001-01-01T00:00:00Z") == {"removed": 0, "missing": 0, "unsafe": 1}


def _native(conn, *, profile_ref="p"):
    conn.execute("INSERT INTO observations(id,observation_kind,source,native_session_id,native_turn_id,request_id,tool,profile_ref,observed_at,payload_hash,quality,parser_version,parse_status,created_at) VALUES('native','session','codex_jsonl','s','t','q','codex',?,'now','h','exact','v','parsed','now')", (profile_ref,))
    conn.execute("INSERT INTO usage_records(id,observation_id,dedup_key,event_kind,input_tokens,output_tokens,counter_scope,recorded_at,source,quality,parser_version,merge_status,created_at) VALUES('nu','native','native-key','request_delta',10,2,'request','now','codex_jsonl','exact','v','primary','now')"); conn.commit()


def test_live_then_native_exact_identity_has_one_primary(tmp_path):
    conn = _db(tmp_path, "live-native"); _run(conn)
    live = _event("live"); record_live_usage(conn, live)
    _persist_usage(conn, "codex", str(tmp_path / "native.jsonl"), "s", ['{"request_id":"q","turn_id":"t","input_tokens":10,"output_tokens":2}'], profile_id="p")
    assert conn.execute("SELECT COUNT(*) FROM observations WHERE request_id='q'").fetchone()[0] == 2
    assert conn.execute("SELECT native_turn_id FROM observations WHERE source='codex_jsonl'").fetchone()[0] == "t"
    assert conn.execute("SELECT COUNT(*) FROM usage_records WHERE merge_status='primary'").fetchone()[0] == 1


def test_native_then_live_exact_identity_has_one_primary(tmp_path):
    conn = _db(tmp_path, "native-live"); _run(conn); _native(conn)
    assert record_live_usage(conn, _event("live")) == "duplicate"
    assert conn.execute("SELECT COUNT(*) FROM observations WHERE request_id='q'").fetchone()[0] == 2
    assert conn.execute("SELECT COUNT(*) FROM usage_records WHERE merge_status='primary'").fetchone()[0] == 1


def test_usage_identity_does_not_merge_across_profiles(tmp_path):
    conn = _db(tmp_path, "profile-identity"); _run(conn); _native(conn, profile_ref="other")
    assert record_live_usage(conn, _event("live")) == "primary"
    assert conn.execute("SELECT COUNT(*) FROM usage_records WHERE merge_status='primary'").fetchone()[0] == 2


def test_weak_usage_match_is_conflict_not_auto_merge():
    decision = merge_decision(
        {"native_session_id": "s", "model": "m", "event_at": "2026-01-01T00:00:00Z"},
        {"native_session_id": "s", "model": "m", "event_at": "2026-01-01T00:00:01Z"},
    )
    assert decision.status == "conflict"
    assert decision.counting_policy == "count_primary_only_until_review"
