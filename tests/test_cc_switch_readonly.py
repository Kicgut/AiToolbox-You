import hashlib
import sqlite3

from app.ai_workbench.compatibility.cc_switch import read_pricing_candidates, read_proxy_request_logs


def _db(path):
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE proxy_request_logs(id TEXT PRIMARY KEY, request_id TEXT, model TEXT, provider TEXT, status TEXT, latency_ms INTEGER, ttft_ms INTEGER, recorded_cost_minor INTEGER, created_at TEXT)")
        conn.execute("INSERT INTO proxy_request_logs VALUES('1','r1','m','p','200',10,2,3,'2026-01-01T00:00:00Z')")
        conn.execute("CREATE TABLE model_pricing(id TEXT, model TEXT, provider TEXT, input_price_per_million REAL, output_price_per_million REAL, currency TEXT, unit TEXT, effective_at TEXT, updated_at TEXT)")
        conn.execute("INSERT INTO model_pricing VALUES('p','m','p',1,2,'USD','per_1m_tokens','2026-01-01T00:00:00Z','2026-01-01T00:00:00Z')")


def test_cc_switch_reads_whitelist_without_writing(tmp_path):
    path = tmp_path / "cc.db"; _db(path)
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    result = read_proxy_request_logs(path)
    assert result["status"] == "available"
    assert result["data"][0]["request_id"] == "r1"
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before


def test_pricing_is_disabled_by_default_and_validates_candidates(tmp_path):
    path = tmp_path / "cc.db"; _db(path)
    assert read_pricing_candidates(path)["status"] == "disabled"
    result = read_pricing_candidates(path, enabled=True)
    assert result["status"] == "available"
    assert result["data"][0]["trust_state"] == "inactive"
