"""Validated, idempotent creation of one interactive Phase 3 run."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4
from app.ai_workbench.storage import acquire_writer_lease, release_writer_lease
from app.ai_workbench.execution.codex_runtime import resolve_codex_executable
from app.ai_workbench.execution.claude_runtime import resolve_claude_executable


class ComposerError(ValueError):
    """A user-correctable run submission error with a stable API code."""

    def __init__(self, message: str, code: str = "invalid_run_request") -> None:
        super().__init__(message)
        self.code = code


def execution_capabilities_for(tool: str) -> dict[str, Any]:
    """Capabilities that the current adapters can actually guarantee at submit time.

    This is intentionally conservative: a requested constraint is rejected when
    an adapter fallback could silently drop it.
    """
    common = {
        "actions": ["new", "resume", "fork"],
        "structured_events": True,
        "model_selection": True,
        "max_duration": "enforced",
        "max_turns": 1,
        "observed_budget_fields": ["max_total_tokens_observed", "max_cost_minor_observed"],
        "limit_strengths": {
            "max_turns": "hard", "max_duration_seconds": "hard",
            "max_total_tokens_observed": "observed_only", "max_cost_minor_observed": "observed_only",
        },
    }
    if tool == "codex":
        return {**common, "native_approval": True, "sandbox": ["read-only"],
                "approval_policy": ["on-request", "never", "untrusted"],
                "tool_allow_deny_lists": False, "max_budget_usd": False,
                "limit_strengths": {**common["limit_strengths"], "max_budget_usd": "unsupported"}}
    if tool == "claude":
        return {**common, "native_approval": False, "sandbox": [],
                "tool_allow_deny_lists": True, "max_budget_usd": True,
                "limit_strengths": {**common["limit_strengths"], "max_budget_usd": "provider_enforced"}}
    return {}


def _validate_execution_contract(tool: str, action: str, model: str | None, permission_policy: dict[str, Any], budget_policy: dict[str, Any]) -> None:
    capabilities = execution_capabilities_for(tool)
    if not capabilities or action not in capabilities.get("actions", []):
        raise ComposerError(f"action {action} is not supported by the selected adapter", "unsupported_action")
    if model is not None and (not isinstance(model, str) or not model.strip() or len(model) > 200):
        raise ComposerError("model must be a non-empty string under 200 characters", "invalid_model")
    for field in ("allowed_tools", "disallowed_tools"):
        value = permission_policy.get(field, [])
        if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
            raise ComposerError(f"{field} must be a list of non-empty strings", "invalid_permission_policy")
        if value and not capabilities["tool_allow_deny_lists"]:
            raise ComposerError(f"{field} cannot be guaranteed by the selected adapter", "unsupported_permission_policy")
    if tool == "codex":
        sandbox = permission_policy.get("sandbox", "read-only")
        if sandbox != "read-only":
            raise ComposerError("Codex Phase 3 only guarantees a read-only sandbox", "unsupported_permission_policy")
        approval_policy = permission_policy.get("approval_policy", "on-request")
        if approval_policy not in capabilities["approval_policy"]:
            raise ComposerError("unsupported Codex approval policy", "invalid_permission_policy")
        if budget_policy.get("max_budget_usd") is not None:
            raise ComposerError("Codex adapter cannot hard-enforce max_budget_usd", "unsupported_budget_policy")
    if budget_policy.get("max_turns", 1) != 1:
        raise ComposerError("Phase 3 accepts exactly one turn per run", "single_turn_required")
    for field in ("max_total_tokens_observed", "max_cost_minor_observed"):
        value = budget_policy.get(field)
        if value is not None and (not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0):
            raise ComposerError(f"{field} must be a non-negative number", "invalid_budget")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _request_hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def _profile_environment_snapshot(tool: str, config_root: str) -> dict[str, Any]:
    """Record only child-env names and a non-reversible root identity."""
    variable = "CODEX_HOME" if tool == "codex" else "CLAUDE_CONFIG_DIR"
    normalized_root = os.path.normcase(os.path.realpath(config_root))
    return {
        "variable_names": [variable],
        "value_sha256": {variable: hashlib.sha256(normalized_root.encode("utf-8")).hexdigest()},
    }


def _profile_snapshot(tool: str, config_root: str, session_root: str) -> dict[str, Any]:
    """Capture normalized profile roots and the executable resolution used by runtime."""
    executable = resolve_codex_executable() if tool == "codex" else resolve_claude_executable()
    executable_available = bool(executable and (os.path.isfile(executable) or shutil.which(executable)))
    return {
        "config_root": os.path.normcase(os.path.realpath(config_root)),
        "session_root": os.path.normcase(os.path.realpath(session_root)),
        "executable": executable,
        "executable_configured": executable_available,
    }


def _observed_capability(conn: Any, tool: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT payload_json FROM runtime_capability_baselines ORDER BY id DESC LIMIT 1").fetchone()
    if not row:
        return None
    try:
        payload = json.loads(row["payload_json"] or "{}")
    except (TypeError, json.JSONDecodeError):
        return None
    value = payload.get(tool)
    return value if isinstance(value, dict) else None


def compose_run(
    conn: Any,
    *,
    action: str,
    tool: str,
    profile_id: str,
    cwd: str,
    cwd_confirmed: bool = True,
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
    if not cwd_confirmed:
        project_roots = [row[0] for row in conn.execute(
            "SELECT cwd_canonical FROM projects WHERE exists_on_disk=1 AND cwd_canonical IS NOT NULL"
        ).fetchall()]
        registered = False
        for root in project_roots:
            normalized_root = os.path.normcase(os.path.realpath(root))
            try:
                if os.path.commonpath((normalized_cwd, normalized_root)) == normalized_root:
                    registered = True
                    break
            except ValueError:
                continue
        if not registered:
            raise ComposerError("cwd is not a registered project root; explicit confirmation is required", "cwd_confirmation_required")

    profile = conn.execute(
        "SELECT id,tool,config_root,session_root,enabled FROM tool_profiles WHERE id=?", (profile_id,)
    ).fetchone()
    if profile is None or profile["tool"] != tool or not profile["enabled"]:
        raise ComposerError("profile does not belong to selected tool", "invalid_profile")

    observed = _observed_capability(conn, tool)
    if observed and observed.get("status") == "missing":
        raise ComposerError("selected CLI is not available on this device", "cli_unavailable")
    if action == "fork" and tool == "codex" and observed and observed.get("features", {}).get("app_server") is False:
        raise ComposerError("Codex App Server is not available for Fork", "unsupported_action")

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
    _validate_execution_contract(tool, action, model, permission_policy, budget_policy)
    request_body = {
        "action": action,
        "tool": tool,
        "profile_id": profile_id,
        "session_copy_id": session_copy_id,
        "cwd": normalized_cwd,
        "cwd_confirmed": cwd_confirmed,
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
        "profile": _profile_snapshot(tool, profile["config_root"], profile["session_root"]),
        "profile_environment": _profile_environment_snapshot(tool, profile["config_root"]),
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
                json.dumps(execution_capabilities_for(tool), sort_keys=True), "not_started", "queued", now, now, json.dumps(snapshot, sort_keys=True),
            ),
        )
        if source_native_session_id:
            lease_key = f"{tool}:{profile_id}:{source_native_session_id}"
            generation = acquire_writer_lease(
                conn, physical_session_key=lease_key, run_id=run_id, owner_id=f"composer:{run_id}",
                now=now, expires_at=(datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat().replace("+00:00", "Z"),
                transactional=False,
            )
            conn.execute("UPDATE runs SET lease_generation=? WHERE id=?", (generation, run_id))
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

    try:
        if row["state"] == "queued":
            persist_status_change(
                conn, run_id=run_id, step_id=step["id"] if step else None, state="cancelled", source_tool=row["tool"],
                reason="cancelled_before_dispatch", step_state="cancelled", run_updates={"finished_at": now},
            )
            source = conn.execute("SELECT source_native_session_id,profile_id FROM runs WHERE id=?", (run_id,)).fetchone()
            if source and source["source_native_session_id"]:
                generation = conn.execute("SELECT lease_generation FROM runs WHERE id=?", (run_id,)).fetchone()[0]
                release_writer_lease(conn, physical_session_key=f"{row['tool']}:{source['profile_id']}:{source['source_native_session_id']}", run_id=run_id, lease_generation=int(generation))
        elif row["state"] in {"starting", "running", "waiting_approval"}:
            persist_status_change(
                conn, run_id=run_id, step_id=step["id"] if step else None, state="cancel_requested", source_tool=row["tool"],
                reason="user_requested", step_state="cancel_requested", run_updates={"cancel_requested_at": now},
            )
    except ValueError:
        # A worker can complete in the narrow window after the API reads the
        # state and before its durable transition commits. A terminal fact wins
        # over cancellation; return it as an idempotent cancel response.
        latest = conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        if latest and latest["state"] in {"succeeded", "failed", "cancelled", "interrupted"}:
            return dict(latest)
        raise
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
