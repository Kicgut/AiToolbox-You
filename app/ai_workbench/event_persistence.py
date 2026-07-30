"""Persistence and Phase 2 usage wiring for live Workbench events."""
from __future__ import annotations
import hashlib, json, os, sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4
from app.ai_workbench.merge import merge_decision
from app.ai_workbench.runtime_stream import runtime_broadcaster
from app.ai_workbench.storage import validate_run_transition

def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

_RUN_UPDATE_COLUMNS = {
    "native_session_id", "native_thread_id", "execution_path", "dispatch_state",
    "dispatch_committed_at", "runtime_instance_id", "lease_generation",
    "failure_code", "failure_message", "started_at", "finished_at", "updated_at",
    "cancel_requested_at", "capabilities_snapshot_json",
}
_INLINE_EVENT_BYTES = 64 * 1024
_SENSITIVE_KEY_PARTS = ("token", "secret", "password", "cookie", "authorization", "api_key", "apikey")


def persist_event(conn: sqlite3.Connection, event: dict[str, Any], *,
                  broadcast: Callable[[dict[str, Any]], None] | None = runtime_broadcaster.publish,
                  run_state: str | None = None, step_state: str | None = None,
                  run_updates: dict[str, Any] | None = None) -> dict[str, Any]:
    """Persist one unified event transactionally before invoking its broadcast hook."""
    run_id = event["run_id"]
    saved = dict(event); kind = saved.get("event_type", saved.get("type", "unknown")); payload = saved.get("payload", {})
    if conn.in_transaction:
        conn.commit()
    conn.execute("BEGIN IMMEDIATE")
    try:
        _externalize_large_event(conn, saved)
        payload = saved.get("payload", {})
        row = conn.execute("SELECT next_sequence_no FROM run_stream_cursors WHERE run_id=?", (run_id,)).fetchone()
        sequence = int(row["next_sequence_no"]) if row else 1
        now = _now(); saved["sequence_no"] = sequence; saved.setdefault("timestamp", now)
        if row:
            conn.execute("UPDATE run_stream_cursors SET next_sequence_no=?,last_persisted_sequence_no=?,updated_at=? WHERE run_id=?", (sequence + 1, sequence, now, run_id))
        else:
            conn.execute("INSERT INTO run_stream_cursors VALUES(?,?,?,?,?)", (run_id, sequence + 1, sequence, 0, now))
        if run_state is not None:
            current = conn.execute("SELECT state FROM runs WHERE id=?", (run_id,)).fetchone()
            if current is None:
                raise KeyError(run_id)
            if current["state"] != run_state:
                validate_run_transition(current["state"], run_state)
        assignments = ["last_sequence_no=?", "updated_at=?"]
        arguments: list[Any] = [sequence, now]
        for column, value in (run_updates or {}).items():
            if column not in _RUN_UPDATE_COLUMNS:
                raise ValueError(f"unsupported run update column: {column}")
            assignments.append(f"{column}=?")
            arguments.append(value)
        if run_state is not None:
            assignments.append("state=?")
            arguments.append(run_state)
        if step_state is not None and saved.get("step_id"):
            conn.execute("UPDATE run_steps SET state=? WHERE id=? AND run_id=?", (step_state, saved["step_id"], run_id))
        conn.execute("INSERT INTO run_events(event_id,run_id,step_id,session_id,sequence_no,event_type,timestamp,payload_json,source_tool,source_event_type,raw_json,persisted_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", (saved["event_id"], run_id, saved.get("step_id"), saved.get("session_id"), sequence, kind, saved["timestamp"], json.dumps(payload, sort_keys=True), saved.get("source_tool", "unknown"), saved.get("source_event_type"), json.dumps(saved.get("raw", payload), sort_keys=True), now))
        conn.execute(f"UPDATE runs SET {', '.join(assignments)} WHERE id=?", (*arguments, run_id))
        conn.commit()
    except Exception:
        conn.rollback(); raise
    if kind == "usage.updated": record_live_usage(conn, saved)
    if broadcast: broadcast(saved)
    return saved


def _externalize_large_event(conn: sqlite3.Connection, event: dict[str, Any]) -> None:
    """Keep oversized raw/event payloads in a run-scoped artifact, not SQLite.

    The artifact is stored beside the product database, never in engineering
    `.artifacts/`; its database record and the compact event reference commit
    together. Sensitive-looking object keys are redacted before either form is
    persisted.
    """
    payload = _redact(event.get("payload", {}))
    raw = _redact(event.get("raw", payload))
    event["payload"] = payload
    event["raw"] = raw
    encoded = json.dumps({"payload": payload, "raw": raw}, ensure_ascii=False, sort_keys=True).encode("utf-8")
    if len(encoded) <= _INLINE_EVENT_BYTES:
        return
    database = next((Path(row[2]) for row in conn.execute("PRAGMA database_list") if row[1] == "main" and row[2]), None)
    if database is None:
        raise RuntimeError("unable to locate workbench database for artifact storage")
    artifact_id = str(uuid4())
    root = database.parent / "run-artifacts" / str(event["run_id"])
    root.mkdir(parents=True, exist_ok=True)
    filename = f"{artifact_id}.json"
    target = root / filename
    temporary = root / f".{filename}.tmp"
    temporary.write_bytes(encoded)
    os.replace(temporary, target)
    digest = hashlib.sha256(encoded).hexdigest()
    relative = target.relative_to(database.parent).as_posix()
    preview = _preview(payload)
    reference = {"artifact_id": artifact_id, "relative_path": relative, "sha256": digest,
                 "size_bytes": len(encoded), "preview": preview, "redaction_state": "redacted"}
    created_at = _now()
    expires_at = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat().replace("+00:00", "Z")
    conn.execute(
        "INSERT INTO run_artifacts(id,run_id,step_id,kind,relative_path,sha256,size_bytes,mime_type,redaction_state,created_at,expires_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        (artifact_id, event["run_id"], event.get("step_id"), "event_payload", relative, digest,
         len(encoded), "application/json", "redacted", created_at, expires_at),
    )
    event["payload"] = {"artifact": reference}
    event["raw"] = {"artifact": reference}


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): "[redacted]" if any(part in str(key).lower() for part in _SENSITIVE_KEY_PARTS) else _redact(item)
                for key, item in value.items()}
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value


def _preview(value: Any) -> str:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    return text[:512] + ("…" if len(text) > 512 else "")


def persist_status_change(conn: sqlite3.Connection, *, run_id: str, step_id: str | None,
                          state: str, source_tool: str, reason: str | None = None,
                          run_updates: dict[str, Any] | None = None,
                          step_state: str | None = None,
                          broadcast: Callable[[dict[str, Any]], None] | None = runtime_broadcaster.publish) -> dict[str, Any]:
    """Persist a legal state transition and its visible status event atomically."""
    return persist_event(
        conn,
        {
            "event_id": hashlib.sha256(f"{run_id}:{state}:{_now()}".encode()).hexdigest(),
            "run_id": run_id,
            "step_id": step_id,
            "source_tool": source_tool,
            "source_event_type": "workbench/status",
            "event_type": "run.status_changed",
            "payload": {"state": state, "reason": reason},
        },
        broadcast=broadcast,
        run_state=state,
        step_state=step_state,
        run_updates=run_updates,
    )

def resync_events(conn: sqlite3.Connection, run_id: str, last_sequence_no: int) -> dict[str, Any]:
    """Return events after a reconnect cursor and report persisted sequence gaps."""
    rows = conn.execute("SELECT * FROM run_events WHERE run_id=? ORDER BY sequence_no", (run_id,)).fetchall()
    numbers = [int(r["sequence_no"]) for r in rows]; contiguous = numbers == list(range(1, max(numbers, default=0) + 1))
    events = []
    for r in rows:
        if int(r["sequence_no"]) > last_sequence_no:
            item = dict(r); item["payload"] = json.loads(item.pop("payload_json")); events.append(item)
    return {"events": events, "resync_required": not contiguous}

def record_live_usage(conn: sqlite3.Connection, event: dict[str, Any]) -> str:
    """Write a live usage observation and one primary record for an exact native match."""
    payload = dict(event.get("payload") or {}); tool = event.get("source_tool") or payload.get("tool"); session = event.get("session_id") or payload.get("native_session_id")
    request_id = payload.get("request_id") or payload.get("requestId"); turn_id = payload.get("native_turn_id") or payload.get("turn_id") or payload.get("turnId"); observed = event.get("timestamp") or _now()
    key = hashlib.sha256(f"live|{event['event_id']}".encode()).hexdigest(); dedup = hashlib.sha256(json.dumps([tool, session, request_id, turn_id, payload], sort_keys=True).encode()).hexdigest()
    conn.execute("INSERT OR IGNORE INTO observations(id,observation_kind,source,native_session_id,native_turn_id,native_event_id,request_id,tool,observed_at,payload_hash,quality,parser_version,parse_status,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (key, "supervised_run", "workbench_live", session, turn_id, event["event_id"], request_id, tool, observed, hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest(), "exact", "workbench-live-v1", "parsed", observed))
    prior = conn.execute("SELECT u.* ,o.native_session_id,o.request_id FROM usage_records u JOIN observations o ON o.id=u.observation_id WHERE o.tool=? AND o.native_session_id=? AND ((? IS NOT NULL AND o.request_id=?) OR (? IS NOT NULL AND o.native_turn_id=?)) LIMIT 1", (tool, session, request_id, request_id, turn_id, turn_id)).fetchone()
    status = "primary"
    if prior:
        decision = merge_decision({**payload, "request_id": request_id, "native_session_id": session, "event_at": observed}, dict(prior)); status = "duplicate" if decision.status == "duplicate" else "conflict" if decision.status == "conflict" else "primary"
    conn.execute("INSERT OR IGNORE INTO usage_records(id,observation_id,dedup_key,event_kind,input_tokens,output_tokens,cache_read_tokens,cache_creation_tokens,reasoning_tokens,total_tokens,counter_scope,counter_reset,event_at,recorded_at,source,quality,parser_version,merge_status,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (hashlib.sha256(dedup.encode()).hexdigest(), key, dedup, "request_delta", payload.get("input_tokens"), payload.get("output_tokens"), payload.get("cache_read_tokens"), payload.get("cache_creation_tokens"), payload.get("reasoning_tokens"), payload.get("total_tokens"), "request", 0, observed, observed, "workbench_live", "exact", "workbench-live-v1", status, observed)); conn.commit(); return status
