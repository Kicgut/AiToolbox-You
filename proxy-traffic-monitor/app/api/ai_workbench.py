from __future__ import annotations

import sqlite3
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

from app.ai_workbench.indexing.scanner import get_session_detail, list_sessions, profile_diagnostics, scan_sessions
from app.ai_workbench.storage import connect_workbench_db, default_workbench_paths

router = APIRouter(prefix="/api/ai-workbench", tags=["ai-workbench"])


def _conn() -> sqlite3.Connection:
    return connect_workbench_db(default_workbench_paths(Path("data") / "ai_workbench").db_path)


@router.get("/profiles")
def profiles():
    with _conn() as conn:
        return {"data": profile_diagnostics(conn)}


@router.post("/scan")
def scan():
    with _conn() as conn:
        summary = scan_sessions(conn)
        return {
            "profiles_seen": summary.profiles_seen,
            "profiles_indexed": summary.profiles_indexed,
            "files_seen": summary.files_seen,
            "sessions_indexed": summary.sessions_indexed,
            "events_indexed": summary.events_indexed,
            "errors": summary.errors,
        }


@router.get("/sessions")
def sessions(
    tool: str | None = Query(default=None, pattern="^(codex|claude)$"),
    search: str | None = None,
    limit: int = Query(default=100, ge=1, le=300),
    cursor: int = Query(default=0, ge=0),
):
    with _conn() as conn:
        return list_sessions(conn, tool=tool, search=search, limit=limit, cursor=cursor)


@router.get("/sessions/{copy_id}")
def session_detail(copy_id: str, event_limit: int = Query(default=300, ge=1, le=1000), event_cursor: int = Query(default=0, ge=0)):
    with _conn() as conn:
        detail = get_session_detail(conn, copy_id, event_limit=event_limit, event_cursor=event_cursor)
    if detail is None:
        raise HTTPException(status_code=404, detail="session not found")
    return detail

