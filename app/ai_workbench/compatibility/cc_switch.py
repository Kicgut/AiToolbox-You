from __future__ import annotations

import sqlite3
import hashlib
import time
import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class CcSwitchSchemaProbe:
    status: str
    path: Path
    user_version: int | None = None
    tables: dict[str, list[str]] = field(default_factory=dict)
    message: str | None = None

    @property
    def supports_proxy_request_logs(self) -> bool:
        return "proxy_request_logs" in self.tables


ALLOWED_PROXY_COLUMNS = frozenset({"id", "request_id", "model", "provider", "status", "latency_ms", "ttft_ms", "recorded_cost_minor", "created_at"})
ALLOWED_PRICING_COLUMNS = frozenset({"id", "model", "provider", "input_price_per_million", "output_price_per_million", "cache_read_price_per_million", "cache_creation_price_per_million", "currency", "unit", "effective_at", "updated_at"})
CAPABILITY_FIELDS = ("request_id", "model", "provider", "status", "latency_ms", "ttft_ms", "recorded_cost_minor")
CAPABILITY_CACHE_TTL_SECONDS = 60.0
CONNECTOR_STATUSES = frozenset({"not_installed", "disabled", "available", "busy", "corrupt", "incompatible", "replaced"})
CC_SWITCH_FIXTURE_EXPECTATIONS = {
    "v10": {"supported": {"model", "status"}, "native_baseline": True, "pricing": "inactive"},
    "v16": {"supported": {"request_id", "provider", "ttft_ms"}, "native_baseline": True, "pricing": "inactive"},
    "future": {"supported": set(), "native_baseline": True, "pricing": "inactive"},
}
PRICING_MODEL_ALIASES = {
    "claude-3-5-sonnet": "claude-3-5-sonnet-20241022",
    "gpt-4o-mini": "gpt-4o-mini-2024-07-18",
}
_capability_cache: dict[str, tuple[float, str, CcSwitchSchemaProbe]] = {}


def resolve_pricing_model(model: str, aliases: dict[str, str] | None = None) -> str:
    """Resolve a model through an explicit, auditable alias map."""
    return (aliases or PRICING_MODEL_ALIASES).get(model, model)


def discover_cc_switch_paths(custom: list[Path] | None = None) -> list[Path]:
    """Resolve configured databases in deterministic order and deduplicate paths."""
    candidates = list(custom or [])
    env_path = os.environ.get("CC_SWITCH_DB")
    if env_path:
        candidates.append(Path(env_path).expanduser())
    candidates.append(Path.home() / ".cc-switch" / "cc-switch.db")
    result: list[Path] = []; seen: set[str] = set()
    for path in candidates:
        key = str(path.expanduser().resolve()).casefold()
        if key not in seen:
            seen.add(key); result.append(path.expanduser())
    return result


def cached_probe_cc_switch_schema(path: Path, *, force: bool = False) -> CcSwitchSchemaProbe:
    key = str(path.expanduser().resolve()).casefold()
    try:
        identity = _identity(path) if path.exists() else "missing"
    except OSError:
        identity = "unreadable"
    cached = _capability_cache.get(key)
    if not force and cached and cached[0] > time.monotonic() and cached[1] == identity:
        return cached[2]
    result = probe_cc_switch_schema(path)
    _capability_cache[key] = (time.monotonic() + CAPABILITY_CACHE_TTL_SECONDS, identity, result)
    return result


def capability_report(path: Path, *, enabled: bool = True) -> dict:
    """Return a versioned, redacted capability matrix for UI and audit use."""
    if not enabled:
        return {"status": "disabled", "native_baseline": "available", "supported_fields": [], "unavailable_fields": list(CAPABILITY_FIELDS), "pricing": "inactive", "read_only": True, "reason_code": "connector_disabled"}
    probe = cached_probe_cc_switch_schema(path)
    if probe.status == "missing":
        return {"status": "not_installed", "native_baseline": "available", "supported_fields": [], "unavailable_fields": list(CAPABILITY_FIELDS), "pricing": "inactive"}
    if probe.status != "available":
        status = "busy" if probe.status == "busy" else "corrupt"
        return {"status": status, "native_baseline": "available", "supported_fields": [], "unavailable_fields": list(CAPABILITY_FIELDS), "pricing": "inactive", "reason_code": probe.message, "read_only": True}
    if probe.user_version is not None and probe.user_version > 16:
        status = "incompatible"
    else:
        status = "available"
    columns = set(probe.tables.get("proxy_request_logs", []))
    supported = [field for field in CAPABILITY_FIELDS if field in columns]
    return {"status": status, "schema_version": probe.user_version, "native_baseline": "available", "supported_fields": supported, "unavailable_fields": [field for field in CAPABILITY_FIELDS if field not in supported], "pricing": "inactive", "read_only": True}


def _identity(path: Path) -> str:
    """Hash bounded main/sidecar bytes plus file metadata for replacement detection."""
    stat = path.stat()
    with path.open("rb") as handle:
        size = stat.st_size
        head = handle.read(min(size, 4096))
        tail = b""
        if size > 4096:
            handle.seek(max(0, size - 4096)); tail = handle.read(4096)
    sidecars = []
    for suffix in ("-wal", "-shm", "-journal"):
        sidecar = Path(str(path) + suffix)
        if sidecar.exists():
            side_stat = sidecar.stat()
            with sidecar.open("rb") as handle:
                side_size = side_stat.st_size
                side_head = handle.read(min(side_size, 4096))
                side_tail = b""
                if side_size > 4096:
                    handle.seek(max(0, side_size - 4096)); side_tail = handle.read(4096)
            sidecars.append((f"{suffix}|{side_size}|{side_stat.st_mtime_ns}").encode() + side_head + side_tail)
        else:
            sidecars.append(f"{suffix}|missing".encode())
    return hashlib.sha256(f"{path.resolve()}|{stat.st_size}|{stat.st_mtime_ns}".encode() + head + tail + b"".join(sidecars)).hexdigest()


def read_proxy_request_logs(path: Path, *, limit: int = 100, since_id: str | None = None, expected_db_identity: str | None = None) -> dict:
    """Read approved proxy telemetry without opening a writable SQLite handle."""
    try:
        exists = path.exists()
    except OSError:
        return {"status": "corrupt", "data": [], "message": "database is unreadable"}
    if not exists:
        return {"status": "not_installed", "data": [], "message": "database not found"}
    try:
        current_identity = _identity(path)
    except OSError:
        return {"status": "corrupt", "data": [], "message": "database is unreadable"}
    if expected_db_identity and expected_db_identity != current_identity:
        return {"status": "replaced", "data": [], "cursor_invalidated": True, "db_identity": current_identity, "message": "database identity changed; restart from a fresh cursor"}
    uri = f"file:{path.resolve().as_posix()}?mode=ro"
    try:
        with sqlite3.connect(uri, uri=True, timeout=0.5) as conn:
            conn.execute("PRAGMA busy_timeout = 500")
            conn.execute("BEGIN")
            transaction_probe = _probe_connection(conn, path)
            if transaction_probe.status != "available":
                return {"status": transaction_probe.status, "data": [], "message": transaction_probe.message}
            if transaction_probe.user_version is not None and transaction_probe.user_version > 16:
                return {"status": "incompatible", "data": [], "message": "future schema requires capability review", "user_version": transaction_probe.user_version}
            probe = transaction_probe
            transaction_columns = [c for c in transaction_probe.tables.get("proxy_request_logs", []) if c in ALLOWED_PROXY_COLUMNS]
            if "id" not in transaction_columns:
                return {"status": "incompatible", "data": [], "message": "proxy telemetry columns unavailable"}
            quoted = ", ".join('"' + c.replace('"', '""') + '"' for c in transaction_columns)
            sql = f'SELECT {quoted} FROM "proxy_request_logs"'
            args: list = []
            if since_id and "id" in transaction_columns:
                sql += ' WHERE "id" > ?'; args.append(since_id)
            sql += ' ORDER BY "id" LIMIT ?'; args.append(min(max(limit, 1), 1000))
            rows = conn.execute(sql, args).fetchall()
            # Re-read the schema inside the same read lifecycle. If a third
            # party replacement/update raced this query, discard the batch.
            after_probe = _probe_connection(conn, path)
            if after_probe.user_version != transaction_probe.user_version or after_probe.tables != transaction_probe.tables:
                return {"status": "replaced", "data": [], "cursor_invalidated": True, "db_identity": _identity(path), "message": "schema changed during read"}
            data = []; rejected = 0
            for row in rows:
                item = dict(zip(transaction_columns, row))
                invalid = any(item.get(field) is not None and (not isinstance(item[field], (int, float)) or item[field] < 0 or item[field] > 10**15) for field in ("latency_ms", "ttft_ms", "recorded_cost_minor"))
                if invalid:
                    rejected += 1
                else:
                    data.append(item)
            return {"status": "available", "data": data, "rejected_count": rejected, "cursor": rows[-1][transaction_columns.index("id")] if rows else since_id, "db_identity": current_identity, "observed_at": time.time()}
    except sqlite3.OperationalError as exc:
        status = "busy" if "locked" in str(exc).lower() or "busy" in str(exc).lower() else "corrupt"
        return {"status": status, "data": [], "message": "database temporarily unavailable" if status == "busy" else "database unreadable"}


def read_pricing_candidates(path: Path, *, enabled: bool = False, limit: int = 100) -> dict:
    """Return validated candidates; CC Switch pricing is never active by default."""
    if not enabled:
        return {"status": "disabled", "data": [], "reason_code": "pricing_source_disabled"}
    try:
        exists = path.exists()
    except OSError:
        return {"status": "corrupt", "data": [], "reason_code": "database_unreadable"}
    if not exists:
        return {"status": "not_installed", "data": [], "reason_code": "database_not_found"}
    uri = f"file:{path.resolve().as_posix()}?mode=ro"
    try:
        with sqlite3.connect(uri, uri=True, timeout=0.5) as conn:
            conn.execute("PRAGMA busy_timeout = 500")
            conn.execute("BEGIN")
            transaction_probe = _probe_connection(conn, path)
            if transaction_probe.status != "available":
                return {"status": transaction_probe.status, "data": [], "reason_code": "pricing_schema_unavailable"}
            if transaction_probe.user_version is not None and transaction_probe.user_version > 16:
                return {"status": "incompatible", "data": [], "reason_code": "future_schema"}
            if "model_pricing" not in transaction_probe.tables:
                return {"status": "incompatible", "data": [], "reason_code": "model_pricing_unavailable"}
            transaction_columns = [c for c in transaction_probe.tables["model_pricing"] if c in ALLOWED_PRICING_COLUMNS]
            required = {"model", "currency", "unit", "effective_at", "input_price_per_million", "output_price_per_million"}
            if not required <= set(transaction_columns):
                return {"status": "incompatible", "data": [], "reason_code": "pricing_semantics_incomplete"}
            quoted = ", ".join('"' + c + '"' for c in transaction_columns)
            rows = conn.execute(f'SELECT {quoted} FROM "model_pricing" LIMIT ?', (min(max(limit, 1), 1000),)).fetchall()
            after_probe = _probe_connection(conn, path)
            if after_probe.user_version != transaction_probe.user_version or after_probe.tables != transaction_probe.tables:
                return {"status": "replaced", "data": [], "reason_code": "schema_changed_during_read"}
            valid = []
            for row in rows:
                item = dict(zip(transaction_columns, row))
                if item.get("currency") and item.get("unit") == "per_1m_tokens" and item.get("effective_at") and item.get("input_price_per_million") is not None and item.get("output_price_per_million") is not None:
                    item.update({"source_kind": "cc_switch", "trust_state": "inactive", "validation_status": "valid"})
                    valid.append(item)
            return {"status": "available", "data": valid, "pricing_enabled": False, "reason_code": "candidate_only"}
    except sqlite3.OperationalError:
        return {"status": "busy", "data": [], "reason_code": "database_busy"}


def probe_cc_switch_schema(path: Path) -> CcSwitchSchemaProbe:
    if not path.exists():
        return CcSwitchSchemaProbe(status="missing", path=path, message="database not found")

    uri = f"file:{path.as_posix()}?mode=ro"
    try:
        connection = sqlite3.connect(uri, uri=True, timeout=1.0)
    except sqlite3.Error as exc:
        message = str(exc)
        return CcSwitchSchemaProbe(status="busy" if "locked" in message.lower() or "busy" in message.lower() else "corrupt", path=path, message=message)

    try:
        result = _probe_connection(connection, path)
        return result
    except sqlite3.Error as exc:
        return CcSwitchSchemaProbe(status="corrupt", path=path, message=str(exc))
    finally:
        connection.close()

def _probe_connection(connection: sqlite3.Connection, path: Path) -> CcSwitchSchemaProbe:
    """Read schema capabilities using the caller's already-open read transaction."""
    try:
        user_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        table_rows = connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name").fetchall()
        tables: dict[str, list[str]] = {}
        for (table_name,) in table_rows:
            escaped = table_name.replace('"', '""')
            tables[table_name] = [row[1] for row in connection.execute(f'PRAGMA table_info("{escaped}")').fetchall()]
        return CcSwitchSchemaProbe(status="available", path=path, user_version=user_version, tables=tables)
    except sqlite3.Error as exc:
        message = str(exc)
        return CcSwitchSchemaProbe(status="busy" if "locked" in message.lower() or "busy" in message.lower() else "corrupt", path=path, message=message)
