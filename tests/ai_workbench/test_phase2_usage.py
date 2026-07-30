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


def test_codex_branch_and_subagent_parent_are_not_merged():
    lines = [
        '{"turn_id":"t1","branch_id":"a","usage":{"input_tokens":10,"output_tokens":1}}',
        '{"turn_id":"t1","branch_id":"b","usage":{"input_tokens":10,"output_tokens":1}}',
        '{"turn_id":"child","parent_turn_id":"parent","usage":{"input_tokens":10,"output_tokens":1}}',
        '{"turn_id":"parent","usage":{"input_tokens":10,"output_tokens":1}}',
    ]
    events, diagnostics = parse_usage_lines(lines, tool="codex", source="fixture", native_session_id="s")
    assert not diagnostics
    assert len(events) == 4
    assert {event.branch_id for event in events[:2]} == {"a", "b"}
    assert events[2].parent_turn_id == "parent"


def test_codex_replay_with_same_identity_is_deduplicated_and_semantics_are_retained():
    lines = [
        '{"turn_id":"t1","branch_id":"main","request_id":"r1","event_at":"2026-01-01T00:00:00Z","usage":{"input_tokens":10,"output_tokens":1}}',
        '{"turn_id":"t1","branch_id":"main","request_id":"r1","event_at":"2026-01-01T00:00:00Z","usage":{"input_tokens":10,"output_tokens":1}}',
    ]
    events, _ = parse_usage_lines(lines, tool="codex", source="replay", native_session_id="s")
    assert len(events) == 1
    assert events[0].parser_semantics_version == "usage-semantics-v1"


def test_codex_unknown_usage_record_is_skipped_and_later_records_are_parsed():
    events, diagnostics = parse_usage_lines([
        '{"type":"future_usage_shape","usage":{"unexpected":true}}',
        '{"request_id":"r1","usage":{"input_tokens":4,"output_tokens":2}}',
    ], tool="codex", source="fixture", native_session_id="s")
    assert len(events) == 1
    assert events[0].request_id == "r1"
    assert not diagnostics


def test_claude_role_and_workflow_prevent_content_only_dedup():
    lines = [
        '{"message_id":"m1","role":"assistant","workflow_id":"main","content":"same","usage":{"input_tokens":1}}',
        '{"message_id":"m1","role":"user","workflow_id":"main","content":"same","usage":{"input_tokens":1}}',
        '{"message_id":"m1","role":"assistant","workflow_id":"subagent","content":"same","usage":{"input_tokens":1}}',
    ]
    events, _ = parse_usage_lines(lines, tool="claude", source="fixture", native_session_id="s")
    assert len(events) == 3


def test_claude_unknown_schema_record_does_not_abort_transcript():
    events, diagnostics = parse_usage_lines([
        '{"type":"future_event","payload":{"new_field":"x"}}',
        '{"message_id":"m1","role":"assistant","usage":{"input_tokens":3}}',
    ], tool="claude", source="fixture", native_session_id="s")
    assert len(events) == 1
    assert events[0].native_event_id == "m1"
    assert not diagnostics
