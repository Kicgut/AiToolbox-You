from app.ai_workbench.usage import UsageEvent, crosscheck_stats_cache


def _event(input_tokens=10):
    return UsageEvent("claude", "s", "m", None, None, None, "w", "2026-01-01T00:00:00Z", input_tokens, 2, None, None, None, None, "x:1", "claude-jsonl-v1")


def test_cache_crosscheck_does_not_change_native_facts():
    result = crosscheck_stats_cache([_event()], {"usage": {"input_tokens": 99, "output_tokens": 2}})
    assert result["status"] == "mismatch"
    assert result["cross_check"] in {"cache_ahead", "cache_behind"}
    assert _event().input_tokens == 10


def test_missing_cache_is_diagnostic_only():
    assert crosscheck_stats_cache([_event()], None)["reason_code"] == "stats_cache_missing"
