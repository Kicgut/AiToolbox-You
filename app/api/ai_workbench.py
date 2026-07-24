from __future__ import annotations

import sqlite3
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

router = APIRouter(prefix="/api/ai-workbench", tags=["ai-workbench"])


class ManualProfileRequest(BaseModel):
    tool: str = Field(pattern="^(codex|claude)$")
    config_root: str
    display_name: str | None = None


class FtsConsentRequest(BaseModel):
    decision: str = Field(pattern="^(accept|decline)$")
    notice_version: int = Field(ge=1)


class FtsSettingsRequest(BaseModel):
    indexing_enabled: bool


def _conn() -> sqlite3.Connection:
    return connect_workbench_db(default_workbench_paths(Path("data") / "ai_workbench").db_path)


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
