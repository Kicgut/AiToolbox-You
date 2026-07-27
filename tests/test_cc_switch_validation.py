import sqlite3

from app.ai_workbench.compatibility.cc_switch import read_proxy_request_logs


def test_invalid_proxy_numbers_are_rejected(tmp_path):
    path = tmp_path / "cc.db"
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE proxy_request_logs(id TEXT PRIMARY KEY, latency_ms INTEGER, ttft_ms INTEGER, recorded_cost_minor INTEGER)")
        conn.execute("INSERT INTO proxy_request_logs VALUES('good',10,2,3)")
        conn.execute("INSERT INTO proxy_request_logs VALUES('bad',-1,2,3)")
    result = read_proxy_request_logs(path)
    assert len(result["data"]) == 1
    assert result["rejected_count"] == 1
