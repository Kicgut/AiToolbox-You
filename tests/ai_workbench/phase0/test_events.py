from app.ai_workbench.events.normalizer import normalize_jsonl
from app.ai_workbench.models import NormalizedEventType, ToolKind


def test_fixture_event_types_match_golden_file():
    fixture_root = __import__("pathlib").Path(__file__).resolve().parents[2] / "fixtures" / "ai_workbench" / "phase0"
    lines = []
    lines.extend((fixture_root / "codex_minimal.jsonl").read_text(encoding="utf-8").splitlines(True))
    lines.extend((fixture_root / "claude_stream_minimal.jsonl").read_text(encoding="utf-8").splitlines(True))
    events = normalize_jsonl(lines[:6], tool=ToolKind.CODEX, source="fixture")
    events.extend(normalize_jsonl(lines[6:], tool=ToolKind.CLAUDE, source="fixture"))

    golden = [line for line in (fixture_root / "golden_event_types.txt").read_text(encoding="utf-8").splitlines() if line]

    assert [event.event_type.value for event in events] == golden


def test_normalize_jsonl_degrades_bad_lines_to_unknown_events():
    lines = [
        '{"type":"message","role":"user","content":"hello"}\n',
        '{"type":"tool_call","name":"shell"}\n',
        '{"type":"usage","usage":{"input_tokens":10,"output_tokens":2}}\n',
        '{"type":',
    ]

    events = normalize_jsonl(lines, tool=ToolKind.CODEX, source="fixture")

    assert [event.event_type for event in events] == [
        NormalizedEventType.USER_MESSAGE,
        NormalizedEventType.TOOL_STARTED,
        NormalizedEventType.USAGE_SNAPSHOT,
        NormalizedEventType.UNKNOWN,
    ]
    assert events[-1].provenance.raw_event_type.startswith("invalid_json")


def test_unknown_record_preserves_raw_payload():
    events = normalize_jsonl(['{"type":"future_event","value":42}\n'], tool=ToolKind.CLAUDE, source="fixture")

    assert events[0].event_type == NormalizedEventType.UNKNOWN
    assert events[0].raw == {"type": "future_event", "value": 42}
