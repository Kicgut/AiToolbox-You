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


def metric(value: int | float | None, *, quality: str = "exact", source: str = "native", reason: str | None = None) -> dict:
    return {"value": value, "availability": "available" if value is not None else "unavailable", "quality": quality, "source": source, "reason_code": reason}


def statistics_overview(conn: sqlite3.Connection, *, start: str | None = None, end: str | None = None,
                        tool: str | None = None, profile_ref: str | None = None, timezone_name: str | None = None, project_ref: str | None = None, model: str | None = None, provider: str | None = None, source: str | None = None) -> dict:
    where, args = _filters(start, end, tool, profile_ref, timezone_name, project_ref, model, provider, source)
    row = conn.execute(f"""SELECT count(*) request_count, sum(input_tokens) input_tokens,
        sum(output_tokens) output_tokens, sum(cache_read_tokens) cache_read_tokens,
        sum(cache_creation_tokens) cache_creation_tokens, sum(recorded_cost_minor) actual,
        sum(estimated_cost_minor) estimate FROM daily_rollups {where}""", args).fetchone()
    pending = conn.execute("SELECT count(*) FROM rollup_invalidations WHERE status='pending'").fetchone()[0]
    return {"filters": {"start": start, "end": end, "tool": tool, "profile_ref": profile_ref, "timezone": timezone_name},
            "metrics": {k: metric(row[k]) for k in ("request_count", "input_tokens", "output_tokens", "cache_read_tokens", "cache_creation_tokens", "actual", "estimate")},
            "rollup_status": "stale" if pending else "available" if row["request_count"] is not None else "empty"}


def statistics_timeseries(conn: sqlite3.Connection, **filters) -> list[dict]:
    where, args = _filters(filters.get("start"), filters.get("end"), filters.get("tool"), filters.get("profile_ref"), filters.get("timezone_name"), filters.get("project_ref"), filters.get("model"), filters.get("provider"), filters.get("source"))
    rows = conn.execute(f"SELECT bucket_date, timezone, bucket_start_utc, bucket_end_utc, request_count, input_tokens, output_tokens, quality, source FROM daily_rollups {where} ORDER BY bucket_start_utc", args).fetchall()
    return [{"bucket_date": r["bucket_date"], "timezone": r["timezone"], "bucket_start_utc": r["bucket_start_utc"], "bucket_end_utc": r["bucket_end_utc"],
             "metrics": {"request_count": metric(r["request_count"], quality=r["quality"], source=r["source"]), "input_tokens": metric(r["input_tokens"], quality=r["quality"], source=r["source"]), "output_tokens": metric(r["output_tokens"], quality=r["quality"], source=r["source"])}} for r in rows]


def statistics_breakdown(conn: sqlite3.Connection, **filters) -> list[dict]:
    where, args = _filters(filters.get("start"), filters.get("end"), filters.get("tool"), filters.get("profile_ref"), filters.get("timezone_name"), filters.get("project_ref"), filters.get("model"), filters.get("provider"), filters.get("source"))
    rows = conn.execute(f"SELECT tool, model, provider, sum(request_count) request_count, sum(input_tokens) input_tokens, sum(output_tokens) output_tokens, min(quality) quality, min(source) source FROM daily_rollups {where} GROUP BY tool, model, provider ORDER BY request_count DESC", args).fetchall()
    return [{"tool": r["tool"], "model": r["model"], "provider": r["provider"], "metrics": {"request_count": metric(r["request_count"], quality=r["quality"], source=r["source"]), "input_tokens": metric(r["input_tokens"], quality=r["quality"], source=r["source"]), "output_tokens": metric(r["output_tokens"], quality=r["quality"], source=r["source"])}} for r in rows]


def statistics_csv(conn: sqlite3.Connection, **filters) -> str:
    rows = statistics_timeseries(conn, **filters)
    output = io.StringIO(); writer = csv.writer(output)
    columns = ["bucket_date", "bucket_start_utc", "bucket_end_utc", "timezone", "tool", "profile_ref", "project_ref", "model", "provider", "source", "quality", "availability", "reason_code", "request_count", "input_tokens", "output_tokens", "cache_read_tokens", "cache_creation_tokens", "reasoning_tokens", "total_tokens", "recorded_actual_amount_minor", "recorded_actual_currency", "recorded_actual_source", "recorded_actual_quality", "api_equivalent_estimate_amount_minor", "api_equivalent_estimate_currency", "api_equivalent_estimate_source", "api_equivalent_estimate_quality", "pricing_snapshot_id", "pricing_effective_at", "merge_status", "conflict_group_id", "parser_version", "rollup_version"]
    writer.writerow(columns)
    for row in rows:
        values = row["metrics"]
        quality = values["input_tokens"]
        writer.writerow([row["bucket_date"], row["bucket_start_utc"], row["bucket_end_utc"], row["timezone"], "", "", "", "", "", quality["source"], quality["quality"], quality["availability"], quality.get("reason_code") or "", values["request_count"]["value"], values["input_tokens"]["value"], values["output_tokens"]["value"], "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "usage-v1", "rollup-v1"])
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
        conn.execute("UPDATE usage_records SET parser_version='current' WHERE parser_version != 'current'")
        conn.execute("UPDATE observations SET parser_version='current' WHERE parser_version != 'current'")
    return {"from_versions": versions, "target_version": target, "migrated_records": conn.execute("SELECT count(*) FROM usage_records WHERE parser_version=?", (target,)).fetchone()[0]}


def rebuild_rollups(conn: sqlite3.Connection, *, timezone_name: str = "UTC", job_id: str | None = None, parser_version: str = "current") -> dict:
    """Rebuild native rollups atomically from Workbench usage records only."""
    job_id = job_id or uuid.uuid4().hex
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    before = conn.execute("SELECT count(*) c, coalesce(sum(input_tokens),0) i, coalesce(sum(output_tokens),0) o FROM usage_records").fetchone()
    if conn.execute("SELECT 1 FROM rebuild_jobs WHERE id=?", (job_id,)).fetchone() is None:
        conn.execute("INSERT INTO rebuild_jobs(id, scope, status, requested_at, checkpoint) VALUES(?, 'workbench_usage_and_rollup', 'running', ?, ?)", (job_id, now, "start"))
    try:
        migration = migrate_parser_version(conn, parser_version)
        conn.execute("UPDATE rebuild_jobs SET checkpoint='parser-migration',current_phase='parser-migration' WHERE id=?", (job_id,)); conn.commit()
        rows = conn.execute("SELECT event_at, source, quality, input_tokens, output_tokens FROM usage_records WHERE event_at IS NOT NULL AND merge_status = 'primary'").fetchall()
        conn.execute("UPDATE rebuild_jobs SET current_phase='aggregate',total_items=?,processed_items=0,progress_percent=5,checkpoint='aggregate-start' WHERE id=?", (len(rows), job_id)); conn.commit()
        grouped: dict[tuple[str, str], dict[str, Any]] = {}
        for index, row in enumerate(rows, 1):
            event = datetime.fromisoformat(row["event_at"].replace("Z", "+00:00"))
            bucket = event.astimezone(ZoneInfo(timezone_name)).date().isoformat()
            key = (bucket, row["source"])
            item = grouped.setdefault(key, {"i": 0, "o": 0, "count": 0, "quality": row["quality"]})
            item["count"] += 1
            if row["input_tokens"] is not None: item["i"] += row["input_tokens"]
            if row["output_tokens"] is not None: item["o"] += row["output_tokens"]
            if row["quality"] == "estimated": item["quality"] = "estimated"
            if index == len(rows) or index % 100 == 0:
                conn.execute("UPDATE rebuild_jobs SET processed_items=?,progress_percent=?,checkpoint=? WHERE id=?", (index, 5 + (index / max(len(rows), 1)) * 65, f"aggregate:{index}", job_id)); conn.commit()
        conn.execute("UPDATE rebuild_jobs SET current_phase='stage',progress_percent=75,checkpoint='stage-start' WHERE id=?", (job_id,)); conn.commit()
        staging = f"daily_rollups_staging_{job_id[:12]}"
        conn.execute(f"CREATE TEMP TABLE \"{staging}\" AS SELECT * FROM daily_rollups WHERE 0")
        build_id = job_id
        data_revision = hashlib.sha256(json.dumps([(r["id"], r["dedup_key"]) for r in conn.execute("SELECT id,dedup_key FROM usage_records ORDER BY id")], separators=(",", ":")).encode()).hexdigest()
        with conn:
            for (bucket, source), item in grouped.items():
                start, end = utc_bucket(bucket, timezone_name)
                conn.execute(f"""INSERT INTO \"{staging}\"(bucket_date,timezone,bucket_start_utc,bucket_end_utc,tool,source,quality,request_count,input_tokens,output_tokens,source_watermark,rollup_version,rebuilt_at,data_revision,build_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (bucket, timezone_name, start, end, "codex" if source == "codex_jsonl" else "claude" if source == "claude_jsonl" else "proxy", source, item["quality"], item["count"], item["i"], item["o"], "usage_records", "rollup-v1", now, data_revision, build_id))
            if conn.execute("SELECT status FROM rebuild_jobs WHERE id=?", (job_id,)).fetchone()[0] == "cancelled":
                conn.execute(f"DROP TABLE \"{staging}\""); return {"job_id": job_id, "status": "cancelled"}
            conn.execute("DELETE FROM daily_rollups WHERE rollup_version = 'rollup-v1'")
            conn.execute(f"INSERT INTO daily_rollups SELECT * FROM \"{staging}\"")
            conn.execute(f"DROP TABLE \"{staging}\"")
            conn.execute("UPDATE rebuild_jobs SET current_phase='audit',progress_percent=90,checkpoint='audit-start' WHERE id=?", (job_id,))
            after = conn.execute("SELECT count(*) c, coalesce(sum(input_tokens),0) i, coalesce(sum(output_tokens),0) o FROM usage_records").fetchone()
            quality_counts = {row["quality"]: row["count"] for row in conn.execute("SELECT quality,count(*) count FROM usage_records GROUP BY quality")}
            parser_versions = [row["parser_version"] for row in conn.execute("SELECT DISTINCT parser_version FROM usage_records ORDER BY parser_version")]
            conflict_count = conn.execute("SELECT count(*) FROM usage_records WHERE merge_status='conflict'").fetchone()[0]
            audit = {"before": dict(before), "after": dict(after), "delta": {"count": after["c"] - before["c"], "input": after["i"] - before["i"], "output": after["o"] - before["o"]}, "quality_counts": quality_counts, "parser_versions": parser_versions, "conflict_count": conflict_count, "data_revision": data_revision, "build_id": build_id, "reasons": ["parser_version_changed"] if migration["from_versions"] != [parser_version] else [], "parser_migration": migration, "external_files_modified": [], "cc_switch_db_modified": False}
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
        conn.execute("UPDATE rebuild_jobs SET status='running',started_at=?,current_phase='prepare',checkpoint='running' WHERE id=?", (datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"), job_id)); conn.commit()
        try:
            if conn.execute("SELECT status FROM rebuild_jobs WHERE id=?", (job_id,)).fetchone()[0] == "cancelled": return
            # The synchronous implementation is executed by the worker; its
            # transaction is isolated from HTTP requests and remains auditable.
            row = conn.execute("SELECT parser_version FROM rebuild_jobs WHERE id=?", (job_id,)).fetchone()
            result = rebuild_rollups(conn, timezone_name=timezone_name, job_id=job_id, parser_version=row[0] if row else "current")
            current = conn.execute("SELECT status FROM rebuild_jobs WHERE id=?", (job_id,)).fetchone()[0]
            if current != "cancelled":
                conn.execute("UPDATE rebuild_jobs SET status=?,completed_at=?,checkpoint=?,audit_json=?,error=? WHERE id=?", (result.get("status"), datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"), "done", json.dumps(result.get("audit")) if result.get("audit") else None, result.get("error"), job_id)); conn.commit()
        except Exception:
            conn.execute("UPDATE rebuild_jobs SET status='failed',completed_at=?,current_phase='failed',error='rebuild failed' WHERE id=?", (datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"), job_id)); conn.commit()
