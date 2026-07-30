import sys
from pathlib import Path

import pytest

from app.ai_workbench.execution.codex_runtime import (
    AppServerClient, AppServerFallback, BusinessError, CodexExecClient,
    execute_with_fallback,
)


FIXTURE = Path(__file__).parents[2] / "fixtures" / "ai_workbench" / "phase3" / "runtime_fixture.py"
PYTHON = sys.executable


def app_client():
    return AppServerClient((PYTHON, str(FIXTURE), "app"), handshake_timeout=1)


def exec_client():
    return CodexExecClient(PYTHON)  # fixture is selected by a small wrapper below


def test_app_server_real_child_process_separates_streams_and_preserves_unknown():
    result = app_client().run("hello")
    kinds = [event["event_type"] for event in result.events]
    assert {"run.started", "user.message", "message.delta", "tool.started", "tool.output", "usage.updated", "unknown"} <= set(kinds)
    stderr = [e for e in result.events if e["event_type"] == "diagnostic.stderr"]
    assert stderr and "fixture stderr" in stderr[0]["payload"]["raw"]
    assert any(e["event_type"] == "unknown" and e["payload"]["raw"] == "not-json" for e in result.events)


def test_exec_mapping_uses_stdin_and_reduced_capabilities():
    result = CodexExecClient((PYTHON, str(FIXTURE), "exec")).run("prompt")
    kinds = [event["event_type"] for event in result.events]
    assert {"run.started", "user.message", "message.delta", "tool.started", "tool.output", "usage.updated", "unknown"} <= set(kinds)
    assert result.capabilities.fork is False
    assert result.capabilities.native_approval is False
    assert any(e["event_type"] == "diagnostic.stderr" for e in result.events)


def test_exec_emits_each_normalized_record_to_live_sink():
    live = []
    result = CodexExecClient((PYTHON, str(FIXTURE), "exec"), on_event=live.append).run("prompt")
    assert [event["event_type"] for event in live] == [event["event_type"] for event in result.events]
    assert any(event["event_type"] == "message.delta" for event in live)


def test_business_error_does_not_fallback(monkeypatch):
    class Rejecting:
        def run(self, *args, **kwargs): raise BusinessError("prompt rejected")
    class Exec:
        def run(self, *args, **kwargs): pytest.fail("business error must not fallback")
    with pytest.raises(BusinessError): execute_with_fallback("x", app=Rejecting(), exec_client=Exec())


def test_missing_app_server_is_a_fallback_trigger():
    with pytest.raises(AppServerFallback): AppServerClient((str(Path("definitely-missing-app-server")),)).run("x",)


@pytest.mark.parametrize("mode", ["timeout", "unsupported", "version"])
def test_transport_capability_fallback_triggers(mode):
    client = AppServerClient((PYTHON, str(FIXTURE), mode), handshake_timeout=0.05)
    with pytest.raises(AppServerFallback): client.run("x")


def test_business_rejection_is_not_a_fallback_trigger():
    with pytest.raises(BusinessError): AppServerClient((PYTHON, str(FIXTURE), "business"), handshake_timeout=1).run("x")


def test_fallback_exec_path_reports_reduced_capabilities():
    app = AppServerClient((str(Path("definitely-missing-app-server")),))
    result = execute_with_fallback("hello", app=app, exec_client=CodexExecClient((PYTHON, str(FIXTURE), "exec")))
    assert result.execution_path == "codex_exec"
    assert result.capabilities.fork is False and result.capabilities.native_approval is False


def test_fork_never_silently_falls_back_to_exec():
    class Exec:
        def run(self, *args, **kwargs): pytest.fail("fork must not become exec resume")
    with pytest.raises(BusinessError, match="fork requires"):
        execute_with_fallback(
            "x", app=AppServerClient((str(Path("definitely-missing-app-server")),)),
            exec_client=Exec(), mode="fork", session_id="thread-1",
        )


def test_submitted_turn_failure_does_not_silently_fallback():
    class Exec:
        def run(self, *args, **kwargs): pytest.fail("submitted turn must not start exec")
    # A fixture that accepts the turn request and then never responds causes the
    # client to classify the run as interrupted/business failure.
    with pytest.raises(BusinessError):
        execute_with_fallback("x", app=AppServerClient((PYTHON, str(FIXTURE), "late"), handshake_timeout=0.05), exec_client=Exec())
