"""Small, dependency-free primitives shared by the statistics pipeline."""
from __future__ import annotations

from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
import csv
import io
import json
import uuid
import sqlite3
import threading
import hashlib
from typing import Any
from app.ai_workbench.merge import estimate_cost
from app.ai_workbench.compatibility.cc_switch import resolve_pricing_model

ROLLUP_ALGORITHM_VERSION = "rollup-v1"
MERGE_ALGORITHM_VERSION = "merge-v1"


def pricing_snapshot_sources(conn: sqlite3.Connection, *, model: str | None = None) -> list[dict[str, Any]]:
    """Return all pricing snapshots, preserving source conflicts for audit/UI display."""
    args: list[Any] = []
    where = ""
    if model:
        where = " WHERE model_key = ?"
        args.append(model)
    rows = conn.execute(
        "SELECT id, source_id, source_kind, model_key, provider, input_price_per_million, "
        "output_price_per_million, currency, unit, effective_at, source_updated_at, "
        "trust_state, validation_status FROM pricing_snapshots" + where + " ORDER BY model_key, effective_at, source_kind",
        args,
    ).fetchall()
    values = [dict(row) for row in rows]
    groups: dict[tuple[str, str | None], list[dict[str, Any]]] = {}
    for value in values:
        groups.setdefault((value["model_key"], value["provider"]), []).append(value)
    for group in groups.values():
        conflict = len({(item["input_price_per_million"], item["output_price_per_million"], item["currency"]) for item in group}) > 1
        for item in group:
            item["conflict_status"] = "conflict" if conflict else "clear"
    return values


def record_rollup_invalidation(conn: sqlite3.Connection, reason: str, *, bucket_date: str | None = None,
                               timezone_name: str = "UTC", observed_at: str | None = None) -> None:
    """Record a pending Workbench rollup invalidation for changed input or algorithms."""
    stamp = observed_at or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    bucket = bucket_date or stamp[:10]
    identity = hashlib.sha256(f"{reason}:{bucket}:{timezone_name}:{stamp}".encode()).hexdigest()
    conn.execute("INSERT OR IGNORE INTO rollup_invalidations(id,bucket_date,timezone,reason,min_observed_at,max_observed_at,status,created_at) VALUES(?,?,?,?,?,?,?,?)",
                 (identity, bucket, timezone_name, reason, stamp, stamp, "pending", stamp))


def utc_bucket(date_value: str | date, timezone_name: str) -> tuple[str, str]:
    """Return the exact UTC bounds for a local calendar day, including DST."""
    try:
        zone = ZoneInfo(timezone_name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError(f"invalid timezone: {timezone_name}") from exc
    local_date = date.fromisoformat(date_value) if isinstance(date_value, str) else date_value
    start = datetime.combine(local_date, time.min, tzinfo=zone)
    end = datetime.combine(local_date, time.min, tzinfo=zone).replace(day=local_date.day)
    # Adding one calendar day in the local zone preserves 23/24/25-hour days.
    from datetime import timedelta
    end = datetime.combine(local_date + timedelta(days=1), time.min, tzinfo=zone)
    fmt = lambda value: value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    return fmt(start), fmt(end)


def metric(value: int | float | None, *, quality: str = "exact", source: str | None = "native", reason: str | None = None, formula: str | None = None) -> dict:
    available = value is not None
    result = {"value": value, "availability": "available" if available else "unavailable", "quality": quality if available else "unavailable", "source": source if available else None, "reason_code": reason if available else (reason or "no_underlying_data")}
    if formula is not None: result["formula"] = formula
    return result


def statistics_overview(conn: sqlite3.Connection, *, start: str | None = None, end: str | None = None,
                        tool: str | None = None, profile_ref: str | None = None, timezone_name: str | None = None, project_ref: str | None = None, model: str | None = None, provider: str | None = None, source: str | None = None) -> dict:
    where, args = _filters(start, end, tool, profile_ref, timezone_name, project_ref, model, provider, source)
    row = conn.execute(f"""SELECT CASE WHEN count(request_count)=0 THEN NULL ELSE sum(request_count) END request_count, sum(input_tokens) input_tokens,
        sum(output_tokens) output_tokens, sum(cache_read_tokens) cache_read_tokens,
        sum(cache_creation_tokens) cache_creation_tokens, sum(reasoning_tokens) reasoning_tokens,
        sum(total_tokens) total_tokens, sum(recorded_cost_minor) actual,
        sum(estimated_cost_minor) estimate, max(recorded_actual_source) actual_source,
        max(recorded_actual_quality) actual_quality, max(estimate_source) estimate_source,
        max(estimate_quality) estimate_quality, max(estimate_formula) estimate_formula,
        max(source) rollup_source, max(quality) rollup_quality,
        max(pricing_snapshot_id) pricing_snapshot_id, max(pricing_effective_at) pricing_effective_at,
        max(recorded_actual_currency) recorded_actual_currency, max(estimate_currency) estimate_currency
        FROM daily_rollups {where}""", args).fetchone()
    pending = conn.execute("SELECT count(*) FROM rollup_invalidations WHERE status='pending'").fetchone()[0]
    metrics = {k: metric(row[k], quality=row["rollup_quality"] or "exact", source=row["rollup_source"], reason="no_rollup_data" if row[k] is None else None) for k in ("request_count", "input_tokens", "output_tokens", "cache_read_tokens", "cache_creation_tokens", "reasoning_tokens", "total_tokens")}
    metrics["actual"] = metric(row["actual"], quality=row["actual_quality"] or "exact", source=row["actual_source"], reason="no_recorded_cost" if row["actual"] is None else None)
    metrics["estimate"] = metric(row["estimate"], quality=row["estimate_quality"] or "estimated", source=row["estimate_source"], reason="no_pricing_snapshot" if row["estimate"] is None else None, formula=row["estimate_formula"])
    return {"filters": {"start": start, "end": end, "tool": tool, "profile_ref": profile_ref, "timezone": timezone_name},
            "metrics": metrics, "cost_provenance": {"source": row["estimate_source"], "snapshot_id": row["pricing_snapshot_id"], "effective_at": row["pricing_effective_at"], "currency": row["estimate_currency"], "formula": row["estimate_formula"], "recorded_actual_currency": row["recorded_actual_currency"]},
            "rollup_status": "stale" if pending else "available" if row["request_count"] is not None else "empty"}


def _attach_rollup_token_metrics(conn: sqlite3.Connection, rows: list[dict]) -> list[dict]:
    """Attach nullable reasoning and total token metrics to timeseries rows."""
    for row in rows:
        token_row = conn.execute("SELECT reasoning_tokens,total_tokens FROM daily_rollups WHERE bucket_date=? AND timezone=? AND tool IS ? AND profile_ref IS ? AND project_ref IS ? AND model IS ? AND provider IS ? LIMIT 1", (row["bucket_date"], row["timezone"], row["tool"], row["profile_ref"], row["project_ref"], row["model"], row["provider"])).fetchone()
        row["metrics"]["reasoning_tokens"] = metric(token_row["reasoning_tokens"] if token_row else None, source=row["provenance"].get("source"))
        row["metrics"]["total_tokens"] = metric(token_row["total_tokens"] if token_row else None, source=row["provenance"].get("source"))
    return rows


def statistics_timeseries(conn: sqlite3.Connection, **filters) -> list[dict]:
    where, args = _filters(filters.get("start"), filters.get("end"), filters.get("tool"), filters.get("profile_ref"), filters.get("timezone_name"), filters.get("project_ref"), filters.get("model"), filters.get("provider"), filters.get("source"))
    rows = conn.execute(f"SELECT * FROM daily_rollups {where} ORDER BY bucket_start_utc", args).fetchall()
    return _attach_rollup_token_metrics(conn, [{"bucket_date": r["bucket_date"], "timezone": r["timezone"], "bucket_start_utc": r["bucket_start_utc"], "bucket_end_utc": r["bucket_end_utc"],
             "tool": r["tool"], "profile_ref": r["profile_ref"], "project_ref": r["project_ref"], "model": r["model"], "provider": r["provider"],
             "metrics": {"request_count": metric(r["request_count"], source="usage_records"), "input_tokens": metric(r["input_tokens"], quality=r["quality"], source=r["source"]), "output_tokens": metric(r["output_tokens"], quality=r["quality"], source=r["source"]), "cache_read_tokens": metric(r["cache_read_tokens"], quality=r["quality"], source=r["source"]), "cache_creation_tokens": metric(r["cache_creation_tokens"], quality=r["quality"], source=r["source"]), "actual": metric(r["recorded_cost_minor"], quality=r["recorded_actual_quality"] or "exact", source=r["recorded_actual_source"], reason="no_recorded_cost" if r["recorded_cost_minor"] is None else None), "estimate": metric(r["estimated_cost_minor"], quality=r["estimate_quality"] or "estimated", source=r["estimate_source"], reason="no_pricing_snapshot" if r["estimated_cost_minor"] is None else None, formula=r["estimate_formula"])}, "provenance": {"source": r["estimate_source"], "snapshot_id": r["pricing_snapshot_id"], "effective_at": r["pricing_effective_at"], "currency": r["estimate_currency"], "formula": r["estimate_formula"], "pricing_snapshot_id": r["pricing_snapshot_id"], "pricing_effective_at": r["pricing_effective_at"], "recorded_actual_currency": r["recorded_actual_currency"], "estimate_currency": r["estimate_currency"], "parser_version": r["parser_version"], "rollup_version": r["rollup_version"], "merge_status": r["merge_status"], "conflict_group_id": r["conflict_group_id"]}} for r in rows])


def statistics_breakdown(conn: sqlite3.Connection, **filters) -> list[dict]:
    where, args = _filters(filters.get("start"), filters.get("end"), filters.get("tool"), filters.get("profile_ref"), filters.get("timezone_name"), filters.get("project_ref"), filters.get("model"), filters.get("provider"), filters.get("source"))
    rows = conn.execute(f"SELECT tool, model, provider, sum(request_count) request_count, sum(input_tokens) input_tokens, sum(output_tokens) output_tokens, sum(cache_read_tokens) cache_read_tokens, sum(cache_creation_tokens) cache_creation_tokens, sum(recorded_cost_minor) actual, sum(estimated_cost_minor) estimate, min(quality) quality, min(source) source, max(recorded_actual_source) actual_source, max(recorded_actual_quality) actual_quality, max(estimate_source) estimate_source, max(estimate_quality) estimate_quality, max(merge_status) merge_status, max(conflict_group_id) conflict_group_id, max(pricing_snapshot_id) pricing_snapshot_id, max(pricing_effective_at) pricing_effective_at, max(recorded_actual_currency) actual_currency, max(estimate_currency) estimate_currency, max(estimate_formula) estimate_formula FROM daily_rollups {where} GROUP BY tool, model, provider ORDER BY request_count DESC", args).fetchall()
    result = []
    for r in rows:
        conflict_count = conn.execute("SELECT count(*) FROM usage_records u JOIN observations o ON o.id=u.observation_id WHERE u.merge_status='conflict' AND o.tool IS ? AND o.model IS ? AND o.provider IS ?", (r["tool"], r["model"], r["provider"])).fetchone()[0]
        result.append({"tool": r["tool"], "model": r["model"], "provider": r["provider"], "conflict_count": conflict_count, "conflict_status": "conflict" if conflict_count else "clear", "metrics": {"request_count": metric(r["request_count"], source="usage_records"), "input_tokens": metric(r["input_tokens"], quality=r["quality"], source=r["source"]), "output_tokens": metric(r["output_tokens"], quality=r["quality"], source=r["source"]), "cache_read_tokens": metric(r["cache_read_tokens"], quality=r["quality"], source=r["source"]), "cache_creation_tokens": metric(r["cache_creation_tokens"], quality=r["quality"], source=r["source"]), "actual": metric(r["actual"], quality=r["actual_quality"] or "exact", source=r["actual_source"], reason="no_recorded_cost" if r["actual"] is None else None), "estimate": metric(r["estimate"], quality=r["estimate_quality"] or "estimated", source=r["estimate_source"], reason="no_pricing_snapshot" if r["estimate"] is None else None, formula=r["estimate_formula"])}, "provenance": {"merge_status": r["merge_status"], "conflict_group_id": r["conflict_group_id"], "pricing_snapshot_id": r["pricing_snapshot_id"], "pricing_effective_at": r["pricing_effective_at"], "recorded_actual_currency": r["actual_currency"], "estimate_currency": r["estimate_currency"]}})
    return result


def statistics_csv(conn: sqlite3.Connection, **filters) -> str:
    rows = statistics_timeseries(conn, **filters)
    output = io.StringIO(); writer = csv.writer(output)
    columns = ["bucket_date", "bucket_start_utc", "bucket_end_utc", "timezone", "tool", "profile_ref", "project_ref", "model", "provider", "source", "quality", "availability", "reason_code", "request_count", "input_tokens", "output_tokens", "cache_read_tokens", "cache_creation_tokens", "reasoning_tokens", "total_tokens", "recorded_actual_amount_minor", "recorded_actual_currency", "recorded_actual_source", "recorded_actual_quality", "api_equivalent_estimate_amount_minor", "api_equivalent_estimate_currency", "api_equivalent_estimate_source", "api_equivalent_estimate_quality", "pricing_snapshot_id", "pricing_effective_at", "merge_status", "conflict_group_id", "parser_version", "rollup_version"]
    writer.writerow(columns)
    for row in rows:
        values = row["metrics"]
        token_row = conn.execute("SELECT reasoning_tokens,total_tokens FROM daily_rollups WHERE bucket_date=? AND timezone=? AND tool IS ? AND profile_ref IS ? AND project_ref IS ? AND model IS ? AND provider IS ? LIMIT 1", (row["bucket_date"], row["timezone"], row["tool"], row["profile_ref"], row["project_ref"], row["model"], row["provider"])).fetchone()
        values.setdefault("reasoning_tokens", metric(token_row["reasoning_tokens"] if token_row else None, source=row.get("provenance", {}).get("source")))
        values.setdefault("total_tokens", metric(token_row["total_tokens"] if token_row else None, source=row.get("provenance", {}).get("source")))
        quality = values["input_tokens"]
        provenance = row.get("provenance", {})
        writer.writerow([row["bucket_date"], row["bucket_start_utc"], row["bucket_end_utc"], row["timezone"], row["tool"] or "", row["profile_ref"] or "", row["project_ref"] or "", row["model"] or "", row["provider"] or "", quality["source"], quality["quality"], quality["availability"], quality.get("reason_code") or "", values["request_count"]["value"], values["input_tokens"]["value"], values["output_tokens"]["value"], values["cache_read_tokens"]["value"], values["cache_creation_tokens"]["value"], values["reasoning_tokens"]["value"], values["total_tokens"]["value"], values["actual"]["value"], provenance.get("recorded_actual_currency") or "", values["actual"]["source"] or "", values["actual"]["quality"], values["estimate"]["value"], provenance.get("estimate_currency") or "", values["estimate"]["source"] or "", values["estimate"]["quality"], provenance.get("pricing_snapshot_id") or "", provenance.get("pricing_effective_at") or "", provenance.get("merge_status") or "", provenance.get("conflict_group_id") or "", provenance.get("parser_version") or "", provenance.get("rollup_version") or ""])
    return output.getvalue()


def _filters(start: str | None, end: str | None, tool: str | None, profile_ref: str | None, timezone_name: str | None = None, project_ref: str | None = None, model: str | None = None, provider: str | None = None, source: str | None = None) -> tuple[str, list]:
    clauses, args = [], []
    if start: clauses.append("bucket_date >= ?"); args.append(start)
    if end: clauses.append("bucket_date <= ?"); args.append(end)
    if tool: clauses.append("tool = ?"); args.append(tool)
    if profile_ref: clauses.append("profile_ref = ?"); args.append(profile_ref)
    if timezone_name: clauses.append("timezone = ?"); args.append(timezone_name)
    for column, value in (("project_ref", project_ref), ("model", model), ("provider", provider), ("source", source)):
        if value: clauses.append(f"{column} = ?"); args.append(value)
    return ("WHERE " + " AND ".join(clauses)) if clauses else "", args


SUPPORTED_PARSER_MIGRATIONS = {"current": {"current", "usage-v1", "codex-jsonl-v1", "claude-jsonl-v1"}, "usage-v1": {"usage-v1", "codex-jsonl-v1", "claude-jsonl-v1"}, "codex-jsonl-v1": {"codex-jsonl-v1"}, "claude-jsonl-v1": {"claude-jsonl-v1"}}


def migrate_parser_version(conn: sqlite3.Connection, target: str) -> dict[str, Any]:
    if target not in SUPPORTED_PARSER_MIGRATIONS:
        raise ValueError(f"unsupported parser version: {target}")
    versions = [row["parser_version"] for row in conn.execute("SELECT DISTINCT parser_version FROM usage_records")]
    unsupported = [version for version in versions if version not in SUPPORTED_PARSER_MIGRATIONS[target]]
    if unsupported:
        raise ValueError("unsupported parser migration source")
    if target == "current":
        if any(version != target for version in versions):
            record_rollup_invalidation(conn, "parser_version_changed")
        conn.execute("UPDATE usage_records SET parser_version='current' WHERE parser_version != 'current'")
        conn.execute("UPDATE observations SET parser_version='current' WHERE parser_version != 'current'")
    return {"from_versions": versions, "target_version": target, "migrated_records": conn.execute("SELECT count(*) FROM usage_records WHERE parser_version=?", (target,)).fetchone()[0]}


def rebuild_rollups(conn: sqlite3.Connection, *, timezone_name: str = "UTC", job_id: str | None = None, parser_version: str = "current", from_date: str | None = None, to_date: str | None = None, include_pricing_estimates: bool = True) -> dict:
    """Rebuild native rollups atomically without requiring migration of raw labels."""
    job_id = job_id or uuid.uuid4().hex
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    before = conn.execute("SELECT count(*) c, sum(input_tokens) i, sum(output_tokens) o, sum(reasoning_tokens) reasoning, sum(total_tokens) total FROM usage_records").fetchone()
    if conn.execute("SELECT 1 FROM rebuild_jobs WHERE id=?", (job_id,)).fetchone() is None:
        conn.execute("INSERT INTO rebuild_jobs(id, scope, status, requested_at, checkpoint) VALUES(?, 'workbench_usage_and_rollup', 'running', ?, ?)", (job_id, now, "start"))
    try:
        previous_rollup = conn.execute("SELECT timezone, rollup_version FROM daily_rollups LIMIT 1").fetchone()
        if previous_rollup and previous_rollup[1] != ROLLUP_ALGORITHM_VERSION:
            record_rollup_invalidation(conn, "rollup_algorithm_changed", timezone_name=timezone_name)
        previous_timezone = previous_rollup
        if previous_timezone and previous_timezone[0] != timezone_name:
            record_rollup_invalidation(conn, "timezone_changed", timezone_name=timezone_name)
        # Rebuild is an aggregation operation, not an implicit parser migration.
        # Unknown historical labels remain valid provenance and must not prevent
        # all rollups from being rebuilt. Explicit migration callers still use
        # migrate_parser_version(), which retains its strict compatibility check.
        versions = [row["parser_version"] for row in conn.execute("SELECT DISTINCT parser_version FROM usage_records")]
        if parser_version == "current":
            if any(version != parser_version for version in versions):
                record_rollup_invalidation(conn, "parser_version_changed")
            migrated_records = conn.execute("SELECT count(*) FROM usage_records WHERE parser_version=?", (parser_version,)).fetchone()[0]
            migration = {"from_versions": versions, "target_version": parser_version, "migrated_records": migrated_records}
        else:
            migration = migrate_parser_version(conn, parser_version)
        if MERGE_ALGORITHM_VERSION != "merge-v1":
            record_rollup_invalidation(conn, "merge_algorithm_changed", timezone_name=timezone_name)
        conn.execute("UPDATE rebuild_jobs SET checkpoint='parser-migration',current_phase='parser-migration' WHERE id=?", (job_id,)); conn.commit()
        rows = conn.execute("SELECT u.id, u.event_at, u.source, u.quality, u.input_tokens, u.output_tokens, u.cache_read_tokens, u.cache_creation_tokens, u.reasoning_tokens, u.total_tokens, u.recorded_cost_minor, u.estimated_cost_minor, u.pricing_snapshot_id, u.currency, o.recorded_cost_currency, o.tool, o.profile_ref, o.project_ref, o.model, o.provider FROM usage_records u JOIN observations o ON o.id=u.observation_id WHERE u.event_at IS NOT NULL AND (u.merge_status = 'primary' OR u.merge_status IS NULL) AND (? IS NULL OR substr(u.event_at,1,10) >= ?) AND (? IS NULL OR substr(u.event_at,1,10) <= ?)", (from_date, from_date, to_date, to_date)).fetchall()
        conn.execute("UPDATE rebuild_jobs SET current_phase='aggregate',total_items=?,processed_items=0,progress_percent=5,checkpoint='aggregate-start' WHERE id=?", (len(rows), job_id)); conn.commit()
        grouped: dict[tuple, dict[str, Any]] = {}
        for index, row in enumerate(rows, 1):
            estimate_source = None
            estimate_quality = None
            pricing_snapshot_id = None
            pricing_effective_at = None
            estimate_formula = None
            if row["model"] and include_pricing_estimates:
                snapshot = conn.execute("SELECT * FROM pricing_snapshots WHERE model_key IN (?, ?) AND (provider=? OR provider='unknown') AND trust_state='trusted' AND validation_status='valid' AND effective_at IS NOT NULL AND effective_at <= ? ORDER BY effective_at DESC LIMIT 1", (row["model"], resolve_pricing_model(row["model"]), row["provider"], row["event_at"])).fetchone()
                priced = estimate_cost(dict(row), dict(snapshot) if snapshot else None)
                if priced.get("value_minor") is not None:
                    row = dict(row)
                    row["estimated_cost_minor"] = priced["value_minor"]
                    row["currency"] = priced.get("currency")
                    conn.execute("UPDATE usage_records SET estimated_cost_minor=?, pricing_snapshot_id=?, currency=?, cost_reason=NULL WHERE id=?", (priced["value_minor"], priced.get("snapshot_id"), priced.get("currency"), row["id"]))
                if priced.get("value_minor") is not None:
                    estimate_source, estimate_quality = priced.get("source"), "estimated"
                    pricing_snapshot_id, pricing_effective_at = priced.get("snapshot_id"), priced.get("effective_at")
                    estimate_formula = priced.get("formula")
                elif row["estimated_cost_minor"] is not None:
                    estimate_source, estimate_quality = "pricing_snapshot", "estimated"
                    pricing_snapshot_id = row["pricing_snapshot_id"]
                    if pricing_snapshot_id:
                        prior_snapshot = conn.execute("SELECT effective_at FROM pricing_snapshots WHERE id=?", (pricing_snapshot_id,)).fetchone()
                        pricing_effective_at = prior_snapshot["effective_at"] if prior_snapshot else None
                    estimate_formula = "sum(token_count * price_per_million / 1,000,000)"
            event = datetime.fromisoformat(row["event_at"].replace("Z", "+00:00"))
            bucket = event.astimezone(ZoneInfo(timezone_name)).date().isoformat()
            key = (bucket, timezone_name, row["tool"], row["profile_ref"], row["project_ref"], row["model"], row["provider"], row["source"], "rollup-v1")
            item = grouped.setdefault(key, {"i": None, "o": None, "cr": None, "cc": None, "reasoning": None, "total": None, "actual": None, "estimate": None, "actual_currency": row["recorded_cost_currency"], "estimate_currency": row["currency"] if row["estimated_cost_minor"] is not None else None, "count": 0, "quality": row["quality"], "actual_source": "proxy_recorded" if row["recorded_cost_minor"] is not None else None, "actual_quality": "exact" if row["recorded_cost_minor"] is not None else None, "estimate_source": estimate_source or ("pricing_snapshot" if row["estimated_cost_minor"] is not None else None), "estimate_quality": estimate_quality or ("estimated" if row["estimated_cost_minor"] is not None else None), "pricing_snapshot_id": pricing_snapshot_id, "pricing_effective_at": pricing_effective_at, "estimate_formula": estimate_formula or ("sum(token_count * price_per_million / 1,000,000)" if row["estimated_cost_minor"] is not None else None), "merge_status": "primary", "conflict_group_id": None, "parser_version": parser_version})
            if item["estimate_currency"] is None and row["estimated_cost_minor"] is not None:
                item["estimate_currency"] = row["currency"]
            item["count"] += 1
            if row["input_tokens"] is not None: item["i"] = (item["i"] or 0) + row["input_tokens"]
            if row["output_tokens"] is not None: item["o"] = (item["o"] or 0) + row["output_tokens"]
            for field, target in (("cache_read_tokens", "cr"), ("cache_creation_tokens", "cc"), ("reasoning_tokens", "reasoning"), ("total_tokens", "total"), ("recorded_cost_minor", "actual"), ("estimated_cost_minor", "estimate")):
                if row[field] is not None: item[target] = (item[target] or 0) + row[field]
            if row["quality"] == "estimated": item["quality"] = "estimated"
            if index == len(rows) or index % 100 == 0:
                conn.execute("UPDATE rebuild_jobs SET processed_items=?,progress_percent=?,checkpoint=? WHERE id=?", (index, 5 + (index / max(len(rows), 1)) * 65, f"aggregate:{index}", job_id)); conn.commit()
        conn.execute("UPDATE rebuild_jobs SET current_phase='stage',progress_percent=75,checkpoint='stage-start' WHERE id=?", (job_id,)); conn.commit()
        staging = f"daily_rollups_staging_{job_id[:12]}"
        conn.execute(f"CREATE TEMP TABLE \"{staging}\" AS SELECT * FROM daily_rollups WHERE 0")
        build_id = job_id
        data_revision = hashlib.sha256(json.dumps([(r["id"], r["dedup_key"]) for r in conn.execute("SELECT id,dedup_key FROM usage_records ORDER BY id")], separators=(",", ":")).encode()).hexdigest()
        with conn:
            for (bucket, tz, tool, profile_ref, project_ref, model, provider, source, rollup_version), item in grouped.items():
                start, end = utc_bucket(bucket, timezone_name)
                placeholders = ",".join("?" for _ in range(38))
                conn.execute(f"""INSERT INTO \"{staging}\"(bucket_date,timezone,bucket_start_utc,bucket_end_utc,tool,profile_ref,project_ref,model,provider,source,quality,request_count,input_tokens,output_tokens,cache_read_tokens,cache_creation_tokens,reasoning_tokens,total_tokens,recorded_cost_minor,estimated_cost_minor,currency,source_watermark,rollup_version,rebuilt_at,data_revision,build_id,recorded_actual_source,recorded_actual_quality,estimate_source,estimate_quality,pricing_snapshot_id,pricing_effective_at,estimate_formula,merge_status,conflict_group_id,parser_version,recorded_actual_currency,estimate_currency) VALUES({placeholders})""", (bucket, tz, start, end, tool, profile_ref, project_ref, model, provider, source, item["quality"], item["count"], item["i"], item["o"], item["cr"], item["cc"], item["reasoning"], item["total"], item["actual"], item["estimate"], item["estimate_currency"], "usage_records", rollup_version, now, data_revision, build_id, item["actual_source"], item["actual_quality"], item["estimate_source"], item["estimate_quality"], item["pricing_snapshot_id"], item["pricing_effective_at"], item["estimate_formula"], item["merge_status"], item["conflict_group_id"], item["parser_version"], item["actual_currency"], item["estimate_currency"]))
            for (bucket, tz, tool, profile_ref, project_ref, model, provider, source, rollup_version), item in grouped.items():
                conn.execute(f"UPDATE \"{staging}\" SET reasoning_tokens=?, total_tokens=? WHERE bucket_date=? AND timezone=? AND tool IS ? AND profile_ref IS ? AND project_ref IS ? AND model IS ? AND provider IS ? AND source=? AND rollup_version=?", (item["reasoning"], item["total"], bucket, tz, tool, profile_ref, project_ref, model, provider, source, rollup_version))
            if conn.execute("SELECT status FROM rebuild_jobs WHERE id=?", (job_id,)).fetchone()[0] in {"cancelling", "cancelled"}:
                conn.execute("UPDATE rebuild_jobs SET status='cancelled', completed_at=?, current_phase='cancelled' WHERE id=?", (now, job_id)); conn.commit()
                conn.execute(f"DROP TABLE \"{staging}\""); return {"job_id": job_id, "status": "cancelled"}
            if from_date or to_date:
                clauses = ["rollup_version = 'rollup-v1'"]
                delete_args: list[str] = []
                if from_date:
                    clauses.append("bucket_date >= ?"); delete_args.append(from_date)
                if to_date:
                    clauses.append("bucket_date <= ?"); delete_args.append(to_date)
                conn.execute(f"DELETE FROM daily_rollups WHERE {' AND '.join(clauses)}", delete_args)
            else:
                conn.execute("DELETE FROM daily_rollups WHERE rollup_version = 'rollup-v1'")
            conn.execute(f"INSERT INTO daily_rollups SELECT * FROM \"{staging}\"")
            conn.execute(f"DROP TABLE \"{staging}\"")
            invalidation_where = "bucket_date >= ? AND bucket_date <= ?" if from_date or to_date else "1=1"
            invalidation_args = ([from_date or "0000-01-01"] + [to_date or "9999-12-31"]) if from_date or to_date else []
            conn.execute(f"UPDATE rollup_invalidations SET status='completed' WHERE status IN ('pending','running') AND {invalidation_where}", invalidation_args)
            conn.execute("UPDATE rebuild_jobs SET current_phase='audit',progress_percent=90,checkpoint='audit-start' WHERE id=?", (job_id,))
            after = conn.execute("SELECT count(*) c, sum(input_tokens) i, sum(output_tokens) o, sum(reasoning_tokens) reasoning, sum(total_tokens) total FROM usage_records").fetchone()
            quality_counts = {row["quality"]: row["count"] for row in conn.execute("SELECT quality,count(*) count FROM usage_records GROUP BY quality")}
            parser_versions = [row["parser_version"] for row in conn.execute("SELECT DISTINCT parser_version FROM usage_records ORDER BY parser_version")]
            conflict_count = conn.execute("SELECT count(*) FROM usage_records WHERE merge_status='conflict'").fetchone()[0]
            def audit_summary(snapshot):
                return {"observation_count": conn.execute("SELECT count(*) FROM observations").fetchone()[0], "usage_record_count": snapshot["c"], "rollup_bucket_count": conn.execute("SELECT count(*) FROM daily_rollups").fetchone()[0], "token_totals": {"input_tokens": snapshot["i"], "output_tokens": snapshot["o"], "reasoning_tokens": snapshot["reasoning"], "total_tokens": snapshot["total"]}, "actual_cost_minor": conn.execute("SELECT sum(recorded_cost_minor) FROM usage_records").fetchone()[0], "estimate_cost_minor": conn.execute("SELECT sum(estimated_cost_minor) FROM usage_records").fetchone()[0], "quality_counts": quality_counts, "conflict_count": conflict_count, "parser_versions": parser_versions}
            audit = {"before": audit_summary(before), "after": audit_summary(after), "delta": {"count": after["c"] - before["c"], "input": (after["i"] or 0) - (before["i"] or 0), "output": (after["o"] or 0) - (before["o"] or 0)}, "quality_counts": quality_counts, "parser_versions": parser_versions, "conflict_count": conflict_count, "data_revision": data_revision, "build_id": build_id, "reasons": ["parser_version_changed"] if migration["from_versions"] != [parser_version] else [], "parser_migration": migration, "external_files_modified": [], "cc_switch_db_modified": False}
            conn.execute("UPDATE rebuild_jobs SET status='completed', completed_at=?, current_phase='done', processed_items=?, total_items=?, progress_percent=100, checkpoint='done', audit_json=? WHERE id=?", (now, len(rows), len(rows), json.dumps(audit), job_id))
        return {"job_id": job_id, "status": "completed", "audit": audit}
    except Exception as exc:
        conn.execute("UPDATE rebuild_jobs SET status='failed', completed_at=?, error=? WHERE id=?", (now, str(exc), job_id)); conn.commit()
        return {"job_id": job_id, "status": "failed", "error": "rebuild failed"}


def enqueue_rebuild(db_path, *, timezone_name: str = "UTC", options: dict[str, Any] | None = None, parser_version: str = "current") -> str:
    """Persist a queued job and run it in a daemon worker outside the request."""
    job_id = uuid.uuid4().hex
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    from app.ai_workbench.storage import connect_workbench_db
    with connect_workbench_db(db_path) as conn:
        existing = conn.execute("SELECT id FROM rebuild_jobs WHERE scope='workbench_usage_and_rollup' AND status='running' ORDER BY requested_at DESC LIMIT 1").fetchone()
        if existing:
            return existing[0]
        # A queued job belongs to a worker that may have died before startup;
        # do not let it block all future rebuild requests.
        conn.execute("UPDATE rebuild_jobs SET status='failed', completed_at=?, error='worker did not start' WHERE scope='workbench_usage_and_rollup' AND status='queued'", (now,))
        conn.execute("INSERT INTO rebuild_jobs(id,scope,status,requested_at,checkpoint,options_json,parser_version) VALUES(?,?, 'queued', ?, ?, ?, ?)", (job_id, "workbench_usage_and_rollup", now, "queued", json.dumps(options or {}, sort_keys=True), parser_version))
    worker = threading.Thread(target=_run_rebuild_job, args=(db_path, job_id, timezone_name), daemon=True)
    worker.start()
    return job_id


def _run_rebuild_job(db_path, job_id: str, timezone_name: str) -> None:
    from app.ai_workbench.storage import connect_workbench_db
    with connect_workbench_db(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        current = conn.execute("SELECT status FROM rebuild_jobs WHERE id=?", (job_id,)).fetchone()
        if current is None or current[0] == "cancelled":
            conn.rollback()
            return
        conn.execute("UPDATE rebuild_jobs SET status='running',started_at=?,current_phase='prepare',checkpoint='running' WHERE id=?", (datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"), job_id)); conn.commit()
        try:
            if conn.execute("SELECT status FROM rebuild_jobs WHERE id=?", (job_id,)).fetchone()[0] == "cancelled": return
            # The synchronous implementation is executed by the worker; its
            # transaction is isolated from HTTP requests and remains auditable.
            row = conn.execute("SELECT parser_version FROM rebuild_jobs WHERE id=?", (job_id,)).fetchone()
            options = json.loads(conn.execute("SELECT options_json FROM rebuild_jobs WHERE id=?", (job_id,)).fetchone()[0] or "{}")
            result = rebuild_rollups(conn, timezone_name=timezone_name, job_id=job_id, parser_version=row[0] if row else "current", from_date=options.get("from_date"), to_date=options.get("to_date"), include_pricing_estimates=options.get("include_pricing_estimates", True))
            current = conn.execute("SELECT status FROM rebuild_jobs WHERE id=?", (job_id,)).fetchone()[0]
            if current != "cancelled":
                conn.execute("UPDATE rebuild_jobs SET status=?,completed_at=?,checkpoint=?,audit_json=?,error=? WHERE id=?", (result.get("status"), datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"), "done", json.dumps(result.get("audit")) if result.get("audit") else None, result.get("error"), job_id)); conn.commit()
        except Exception:
            conn.execute("UPDATE rebuild_jobs SET status='failed',completed_at=?,current_phase='failed',error='rebuild failed' WHERE id=?", (datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"), job_id)); conn.commit()
