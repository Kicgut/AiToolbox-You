import os
import json
import sqlite3

import app.ai_workbench.compatibility.cc_switch as cc_switch
from app.ai_workbench.compatibility.cc_switch import probe_cc_switch_schema, cached_probe_cc_switch_schema


def test_cc_switch_probe_reports_missing_database(tmp_path):
    result = probe_cc_switch_schema(tmp_path / "missing.db")

    assert result.status == "missing"
    assert result.user_version is None


def test_cc_switch_probe_reads_schema_without_writing(tmp_path):
    db_path = tmp_path / "cc-switch.db"
    connection = sqlite3.connect(db_path)
    connection.execute("PRAGMA user_version = 10")
    connection.execute(
        "CREATE TABLE proxy_request_logs (id TEXT PRIMARY KEY, model TEXT, input_tokens INTEGER, total_cost_usd REAL)"
    )
    connection.commit()
    connection.close()
    before_size = os.path.getsize(db_path)

    result = probe_cc_switch_schema(db_path)

    assert result.status == "available"
    assert result.user_version == 10
    assert result.supports_proxy_request_logs is True
    assert result.tables["proxy_request_logs"] == ["id", "model", "input_tokens", "total_cost_usd"]
    assert os.path.getsize(db_path) == before_size


def test_cc_switch_probe_reports_corrupt_database(tmp_path):
    db_path = tmp_path / "cc-switch.db"
    db_path.write_text("not sqlite", encoding="utf-8")

    result = probe_cc_switch_schema(db_path)

    assert result.status == "corrupt"
    assert result.message


def test_cc_switch_schema_capability_fixture_documents_statistics_tables():
    fixture_path = __import__("pathlib").Path(__file__).resolve().parents[2] / "fixtures" / "ai_workbench" / "phase0" / "cc_switch_schema_capabilities.json"
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))

    assert "proxy_request_logs" in fixture["required_statistics_tables"]
    assert "usage_daily_rollups" in fixture["required_statistics_tables"]
    assert "data_source" in fixture["required_statistics_tables"]["proxy_request_logs"]


def _capability_db(path):
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA user_version = 10")
    connection.execute("CREATE TABLE proxy_request_logs (id TEXT PRIMARY KEY, model TEXT)")
    connection.commit()
    connection.close()


def test_capability_cache_expires_after_ttl(tmp_path, monkeypatch):
    path = tmp_path / "cc-switch.db"
    _capability_db(path)
    cc_switch._capability_cache.clear()
    now = [100.0]
    monkeypatch.setattr(cc_switch.time, "monotonic", lambda: now[0])
    first = cached_probe_cc_switch_schema(path)
    connection = sqlite3.connect(path); connection.execute("ALTER TABLE proxy_request_logs ADD COLUMN provider TEXT"); connection.commit(); connection.close()
    assert "provider" not in first.tables["proxy_request_logs"]
    now[0] += cc_switch.CAPABILITY_CACHE_TTL_SECONDS + 1
    assert "provider" in cached_probe_cc_switch_schema(path).tables["proxy_request_logs"]


def test_capability_cache_invalidates_when_db_identity_changes(tmp_path):
    path = tmp_path / "cc-switch.db"
    _capability_db(path)
    cc_switch._capability_cache.clear()
    cached_probe_cc_switch_schema(path)
    replacement = tmp_path / "replacement.db"
    _capability_db(replacement)
    path.write_bytes(replacement.read_bytes())
    assert cached_probe_cc_switch_schema(path).status == "available"


def test_capability_cache_invalidates_when_user_version_changes(tmp_path):
    path = tmp_path / "cc-switch.db"; _capability_db(path); cc_switch._capability_cache.clear()
    cached_probe_cc_switch_schema(path)
    connection = sqlite3.connect(path); connection.execute("PRAGMA user_version = 11"); connection.commit(); connection.close()
    assert cached_probe_cc_switch_schema(path).user_version == 11


def test_capability_cache_invalidates_when_schema_hash_changes(tmp_path):
    path = tmp_path / "cc-switch.db"; _capability_db(path); cc_switch._capability_cache.clear()
    cached_probe_cc_switch_schema(path)
    connection = sqlite3.connect(path); connection.execute("ALTER TABLE proxy_request_logs ADD COLUMN status TEXT"); connection.commit(); connection.close()
    assert "status" in cached_probe_cc_switch_schema(path).tables["proxy_request_logs"]


def test_capability_cache_reprobes_after_identity_read_failure(tmp_path, monkeypatch):
    path = tmp_path / "cc-switch.db"; _capability_db(path); cc_switch._capability_cache.clear()
    cached_probe_cc_switch_schema(path)
    original = cc_switch._identity
    calls = {"count": 0}
    def failing_identity(candidate):
        calls["count"] += 1
        if calls["count"] == 1: raise OSError("unreadable")
        return original(candidate)
    monkeypatch.setattr(cc_switch, "_identity", failing_identity)
    assert cached_probe_cc_switch_schema(path).status == "available"


def test_capability_manual_refresh_bypasses_cache(tmp_path):
    path = tmp_path / "cc-switch.db"; _capability_db(path); cc_switch._capability_cache.clear()
    first = cached_probe_cc_switch_schema(path)
    assert cached_probe_cc_switch_schema(path, force=True) is not first
