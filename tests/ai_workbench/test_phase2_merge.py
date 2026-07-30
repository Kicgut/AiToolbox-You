from app.ai_workbench.merge import estimate_cost, merge_decision


def test_proxy_enrichment_does_not_double_count_session_tokens(tmp_path):
    """A proxy row with the same request identity enriches, but never contributes tokens."""
    from app.ai_workbench.storage import connect_workbench_db
    from app.ai_workbench.statistics import rebuild_rollups

    with connect_workbench_db(tmp_path / "db.sqlite") as conn:
        conn.execute("INSERT INTO observations(id,observation_kind,source,request_id,tool,model,provider,observed_at,payload_hash,quality,parser_version,parse_status,created_at) VALUES('session','session','fixture','req-1','codex','m','p','2026-01-01T00:00:00Z','h1','exact','current','parsed','2026-01-01T00:00:00Z')")
        conn.execute("INSERT INTO observations(id,observation_kind,source,request_id,tool,model,provider,observed_at,payload_hash,quality,parser_version,parse_status,latency_ms,ttft_ms,http_status,created_at) VALUES('proxy','proxy','cc_switch','req-1','proxy','m','p','2026-01-01T00:00:00Z','h2','exact','current','parsed',120,30,200,'2026-01-01T00:00:00Z')")
        conn.execute("INSERT INTO usage_records(id,observation_id,dedup_key,event_kind,input_tokens,output_tokens,counter_scope,event_at,recorded_at,source,quality,parser_version,merge_status,created_at) VALUES('usage','session','req-1','request_delta',100,25,'request','2026-01-01T00:00:00Z','2026-01-01T00:00:00Z','codex_jsonl','exact','current','primary','2026-01-01T00:00:00Z')")
        rebuild_rollups(conn)
        row = conn.execute("SELECT input_tokens, output_tokens FROM daily_rollups").fetchone()
        assert tuple(row) == (100, 25)


def test_merge_preserves_conflicts():
    result = merge_decision({"request_id": "r", "input_tokens": 1}, {"request_id": "r", "input_tokens": 2})
    assert result.status == "conflict"
    assert result.conflict_group_id


def test_cost_requires_effective_trusted_snapshot():
    record = {"event_at": "2026-01-02T00:00:00Z", "input_tokens": 1_000_000, "output_tokens": 2_000_000}
    snapshot = {"id": "p", "source_id": "local", "model_key": "m", "currency": "USD", "unit": "per_1m_tokens", "effective_at": "2026-01-01T00:00:00Z", "input_price_per_million": 1, "output_price_per_million": 2, "trust_state": "trusted", "validation_status": "valid"}
    result = estimate_cost(record, snapshot)
    assert result["value_minor"] == 500
    assert result["quality"] == "estimated"


def test_pricing_sources_are_returned_side_by_side_when_prices_conflict(tmp_path):
    from app.ai_workbench.statistics import pricing_snapshot_sources
    from app.ai_workbench.storage import connect_workbench_db
    with connect_workbench_db(tmp_path / "db.sqlite") as conn:
        for row in (("local", "manual", 1.0), ("cc", "cc_switch", 2.0)):
            conn.execute("INSERT INTO pricing_snapshots(id,source_id,source_kind,model_key,provider,input_price_per_million,output_price_per_million,currency,unit,effective_at,source_updated_at,imported_at,observed_at,parser_version,trust_state,validation_status) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (row[0], row[0], row[1], "m", "p", row[2], row[2], "USD", "per_1m_tokens", "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z", "test", "trusted", "valid"))
        values = pricing_snapshot_sources(conn, model="m")
        assert {value["source_kind"] for value in values} == {"manual", "cc_switch"}
        assert {value["conflict_status"] for value in values} == {"conflict"}


def test_weak_match_is_mark_only_and_does_not_count_tokens_as_duplicate():
    result = merge_decision(
        {"native_session_id": "s", "model": "m", "event_at": "2026-01-01T00:00:00Z", "input_tokens": None},
        {"session_id": "s", "model": "m", "event_at": "2026-01-01T00:00:02Z", "input_tokens": None},
    )
    assert result.status == "weak_match"
    assert result.counting_policy == "mark_only_count_independently"
