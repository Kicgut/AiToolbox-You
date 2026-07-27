import sqlite3

from app.ai_workbench.compatibility.cc_switch import capability_report


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
