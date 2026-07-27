"""Auditable observation matching and pricing semantics."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
import sqlite3


@dataclass(frozen=True)
class MergeDecision:
    status: str
    counting_policy: str
    conflict_group_id: str | None = None
    reason_code: str | None = None


def merge_decision(left: dict[str, Any], right: dict[str, Any]) -> MergeDecision:
    """Never merge weak matches; equal stable request identities are safe."""
    request_left, request_right = left.get("request_id"), right.get("request_id")
    token_fields = ("input_tokens", "output_tokens", "cache_read_tokens", "cache_creation_tokens")
    same_tokens = all(left.get(k) == right.get(k) for k in token_fields)
    if request_left and request_right and request_left == request_right:
        if same_tokens:
            return MergeDecision("duplicate", "count_primary_once", reason_code="same_request_same_tokens")
        return MergeDecision("conflict", "count_primary_only_until_review", conflict_group_id=f"conflict:{request_left}", reason_code="same_request_different_tokens")
    return MergeDecision("unmatched", "count_independently", reason_code="no_stable_identity")


def estimate_cost(record: dict[str, Any], snapshot: dict[str, Any] | None) -> dict[str, Any]:
    if snapshot is None:
        return {"value_minor": None, "availability": "unavailable", "quality": "unavailable", "reason_code": "no_pricing_snapshot"}
    required = ("currency", "unit", "effective_at", "model_key")
    if any(not snapshot.get(key) for key in required) or snapshot.get("validation_status") != "valid" or snapshot.get("trust_state") != "trusted":
        return {"value_minor": None, "availability": "unavailable", "quality": "unavailable", "reason_code": "pricing_snapshot_incomplete"}
    event_at = record.get("event_at")
    if not event_at or _parse(snapshot["effective_at"]) > _parse(event_at):
        return {"value_minor": None, "availability": "unavailable", "quality": "unavailable", "reason_code": "no_price_effective_at_event"}
    total = 0.0
    formula = []
    for field, price_key in (("input_tokens", "input_price_per_million"), ("output_tokens", "output_price_per_million"), ("cache_read_tokens", "cache_read_price_per_million"), ("cache_creation_tokens", "cache_creation_price_per_million")):
        tokens, price = record.get(field), snapshot.get(price_key)
        if tokens is not None and price is not None:
            total += tokens * float(price) / 1_000_000
            formula.append(f"{field}*{price_key}/1000000")
    if not formula:
        return {"value_minor": None, "availability": "unavailable", "quality": "unavailable", "reason_code": "missing_price_component"}
    return {"value_minor": round(total * 100), "availability": "available", "quality": "estimated", "source": snapshot.get("source_id"), "snapshot_id": snapshot.get("id"), "effective_at": snapshot.get("effective_at"), "currency": snapshot.get("currency"), "formula": " + ".join(formula)}


def _parse(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def reprice_usage(conn: sqlite3.Connection) -> dict[str, int]:
    """Apply only trusted, historically effective snapshots to usage records."""
    updated = unavailable = 0
    rows = conn.execute("""SELECT u.id,u.event_at,u.input_tokens,u.output_tokens,u.cache_read_tokens,u.cache_creation_tokens,o.model,o.provider
        FROM usage_records u JOIN observations o ON o.id=u.observation_id""").fetchall()
    for row in rows:
        snapshot = conn.execute("""SELECT * FROM pricing_snapshots
            WHERE model_key=? AND (provider=? OR provider='unknown')
              AND trust_state='trusted' AND validation_status='valid'
              AND effective_at IS NOT NULL AND effective_at <= ?
            ORDER BY effective_at DESC LIMIT 1""", (row["model"], row["provider"], row["event_at"] or "9999-12-31T00:00:00Z")).fetchone()
        result = estimate_cost(dict(row), dict(snapshot) if snapshot else None)
        if result.get("value_minor") is None:
            conn.execute("UPDATE usage_records SET estimated_cost_minor=NULL,pricing_snapshot_id=NULL,currency=NULL,cost_reason=? WHERE id=?", (result.get("reason_code"), row["id"])); unavailable += 1
        else:
            conn.execute("UPDATE usage_records SET estimated_cost_minor=?,pricing_snapshot_id=?,currency=?,cost_reason=NULL WHERE id=?", (result["value_minor"], result["snapshot_id"], result["currency"], row["id"])); updated += 1
    conn.commit()
    return {"updated": updated, "unavailable": unavailable}
