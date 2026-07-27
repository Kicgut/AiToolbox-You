from app.ai_workbench.merge import estimate_cost, merge_decision


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
