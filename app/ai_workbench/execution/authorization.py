"""One-time authorization checks for the separately approved P3-10 gate."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class AuthorizationError(ValueError):
    def __init__(self, message: str, code: str) -> None:
        super().__init__(message)
        self.code = code


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def nonce_hash(nonce: str) -> str:
    return hashlib.sha256(nonce.encode("utf-8")).hexdigest()


def load_p3_10_approval(conn: Any, path: Path) -> dict[str, Any]:
    """Load a local approval artifact without ever storing its raw nonce.

    The artifact must name exactly one request body hash and hard upper bounds.
    Re-loading is idempotent but cannot reset a consumed authorization.
    """
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AuthorizationError("P3-10 approval artifact cannot be read", "approval_artifact_invalid") from exc
    required = {"nonce", "request_body_hash", "expires_at", "allowed_tools", "budget_policy", "max_uses"}
    if not required.issubset(document) or not isinstance(document["nonce"], str):
        raise AuthorizationError("P3-10 approval artifact is missing required fields", "approval_artifact_invalid")
    if document.get("mode", "p3_10") != "p3_10":
        raise AuthorizationError("approval artifact is not for P3-10", "approval_mode_invalid")
    if not isinstance(document["allowed_tools"], list) or set(document["allowed_tools"]) - {"codex", "claude"}:
        raise AuthorizationError("approval artifact has invalid allowed_tools", "approval_artifact_invalid")
    if not isinstance(document["budget_policy"], dict) or not isinstance(document["max_uses"], int) or document["max_uses"] < 1:
        raise AuthorizationError("approval artifact has invalid limits", "approval_artifact_invalid")
    try:
        _parse_time(document["expires_at"])
    except (TypeError, ValueError) as exc:
        raise AuthorizationError("approval artifact has invalid expiry", "approval_artifact_invalid") from exc
    digest = nonce_hash(document["nonce"])
    existing = conn.execute("SELECT * FROM real_execution_authorizations WHERE nonce_hash=?", (digest,)).fetchone()
    if existing:
        return dict(existing)
    now = _now().isoformat().replace("+00:00", "Z")
    conn.execute(
        "INSERT INTO real_execution_authorizations(nonce_hash,mode,request_body_hash,allowed_tools_json,model,budget_policy_json,max_uses,expires_at,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
        (digest, "p3_10", document["request_body_hash"], json.dumps(document["allowed_tools"], sort_keys=True),
         document.get("model"), json.dumps(document["budget_policy"], sort_keys=True), document["max_uses"], document["expires_at"], now),
    )
    conn.commit()
    return dict(conn.execute("SELECT * FROM real_execution_authorizations WHERE nonce_hash=?", (digest,)).fetchone())


def consume_p3_10_authorization(conn: Any, *, nonce: str | None, request_body_hash: str,
                                 tool: str, model: str | None, budget_policy: dict[str, Any]) -> None:
    """Atomically consume one exact approved request before it can be enqueued."""
    if not nonce:
        raise AuthorizationError("P3-10 execution requires a one-time authorization nonce", "authorization_required")
    digest = nonce_hash(nonce)
    conn.execute("BEGIN IMMEDIATE")
    try:
        row = conn.execute("SELECT * FROM real_execution_authorizations WHERE nonce_hash=?", (digest,)).fetchone()
        if row is None:
            raise AuthorizationError("authorization nonce is unknown", "authorization_unknown")
        if _parse_time(row["expires_at"]) <= _now():
            raise AuthorizationError("authorization nonce has expired", "authorization_expired")
        if row["request_body_hash"] != request_body_hash:
            raise AuthorizationError("authorization does not match this request", "authorization_mismatch")
        if tool not in json.loads(row["allowed_tools_json"]):
            raise AuthorizationError("authorization does not permit this tool", "authorization_mismatch")
        if row["model"] is not None and row["model"] != model:
            raise AuthorizationError("authorization does not permit this model", "authorization_mismatch")
        approved_budget = json.loads(row["budget_policy_json"])
        if budget_policy != approved_budget:
            raise AuthorizationError("authorization does not match this budget policy", "authorization_mismatch")
        if int(row["consumed_uses"]) >= int(row["max_uses"]):
            raise AuthorizationError("authorization nonce has already been consumed", "authorization_consumed")
        conn.execute(
            "UPDATE real_execution_authorizations SET consumed_uses=consumed_uses+1,consumed_at=? WHERE nonce_hash=? AND consumed_uses < max_uses",
            (_now().isoformat().replace("+00:00", "Z"), digest),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
