import sqlite3
import json
from pathlib import Path

from app.ai_workbench.compatibility.cc_switch import capability_report, CC_SWITCH_FIXTURE_EXPECTATIONS, CONNECTOR_STATUSES, resolve_pricing_model


def _fixture(path, version, columns):
    with sqlite3.connect(path) as conn:
        conn.execute(f"PRAGMA user_version={version}")
        conn.execute(f"CREATE TABLE proxy_request_logs({', '.join(columns)})")


def test_v10_matrix_keeps_native_baseline(tmp_path):
    path = tmp_path / "v10.db"; _fixture(path, 10, ["id TEXT", "model TEXT", "status TEXT"])
    result = capability_report(path)
    assert result["status"] == "available"
    assert result["native_baseline"] == "available"
    assert result["supported_fields"] == ["model", "status"]


def test_v16_matrix_reports_missing_fields(tmp_path):
    path = tmp_path / "v16.db"; _fixture(path, 16, ["id TEXT", "request_id TEXT", "provider TEXT", "ttft_ms INTEGER"])
    result = capability_report(path)
    assert result["status"] == "available"
    assert "latency_ms" in result["unavailable_fields"]


def test_future_matrix_disables_enhancement(tmp_path):
    path = tmp_path / "future.db"; _fixture(path, 99, ["id TEXT"])
    assert capability_report(path)["status"] == "incompatible"


def test_fixture_matrix_declares_supported_and_forbidden_baseline_contract():
    assert set(CC_SWITCH_FIXTURE_EXPECTATIONS) == {"v10", "v16", "future"}
    assert all(item["native_baseline"] and item["pricing"] == "inactive" for item in CC_SWITCH_FIXTURE_EXPECTATIONS.values())


def test_schema_matrix_uses_concrete_redacted_fixture_files():
    fixture_dir = Path(__file__).parent / "fixtures" / "ai_workbench" / "phase2"
    fixtures = {path.stem: json.loads(path.read_text(encoding="utf-8")) for path in fixture_dir.glob("cc_switch_*.json")}
    assert {"cc_switch_v10", "cc_switch_v16", "cc_switch_future"} <= set(fixtures)
    assert {item["schema_version"] for item in fixtures.values()} == {10, 16, 99}
    assert all(item["redacted"] and item["pricing_enabled"] is False for item in fixtures.values())


def test_connector_status_enum_is_observable_at_capability_boundary(tmp_path):
    assert CONNECTOR_STATUSES == {"not_installed", "disabled", "available", "busy", "corrupt", "incompatible", "replaced"}
    assert capability_report(tmp_path / "missing.db")["status"] == "not_installed"
    assert capability_report(tmp_path / "missing.db", enabled=False)["status"] == "disabled"


def test_pricing_alias_is_explicit_not_fuzzy():
    assert resolve_pricing_model("gpt-4o-mini") == "gpt-4o-mini-2024-07-18"
    assert resolve_pricing_model("gpt-4o-miniish") == "gpt-4o-miniish"
