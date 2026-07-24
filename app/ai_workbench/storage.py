from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1


DDL = [
    """
    CREATE TABLE IF NOT EXISTS schema_meta (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS manual_profile_roots (
        id TEXT PRIMARY KEY,
        tool TEXT NOT NULL,
        config_root TEXT NOT NULL,
        display_name TEXT,
        enabled INTEGER NOT NULL DEFAULT 1,
        created_at INTEGER NOT NULL,
        UNIQUE(tool, config_root)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS scan_runs (
        id TEXT PRIMARY KEY,
        started_at INTEGER NOT NULL,
        completed_at INTEGER,
        status TEXT NOT NULL,
        profiles_seen INTEGER NOT NULL DEFAULT 0,
        profiles_indexed INTEGER NOT NULL DEFAULT 0,
        files_seen INTEGER NOT NULL DEFAULT 0,
        sessions_indexed INTEGER NOT NULL DEFAULT 0,
        events_indexed INTEGER NOT NULL DEFAULT 0,
        errors_json TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS tool_profiles (
        id TEXT PRIMARY KEY,
        tool TEXT NOT NULL,
        display_name TEXT NOT NULL,
        config_root TEXT NOT NULL,
        session_root TEXT NOT NULL,
        discovery_source TEXT NOT NULL,
        capability_status TEXT NOT NULL DEFAULT 'unknown',
        enabled INTEGER NOT NULL DEFAULT 1,
        last_probe_at INTEGER
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS accounts (
        id TEXT PRIMARY KEY,
        account_ref TEXT,
        account_source TEXT NOT NULL DEFAULT 'unknown',
        account_confidence TEXT NOT NULL DEFAULT 'unknown'
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS repositories (
        id TEXT PRIMARY KEY,
        root_path TEXT,
        remote_url TEXT,
        exists_on_disk INTEGER NOT NULL DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS projects (
        id TEXT PRIMARY KEY,
        cwd_raw TEXT,
        cwd_canonical TEXT,
        repository_id TEXT,
        exists_on_disk INTEGER NOT NULL DEFAULT 0,
        FOREIGN KEY(repository_id) REFERENCES repositories(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS conversation_families (
        id TEXT PRIMARY KEY,
        tool TEXT NOT NULL,
        native_session_id TEXT NOT NULL,
        initial_fingerprint TEXT,
        created_at INTEGER,
        updated_at INTEGER
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS session_copies (
        id TEXT PRIMARY KEY,
        family_id TEXT NOT NULL,
        tool TEXT NOT NULL,
        native_session_id TEXT NOT NULL,
        profile_id TEXT NOT NULL,
        project_id TEXT,
        transcript_path TEXT NOT NULL,
        transcript_kind TEXT NOT NULL,
        title TEXT,
        model TEXT,
        kind TEXT NOT NULL DEFAULT 'main',
        created_at INTEGER,
        updated_at INTEGER,
        content_hash TEXT,
        head_event_hash TEXT,
        parse_version INTEGER NOT NULL,
        account_source TEXT NOT NULL DEFAULT 'unknown',
        account_confidence TEXT NOT NULL DEFAULT 'unknown',
        index_status TEXT NOT NULL,
        divergence_status TEXT NOT NULL DEFAULT 'unknown',
        event_count INTEGER NOT NULL DEFAULT 0,
        UNIQUE(tool, profile_id, native_session_id, transcript_path),
        FOREIGN KEY(family_id) REFERENCES conversation_families(id),
        FOREIGN KEY(profile_id) REFERENCES tool_profiles(id),
        FOREIGN KEY(project_id) REFERENCES projects(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS session_relations (
        id TEXT PRIMARY KEY,
        source_copy_id TEXT NOT NULL,
        target_copy_id TEXT NOT NULL,
        relation_type TEXT NOT NULL,
        evidence TEXT,
        FOREIGN KEY(source_copy_id) REFERENCES session_copies(id),
        FOREIGN KEY(target_copy_id) REFERENCES session_copies(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS turns (
        id TEXT PRIMARY KEY,
        session_copy_id TEXT NOT NULL,
        turn_index INTEGER NOT NULL,
        started_at INTEGER,
        completed_at INTEGER,
        FOREIGN KEY(session_copy_id) REFERENCES session_copies(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS events (
        id TEXT PRIMARY KEY,
        session_copy_id TEXT NOT NULL,
        turn_id TEXT,
        sequence_no INTEGER NOT NULL,
        event_type TEXT NOT NULL,
        role TEXT,
        text_content TEXT,
        structured_json TEXT,
        raw_json TEXT,
        source_offset INTEGER,
        data_quality TEXT NOT NULL DEFAULT 'exact',
        FOREIGN KEY(session_copy_id) REFERENCES session_copies(id),
        FOREIGN KEY(turn_id) REFERENCES turns(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS source_checkpoints (
        path TEXT PRIMARY KEY,
        profile_id TEXT NOT NULL,
        file_size INTEGER NOT NULL,
        mtime_ns INTEGER NOT NULL,
        parsed_offset INTEGER NOT NULL,
        last_complete_line_offset INTEGER NOT NULL,
        content_hash TEXT NOT NULL,
        parser_version INTEGER NOT NULL,
        last_indexed_at INTEGER NOT NULL,
        FOREIGN KEY(profile_id) REFERENCES tool_profiles(id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_session_copies_updated ON session_copies(updated_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_session_copies_tool ON session_copies(tool, profile_id)",
    "CREATE INDEX IF NOT EXISTS idx_events_session_seq ON events(session_copy_id, sequence_no)",
    "CREATE INDEX IF NOT EXISTS idx_source_checkpoints_profile ON source_checkpoints(profile_id)",
    """
    CREATE VIRTUAL TABLE IF NOT EXISTS events_fts USING fts5(
        session_copy_id UNINDEXED,
        event_id UNINDEXED,
        text_content,
        tokenize = 'unicode61'
    )
    """,
]


@dataclass(frozen=True)
class WorkbenchPaths:
    db_path: Path


def default_workbench_paths(base_dir: Path | None = None) -> WorkbenchPaths:
    root = base_dir or Path("data") / "ai_workbench"
    return WorkbenchPaths(db_path=root / "workbench.db")


def connect_workbench_db(path: Path | None = None) -> sqlite3.Connection:
    target = path or default_workbench_paths().db_path
    target.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(target)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    for stmt in DDL:
        conn.execute(stmt)
    conn.execute(
        "INSERT INTO schema_meta(key, value) VALUES('schema_version', ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (str(SCHEMA_VERSION),),
    )
    _ensure_column(conn, "source_checkpoints", "missing_since", "INTEGER")
    _ensure_column(conn, "source_checkpoints", "status", "TEXT NOT NULL DEFAULT 'active'")
    conn.commit()
    return conn


def row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {key: row[key] for key in row.keys()}


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    columns = {row["name"] for row in conn.execute(f'PRAGMA table_info("{table}")').fetchall()}
    if column not in columns:
        conn.execute(f'ALTER TABLE "{table}" ADD COLUMN {column} {definition}')
