import os
import json
import sqlite3

from app.ai_workbench.compatibility.cc_switch import probe_cc_switch_schema


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

    assert result.status == "error"
    assert result.message


def test_cc_switch_schema_capability_fixture_documents_statistics_tables():
    fixture_path = __import__("pathlib").Path(__file__).resolve().parents[2] / "fixtures" / "ai_workbench" / "phase0" / "cc_switch_schema_capabilities.json"
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))

    assert "proxy_request_logs" in fixture["required_statistics_tables"]
    assert "usage_daily_rollups" in fixture["required_statistics_tables"]
    assert "data_source" in fixture["required_statistics_tables"]["proxy_request_logs"]
