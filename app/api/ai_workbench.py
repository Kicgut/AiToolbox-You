from __future__ import annotations

import sqlite3
from fastapi.responses import PlainTextResponse
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.ai_workbench.indexing.scanner import (
    FtsConsentRequiredError,
    FtsIndexingDisabledError,
    add_manual_profile,
    clear_fts,
    fts_status,
    get_session_detail,
    latest_scan_runs,
    list_manual_profiles,
    list_sessions,
    profile_diagnostics,
    record_fts_consent,
    rebuild_fts,
    reconcile_sessions,
    scan_sessions,
    set_fts_indexing_enabled,
)
from app.ai_workbench.storage import connect_workbench_db, default_workbench_paths
from app.ai_workbench.statistics import statistics_overview, statistics_timeseries, statistics_breakdown, statistics_csv, enqueue_rebuild
from app.ai_workbench.compatibility.cc_switch import read_proxy_request_logs, read_pricing_candidates, capability_report
from app.ai_workbench.usage import UsageEvent
from app.ai_workbench.merge import merge_decision
from app.ai_workbench.merge import reprice_usage
import hashlib
import json
from datetime import datetime, timezone, date
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

router = APIRouter(prefix="/api/ai-workbench", tags=["ai-workbench"])


def _audit_cc_switch(result: dict, *, action: str) -> None:
    with _conn() as conn:
        conn.execute("INSERT INTO cc_switch_audit(id,observed_at,db_identity,status,user_version,capabilities_json,message,action) VALUES(?,?,?,?,?,?,?,?)", (hashlib.sha256(f"{action}:{datetime.now(timezone.utc).isoformat()}".encode()).hexdigest(), datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"), result.get("db_identity"), result.get("status", "unknown"), result.get("user_version"), json.dumps(result.get("capabilities", {})), result.get("message") or result.get("reason_code"), action))


def _statistics_filters(start: str | None, end: str | None, tool: str | None, profile_ref: str | None, timezone_name: str | None = None, project_ref: str | None = None, model: str | None = None, provider: str | None = None, source: str | None = None) -> dict:
    if tool is not None and tool not in {"codex", "claude", "proxy"}:
        raise HTTPException(400, "invalid tool")
    if start and end and start > end:
        raise HTTPException(400, "start must not be after end")
    if start and end:
        try:
            if (date.fromisoformat(end) - date.fromisoformat(start)).days > 366:
                raise HTTPException(400, "date range exceeds 366 days")
        except ValueError:
            raise HTTPException(400, "invalid date")
    if timezone_name:
        try: ZoneInfo(timezone_name)
        except (ZoneInfoNotFoundError, ValueError): raise HTTPException(400, "invalid timezone")
    if source is not None and source not in {"native", "proxy", "cc_switch", "mixed", "codex_jsonl", "claude_jsonl", "proxy_log"}:
        raise HTTPException(400, "invalid source")
    return {"start": start, "end": end, "tool": tool, "profile_ref": profile_ref, "timezone_name": timezone_name, "project_ref": project_ref, "model": model, "provider": provider, "source": source}


@router.get("/statistics/overview")
def statistics_overview_api(start: str | None = None, end: str | None = None, tool: str | None = None, profile_ref: str | None = None, timezone_name: str | None = None, project_ref: str | None = None, model: str | None = None, provider: str | None = None, source: str | None = None):
    with _conn() as conn:
        return statistics_overview(conn, **_statistics_filters(start, end, tool, profile_ref, timezone_name, project_ref, model, provider, source))


@router.get("/statistics/timeseries")
def statistics_timeseries_api(start: str | None = None, end: str | None = None, tool: str | None = None, profile_ref: str | None = None, timezone_name: str | None = None, project_ref: str | None = None, model: str | None = None, provider: str | None = None, source: str | None = None):
    with _conn() as conn:
        return {"data": statistics_timeseries(conn, **_statistics_filters(start, end, tool, profile_ref, timezone_name, project_ref, model, provider, source))}


@router.get("/statistics/breakdown")
def statistics_breakdown_api(start: str | None = None, end: str | None = None, tool: str | None = None, profile_ref: str | None = None, timezone_name: str | None = None, project_ref: str | None = None, model: str | None = None, provider: str | None = None, source: str | None = None):
    with _conn() as conn:
        return {"data": statistics_breakdown(conn, **_statistics_filters(start, end, tool, profile_ref, timezone_name, project_ref, model, provider, source))}


@router.get("/statistics/reliability")
def statistics_reliability_api():
    with _conn() as conn:
        native = conn.execute("SELECT count(*) count, min(quality) quality FROM observations WHERE observation_kind IN ('session','supervised_run')").fetchone()
        proxy = conn.execute("SELECT count(*) count, min(quality) quality FROM observations WHERE observation_kind='proxy'").fetchone()
    return {
        "proxy": {"availability": "available" if proxy["count"] else "unavailable", "quality": proxy["quality"] or "unavailable", "source": "proxy", "reason_code": None if proxy["count"] else "no_proxy_observations"},
        "native": {"availability": "available" if native["count"] else "unavailable", "quality": native["quality"] or "unavailable", "source": "native", "reason_code": None if native["count"] else "no_native_observations"},
    }


@router.get("/statistics/data-quality")
def statistics_quality_api():
    with _conn() as conn:
        rows = conn.execute("SELECT quality, source, count(*) count FROM observations GROUP BY quality, source").fetchall()
        return {"data": [dict(row) for row in rows]}


@router.get("/statistics/conflicts")
def statistics_conflicts_api(limit: int = Query(default=100, ge=1, le=500)):
    with _conn() as conn:
        rows = conn.execute("SELECT id,source_observation_id,target_observation_id,link_kind,confidence,details_json,created_at FROM observation_links WHERE link_kind IN ('conflict','proxy_enrichment') ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            try: item["details"] = json.loads(item.pop("details_json") or "{}")
            except json.JSONDecodeError: item["details"] = {"reason_code": "invalid_details"}
            result.append(item)
        return {"data": result}


@router.get("/statistics/export.csv", response_class=PlainTextResponse)
def statistics_export_api(start: str | None = None, end: str | None = None, tool: str | None = None, profile_ref: str | None = None, timezone_name: str | None = None, project_ref: str | None = None, model: str | None = None, provider: str | None = None, source: str | None = None):
    with _conn() as conn:
        return statistics_csv(conn, **_statistics_filters(start, end, tool, profile_ref, timezone_name, project_ref, model, provider, source))


@router.get("/statistics/cc-switch")
def cc_switch_statistics(path: str | None = None, limit: int = Query(default=100, ge=1, le=1000), since_id: str | None = None, db_identity: str | None = None):
    candidate = Path(path).expanduser() if path else Path.home() / ".cc-switch" / "cc-switch.db"
    result = read_proxy_request_logs(candidate, limit=limit, since_id=since_id, expected_db_identity=db_identity); _audit_cc_switch(result, action="read_proxy_request_logs"); return result


@router.get("/statistics/cc-switch/capabilities")
def cc_switch_capabilities(path: str | None = None):
    candidate = Path(path).expanduser() if path else Path.home() / ".cc-switch" / "cc-switch.db"
    result = capability_report(candidate); _audit_cc_switch(result, action="capability_report"); return result


@router.get("/statistics/cc-switch/audit")
def cc_switch_audit(limit: int = Query(default=20, ge=1, le=100)):
    with _conn() as conn:
        rows = conn.execute("SELECT * FROM cc_switch_audit ORDER BY observed_at DESC LIMIT ?", (limit,)).fetchall()
        return {"data": [dict(row) for row in rows]}


@router.get("/statistics/cc-switch/pricing")
def cc_switch_pricing(path: str | None = None, enabled: bool = False, limit: int = Query(default=100, ge=1, le=1000)):
    candidate = Path(path).expanduser() if path else Path.home() / ".cc-switch" / "cc-switch.db"
    result = read_pricing_candidates(candidate, enabled=enabled, limit=limit); _audit_cc_switch(result, action="read_pricing_candidates"); return result


@router.post("/statistics/cc-switch/pricing/import")
def import_cc_switch_pricing(path: str | None = None, limit: int = Query(default=100, ge=1, le=1000)):
    candidate = Path(path).expanduser() if path else Path.home() / ".cc-switch" / "cc-switch.db"
    result = read_pricing_candidates(candidate, enabled=True, limit=limit)
    if result.get("status") != "available":
        return result
    imported = 0
    with _conn() as conn:
        for item in result["data"]:
            snapshot_id = hashlib.sha256(f"cc_switch:{item.get('id')}:{item.get('model')}".encode()).hexdigest()
            observed_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            cursor = conn.execute("""INSERT OR IGNORE INTO pricing_snapshots(id,source_id,source_kind,model_key,provider,input_price_per_million,output_price_per_million,cache_read_price_per_million,cache_creation_price_per_million,currency,unit,effective_at,source_updated_at,imported_at,observed_at,parser_version,trust_state,validation_status) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (snapshot_id, "cc_switch:model_pricing", "cc_switch", item.get("model"), item.get("provider") or "unknown", item.get("input_price_per_million"), item.get("output_price_per_million"), item.get("cache_read_price_per_million"), item.get("cache_creation_price_per_million"), item.get("currency"), item.get("unit"), item.get("effective_at"), item.get("updated_at"), observed_at, observed_at, "cc-switch-pricing-v1", "inactive", "valid"))
            imported += cursor.rowcount
    return {"status": "available", "imported": imported, "pricing_enabled": False}


@router.post("/statistics/pricing/recalculate")
def recalculate_pricing():
    with _conn() as conn:
        return reprice_usage(conn)


@router.post("/statistics/cc-switch/import")
def import_cc_switch_observations(path: str | None = None, limit: int = Query(default=100, ge=1, le=1000)):
    """Copy approved proxy observations into Workbench; never writes CC Switch."""
    candidate = Path(path).expanduser() if path else Path.home() / ".cc-switch" / "cc-switch.db"
    result = read_proxy_request_logs(candidate, limit=limit)
    if result.get("status") != "available":
        return result
    inserted = 0; links = 0
    with _conn() as conn:
        for item in result["data"]:
            request_id = item.get("request_id")
            source_locator = f"cc_switch:{item.get('id')}"
            observation_id = hashlib.sha256(source_locator.encode()).hexdigest()
            observed_at = item.get("created_at") or "1970-01-01T00:00:00Z"
            cursor = conn.execute("""INSERT OR IGNORE INTO observations(id,observation_kind,source,source_locator,request_id,tool,provider,model,observed_at,payload_hash,quality,parser_version,parse_status,http_status,latency_ms,ttft_ms,recorded_cost_minor,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (observation_id, "proxy", "cc_switch", source_locator, request_id, "proxy", item.get("provider"), item.get("model"), observed_at, hashlib.sha256(json.dumps(item, sort_keys=True).encode()).hexdigest(), "exact", "cc-switch-proxy-v1", "parsed", item.get("status"), item.get("latency_ms"), item.get("ttft_ms"), item.get("recorded_cost_minor"), observed_at))
            inserted += cursor.rowcount
            if request_id:
                natives = conn.execute("SELECT id,request_id FROM observations WHERE request_id=? AND observation_kind != 'proxy'", (request_id,)).fetchall()
                for native in natives:
                    decision = merge_decision({"request_id": request_id}, {"request_id": request_id})
                    conn.execute("INSERT OR IGNORE INTO observation_links(id,source_observation_id,target_observation_id,link_kind,confidence,details_json,created_at) VALUES(?,?,?,?,?,?,?)", (hashlib.sha256(f"{observation_id}:{native['id']}".encode()).hexdigest(), observation_id, native["id"], "proxy_enrichment", "high", json.dumps({"merge_status": decision.status, "counting_policy": decision.counting_policy}), observed_at)); links += 1
    return {"status": "available", "inserted": inserted, "links": links, "cursor": result.get("cursor")}


@router.post("/statistics/rebuild")
def statistics_rebuild(payload: "RebuildRequest | None" = None):
    payload = payload or RebuildRequest()
    if payload.parser_version not in {"current", "usage-v1", "codex-jsonl-v1", "claude-jsonl-v1"}:
        raise HTTPException(400, "unsupported parser_version")
    if payload.from_date and payload.to_date:
        try:
            if date.fromisoformat(payload.from_date) > date.fromisoformat(payload.to_date):
                raise HTTPException(400, "from_date must not be after to_date")
        except ValueError:
            raise HTTPException(400, "invalid rebuild date")
    try:
        ZoneInfo(payload.timezone)
    except (ZoneInfoNotFoundError, ValueError):
        raise HTTPException(400, "invalid timezone")
    db_path = default_workbench_paths(Path("data") / "ai_workbench").db_path
    options = payload.model_dump()
    return {"job_id": enqueue_rebuild(db_path, timezone_name=payload.timezone, options=options, parser_version=payload.parser_version), "status": "queued", "options": options}


@router.get("/statistics/rebuild/{job_id}")
def statistics_rebuild_status(job_id: str):
    with _conn() as conn:
        row = conn.execute("SELECT * FROM rebuild_jobs WHERE id=?", (job_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "rebuild job not found")
        return dict(row)


@router.post("/statistics/rebuild/{job_id}/cancel")
def statistics_rebuild_cancel(job_id: str):
    with _conn() as conn:
        row = conn.execute("SELECT status FROM rebuild_jobs WHERE id=?", (job_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "rebuild job not found")
        if row["status"] in {"completed", "failed", "cancelled"}:
            return {"job_id": job_id, "status": row["status"]}
        conn.execute("UPDATE rebuild_jobs SET status='cancelled' WHERE id=?", (job_id,)); conn.commit()
        return {"job_id": job_id, "status": "cancelled"}


class ManualProfileRequest(BaseModel):
    tool: str = Field(pattern="^(codex|claude)$")
    config_root: str
    display_name: str | None = None


class FtsConsentRequest(BaseModel):
    decision: str = Field(pattern="^(accept|decline)$")
    notice_version: int = Field(ge=1)


class FtsSettingsRequest(BaseModel):
    indexing_enabled: bool


class UsageIngestRequest(BaseModel):
    events: list[dict]


class RebuildRequest(BaseModel):
    scope: str = Field(default="workbench_usage_and_rollup", pattern="^workbench_usage_and_rollup$")
    from_date: str | None = None
    to_date: str | None = None
    timezone: str = "UTC"
    parser_version: str = "current"
    include_pricing_estimates: bool = True


def _conn() -> sqlite3.Connection:
    return connect_workbench_db(default_workbench_paths(Path("data") / "ai_workbench").db_path)


@router.post("/statistics/usage")
def ingest_usage(payload: UsageIngestRequest):
    """Persist normalized usage facts; raw provider files remain untouched."""
    inserted = 0
    with _conn() as conn:
        for raw in payload.events:
            event = UsageEvent(**raw)
            observation_id = hashlib.sha256(f"{event.source_locator}|{event.dedup_key}".encode()).hexdigest()
            observed_at = event.event_at or "1970-01-01T00:00:00Z"
            conn.execute("""INSERT OR IGNORE INTO observations(id,observation_kind,source,source_locator,native_session_id,native_event_id,request_id,tool,model,observed_at,payload_hash,quality,parser_version,parse_status,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (observation_id, "session", f"{event.tool}_jsonl", event.source_locator, event.native_session_id, event.native_event_id, event.request_id, event.tool, None, observed_at, hashlib.sha256(json.dumps(raw, sort_keys=True).encode()).hexdigest(), event.quality, event.parser_version, "parsed", observed_at))
            cursor = conn.execute("""INSERT OR IGNORE INTO usage_records(id,observation_id,dedup_key,event_kind,input_tokens,output_tokens,cache_read_tokens,cache_creation_tokens,reasoning_tokens,total_tokens,counter_scope,counter_reset,event_at,recorded_at,source,quality,parser_version,merge_status,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (hashlib.sha256(event.dedup_key.encode()).hexdigest(), observation_id, event.dedup_key, "request_delta", event.input_tokens, event.output_tokens, event.cache_read_tokens, event.cache_creation_tokens, event.reasoning_tokens, event.total_tokens, "request", int(event.counter_reset), event.event_at, observed_at, f"{event.tool}_jsonl", event.quality, event.parser_version, "primary", observed_at))
            inserted += cursor.rowcount
            if cursor.rowcount:
                conn.execute("INSERT OR IGNORE INTO rollup_invalidations(id,bucket_date,timezone,reason,min_observed_at,max_observed_at,status,created_at) VALUES(?,?,?,?,?,?,?,?)", (hashlib.sha256(f"{event.dedup_key}:invalidation".encode()).hexdigest(), observed_at[:10], "UTC", "raw_changed", observed_at, observed_at, "pending", observed_at))
    return {"inserted": inserted}


@router.get("/profiles")
def profiles():
    with _conn() as conn:
        return {"data": profile_diagnostics(conn), "manual": list_manual_profiles(conn)}


@router.post("/profiles/manual")
def create_manual_profile(payload: ManualProfileRequest):
    root = Path(payload.config_root).expanduser()
    if not root.exists():
        raise HTTPException(status_code=400, detail="config_root does not exist")
    with _conn() as conn:
        return add_manual_profile(conn, tool=payload.tool, config_root=root, display_name=payload.display_name)


@router.post("/scan")
def scan():
    with _conn() as conn:
        summary = scan_sessions(conn)
        return {
            "run_id": summary.run_id,
            "profiles_seen": summary.profiles_seen,
            "profiles_indexed": summary.profiles_indexed,
            "files_seen": summary.files_seen,
            "sessions_indexed": summary.sessions_indexed,
            "events_indexed": summary.events_indexed,
            "errors": summary.errors,
        }


@router.post("/reconcile")
def reconcile():
    with _conn() as conn:
        summary = reconcile_sessions(conn)
        return {
            "run_id": summary.run_id,
            "profiles_seen": summary.profiles_seen,
            "profiles_indexed": summary.profiles_indexed,
            "files_seen": summary.files_seen,
            "sessions_indexed": summary.sessions_indexed,
            "events_indexed": summary.events_indexed,
            "errors": summary.errors,
        }


@router.get("/scan-runs")
def scan_runs(limit: int = Query(default=10, ge=1, le=100)):
    with _conn() as conn:
        return {"data": latest_scan_runs(conn, limit=limit)}


@router.get("/search/status")
def search_status():
    """Return persisted FTS consent, future-write setting, and index size."""
    with _conn() as conn:
        return fts_status(conn)


@router.post("/search/consent")
def search_consent(payload: FtsConsentRequest):
    """Record an explicit decision for the current full-text indexing notice."""
    with _conn() as conn:
        try:
            return record_fts_consent(
                conn,
                decision=payload.decision,
                notice_version=payload.notice_version,
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=409,
                detail={"code": "fts_notice_version_mismatch", "message": str(exc)},
            ) from exc


@router.patch("/search/settings")
def search_settings(payload: FtsSettingsRequest):
    """Enable or disable future FTS writes without implicitly recording consent."""
    with _conn() as conn:
        try:
            return set_fts_indexing_enabled(conn, enabled=payload.indexing_enabled)
        except FtsConsentRequiredError as exc:
            raise HTTPException(
                status_code=409,
                detail={"code": "fts_consent_required", "message": str(exc)},
            ) from exc


@router.post("/search/rebuild")
def search_rebuild():
    """Rebuild FTS only after consent and the future-write setting both permit it."""
    with _conn() as conn:
        try:
            return rebuild_fts(conn)
        except FtsConsentRequiredError as exc:
            raise HTTPException(
                status_code=409,
                detail={"code": "fts_consent_required", "message": str(exc)},
            ) from exc
        except FtsIndexingDisabledError as exc:
            raise HTTPException(
                status_code=409,
                detail={"code": "fts_indexing_disabled", "message": str(exc)},
            ) from exc


@router.post("/search/clear")
def search_clear():
    """Clear indexed text without changing consent or future-write settings."""
    with _conn() as conn:
        return clear_fts(conn)


@router.get("/sessions")
def sessions(
    tool: str | None = Query(default=None, pattern="^(codex|claude)$"),
    search: str | None = None,
    profile_id: str | None = None,
    project_id: str | None = None,
    divergence: str | None = Query(default=None, pattern="^(in_sync|ahead|diverged|unknown)$"),
    archived: bool | None = None,
    limit: int = Query(default=100, ge=1, le=300),
    cursor: int = Query(default=0, ge=0),
):
    with _conn() as conn:
        return list_sessions(
            conn,
            tool=tool,
            search=search,
            profile_id=profile_id,
            project_id=project_id,
            divergence=divergence,
            archived=archived,
            limit=limit,
            cursor=cursor,
        )


@router.get("/sessions/{copy_id}")
def session_detail(copy_id: str, event_limit: int = Query(default=300, ge=1, le=1000), event_cursor: int = Query(default=0, ge=0)):
    with _conn() as conn:
        detail = get_session_detail(conn, copy_id, event_limit=event_limit, event_cursor=event_cursor)
    if detail is None:
        raise HTTPException(status_code=404, detail="session not found")
    return detail
