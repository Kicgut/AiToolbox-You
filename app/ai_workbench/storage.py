from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 5
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


BASE_DDL = [
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

PHASE2_STATISTICS_DDL = [
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
        reasoning_tokens INTEGER, total_tokens INTEGER,
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

PHASE3_EXECUTION_DDL = [
    """
    CREATE TABLE IF NOT EXISTS runs (
        id TEXT PRIMARY KEY, tool TEXT NOT NULL CHECK(tool IN ('codex', 'claude')),
        client_request_id TEXT, request_body_hash TEXT,
        profile_id TEXT NOT NULL, session_copy_id TEXT, source_native_session_id TEXT,
        native_session_id TEXT, native_thread_id TEXT,
        provider TEXT, account_ref TEXT, model TEXT, project_id TEXT, cwd TEXT,
        mode TEXT NOT NULL CHECK(mode IN ('new', 'resume', 'fork')),
        execution_path TEXT NOT NULL CHECK(execution_path IN ('codex_app_server', 'codex_exec', 'claude_step_process')),
        permission_policy_json TEXT NOT NULL, budget_policy_json TEXT NOT NULL,
        capabilities_snapshot_json TEXT NOT NULL DEFAULT '{}',
        dispatch_state TEXT NOT NULL DEFAULT 'not_started', dispatch_committed_at TEXT,
        runtime_instance_id TEXT, lease_generation INTEGER, cancel_requested_at TEXT,
        retry_of_run_id TEXT, retry_of_step_id TEXT,
        state TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL DEFAULT '', started_at TEXT,
        finished_at TEXT, last_sequence_no INTEGER NOT NULL DEFAULT 0,
        failure_code TEXT, failure_message TEXT, config_snapshot_json TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS run_steps (
        id TEXT PRIMARY KEY, run_id TEXT NOT NULL, ordinal INTEGER NOT NULL,
        prompt_text TEXT NOT NULL, state TEXT NOT NULL, native_turn_id TEXT,
        started_at TEXT, finished_at TEXT, timeout_ms INTEGER, usage_event_id TEXT,
        error_code TEXT, error_message TEXT, continue_on_error INTEGER NOT NULL DEFAULT 0,
        attempt_no INTEGER NOT NULL DEFAULT 1, UNIQUE(run_id, ordinal),
        FOREIGN KEY(run_id) REFERENCES runs(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS approval_requests (
        id TEXT PRIMARY KEY, run_id TEXT NOT NULL, step_id TEXT NOT NULL,
        native_request_id TEXT NOT NULL, operation TEXT NOT NULL,
        target_summary TEXT NOT NULL, risk_level TEXT NOT NULL,
        command_argv_json TEXT, cwd TEXT, affected_paths_json TEXT, network_targets_json TEXT, reason TEXT,
        expires_at TEXT, state TEXT NOT NULL, decision TEXT,
        decided_at TEXT, decided_by TEXT, disconnect_policy TEXT NOT NULL DEFAULT 'wait',
        FOREIGN KEY(run_id) REFERENCES runs(id), FOREIGN KEY(step_id) REFERENCES run_steps(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS run_events (
        event_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, step_id TEXT, session_id TEXT,
        sequence_no INTEGER NOT NULL, event_type TEXT NOT NULL, timestamp TEXT NOT NULL,
        payload_json TEXT NOT NULL, source_tool TEXT NOT NULL, source_event_type TEXT,
        raw_json TEXT, persisted_at TEXT NOT NULL, UNIQUE(run_id, sequence_no),
        FOREIGN KEY(run_id) REFERENCES runs(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS run_stream_cursors (
        run_id TEXT PRIMARY KEY, next_sequence_no INTEGER NOT NULL,
        last_persisted_sequence_no INTEGER NOT NULL,
        last_broadcast_sequence_no INTEGER NOT NULL, updated_at TEXT NOT NULL,
        FOREIGN KEY(run_id) REFERENCES runs(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS session_writer_leases (
        physical_session_key TEXT PRIMARY KEY, run_id TEXT NOT NULL, owner_id TEXT NOT NULL,
        acquired_at TEXT NOT NULL, heartbeat_at TEXT NOT NULL, expires_at TEXT NOT NULL,
        lease_generation INTEGER NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS run_artifacts (
        id TEXT PRIMARY KEY, run_id TEXT NOT NULL, step_id TEXT,
        kind TEXT NOT NULL, relative_path TEXT NOT NULL, sha256 TEXT NOT NULL,
        size_bytes INTEGER NOT NULL, mime_type TEXT, redaction_state TEXT NOT NULL,
        created_at TEXT NOT NULL, expires_at TEXT,
        FOREIGN KEY(run_id) REFERENCES runs(id), FOREIGN KEY(step_id) REFERENCES run_steps(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS runtime_capability_baselines (
        id INTEGER PRIMARY KEY AUTOINCREMENT, observed_at TEXT NOT NULL,
        payload_json TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS real_execution_authorizations (
        nonce_hash TEXT PRIMARY KEY, mode TEXT NOT NULL CHECK(mode IN ('p3_10')),
        request_body_hash TEXT NOT NULL, allowed_tools_json TEXT NOT NULL,
        model TEXT, budget_policy_json TEXT NOT NULL, max_uses INTEGER NOT NULL,
        consumed_uses INTEGER NOT NULL DEFAULT 0, expires_at TEXT NOT NULL,
        created_at TEXT NOT NULL, consumed_at TEXT
    )
    """,
]

DDL = BASE_DDL + PHASE2_STATISTICS_DDL + PHASE3_EXECUTION_DDL


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
        # The version marker is written only after every additive migration
        # commits.  Do not run CREATE/UPDATE repair statements here: opening a
        # read connection must remain possible while a scanner owns SQLite's
        # single writer slot.
        required_tables = {
            "observations", "usage_records", "daily_rollups", "pricing_snapshots",
            "runs", "run_steps", "approval_requests", "run_events", "run_stream_cursors",
            "session_writer_leases", "run_artifacts", "runtime_capability_baselines",
            "real_execution_authorizations",
        }
        if required_tables.issubset(existing_tables):
            return conn
        # A manually damaged/test fixture database can report the latest
        # version while missing a CREATE IF NOT EXISTS table.  Repair only
        # that exceptional case; ordinary concurrent readers stay read-only.
        _ensure_statistics_schema(conn)
        _ensure_phase3_schema(conn)
        conn.commit()
        return conn

    old_fts_count = _read_fts_count(conn, existing_tables)
    is_new_instance = not database_existed or not (
        "schema_meta" in existing_tables or existing_tables.intersection(LEGACY_BUSINESS_TABLES)
    )
    for stmt in DDL:
        conn.execute(stmt)
    # Apply additive Phase 2 columns on both new and pre-existing schema paths.
    # The full DDL is intentionally CREATE IF NOT EXISTS, so it cannot alter an
    # already-created daily_rollups table by itself.
    _ensure_statistics_schema(conn)
    _ensure_phase3_schema(conn)
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


def _ensure_phase3_schema(conn: sqlite3.Connection) -> None:
    """Create the additive Phase 3 execution tables on every schema path."""
    for stmt in PHASE3_EXECUTION_DDL:
        conn.execute(stmt)
    for column, definition in (
        ("client_request_id", "TEXT"),
        ("request_body_hash", "TEXT"),
        ("source_native_session_id", "TEXT"),
        ("native_thread_id", "TEXT"),
        ("capabilities_snapshot_json", "TEXT NOT NULL DEFAULT '{}'"),
        ("dispatch_state", "TEXT NOT NULL DEFAULT 'not_started'"),
        ("dispatch_committed_at", "TEXT"),
        ("runtime_instance_id", "TEXT"),
        ("lease_generation", "INTEGER"),
        ("cancel_requested_at", "TEXT"),
        ("retry_of_run_id", "TEXT"),
        ("retry_of_step_id", "TEXT"),
        ("updated_at", "TEXT"),
    ):
        _ensure_column(conn, "runs", column, definition)
    conn.execute("UPDATE runs SET updated_at=created_at WHERE updated_at IS NULL")
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_runs_client_request ON runs(client_request_id) WHERE client_request_id IS NOT NULL")
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_runs_request_body ON runs(client_request_id, request_body_hash) WHERE client_request_id IS NOT NULL")
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_approval_native_request ON approval_requests(run_id, native_request_id)")
    _ensure_column(conn, "approval_requests", "network_targets_json", "TEXT")


RUN_TERMINAL_STATES = {"succeeded", "failed", "cancelled", "interrupted"}
RUN_TRANSITIONS = {
    "queued": {"starting", "cancelled"},
    "starting": {"running", "cancel_requested", "failed", "interrupted"},
    "running": {"waiting_approval", "cancel_requested", "succeeded", "failed", "interrupted"},
    "waiting_approval": {"running", "cancel_requested", "failed", "interrupted"},
    "cancel_requested": {"cancelling", "succeeded", "interrupted"},
    "cancelling": {"cancelled", "failed", "interrupted"},
}


def validate_run_transition(current_state: str, proposed_state: str) -> None:
    """Validate one run state transition, raising ValueError for illegal edges."""
    if proposed_state not in RUN_TRANSITIONS.get(current_state, set()):
        raise ValueError(f"illegal run state transition: {current_state} -> {proposed_state}")


class RunTransitionConflict(RuntimeError):
    """The durable state changed after a coordinator path observed it."""


def compare_and_set_run_state(conn: sqlite3.Connection, *, run_id: str, expected_state: str,
                              proposed_state: str, updates: dict[str, object]) -> None:
    """Apply one already-validated state transition without a lost update.

    Callers own the surrounding SQLite transaction so the state event and run
    mutation remain one atomic fact.
    """
    if expected_state != proposed_state:
        validate_run_transition(expected_state, proposed_state)
    assignments = [f"{column}=?" for column in updates]
    values = [*updates.values(), proposed_state, run_id, expected_state]
    cursor = conn.execute(
        f"UPDATE runs SET {', '.join(assignments)}, state=? WHERE id=? AND state=?", values
    )
    if cursor.rowcount != 1:
        raise RunTransitionConflict(f"run state changed before transition: {run_id}")


class SessionBusyError(RuntimeError):
    """Raised when another non-expired run owns a physical session writer lease."""

    code = "session_busy"


def acquire_writer_lease(conn: sqlite3.Connection, *, physical_session_key: str, run_id: str,
                         owner_id: str, now: str, expires_at: str, transactional: bool = True) -> int:
    """Acquire or take over an expired writer lease and return its generation."""
    if transactional:
        conn.execute("BEGIN IMMEDIATE")
    try:
        row = conn.execute("SELECT * FROM session_writer_leases WHERE physical_session_key = ?",
                           (physical_session_key,)).fetchone()
        if row is not None and row["expires_at"] >= now and row["run_id"] != run_id:
            raise SessionBusyError("session_busy")
        generation = (int(row["lease_generation"]) + 1) if row is not None else 1
        conn.execute("""INSERT INTO session_writer_leases
            (physical_session_key, run_id, owner_id, acquired_at, heartbeat_at, expires_at, lease_generation)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(physical_session_key) DO UPDATE SET run_id=excluded.run_id,
            owner_id=excluded.owner_id, acquired_at=excluded.acquired_at,
            heartbeat_at=excluded.heartbeat_at, expires_at=excluded.expires_at,
            lease_generation=excluded.lease_generation""",
            (physical_session_key, run_id, owner_id, now, now, expires_at, generation))
        if transactional:
            conn.commit()
        return generation
    except Exception:
        if transactional:
            conn.rollback()
        raise


def heartbeat_writer_lease(conn: sqlite3.Connection, *, physical_session_key: str,
                           run_id: str, lease_generation: int, heartbeat_at: str,
                           expires_at: str) -> None:
    """Extend a lease only when its run and generation still own it."""
    cur = conn.execute("""UPDATE session_writer_leases SET heartbeat_at=?, expires_at=?
        WHERE physical_session_key=? AND run_id=? AND lease_generation=?""",
        (heartbeat_at, expires_at, physical_session_key, run_id, lease_generation))
    conn.commit()
    if cur.rowcount != 1:
        raise SessionBusyError("session_busy")


def release_writer_lease(conn: sqlite3.Connection, *, physical_session_key: str,
                         run_id: str, lease_generation: int) -> bool:
    """Release a lease only for its current run and generation.

    The boolean result makes a stale generation observable to callers instead
    of silently treating a lost lease as a successful release.
    """
    cur = conn.execute("""DELETE FROM session_writer_leases
        WHERE physical_session_key=? AND run_id=? AND lease_generation=?""",
        (physical_session_key, run_id, lease_generation))
    conn.commit()
    return cur.rowcount == 1


def _ensure_statistics_schema(conn: sqlite3.Connection) -> None:
    """Install additive Phase 2 tables for databases already at schema v2."""
    for stmt in PHASE2_STATISTICS_DDL:
        conn.execute(stmt)
    for column, definition in (
        ("recorded_cost_minor", "INTEGER"),
        ("estimated_cost_minor", "INTEGER"),
        ("currency", "TEXT"),
        ("pricing_snapshot_id", "TEXT"),
        ("cost_reason", "TEXT"),
    ):
        _ensure_column(conn, "usage_records", column, definition)
    _ensure_column(conn, "observations", "native_turn_id", "TEXT")
    _ensure_column(conn, "daily_rollups", "data_revision", "TEXT")
    _ensure_column(conn, "daily_rollups", "build_id", "TEXT")
    _ensure_column(conn, "daily_rollups", "reasoning_tokens", "INTEGER")
    _ensure_column(conn, "daily_rollups", "total_tokens", "INTEGER")
    for column, kind in {
        "recorded_actual_source": "TEXT", "recorded_actual_quality": "TEXT",
        "estimate_source": "TEXT", "estimate_quality": "TEXT", "pricing_snapshot_id": "TEXT",
        "pricing_effective_at": "TEXT", "estimate_formula": "TEXT", "merge_status": "TEXT",
        "conflict_group_id": "TEXT", "parser_version": "TEXT", "recorded_actual_currency": "TEXT",
        "estimate_currency": "TEXT",
    }.items():
        _ensure_column(conn, "daily_rollups", column, kind)
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
