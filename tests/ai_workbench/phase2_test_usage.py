from app.ai_workbench.usage import parse_usage_lines


def test_codex_snapshot_delta_reset_and_duplicate():
    lines = [
        '{"turn_id":"t1","request_id":"r1","usage":{"input_tokens":100,"output_tokens":20}}',
        '{"turn_id":"t1","request_id":"r1","usage":{"input_tokens":130,"output_tokens":25}}',
        '{"turn_id":"t1","request_id":"r1","usage":{"input_tokens":130,"output_tokens":25}}',
        '{"turn_id":"t1","request_id":"r2","usage":{"input_tokens":10,"output_tokens":2}}',
    ]
    events, diagnostics = parse_usage_lines(lines, tool="codex", source="x", native_session_id="s")
    assert not diagnostics
    assert [(e.input_tokens, e.output_tokens) for e in events] == [(100, 20), (30, 5), (None, None)]
    assert events[-1].counter_reset


def test_claude_message_identity_deduplicates_only_exact_identity():
    lines = [
        '{"message_id":"m1","role":"assistant","usage":{"input_tokens":10,"output_tokens":2}}',
        '{"message_id":"m1","role":"assistant","usage":{"input_tokens":10,"output_tokens":2}}',
        '{"message_id":"m1","role":"user","usage":{"input_tokens":10,"output_tokens":2}}',
    ]
    events, _ = parse_usage_lines(lines, tool="claude", source="x", native_session_id="s")
    assert len(events) == 2
