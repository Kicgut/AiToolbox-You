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
_capability_cache: dict[str, tuple[float, str, CcSwitchSchemaProbe]] = {}


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


def capability_report(path: Path) -> dict:
    """Return a versioned, redacted capability matrix for UI and audit use."""
    probe = cached_probe_cc_switch_schema(path)
    if probe.status == "missing":
        return {"status": "not_installed", "native_baseline": "available", "supported_fields": [], "unavailable_fields": list(CAPABILITY_FIELDS), "pricing": "inactive"}
    if probe.status != "available":
        return {"status": "corrupt", "native_baseline": "available", "supported_fields": [], "unavailable_fields": list(CAPABILITY_FIELDS), "pricing": "inactive"}
    if probe.user_version is not None and probe.user_version > 16:
        status = "incompatible"
    else:
        status = "available"
    columns = set(probe.tables.get("proxy_request_logs", []))
    supported = [field for field in CAPABILITY_FIELDS if field in columns]
    return {"status": status, "schema_version": probe.user_version, "native_baseline": "available", "supported_fields": supported, "unavailable_fields": [field for field in CAPABILITY_FIELDS if field not in supported], "pricing": "inactive", "read_only": True}


def _identity(path: Path) -> str:
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
            side_stat = sidecar.stat(); sidecars.append(f"{suffix}|{side_stat.st_size}|{side_stat.st_mtime_ns}")
        else:
            sidecars.append(f"{suffix}|missing")
    return hashlib.sha256(f"{path.resolve()}|{stat.st_size}|{stat.st_mtime_ns}|{'/'.join(sidecars)}".encode() + head + tail).hexdigest()


def read_proxy_request_logs(path: Path, *, limit: int = 100, since_id: str | None = None, expected_db_identity: str | None = None) -> dict:
    """Read approved proxy telemetry without opening a writable SQLite handle."""
    probe = cached_probe_cc_switch_schema(path)
    if probe.status != "available":
        return {"status": "not_installed" if probe.status == "missing" else "corrupt" if probe.status == "error" else "incompatible", "data": [], "message": probe.message}
    if probe.user_version is not None and probe.user_version > 16:
        return {"status": "incompatible", "data": [], "message": "future schema requires capability review", "user_version": probe.user_version}
    current_identity = _identity(path)
    if expected_db_identity and expected_db_identity != current_identity:
        return {"status": "replaced", "data": [], "cursor_invalidated": True, "db_identity": current_identity, "message": "database identity changed; restart from a fresh cursor"}
    columns = [c for c in probe.tables.get("proxy_request_logs", []) if c in ALLOWED_PROXY_COLUMNS]
    if "id" not in columns or not columns:
        return {"status": "incompatible", "data": [], "message": "proxy telemetry columns unavailable"}
    uri = f"file:{path.resolve().as_posix()}?mode=ro"
    try:
        with sqlite3.connect(uri, uri=True, timeout=0.5) as conn:
            conn.execute("PRAGMA busy_timeout = 500")
            quoted = ", ".join('"' + c.replace('"', '""') + '"' for c in columns)
            sql = f'SELECT {quoted} FROM "proxy_request_logs"'
            args: list = []
            if since_id and "id" in columns:
                sql += ' WHERE "id" > ?'; args.append(since_id)
            sql += ' ORDER BY "id" LIMIT ?'; args.append(min(max(limit, 1), 1000))
            rows = conn.execute(sql, args).fetchall()
            # Re-read the schema inside the same read lifecycle. If a third
            # party replacement/update raced this query, discard the batch.
            after_probe = probe_cc_switch_schema(path)
            if after_probe.user_version != probe.user_version or after_probe.tables.get("proxy_request_logs") != probe.tables.get("proxy_request_logs"):
                return {"status": "replaced", "data": [], "cursor_invalidated": True, "db_identity": _identity(path), "message": "schema changed during read"}
            data = []; rejected = 0
            for row in rows:
                item = dict(zip(columns, row))
                invalid = any(item.get(field) is not None and (not isinstance(item[field], (int, float)) or item[field] < 0 or item[field] > 10**15) for field in ("latency_ms", "ttft_ms", "recorded_cost_minor"))
                if invalid:
                    rejected += 1
                else:
                    data.append(item)
            return {"status": "available", "data": data, "rejected_count": rejected, "cursor": rows[-1][columns.index("id")] if rows else since_id, "db_identity": current_identity, "observed_at": time.time()}
    except sqlite3.OperationalError as exc:
        status = "busy" if "locked" in str(exc).lower() or "busy" in str(exc).lower() else "corrupt"
        return {"status": status, "data": [], "message": "database temporarily unavailable" if status == "busy" else "database unreadable"}


def read_pricing_candidates(path: Path, *, enabled: bool = False, limit: int = 100) -> dict:
    """Return validated candidates; CC Switch pricing is never active by default."""
    if not enabled:
        return {"status": "disabled", "data": [], "reason_code": "pricing_source_disabled"}
    probe = cached_probe_cc_switch_schema(path)
    if probe.status != "available" or "model_pricing" not in probe.tables:
        return {"status": "incompatible", "data": [], "reason_code": "model_pricing_unavailable"}
    if probe.user_version is not None and probe.user_version > 16:
        return {"status": "incompatible", "data": [], "reason_code": "future_schema"}
    columns = [c for c in probe.tables["model_pricing"] if c in ALLOWED_PRICING_COLUMNS]
    required = {"model", "currency", "unit", "effective_at", "input_price_per_million", "output_price_per_million"}
    if not required <= set(columns):
        return {"status": "incompatible", "data": [], "reason_code": "pricing_semantics_incomplete"}
    uri = f"file:{path.resolve().as_posix()}?mode=ro"
    try:
        with sqlite3.connect(uri, uri=True, timeout=0.5) as conn:
            conn.execute("PRAGMA busy_timeout = 500")
            quoted = ", ".join('"' + c + '"' for c in columns)
            rows = conn.execute(f'SELECT {quoted} FROM "model_pricing" LIMIT ?', (min(max(limit, 1), 1000),)).fetchall()
            valid = []
            for row in rows:
                item = dict(zip(columns, row))
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
        return CcSwitchSchemaProbe(status="error", path=path, message=str(exc))

    try:
        user_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        table_rows = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()
        tables: dict[str, list[str]] = {}
        for (table_name,) in table_rows:
            escaped = table_name.replace('"', '""')
            columns = [row[1] for row in connection.execute(f'PRAGMA table_info("{escaped}")').fetchall()]
            tables[table_name] = columns
    except sqlite3.Error as exc:
        return CcSwitchSchemaProbe(status="error", path=path, message=str(exc))
    finally:
        connection.close()

    return CcSwitchSchemaProbe(status="available", path=path, user_version=user_version, tables=tables)
