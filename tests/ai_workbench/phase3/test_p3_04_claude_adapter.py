import sys
from pathlib import Path

from app.ai_workbench.execution.claude_runtime import ClaudeAdapter
from app.ai_workbench.execution.codex_runtime import CodexExecClient


FIXTURE = Path(__file__).parents[2] / "fixtures" / "ai_workbench" / "phase3" / "runtime_fixture.py"
PYTHON = sys.executable


def adapter(*extra):
    return ClaudeAdapter((PYTHON, str(FIXTURE), "claude", *extra))


def test_new_session_maps_stream_json_and_separates_stderr():
    result = adapter().stream_events(adapter().start_session("hello"))
    assert {"run.started", "message.delta", "message.completed", "tool.started",
            "tool.output", "hook.event", "run.completed"} <= {e["event_type"] for e in result.events}
    assert any(e["event_type"] == "diagnostic.stderr" for e in result.events)
    assert result.events[0]["source_tool"] == "claude"
    assert all(e["source_tool"] == "codex" for e in CodexExecClient((PYTHON, str(FIXTURE), "exec")).run("x").events)


def test_resume_and_fork_use_explicit_session_id_and_each_step_has_process():
    a = adapter()
    resumed = a.resume_session("known-id", "next")
    forked = a.fork_session("known-id", "branch")
    assert "--resume" in resumed.argv and resumed.argv[resumed.argv.index("--resume") + 1] == "known-id"
    assert "--continue" not in resumed.argv
    assert "--fork-session" in forked.argv
    assert resumed.process.pid != forked.process.pid
    a.stream_events(resumed)
    a.stream_events(forked)


def test_missing_session_id_uses_continue_and_marks_result_low_confidence():
    a = adapter()
    step = a.start_turn("hello")
    assert "--continue" in step.argv
    result = a.stream_events(step)
    assert all(e["session_confidence"] == "low" for e in result.events)


def test_unknown_and_malformed_records_are_preserved():
    a = adapter("malformed")
    result = a.stream_events(a.start_session("hello"))
    assert any(e["event_type"] == "unknown" and e["payload"]["raw"] == "not-json" for e in result.events)
    assert any(e["event_type"] == "unknown" and e["source_event_type"] == "new_future_record" for e in result.events)


def test_budget_permission_and_tool_lists_are_real_argv():
    a = adapter()
    step = a.start_turn("hello", max_budget=1.5, permission_mode="acceptEdits",
                        allowed_tools=("Read", "Bash"), disallowed_tools=("WebFetch",))
    assert step.argv[step.argv.index("--max-budget-usd") + 1] == "1.5"
    assert step.argv[step.argv.index("--permission-mode") + 1] == "acceptEdits"
    assert step.argv.count("--allowedTools") == 2 and "Read" in step.argv and "Bash" in step.argv
    assert step.argv[step.argv.index("--disallowedTools") + 1] == "WebFetch"
    a.stream_events(step)


def test_claude_and_codex_structural_event_shapes_match():
    claude = adapter().stream_events(adapter().start_session("x")).events
    codex = CodexExecClient((PYTHON, str(FIXTURE), "exec")).run("x").events
    assert {e["event_type"] for e in claude} >= {"run.started", "message.delta", "tool.started", "tool.output", "run.completed"}
    assert {e["event_type"] for e in codex} >= {"run.started", "message.delta", "tool.started", "tool.output", "run.completed"}
    fields = {"event_type", "payload", "source_tool", "source_event_type", "execution_path"}
    assert all(fields <= set(e) for e in claude + codex)
    assert {e["source_tool"] for e in claude} == {"claude"}
    assert {e["source_tool"] for e in codex} == {"codex"}
