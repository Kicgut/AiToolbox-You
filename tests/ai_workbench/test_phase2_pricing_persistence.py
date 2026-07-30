from app.ai_workbench.merge import reprice_usage
from app.ai_workbench.storage import connect_workbench_db
from app.ai_workbench.statistics import rebuild_rollups


def test_reprice_uses_historical_trusted_snapshot(tmp_path):
    with connect_workbench_db(tmp_path / "db.sqlite") as conn:
        conn.execute("INSERT INTO observations(id,observation_kind,source,tool,model,provider,observed_at,payload_hash,quality,parser_version,parse_status,created_at) VALUES('o','session','codex_jsonl','codex','m','p','2026-01-02T00:00:00Z','h','exact','current','parsed','2026-01-02T00:00:00Z')")
        conn.execute("INSERT INTO usage_records(id,observation_id,dedup_key,event_kind,input_tokens,output_tokens,counter_scope,event_at,recorded_at,source,quality,parser_version,created_at) VALUES('u','o','d','request_delta',1000000,2000000,'request','2026-01-02T00:00:00Z','2026-01-02T00:00:00Z','codex_jsonl','exact','v','2026-01-02T00:00:00Z')")
        conn.execute("INSERT INTO pricing_snapshots(id,source_id,source_kind,model_key,provider,input_price_per_million,output_price_per_million,currency,unit,effective_at,imported_at,observed_at,parser_version,trust_state,validation_status) VALUES('p','local','user_configured','m','p',1,2,'USD','per_1m_tokens','2026-01-01T00:00:00Z','2026-01-01T00:00:00Z','2026-01-01T00:00:00Z','v','trusted','valid')")
        assert reprice_usage(conn) == {"updated": 1, "unavailable": 0}
        row = conn.execute("SELECT estimated_cost_minor,currency,pricing_snapshot_id FROM usage_records WHERE id='u'").fetchone()
        assert tuple(row) == (500, "USD", "p")


def test_disabled_pricing_source_keeps_history_and_is_not_used_again(tmp_path):
    db = tmp_path / "db.sqlite"
    with connect_workbench_db(db) as conn:
        conn.execute("INSERT INTO observations(id,observation_kind,source,tool,model,provider,observed_at,payload_hash,quality,parser_version,parse_status,created_at) VALUES('o','session','codex_jsonl','codex','m','p','2026-01-02T00:00:00Z','h','exact','current','parsed','2026-01-02T00:00:00Z')")
        conn.execute("INSERT INTO usage_records(id,observation_id,dedup_key,event_kind,input_tokens,output_tokens,counter_scope,event_at,recorded_at,source,quality,parser_version,estimated_cost_minor,pricing_snapshot_id,currency,created_at) VALUES('u','o','d','request_delta',1000000,2000000,'request','2026-01-02T00:00:00Z','2026-01-02T00:00:00Z','codex_jsonl','exact','current',500,'p','USD','2026-01-02T00:00:00Z')")
        conn.execute("INSERT INTO pricing_snapshots(id,source_id,source_kind,model_key,provider,input_price_per_million,output_price_per_million,currency,unit,effective_at,imported_at,observed_at,parser_version,trust_state,validation_status) VALUES('p','source-a','user_configured','m','p',1,2,'USD','per_1m_tokens','2026-01-01T00:00:00Z','2026-01-01T00:00:00Z','2026-01-01T00:00:00Z','v','trusted','valid')")
        conn.commit()
        rebuild_rollups(conn)
        before = tuple(conn.execute("SELECT estimated_cost_minor,pricing_snapshot_id FROM usage_records WHERE id='u'").fetchone())
        conn.execute("DELETE FROM pricing_snapshots WHERE id='p'")
        rebuild_rollups(conn)
        after = tuple(conn.execute("SELECT estimated_cost_minor,pricing_snapshot_id FROM usage_records WHERE id='u'").fetchone())
        rollup = tuple(conn.execute("SELECT estimated_cost_minor,pricing_snapshot_id FROM daily_rollups").fetchone())
        assert before == after == (500, "p")
        assert rollup == (500, "p")
