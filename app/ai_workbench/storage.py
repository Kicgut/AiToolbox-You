from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 2
FTS_NOTICE_VERSION = 1
LEGACY_BUSINESS_TABLES = {
    "manual_profile_roots",
    "scan_runs",
    "tool_profiles",
    "accounts",
    "repositories",
    "projects",
    "conversation_families",
    "session_copies",
    "session_relations",
    "turns",
    "events",
    "source_checkpoints",
    "events_fts",
}


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
    """
    CREATE TABLE IF NOT EXISTS fts_settings (
        id INTEGER PRIMARY KEY CHECK(id = 1),
        consent_state TEXT NOT NULL CHECK(
            consent_state IN ('recommended_pending', 'user_enabled', 'user_declined', 'legacy_preserved')
        ),
        indexing_enabled INTEGER NOT NULL CHECK(indexing_enabled IN (0, 1)),
        notice_version INTEGER NOT NULL DEFAULT 0,
        decision_at INTEGER,
        origin_schema_version INTEGER,
        updated_at INTEGER NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS observations (
        id TEXT PRIMARY KEY,
        observation_kind TEXT NOT NULL CHECK(observation_kind IN ('session','supervised_run','proxy')),
        source TEXT NOT NULL,
        source_locator TEXT,
        native_session_id TEXT,
        native_event_id TEXT,
        request_id TEXT,
        conversation_family_id TEXT,
        tool TEXT NOT NULL CHECK(tool IN ('codex','claude','proxy')),
        profile_ref TEXT,
        project_ref TEXT,
        model TEXT,
        provider TEXT,
        started_at TEXT,
        observed_at TEXT NOT NULL,
        payload_hash TEXT NOT NULL,
        quality TEXT NOT NULL CHECK(quality IN ('exact','estimated','unavailable')),
        parser_version TEXT NOT NULL,
        parse_status TEXT NOT NULL CHECK(parse_status IN ('parsed','partial','unknown','rejected')),
        raw_ref TEXT,
        http_status INTEGER,
        latency_ms INTEGER,
        ttft_ms INTEGER,
        recorded_cost_minor INTEGER,
        recorded_cost_currency TEXT,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS usage_records (
        id TEXT PRIMARY KEY,
        observation_id TEXT NOT NULL REFERENCES observations(id),
        dedup_key TEXT NOT NULL UNIQUE,
        event_kind TEXT NOT NULL CHECK(event_kind IN ('request_delta','request_total','session_total')),
        input_tokens INTEGER CHECK(input_tokens IS NULL OR input_tokens >= 0),
        output_tokens INTEGER CHECK(output_tokens IS NULL OR output_tokens >= 0),
        cache_read_tokens INTEGER CHECK(cache_read_tokens IS NULL OR cache_read_tokens >= 0),
        cache_creation_tokens INTEGER CHECK(cache_creation_tokens IS NULL OR cache_creation_tokens >= 0),
        reasoning_tokens INTEGER CHECK(reasoning_tokens IS NULL OR reasoning_tokens >= 0),
        total_tokens INTEGER CHECK(total_tokens IS NULL OR total_tokens >= 0),
        counter_scope TEXT NOT NULL,
        counter_baseline TEXT,
        counter_reset INTEGER NOT NULL DEFAULT 0 CHECK(counter_reset IN (0,1)),
        event_at TEXT,
        recorded_at TEXT NOT NULL,
        source TEXT NOT NULL,
        quality TEXT NOT NULL,
        parser_version TEXT NOT NULL,
        merge_status TEXT NOT NULL DEFAULT 'primary',
        conflict_group_id TEXT,
        supersedes_id TEXT REFERENCES usage_records(id),
        recorded_cost_minor INTEGER,
        estimated_cost_minor INTEGER,
        currency TEXT,
        pricing_snapshot_id TEXT,
        cost_reason TEXT,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS daily_rollups (
        bucket_date TEXT NOT NULL, timezone TEXT NOT NULL,
        bucket_start_utc TEXT NOT NULL, bucket_end_utc TEXT NOT NULL,
        tool TEXT, profile_ref TEXT, project_ref TEXT, model TEXT, provider TEXT,
        source TEXT NOT NULL, quality TEXT NOT NULL,
        request_count INTEGER, input_tokens INTEGER, output_tokens INTEGER,
        cache_read_tokens INTEGER, cache_creation_tokens INTEGER,
        recorded_cost_minor INTEGER, estimated_cost_minor INTEGER, currency TEXT,
        source_watermark TEXT NOT NULL, rollup_version TEXT NOT NULL, rebuilt_at TEXT NOT NULL,
        data_revision TEXT, build_id TEXT,
        PRIMARY KEY(bucket_date, timezone, tool, profile_ref, project_ref, model, provider, source, rollup_version)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS pricing_snapshots (
        id TEXT PRIMARY KEY, source_id TEXT NOT NULL, source_kind TEXT NOT NULL,
        model_key TEXT NOT NULL, provider TEXT NOT NULL,
        input_price_per_million REAL, output_price_per_million REAL,
        cache_read_price_per_million REAL, cache_creation_price_per_million REAL,
        currency TEXT, unit TEXT NOT NULL, effective_at TEXT, published_at TEXT,
        source_updated_at TEXT, imported_at TEXT NOT NULL, observed_at TEXT NOT NULL,
        parser_version TEXT NOT NULL, trust_state TEXT NOT NULL, validation_status TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS rollup_invalidations (
        id TEXT PRIMARY KEY, bucket_date TEXT NOT NULL, timezone TEXT NOT NULL,
        reason TEXT NOT NULL, min_observed_at TEXT, max_observed_at TEXT,
        status TEXT NOT NULL DEFAULT 'pending', created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS observation_links (
        id TEXT PRIMARY KEY, source_observation_id TEXT NOT NULL REFERENCES observations(id),
        target_observation_id TEXT NOT NULL REFERENCES observations(id),
        link_kind TEXT NOT NULL, confidence TEXT NOT NULL, details_json TEXT,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS rebuild_jobs (
        id TEXT PRIMARY KEY, scope TEXT NOT NULL, status TEXT NOT NULL,
        requested_at TEXT NOT NULL, started_at TEXT, completed_at TEXT,
        checkpoint TEXT, error TEXT, audit_json TEXT,
        current_phase TEXT NOT NULL DEFAULT 'queued', processed_items INTEGER NOT NULL DEFAULT 0,
        total_items INTEGER NOT NULL DEFAULT 0, progress_percent REAL NOT NULL DEFAULT 0,
        options_json TEXT, parser_version TEXT NOT NULL DEFAULT 'current'
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS cc_switch_audit (
        id TEXT PRIMARY KEY, observed_at TEXT NOT NULL, db_identity TEXT,
        status TEXT NOT NULL, user_version INTEGER, capabilities_json TEXT,
        message TEXT, action TEXT NOT NULL
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
    """Open the Workbench database, running schema migration only when the on-disk
    schema_version does not already match SCHEMA_VERSION.

    Every call used to re-run the full DDL list plus a schema_meta upsert, even when
    nothing needed to change. Under concurrent requests (e.g. a scan holding a write
    transaction while another request opens a fresh connection), that guaranteed write
    on every connection could collide and surface as `sqlite3.OperationalError:
    database is locked`. Migration now runs at most once per schema version bump;
    ordinary connections after that only set pragmas and return.
    """
    target = path or default_workbench_paths().db_path
    database_existed = target.exists()
    target.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(target, timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    # WAL mode lets readers (e.g. session detail lookups) proceed against a
    # consistent snapshot while a writer (e.g. an in-progress scan) holds its
    # transaction open, instead of blocking on the writer's lock. This is a
    # database-level setting that persists across connections once applied;
    # re-issuing it on every connect is a cheap no-op when already active.
    conn.execute("PRAGMA journal_mode = WAL")

    existing_tables = _table_names(conn)
    origin_schema_version = _read_schema_version(conn, existing_tables)
    if origin_schema_version == SCHEMA_VERSION:
        _ensure_statistics_schema(conn)
        return conn

    old_fts_count = _read_fts_count(conn, existing_tables)
    is_new_instance = not database_existed or not (
        "schema_meta" in existing_tables or existing_tables.intersection(LEGACY_BUSINESS_TABLES)
    )
    for stmt in DDL:
        conn.execute(stmt)
    _initialize_fts_settings(
        conn,
        is_new_instance=is_new_instance,
        origin_schema_version=origin_schema_version,
        old_fts_count=old_fts_count,
    )
    conn.execute(
        "INSERT INTO schema_meta(key, value) VALUES('schema_version', ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (str(SCHEMA_VERSION),),
    )
    _ensure_column(conn, "source_checkpoints", "missing_since", "INTEGER")
    _ensure_column(conn, "source_checkpoints", "status", "TEXT NOT NULL DEFAULT 'active'")
    conn.commit()
    return conn


def _ensure_statistics_schema(conn: sqlite3.Connection) -> None:
    """Install additive Phase 2 tables for databases already at schema v2."""
    for stmt in DDL[-9:]:
        conn.execute(stmt)
    for column, definition in (
        ("recorded_cost_minor", "INTEGER"),
        ("estimated_cost_minor", "INTEGER"),
        ("currency", "TEXT"),
        ("pricing_snapshot_id", "TEXT"),
        ("cost_reason", "TEXT"),
    ):
        _ensure_column(conn, "usage_records", column, definition)
    _ensure_column(conn, "daily_rollups", "data_revision", "TEXT")
    _ensure_column(conn, "daily_rollups", "build_id", "TEXT")
    for column, definition in (("http_status", "INTEGER"), ("latency_ms", "INTEGER"), ("ttft_ms", "INTEGER"), ("recorded_cost_minor", "INTEGER"), ("recorded_cost_currency", "TEXT")):
        _ensure_column(conn, "observations", column, definition)
    for column, definition in (("current_phase", "TEXT NOT NULL DEFAULT 'queued'"), ("processed_items", "INTEGER NOT NULL DEFAULT 0"), ("total_items", "INTEGER NOT NULL DEFAULT 0"), ("progress_percent", "REAL NOT NULL DEFAULT 0")):
        _ensure_column(conn, "rebuild_jobs", column, definition)
    _ensure_column(conn, "rebuild_jobs", "options_json", "TEXT")
    _ensure_column(conn, "rebuild_jobs", "parser_version", "TEXT NOT NULL DEFAULT 'current'")


def row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {key: row[key] for key in row.keys()}


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    """Add one column to an existing table when an older schema does not have it."""
    columns = {row["name"] for row in conn.execute(f'PRAGMA table_info("{table}")').fetchall()}
    if column not in columns:
        conn.execute(f'ALTER TABLE "{table}" ADD COLUMN {column} {definition}')


def _table_names(conn: sqlite3.Connection) -> set[str]:
    """Return the user-defined table names present before schema migration."""
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type IN ('table', 'view') AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    return {row["name"] for row in rows}


def _read_schema_version(conn: sqlite3.Connection, tables: set[str]) -> int | None:
    """Read the pre-migration schema version, returning None for missing or invalid metadata."""
    if "schema_meta" not in tables:
        return None
    row = conn.execute("SELECT value FROM schema_meta WHERE key = 'schema_version'").fetchone()
    if row is None:
        return None
    try:
        return int(row["value"])
    except (TypeError, ValueError):
        return None


def _read_fts_count(conn: sqlite3.Connection, tables: set[str]) -> int:
    """Count legacy FTS rows without creating, clearing, or rebuilding the index."""
    if "events_fts" not in tables:
        return 0
    return int(conn.execute("SELECT count(*) AS count FROM events_fts").fetchone()["count"])


def _initialize_fts_settings(
    conn: sqlite3.Connection,
    *,
    is_new_instance: bool,
    origin_schema_version: int | None,
    old_fts_count: int,
) -> None:
    """Create the singleton consent row while preserving observable legacy FTS behavior."""
    if conn.execute("SELECT 1 FROM fts_settings WHERE id = 1").fetchone() is not None:
        return
    now = int(time.time())
    if is_new_instance:
        values = ("recommended_pending", 0, 0, None, None, now)
    else:
        values = (
            "legacy_preserved",
            1 if old_fts_count > 0 else 0,
            0,
            None,
            origin_schema_version,
            now,
        )
    conn.execute(
        """
        INSERT INTO fts_settings(
            id, consent_state, indexing_enabled, notice_version,
            decision_at, origin_schema_version, updated_at
        )
        VALUES(1, ?, ?, ?, ?, ?, ?)
        """,
        values,
    )
