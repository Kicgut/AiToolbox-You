"""Validated, idempotent creation of one interactive Phase 3 run."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


class ComposerError(ValueError):
    """A user-correctable run submission error with a stable API code."""

    def __init__(self, message: str, code: str = "invalid_run_request") -> None:
        super().__init__(message)
        self.code = code


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _request_hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def compose_run(
    conn: Any,
    *,
    action: str,
    tool: str,
    profile_id: str,
    cwd: str,
    prompt: str | None = None,
    prompts: list[str] | None = None,
    model: str | None = None,
    permission_policy: dict | None = None,
    budget_policy: dict | None = None,
    session_copy_id: str | None = None,
    client_request_id: str | None = None,
    mode: str | None = None,
) -> dict[str, Any]:
    """Create a queued, single-turn run without spawning a process.

    ``prompts`` and ``mode`` are accepted only as a short compatibility bridge for
    callers written before the Phase 3 single-turn contract. New callers pass one
    ``prompt`` and one ``action``.
    """
    if action not in {"new", "resume", "fork"}:
        raise ComposerError("invalid composer action")
    if mode is not None and mode != action:
        raise ComposerError("action and mode must match")
    if prompt is None and prompts is not None:
        if len(prompts) != 1:
            raise ComposerError("Phase 3 accepts exactly one prompt per run", "single_turn_required")
        prompt = prompts[0]
    if not isinstance(prompt, str) or not prompt.strip():
        raise ComposerError("prompt must be a non-empty string")
    if len(prompt) > 100_000:
        raise ComposerError("prompt exceeds the 100000 character limit", "prompt_too_large")
    if not os.path.isdir(cwd):
        raise ComposerError("cwd does not exist", "cwd_not_found")
    normalized_cwd = os.path.normcase(os.path.realpath(cwd))

    profile = conn.execute(
        "SELECT id,tool,config_root,session_root,enabled FROM tool_profiles WHERE id=?", (profile_id,)
    ).fetchone()
    if profile is None or profile["tool"] != tool or not profile["enabled"]:
        raise ComposerError("profile does not belong to selected tool", "invalid_profile")

    source_native_session_id: str | None = None
    if action == "new":
        if session_copy_id:
            raise ComposerError("new runs cannot include session_copy_id", "unexpected_session_copy")
    else:
        if not session_copy_id:
            raise ComposerError("resume and fork require session_copy_id", "session_copy_required")
        copy = conn.execute(
            "SELECT profile_id,tool,native_session_id,index_status FROM session_copies WHERE id=?",
            (session_copy_id,),
        ).fetchone()
        if copy is None or copy["profile_id"] != profile_id or copy["tool"] != tool:
            raise ComposerError("session_copy_id does not belong to selected profile", "invalid_session_copy")
        if copy["index_status"] not in {"indexed", "active", "available"}:
            raise ComposerError("session copy is not available for interactive use", "session_copy_unavailable")
        source_native_session_id = copy["native_session_id"]
        if not source_native_session_id:
            raise ComposerError("session copy has no native session id", "native_session_missing")

    permission_policy = dict(permission_policy or {})
    budget_policy = dict(budget_policy or {})
    request_body = {
        "action": action,
        "tool": tool,
        "profile_id": profile_id,
        "session_copy_id": session_copy_id,
        "cwd": normalized_cwd,
        "model": model,
        "permission_policy": permission_policy,
        "budget_policy": budget_policy,
        "prompt": prompt,
    }
    body_hash = _request_hash(request_body)
    if client_request_id:
        existing = conn.execute("SELECT * FROM runs WHERE client_request_id=?", (client_request_id,)).fetchone()
        if existing:
            if existing["request_body_hash"] not in {None, body_hash}:
                raise ComposerError("client_request_id was already used for different content", "idempotency_conflict")
            return {"run": dict(existing), "idempotent": True}

    now = _now()
    run_id = str(uuid4())
    step_id = str(uuid4())
    execution_path = "codex_app_server" if tool == "codex" else "claude_step_process"
    snapshot = {
        **request_body,
        "profile_root_identity": os.path.normcase(os.path.realpath(profile["config_root"])),
        "created_at": now,
    }
    conn.execute("BEGIN IMMEDIATE")
    try:
        if client_request_id:
            race = conn.execute("SELECT * FROM runs WHERE client_request_id=?", (client_request_id,)).fetchone()
            if race:
                conn.commit()
                if race["request_body_hash"] not in {None, body_hash}:
                    raise ComposerError("client_request_id was already used for different content", "idempotency_conflict")
                return {"run": dict(race), "idempotent": True}
        conn.execute(
            """INSERT INTO runs(
                id,tool,client_request_id,request_body_hash,profile_id,session_copy_id,
                source_native_session_id,model,cwd,mode,execution_path,
                permission_policy_json,budget_policy_json,capabilities_snapshot_json,
                dispatch_state,state,created_at,updated_at,config_snapshot_json
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                run_id, tool, client_request_id, body_hash, profile_id, session_copy_id,
                source_native_session_id, model, normalized_cwd, action, execution_path,
                json.dumps(permission_policy, sort_keys=True), json.dumps(budget_policy, sort_keys=True),
                "{}", "not_started", "queued", now, now, json.dumps(snapshot, sort_keys=True),
            ),
        )
        conn.execute(
            """INSERT INTO run_steps(id,run_id,ordinal,prompt_text,state,timeout_ms)
               VALUES(?,?,?,?,?,?)""",
            (step_id, run_id, 1, prompt, "queued", _timeout_ms(budget_policy)),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return {"run": dict(conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()), "idempotent": False}


def request_cancel(conn: Any, run_id: str) -> dict[str, Any]:
    """Persist an idempotent cancellation request; the coordinator owns cleanup."""
    now = _now()
    row = conn.execute("SELECT state,tool FROM runs WHERE id=?", (run_id,)).fetchone()
    if row is None:
        raise KeyError(run_id)
    step = conn.execute("SELECT id FROM run_steps WHERE run_id=? ORDER BY ordinal LIMIT 1", (run_id,)).fetchone()
    # Every state change is emitted by the same durable event transaction.  The
    # coordinator owns process cleanup, while this wakes attached Run Centers.
    from app.ai_workbench.event_persistence import persist_status_change

    if row["state"] == "queued":
        persist_status_change(
            conn, run_id=run_id, step_id=step["id"] if step else None, state="cancelled", source_tool=row["tool"],
            reason="cancelled_before_dispatch", step_state="cancelled", run_updates={"finished_at": now},
        )
    elif row["state"] in {"starting", "running", "waiting_approval"}:
        persist_status_change(
            conn, run_id=run_id, step_id=step["id"] if step else None, state="cancel_requested", source_tool=row["tool"],
            reason="user_requested", step_state="cancel_requested", run_updates={"cancel_requested_at": now},
        )
    return dict(conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone())


def cancel_run(conn: Any, run_id: str) -> dict[str, Any]:
    """Backward-compatible name for the API's cancellation request operation."""
    return request_cancel(conn, run_id)


def retry_failed_step(conn: Any, run_id: str, step_id: str) -> dict[str, Any]:
    """Create a new run for a failed/interrupted source step; never reopen it."""
    step = conn.execute("SELECT * FROM run_steps WHERE id=? AND run_id=?", (step_id, run_id)).fetchone()
    run = conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
    if step is None or run is None:
        raise KeyError(step_id if step is None else run_id)
    if run["state"] not in {"failed", "interrupted", "cancelled"} or step["state"] not in {"failed", "interrupted", "cancelled"}:
        raise ComposerError("only a terminal unsuccessful step can be retried", "retry_not_allowed")
    result = compose_run(
        conn,
        action=run["mode"],
        tool=run["tool"],
        profile_id=run["profile_id"],
        cwd=run["cwd"],
        prompt=step["prompt_text"],
        model=run["model"],
        permission_policy=json.loads(run["permission_policy_json"]),
        budget_policy=json.loads(run["budget_policy_json"]),
        session_copy_id=run["session_copy_id"],
    )
    now = _now()
    conn.execute(
        "UPDATE runs SET retry_of_run_id=?, retry_of_step_id=?, updated_at=? WHERE id=?",
        (run_id, step_id, now, result["run"]["id"]),
    )
    conn.commit()
    result["step"] = dict(conn.execute("SELECT * FROM run_steps WHERE run_id=?", (result["run"]["id"],)).fetchone())
    result["run"] = dict(conn.execute("SELECT * FROM runs WHERE id=?", (result["run"]["id"],)).fetchone())
    return result


def _timeout_ms(budget_policy: dict[str, Any]) -> int | None:
    value = budget_policy.get("max_duration_ms")
    if value is None and budget_policy.get("max_duration_seconds") is not None:
        value = int(budget_policy["max_duration_seconds"]) * 1000
    if value is None:
        return None
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise ComposerError("max_duration must be an integer", "invalid_budget") from exc
    if result <= 0 or result > 3_600_000:
        raise ComposerError("max_duration must be between 1 and 3600000 ms", "invalid_budget")
    return result
