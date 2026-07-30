"""Database-backed approval bridge primitives."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def create_approval(conn: Any, *, run_id: str, step_id: str, native_request_id: str,
                    operation: str, target_summary: str, risk_level: str,
                    command_argv: list[str] | None = None, cwd: str | None = None,
                    affected_paths: list[str] | None = None, reason: str | None = None,
                    expires_at: str | None = None) -> dict[str, Any]:
    """Create an idempotent pending request; disconnects never decide it."""
    row = conn.execute(
        "SELECT * FROM approval_requests WHERE run_id=? AND native_request_id=?",
        (run_id, native_request_id),
    ).fetchone()
    if row:
        return dict(row)
    request_id = str(uuid4())
    conn.execute("""INSERT INTO approval_requests
        (id,run_id,step_id,native_request_id,operation,target_summary,risk_level,
         command_argv_json,cwd,affected_paths_json,reason,expires_at,state,disconnect_policy)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,'wait')""", (
        request_id, run_id, step_id, native_request_id, operation, target_summary,
        risk_level, json.dumps(command_argv) if command_argv is not None else None,
        cwd, json.dumps(affected_paths) if affected_paths is not None else None,
        reason, expires_at, "pending"))
    conn.commit()
    return dict(conn.execute("SELECT * FROM approval_requests WHERE id=?", (request_id,)).fetchone())


def decide_approval(conn: Any, request_id: str, *, decision: str, decided_by: str) -> dict[str, Any]:
    if decision not in {"accept", "decline", "cancel"}:
        raise ValueError("invalid approval decision")
    now = _now()
    cur = conn.execute("""UPDATE approval_requests
        SET state=?, decision=?, decided_at=?, decided_by=?
        WHERE id=? AND state='pending'""", ("responding", decision, now, decided_by, request_id))
    conn.commit()
    row = conn.execute("SELECT * FROM approval_requests WHERE id=?", (request_id,)).fetchone()
    if row is None:
        raise KeyError(request_id)
    result = dict(row)
    if cur.rowcount != 1:
        result["conflict"] = True
    return result


def record_approval_delivery(conn: Any, request_id: str, *, delivered: bool) -> dict[str, Any]:
    """Finalize a responding decision only after its native response was sent."""
    row = conn.execute("SELECT * FROM approval_requests WHERE id=?", (request_id,)).fetchone()
    if row is None:
        raise KeyError(request_id)
    if row["state"] != "responding":
        return {**dict(row), "conflict": True}
    final = (
        "accepted" if row["decision"] == "accept" else "declined" if row["decision"] == "decline" else "cancelled"
    ) if delivered else "delivery_failed"
    conn.execute("UPDATE approval_requests SET state=? WHERE id=? AND state='responding'", (final, request_id))
    conn.commit()
    return dict(conn.execute("SELECT * FROM approval_requests WHERE id=?", (request_id,)).fetchone())


def expire_approvals(conn: Any, *, now: str | None = None) -> int:
    now = now or _now()
    cur = conn.execute("""UPDATE approval_requests SET state='expired'
        WHERE state='pending' AND expires_at IS NOT NULL AND expires_at < ?""", (now,))
    conn.commit()
    return cur.rowcount
