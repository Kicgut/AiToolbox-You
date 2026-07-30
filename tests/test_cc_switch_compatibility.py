import os
import sqlite3

from app.ai_workbench.compatibility.cc_switch import _identity, cached_probe_cc_switch_schema, discover_cc_switch_paths, read_proxy_request_logs


def test_discovery_deduplicates_custom_env_and_default(tmp_path, monkeypatch):
    path = tmp_path / "cc.db"
    monkeypatch.setenv("CC_SWITCH_DB", str(path))
    paths = discover_cc_switch_paths([path, path])
    assert len([p for p in paths if p.resolve() == path.resolve()]) == 1


def test_cached_probe_invalidates_when_file_changes(tmp_path):
    path = tmp_path / "cc.db"
    with sqlite3.connect(path) as conn:
        conn.execute("PRAGMA user_version=10")
    first = cached_probe_cc_switch_schema(path)
    with path.open("ab") as handle:
        handle.write(b"x")
    second = cached_probe_cc_switch_schema(path)
    assert first.user_version == second.user_version == 10


def test_future_schema_disables_proxy_enhancement(tmp_path):
    path = tmp_path / "cc.db"
    with sqlite3.connect(path) as conn:
        conn.execute("PRAGMA user_version=99")
        conn.execute("CREATE TABLE proxy_request_logs(id TEXT PRIMARY KEY)")
    result = read_proxy_request_logs(path)
    assert result["status"] == "incompatible"


def test_sidecar_or_main_replacement_invalidates_cursor(tmp_path):
    path = tmp_path / "cc.db"
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE proxy_request_logs(id TEXT PRIMARY KEY)")
        conn.execute("INSERT INTO proxy_request_logs VALUES('1')")
    first = read_proxy_request_logs(path)
    path.write_bytes(path.read_bytes() + b" ")
    result = read_proxy_request_logs(path, since_id="1", expected_db_identity=first["db_identity"])
    assert result["status"] == "replaced"
    assert result["cursor_invalidated"] is True


def test_identity_is_sha256_of_normalized_metadata_content_and_sidecar_state(tmp_path):
    path = tmp_path / "cc.db"
    path.write_bytes(b"database")
    identity = _identity(path)
    assert len(identity) == 64
    assert all(char in "0123456789abcdef" for char in identity)
    path.with_name(path.name + "-wal").write_bytes(b"wal")
    assert _identity(path) != identity


def test_sidecar_missing_and_corrupt_are_observable_without_writing(tmp_path):
    path = tmp_path / "cc.db"
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE proxy_request_logs(id TEXT PRIMARY KEY)")
    before = path.read_bytes()
    path.with_name(path.name + "-wal").write_bytes(b"not-a-wal")
    result = read_proxy_request_logs(path)
    assert result["status"] in {"available", "corrupt"}
    assert path.read_bytes() == before


def test_busy_and_incompatible_have_distinct_external_statuses(tmp_path):
    incompatible = tmp_path / "future.db"
    with sqlite3.connect(incompatible) as conn:
        conn.execute("PRAGMA user_version=99")
        conn.execute("CREATE TABLE proxy_request_logs(id TEXT PRIMARY KEY)")
    assert read_proxy_request_logs(incompatible)["status"] == "incompatible"
    locked = tmp_path / "locked.db"
    with sqlite3.connect(locked) as conn:
        conn.execute("CREATE TABLE proxy_request_logs(id TEXT PRIMARY KEY)")
        conn.execute("BEGIN EXCLUSIVE")
        result = read_proxy_request_logs(locked)
    assert result["status"] == "busy"
