from __future__ import annotations

import asyncio
import os
import sqlite3
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
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
from app.ai_workbench.statistics import statistics_overview, statistics_timeseries, statistics_breakdown, statistics_csv, enqueue_rebuild, record_rollup_invalidation, pricing_snapshot_sources
from app.ai_workbench.compatibility.cc_switch import read_proxy_request_logs, read_pricing_candidates, capability_report
from app.ai_workbench.usage import UsageEvent
from app.ai_workbench.merge import merge_decision
from app.ai_workbench.merge import reprice_usage
from app.ai_workbench.composer import ComposerError, compose_run, execution_capabilities_for, request_cancel, retry_failed_step
from app.ai_workbench.approval import decide_approval, expire_approvals, record_approval_delivery
from app.ai_workbench.event_persistence import list_events_before, resync_events
from app.ai_workbench.execution.runtime_coordinator import RuntimeCoordinator
from app.ai_workbench.execution.authorization import AuthorizationError, consume_p3_10_authorization, load_p3_10_approval
from app.ai_workbench.runtime_stream import runtime_broadcaster
from app.repository_update import RepositoryUpdateError, apply_update, check_for_updates, load_settings, save_settings
import hashlib
import json
import base64
from uuid import uuid4
from datetime import datetime, timezone, date
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

class WorkbenchRoute(APIRoute):
    """Keep validation failures on the same public error contract as P3 APIs."""

    def get_route_handler(self):
        handler = super().get_route_handler()

        async def wrapped(request: Request):
            try:
                return await handler(request)
            except RequestValidationError as exc:
                return JSONResponse(status_code=422, content={
                    "code": "invalid_request", "message": "request validation failed",
                    "details": {"errors": exc.errors()}, "retryable": False,
                })

        return wrapped


router = APIRouter(prefix="/api/ai-workbench", tags=["ai-workbench"], route_class=WorkbenchRoute)


def _audit_cc_switch(result: dict, *, action: str) -> None:
    with _conn() as conn:
        conn.execute("INSERT INTO cc_switch_audit(id,observed_at,db_identity,status,user_version,capabilities_json,message,action) VALUES(?,?,?,?,?,?,?,?)", (hashlib.sha256(f"{action}:{datetime.now(timezone.utc).isoformat()}".encode()).hexdigest(), datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"), result.get("db_identity"), result.get("status", "unknown"), result.get("user_version"), json.dumps(result.get("capabilities", {})), result.get("message") or result.get("reason_code"), action))


def _statistics_filters(start: str | None, end: str | None, tool: str | None, profile_ref: str | None, timezone_name: str | None = None, project_ref: str | None = None, model: str | None = None, provider: str | None = None, source: str | None = None) -> dict:
    if tool is not None and tool not in {"codex", "claude", "proxy"}:
        raise HTTPException(400, "invalid tool")
    try:
        start_date = date.fromisoformat(start) if start else None
        end_date = date.fromisoformat(end) if end else None
    except ValueError:
        raise HTTPException(400, "invalid date")
    if start_date and end_date and start_date > end_date:
        raise HTTPException(400, "start must not be after end")
    if start_date and end_date and (end_date - start_date).days > 366:
        raise HTTPException(400, "date range exceeds 366 days")
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
def statistics_reliability_api(start: str | None = None, end: str | None = None, tool: str | None = None, profile_ref: str | None = None, timezone_name: str | None = None, project_ref: str | None = None, model: str | None = None, provider: str | None = None, source: str | None = None):
    filters = _statistics_filters(start, end, tool, profile_ref, timezone_name, project_ref, model, provider, source)
    with _conn() as conn:
        clauses, args = ["observation_kind IN ('session','supervised_run')"], []
        if filters["start"]: clauses.append("substr(observed_at,1,10) >= ?"); args.append(filters["start"])
        if filters["end"]: clauses.append("substr(observed_at,1,10) <= ?"); args.append(filters["end"])
        for column in ("tool", "profile_ref", "project_ref", "model", "provider", "source"):
            if filters.get(column): clauses.append(f"{column} = ?"); args.append(filters[column])
        native = conn.execute(f"SELECT count(*) count, min(quality) quality FROM observations WHERE {' AND '.join(clauses)}", args).fetchone()
        proxy_clauses = [c.replace("observation_kind IN ('session','supervised_run')", "observation_kind='proxy'") for c in clauses]
        proxy = conn.execute(f"SELECT count(*) count, min(quality) quality FROM observations WHERE {' AND '.join(proxy_clauses)}", args).fetchone()
    return {
        "proxy": {"availability": "available" if proxy["count"] else "unavailable", "quality": proxy["quality"] or "unavailable", "source": "proxy", "reason_code": None if proxy["count"] else "no_proxy_observations"},
        "native": {"availability": "available" if native["count"] else "unavailable", "quality": native["quality"] or "unavailable", "source": "native", "reason_code": None if native["count"] else "no_native_observations"},
    }


@router.get("/statistics/data-quality")
def statistics_quality_api(start: str | None = None, end: str | None = None, tool: str | None = None, profile_ref: str | None = None, timezone_name: str | None = None, project_ref: str | None = None, model: str | None = None, provider: str | None = None, source: str | None = None):
    filters = _statistics_filters(start, end, tool, profile_ref, timezone_name, project_ref, model, provider, source)
    with _conn() as conn:
        clauses, args = [], []
        if filters["start"]: clauses.append("substr(observed_at,1,10) >= ?"); args.append(filters["start"])
        if filters["end"]: clauses.append("substr(observed_at,1,10) <= ?"); args.append(filters["end"])
        for column in ("tool", "profile_ref", "project_ref", "model", "provider", "source"):
            if filters.get(column): clauses.append(f"{column} = ?"); args.append(filters[column])
        rows = conn.execute("SELECT quality, source, count(*) count FROM observations" + (" WHERE " + " AND ".join(clauses) if clauses else "") + " GROUP BY quality, source", args).fetchall()
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
            if cursor.rowcount:
                record_rollup_invalidation(conn, "pricing_snapshot_changed", bucket_date=item.get("effective_at", observed_at)[:10], observed_at=observed_at)
    return {"status": "available", "imported": imported, "pricing_enabled": False}


@router.post("/statistics/pricing/recalculate")
def recalculate_pricing():
    with _conn() as conn:
        return reprice_usage(conn)


@router.get("/statistics/pricing/snapshots")
def pricing_snapshots(model: str | None = None):
    """Expose all configured pricing sources so conflicts are not silently hidden."""
    with _conn() as conn:
        return {"data": pricing_snapshot_sources(conn, model=model)}


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
                natives = conn.execute("""SELECT o.id,o.request_id,u.input_tokens,u.output_tokens,u.cache_read_tokens,u.cache_creation_tokens
                    FROM observations o LEFT JOIN usage_records u ON u.observation_id=o.id
                    WHERE o.request_id=? AND o.observation_kind != 'proxy'""", (request_id,)).fetchall()
                for native in natives:
                    decision = merge_decision({"request_id": request_id, "input_tokens": native["input_tokens"], "output_tokens": native["output_tokens"], "cache_read_tokens": native["cache_read_tokens"], "cache_creation_tokens": native["cache_creation_tokens"]}, {"request_id": request_id, "input_tokens": item.get("input_tokens"), "output_tokens": item.get("output_tokens"), "cache_read_tokens": item.get("cache_read_tokens"), "cache_creation_tokens": item.get("cache_creation_tokens")})
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


@router.get("/statistics/rebuild/{job_id}/audit")
def statistics_rebuild_audit(job_id: str):
    """Return the persisted before/after rebuild audit without rerunning work."""
    with _conn() as conn:
        row = conn.execute("SELECT audit_json FROM rebuild_jobs WHERE id=?", (job_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "rebuild job not found")
        if not row["audit_json"]:
            raise HTTPException(409, "rebuild audit is not available")
        return json.loads(row["audit_json"])


@router.get("/statistics/rebuild/{job_id}")
def statistics_rebuild_status(job_id: str):
    with _conn() as conn:
        row = conn.execute("SELECT * FROM rebuild_jobs WHERE id=?", (job_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "rebuild job not found")
        if row["status"] == "failed":
            raise HTTPException(500, row["error"] or "rebuild failed")
        return dict(row)


@router.post("/statistics/rebuild/{job_id}/cancel")
def statistics_rebuild_cancel(job_id: str):
    with _conn() as conn:
        row = conn.execute("SELECT status FROM rebuild_jobs WHERE id=?", (job_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "rebuild job not found")
        if row["status"] in {"completed", "failed", "cancelled", "cancelling"}:
            return {"job_id": job_id, "status": row["status"]}
        next_status = "cancelling" if row["status"] == "running" else "cancelled"
        conn.execute("UPDATE rebuild_jobs SET status=? WHERE id=?", (next_status, job_id)); conn.commit()
        return {"job_id": job_id, "status": next_status}


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


class ComposeRunRequest(BaseModel):
    action: str = Field(pattern="^(new|resume|fork)$")
    tool: str = Field(pattern="^(codex|claude)$")
    profile_id: str
    cwd: str
    cwd_confirmed: bool = False
    prompt: str = Field(min_length=1, max_length=100_000)
    model: str | None = None
    permission_policy: dict = Field(default_factory=dict)
    budget_policy: dict = Field(default_factory=dict)
    session_copy_id: str | None = None
    client_request_id: str | None = None
    authorization_nonce: str | None = Field(default=None, min_length=1, max_length=256)


class ApprovalDecisionRequest(BaseModel):
    decision: str = Field(pattern="^(accept|decline|cancel)$")
    decided_by: str = Field(min_length=1)


class RetryStepRequest(BaseModel):
    step_id: str


class RepositoryUpdateSettingsRequest(BaseModel):
    auto_update_enabled: bool


def _db_path() -> Path:
    override = os.environ.get("AI_WORKBENCH_DB_PATH")
    return Path(override) if override else default_workbench_paths(Path("data") / "ai_workbench").db_path


def _conn() -> sqlite3.Connection:
    return connect_workbench_db(_db_path())


def _active_run_count() -> int:
    with _conn() as conn:
        return int(conn.execute(
            "SELECT COUNT(*) FROM runs WHERE state IN ('queued','running','cancel_requested','cancelling')"
        ).fetchone()[0])


@router.get("/repository-update")
def repository_update_status(refresh: bool = False):
    """Inspect the fixed official origin; no browser-provided Git target exists."""
    return check_for_updates(refresh=refresh)


@router.get("/repository-update/settings")
def repository_update_settings():
    return load_settings()


@router.patch("/repository-update/settings")
def repository_update_settings_update(payload: RepositoryUpdateSettingsRequest):
    return save_settings(auto_update_enabled=payload.auto_update_enabled)


@router.post("/repository-update/apply", status_code=202)
def repository_update_apply():
    active_runs = _active_run_count()
    if active_runs:
        raise HTTPException(status_code=409, detail={
            "code": "active_runs", "message": "有正在运行的任务，不能更新应用。", "details": {"active_runs": active_runs}, "retryable": True,
        })
    try:
        return apply_update()
    except RepositoryUpdateError as exc:
        raise HTTPException(status_code=409, detail={
            "code": exc.code, "message": exc.message, "details": {}, "retryable": exc.code in {"worktree_dirty", "branch_diverged"},
        }) from exc


def _approval_dto(row: sqlite3.Row) -> dict:
    """Expose approval evidence as structured display data, never a shell string."""
    item = dict(row)
    for source, target in (("command_argv_json", "command_argv"), ("affected_paths_json", "affected_paths"), ("network_targets_json", "network_targets")):
        raw = item.pop(source, None)
        try:
            item[target] = json.loads(raw) if raw else []
        except (TypeError, json.JSONDecodeError):
            item[target] = []
    return item


def _run_dto(row: sqlite3.Row) -> dict:
    """Expose policy values with their enforcement strength, never raw JSON only."""
    item = dict(row)
    try:
        budget = json.loads(item.get("budget_policy_json") or "{}")
    except (TypeError, json.JSONDecodeError):
        budget = {}
    tool = item.get("tool")
    limits: list[dict[str, object]] = [
        {"name": "max_turns", "value": budget.get("max_turns", 1), "strength": "hard"},
        {"name": "max_duration_seconds", "value": budget.get("max_duration_seconds"), "strength": "hard"},
    ]
    if "max_budget_usd" in budget:
        limits.append({"name": "max_budget_usd", "value": budget["max_budget_usd"],
                       "strength": "provider_enforced" if tool == "claude" else "unsupported"})
    for name in ("max_total_tokens_observed", "max_cost_minor_observed"):
        if name in budget:
            limits.append({"name": name, "value": budget[name], "strength": "observed_only"})
    for limit in limits:
        value = limit.get("value")
        limit["availability"] = "unavailable" if value is None else "estimated" if limit["strength"] == "observed_only" else "exact"
    item["budget_policy"] = budget
    item["budget_limits"] = limits
    return item


def _p3_error(status_code: int, code: str, message: str, *, details: dict | None = None,
              retryable: bool = False) -> JSONResponse:
    """Return the stable error contract used by interactive-runtime clients."""
    return JSONResponse(status_code=status_code, content={
        "code": code, "message": message, "details": details or {}, "retryable": retryable,
    })


def _run_cursor(created_at: str, run_id: str) -> str:
    return base64.urlsafe_b64encode(json.dumps([created_at, run_id], separators=(",", ":")).encode()).decode().rstrip("=")


def _parse_run_cursor(cursor: str) -> tuple[str, str] | None:
    try:
        decoded = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)).decode()
        created_at, run_id = json.loads(decoded)
        if not isinstance(created_at, str) or not isinstance(run_id, str):
            raise ValueError
        return created_at, run_id
    except (ValueError, TypeError, UnicodeDecodeError, json.JSONDecodeError):
        return None


def _runtime(request: Request) -> RuntimeCoordinator | JSONResponse:
    runtime = getattr(request.app.state, "ai_workbench_runtime", None)
    if runtime is None:
        code = getattr(request.app.state, "ai_workbench_runtime_error", "runtime_unavailable")
        return _p3_error(503, code, "interactive runtime is not available in this server process",
                         retryable=code != "unsupported_multi_worker_runtime")
    return runtime


@router.post("/runs")
def create_run(payload: ComposeRunRequest, request: Request):
    runtime = _runtime(request)
    if isinstance(runtime, JSONResponse):
        return runtime
    if not runtime.execution_available:
        return _p3_error(409, "real_execution_disabled", "real model execution is disabled by the server owner")
        raise HTTPException(
            status_code=409,
            detail={
                "code": "real_execution_disabled",
                "message": "真实模型执行已关闭；请由服务所有者在明确授权后设置 AI_WORKBENCH_REAL_EXECUTION=1 并重启服务。",
                "retryable": False,
            },
        )
    with _conn() as conn:
        try:
            p3_10_mode = os.environ.get("AI_WORKBENCH_EXECUTION_MODE") == "p3_10"
            if p3_10_mode:
                artifact_path = os.environ.get("AI_WORKBENCH_P3_10_APPROVAL_FILE")
                if not artifact_path:
                    raise AuthorizationError("P3-10 approval artifact path is not configured", "approval_artifact_required")
                load_p3_10_approval(conn, Path(artifact_path))
            data = payload.model_dump(exclude={"authorization_nonce"})
            result = compose_run(conn, **data)
            if p3_10_mode and not result.get("idempotent"):
                try:
                    consume_p3_10_authorization(
                        conn, nonce=payload.authorization_nonce, request_body_hash=result["run"]["request_body_hash"],
                        tool=result["run"]["tool"], model=result["run"]["model"],
                        budget_policy=data["budget_policy"],
                    )
                except AuthorizationError:
                    # The request was never enqueued; remove only these fresh
                    # rows so a rejected approval cannot leave a runnable run.
                    conn.execute("DELETE FROM run_steps WHERE run_id=?", (result["run"]["id"],))
                    conn.execute("DELETE FROM runs WHERE id=?", (result["run"]["id"],))
                    conn.commit()
                    raise
            if not result.get("idempotent"):
                runtime.enqueue(result["run"]["id"])
            return JSONResponse(status_code=200 if result.get("idempotent") else 202, content=result)
        except AuthorizationError as exc:
            return _p3_error(409, exc.code, str(exc))
        except ComposerError as exc:
            status = 409 if exc.code in {"idempotency_conflict", "session_busy"} else 400
            return _p3_error(status, exc.code, str(exc))


@router.get("/runs")
def list_runs(
    limit: int = Query(default=50, ge=1, le=200), state: str | None = None,
    tool: str | None = Query(default=None, pattern="^(codex|claude)$"), profile_id: str | None = None,
    cursor: str | None = None,
):
    with _conn() as conn:
        clauses, args = [], []
        if state:
            clauses.append("state=?"); args.append(state)
        if tool:
            clauses.append("tool=?"); args.append(tool)
        if profile_id:
            clauses.append("profile_id=?"); args.append(profile_id)
        if cursor:
            parsed_cursor = _parse_run_cursor(cursor)
            if parsed_cursor is None:
                return _p3_error(400, "invalid_cursor", "run cursor is invalid")
            created_at, run_id = parsed_cursor
            clauses.append("(created_at < ? OR (created_at = ? AND id < ?))")
            args.extend((created_at, created_at, run_id))
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        rows = conn.execute(f"""SELECT r.*,
            (SELECT count(*) FROM approval_requests a WHERE a.run_id=r.id AND a.state='pending') AS pending_approval_count,
            (SELECT event_type FROM run_events e WHERE e.run_id=r.id ORDER BY sequence_no DESC LIMIT 1) AS latest_event_type,
            (SELECT timestamp FROM run_events e WHERE e.run_id=r.id ORDER BY sequence_no DESC LIMIT 1) AS latest_event_at
            FROM runs r{where} ORDER BY created_at DESC, id DESC LIMIT ?""", (*args, limit + 1)).fetchall()
        page = rows[:limit]
        return {"data": [_run_dto(row) for row in page], "next_cursor": _run_cursor(page[-1]["created_at"], page[-1]["id"]) if len(rows) > limit and page else None}


@router.get("/runs/{run_id}")
def run_detail(run_id: str, last_sequence_no: int = Query(default=0, ge=0)):
    with _conn() as conn:
        run = conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        if run is None:
            return _p3_error(404, "run_not_found", "run not found", details={"run_id": run_id})
        steps = [dict(row) for row in conn.execute("SELECT * FROM run_steps WHERE run_id=? ORDER BY ordinal", (run_id,))]
        approvals = [_approval_dto(row) for row in conn.execute("SELECT * FROM approval_requests WHERE run_id=? ORDER BY decided_at IS NOT NULL, id", (run_id,))]
        stream = resync_events(conn, run_id, last_sequence_no)
        return {"run": _run_dto(run), "steps": steps, "approvals": approvals,
                "events": stream["events"], "resync_required": stream["resync_required"],
                "has_more": stream["has_more"],
                "next_sequence_no": int(run["last_sequence_no"]) + 1}


@router.get("/runs/{run_id}/events")
def run_events(
    run_id: str,
    after_sequence: int = Query(default=0, ge=0),
    before_sequence: int | None = Query(default=None, ge=1),
    limit: int = Query(default=200, ge=1, le=500),
):
    """Page run history without forcing clients to reload the full stream."""
    with _conn() as conn:
        exists = conn.execute("SELECT 1 FROM runs WHERE id=?", (run_id,)).fetchone()
        if exists is None:
            return _p3_error(404, "run_not_found", "run not found", details={"run_id": run_id})
        if before_sequence is not None:
            return list_events_before(conn, run_id, before_sequence, limit=limit)
        return resync_events(conn, run_id, after_sequence, limit=limit)


@router.get("/runs/{run_id}/artifacts/{artifact_id}")
def download_run_artifact(run_id: str, artifact_id: str):
    with _conn() as conn:
        artifact = conn.execute(
            "SELECT relative_path,mime_type FROM run_artifacts WHERE id=? AND run_id=?", (artifact_id, run_id)
        ).fetchone()
    if artifact is None:
        return _p3_error(404, "artifact_not_found", "artifact not found", details={"artifact_id": artifact_id})
    root = (_db_path().parent / "run-artifacts").resolve()
    candidate = (_db_path().parent / artifact["relative_path"]).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        return _p3_error(400, "invalid_artifact_path", "artifact path is outside the artifact root")
    if not candidate.is_file():
        return _p3_error(404, "artifact_file_not_found", "artifact file not found", details={"artifact_id": artifact_id})
    return FileResponse(candidate, media_type=artifact["mime_type"] or "application/octet-stream")


@router.delete("/runs/{run_id}/artifacts/{artifact_id}")
def delete_run_artifact(run_id: str, artifact_id: str):
    with _conn() as conn:
        artifact = conn.execute(
            "SELECT relative_path FROM run_artifacts WHERE id=? AND run_id=?", (artifact_id, run_id)
        ).fetchone()
        if artifact is None:
            return _p3_error(404, "artifact_not_found", "artifact not found", details={"artifact_id": artifact_id})
        root = (_db_path().parent / "run-artifacts").resolve()
        candidate = (_db_path().parent / artifact["relative_path"]).resolve()
        try:
            candidate.relative_to(root)
        except ValueError as exc:
            return _p3_error(400, "invalid_artifact_path", "artifact path is outside the artifact root")
        # Delete only the exact file registered for this run, then remove its
        # reference.  A missing file is treated as an already-cleaned artifact.
        if candidate.exists():
            candidate.unlink()
        conn.execute("DELETE FROM run_artifacts WHERE id=? AND run_id=?", (artifact_id, run_id))
        conn.commit()
    return {"deleted": artifact_id}


@router.post("/runs/{run_id}/cancel")
def cancel_run_api(run_id: str, request: Request):
    runtime = _runtime(request)
    if isinstance(runtime, JSONResponse):
        return runtime
    with _conn() as conn:
        try:
            result = request_cancel(conn, run_id)
            runtime.request_cancel(run_id)
            # A queued run may have been cancelled before its worker consumes
            # it; enqueueing is harmless and lets the coordinator discard it.
            runtime.enqueue(run_id)
            return JSONResponse(status_code=202, content=result)
        except KeyError as exc:
            return _p3_error(404, "run_not_found", "run not found", details={"run_id": run_id})


@router.post("/runs/{run_id}/retry")
def retry_run_api(run_id: str, payload: RetryStepRequest, request: Request):
    with _conn() as conn:
        try:
            result = retry_failed_step(conn, run_id, payload.step_id)
            runtime = _runtime(request)
            if isinstance(runtime, JSONResponse):
                return runtime
            runtime.enqueue(result["run"]["id"])
            return JSONResponse(status_code=201, content=result)
        except KeyError as exc:
            return _p3_error(404, "run_or_step_not_found", "run or step not found", details={"run_id": run_id, "step_id": payload.step_id})
        except ComposerError as exc:
            return _p3_error(409, exc.code, str(exc))


@router.websocket("/runs/{run_id}/stream")
async def run_stream(websocket: WebSocket, run_id: str):
    await websocket.accept()
    queue = None
    try:
        cursor = int(websocket.query_params.get("last_sequence_no", "0"))
        # Subscribe first, then replay the durable cursor.  This closes the
        # race in which an event is committed while a browser is connecting.
        queue = await runtime_broadcaster.subscribe(run_id)
        with _conn() as conn:
            run = conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
            if run is None:
                await websocket.close(code=4404)
                return
            high_watermark = int(run["last_sequence_no"] or 0)
            replay = resync_events(conn, run_id, cursor, up_to_sequence_no=high_watermark)
        await websocket.send_json({
            "type": "hello", "connection_id": str(uuid4()), "run_id": run_id,
            "run": dict(run), "high_watermark": high_watermark,
            "capabilities": json.loads(run["capabilities_snapshot_json"] or "{}"),
            "events": replay["events"], "resync_required": replay["resync_required"], "has_more": replay["has_more"],
        })
        while True:
            try:
                message = await asyncio.wait_for(websocket.receive_json(), timeout=0.05)
                if message.get("type") == "resync":
                    cursor = int(message.get("last_sequence_no", cursor))
                    with _conn() as conn:
                        high_watermark = int(conn.execute("SELECT last_sequence_no FROM runs WHERE id=?", (run_id,)).fetchone()[0] or 0)
                        replay = resync_events(conn, run_id, cursor, up_to_sequence_no=high_watermark)
                    await websocket.send_json({"type": "events", "events": replay["events"], "resync_required": replay["resync_required"], "has_more": replay["has_more"]})
            except asyncio.TimeoutError:
                try:
                    event = queue.get_nowait()
                except asyncio.QueueEmpty:
                    continue
                if event.get("type") == "stream.gap":
                    await websocket.send_json({"type": "events", "events": [], "resync_required": True})
                    continue
                if int(event.get("sequence_no", 0)) <= cursor:
                    continue
                cursor = int(event["sequence_no"])
                await websocket.send_json({"type": "events", "events": [event]})
    except WebSocketDisconnect:
        return
    finally:
        if queue is not None:
            runtime_broadcaster.unsubscribe(run_id, queue)


@router.post("/approvals/{request_id}/decision")
def approval_decision(request_id: str, payload: ApprovalDecisionRequest, request: Request):
    with _conn() as conn:
        capability_row = conn.execute(
            "SELECT r.capabilities_snapshot_json FROM approval_requests a JOIN runs r ON r.id=a.run_id WHERE a.id=?",
            (request_id,),
        ).fetchone()
        if capability_row is not None:
            try:
                native_approval = json.loads(capability_row["capabilities_snapshot_json"] or "{}").get("native_approval")
            except (TypeError, json.JSONDecodeError):
                native_approval = None
            if native_approval is False:
                return _p3_error(409, "capability_not_supported", "this run's adapter cannot deliver native approval decisions")
        try:
            # This is a local single-user Workbench.  Client supplied labels
            # are display data, never an audit identity.
            result = decide_approval(conn, request_id, decision=payload.decision, decided_by="workbench-local-user")
        except KeyError as exc:
            return _p3_error(404, "approval_request_not_found", "approval request not found", details={"request_id": request_id})
        if result.get("conflict"):
            return _p3_error(409, "approval_already_decided", "approval request has already been decided", details={"request": result})
        runtime = _runtime(request)
        if isinstance(runtime, JSONResponse):
            return runtime
        delivered = runtime.resolve_approval(request_id, payload.decision)
        if not delivered:
            record_approval_delivery(conn, request_id, delivered=False)
            return _p3_error(409, "approval_delivery_failed", "native approval request is no longer connected")
        return JSONResponse(status_code=202, content=result)


@router.post("/approvals/expire")
def expire_approval_requests():
    with _conn() as conn:
        return {"expired": expire_approvals(conn)}


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
            merge_status = "primary"
            conflict_group_id = None
            if event.request_id:
                peers = conn.execute("SELECT input_tokens,output_tokens,cache_read_tokens,cache_creation_tokens FROM usage_records u JOIN observations o ON o.id=u.observation_id WHERE o.request_id=? AND o.observation_kind != 'proxy'", (event.request_id,)).fetchall()
                for peer in peers:
                    decision = merge_decision(dict(peer), event.as_dict())
                    if decision.status == "duplicate": merge_status = "duplicate"
                    elif decision.status == "conflict": merge_status = "conflict"; conflict_group_id = decision.conflict_group_id
            cursor = conn.execute("""INSERT OR IGNORE INTO usage_records(id,observation_id,dedup_key,event_kind,input_tokens,output_tokens,cache_read_tokens,cache_creation_tokens,reasoning_tokens,total_tokens,counter_scope,counter_reset,event_at,recorded_at,source,quality,parser_version,merge_status,conflict_group_id,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (hashlib.sha256(event.dedup_key.encode()).hexdigest(), observation_id, event.dedup_key, "request_delta", event.input_tokens, event.output_tokens, event.cache_read_tokens, event.cache_creation_tokens, event.reasoning_tokens, event.total_tokens, "request", int(event.counter_reset), event.event_at, observed_at, f"{event.tool}_jsonl", event.quality, event.parser_version, merge_status, conflict_group_id, observed_at))
            inserted += cursor.rowcount
            if cursor.rowcount:
                record_rollup_invalidation(conn, "raw_changed", bucket_date=observed_at[:10], observed_at=observed_at)
    return {"inserted": inserted}


@router.get("/profiles")
def profiles():
    with _conn() as conn:
        rows = profile_diagnostics(conn)
        baseline_row = conn.execute(
            "SELECT payload_json, observed_at FROM runtime_capability_baselines ORDER BY id DESC LIMIT 1"
        ).fetchone()
        observed = {}
        observed_at = None
        if baseline_row:
            try:
                observed = json.loads(baseline_row["payload_json"] or "{}")
                observed_at = baseline_row["observed_at"]
            except (TypeError, json.JSONDecodeError):
                observed = {}
        for row in rows:
            row["execution_capabilities"] = execution_capabilities_for(row["tool"])
            row["observed_capabilities"] = observed.get(row["tool"])
            row["observed_capabilities_at"] = observed_at
        return {"data": rows, "manual": list_manual_profiles(conn)}


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
