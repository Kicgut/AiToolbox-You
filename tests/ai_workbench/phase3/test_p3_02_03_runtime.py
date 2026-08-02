import json
import sys
import threading
from pathlib import Path

import pytest

from app.ai_workbench.execution.codex_runtime import (
    AppServerClient, AppServerFallback, BusinessError, CodexExecClient,
    METHODS, _map_record, execute_with_fallback,
)
from app.ai_workbench.execution.schema_contract import load_codex_app_server_manifest, validate_method_params


FIXTURE = Path(__file__).parents[2] / "fixtures" / "ai_workbench" / "phase3" / "runtime_fixture.py"
PYTHON = sys.executable


def app_client():
    return AppServerClient((PYTHON, str(FIXTURE), "app"), handshake_timeout=1)


def test_default_app_server_command_uses_stdio_protocol():
    client = AppServerClient()
    assert client.argv[1:] == ("app-server", "--stdio")


def test_app_server_method_whitelist_excludes_experimental_api():
    assert "experimentalApi" not in METHODS


def test_minimal_contract_manifest_drives_non_experimental_protocol_methods():
    manifest = load_codex_app_server_manifest()
    assert manifest["experimental_enabled"] is False
    assert set(manifest["client_methods"]) == set(METHODS)
    assert manifest["required_params"]["turn/interrupt"] == ["threadId", "turnId"]


def test_initialize_payload_is_checked_against_manifest_contract():
    manifest = load_codex_app_server_manifest()
    validate_method_params("initialize", {"clientInfo": {"name": "test"}})
    assert manifest["required_params"]["initialize"] == ["clientInfo"]
    with pytest.raises(ValueError, match="initialize missing"):
        validate_method_params("initialize", {})


def test_app_server_item_records_are_visible_as_user_facing_events():
    message = _map_record({"type": "item.completed", "item": {"type": "agent_message", "text": "只返回 OK"}}, "codex_app_server")
    command = _map_record({"type": "item.completed", "item": {"type": "command_execution", "aggregated_output": "OK", "status": "completed"}}, "codex_app_server")
    completed = _map_record({"type": "turn.completed", "usage": {"input_tokens": 1}}, "codex_app_server")
    assert message["event_type"] == "message.completed" and message["payload"]["text"] == "只返回 OK"
    assert command["event_type"] == "tool.completed" and command["payload"]["output"] == "OK"
    assert completed["event_type"] == "run.completed"


def test_app_server_jsonrpc_notifications_promote_params_and_deltas():
    delta = _map_record({"method": "item/agentMessage/delta", "params": {"delta": "回答", "itemId": "m1"}}, "codex_app_server")
    final = _map_record({"method": "item/completed", "params": {"item": {"type": "agentMessage", "text": "最终回答"}}}, "codex_app_server")
    completed = _map_record({"method": "turn/completed", "params": {"turn": {"status": "completed"}}}, "codex_app_server")
    assert delta["event_type"] == "message.delta" and delta["payload"]["delta"] == "回答"
    assert final["event_type"] == "message.completed" and final["payload"]["text"] == "最终回答"
    assert completed["event_type"] == "run.completed"


def test_native_approval_request_keeps_structured_request_identity():
    seen = []
    client = AppServerClient((PYTHON, str(FIXTURE), "app_approval"), handshake_timeout=1, approval_handler=lambda request: seen.append(request) or {"decision": "decline"})
    result = client.run("hello")
    requested = next(event for event in result.events if event["event_type"] == "approval.requested")
    assert requested["payload"]["native_request_id"] == str(seen[0]["id"])
    assert requested["payload"]["method"] == "item/commandExecution/requestApproval"
    assert seen and seen[0]["method"] == "item/commandExecution/requestApproval"


def test_unsupported_server_request_gets_explicit_jsonrpc_error():
    class Stream:
        closed = False
        def __init__(self): self.messages = []
        def write(self, value): self.messages.append(value)
        def flush(self): pass

    class Process:
        def __init__(self): self.stdin = Stream()

    process = Process()
    AppServerClient()._respond_unsupported_request(process, {"id": 42, "method": "future/request"})
    response = json.loads(process.stdin.messages[0])
    assert response["id"] == 42 and response["error"]["code"] == "unsupported_method"


def test_unknown_server_request_round_trip_does_not_hang_app_server():
    result = AppServerClient((PYTHON, str(FIXTURE), "app_unknown"), handshake_timeout=1).run("hello")
    assert any(event["event_type"] == "error" and event["payload"]["code"] == "unsupported_server_request" for event in result.events)
    assert any(event["event_type"] == "run.completed" for event in result.events)


def exec_client():
    return CodexExecClient(PYTHON)  # fixture is selected by a small wrapper below


def test_app_server_real_child_process_separates_streams_and_preserves_unknown():
    result = app_client().run("hello")
    kinds = [event["event_type"] for event in result.events]
    assert {"run.started", "user.message", "message.delta", "tool.started", "tool.output", "usage.updated", "unknown"} <= set(kinds)
    stderr = [e for e in result.events if e["event_type"] == "diagnostic.stderr"]
    assert stderr and "fixture stderr" in stderr[0]["payload"]["raw"]
    assert any(e["event_type"] == "unknown" and e["payload"]["raw"] == "not-json" for e in result.events)


def test_app_server_uses_explicit_resume_and_fork_thread_ids():
    resumed = AppServerClient((PYTHON, str(FIXTURE), "app_resume"), handshake_timeout=1).run("hello", mode="resume", session_id="source-thread")
    forked = AppServerClient((PYTHON, str(FIXTURE), "app_fork"), handshake_timeout=1).run("hello", mode="fork", session_id="source-thread")
    assert next(event for event in resumed.events if event["event_type"] == "run.started")["payload"]["thread_id"] == "source-thread"
    assert next(event for event in forked.events if event["event_type"] == "run.started")["payload"]["thread_id"] == "forked-thread"


def test_handshake_noise_is_retained_without_breaking_response_matching():
    result = AppServerClient((PYTHON, str(FIXTURE), "app_noise"), handshake_timeout=1).run("hello")
    assert any(e["event_type"] == "unknown" and e["payload"]["raw"] == "not-json-before-response" for e in result.events)
    assert any(e["event_type"] == "diagnostic.stderr" and "before response" in e["payload"]["raw"] for e in result.events)


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


def test_turn_start_rejection_is_a_business_error():
    with pytest.raises(BusinessError, match="prompt_rejected"):
        AppServerClient((PYTHON, str(FIXTURE), "turn_business"), handshake_timeout=1).run("hello")


def test_coordinator_cleanup_callback_owns_app_server_cleanup():
    cleaned = []
    client = AppServerClient(
        (PYTHON, str(FIXTURE), "app"), handshake_timeout=1,
        on_cleanup=lambda process: cleaned.append(process.pid),
    )
    client.run("hello")
    assert len(cleaned) == 1


def test_app_server_interrupt_uses_schema_confirmed_thread_and_turn_ids():
    ready = threading.Event()
    callbacks = []
    result = {}
    client = AppServerClient(
        (PYTHON, str(FIXTURE), "app_interrupt"), handshake_timeout=1,
        on_interrupt=lambda callback: (callbacks.append(callback), ready.set()),
    )
    worker = threading.Thread(target=lambda: result.setdefault("value", client.run("hello")))
    worker.start()
    assert ready.wait(2)
    assert callbacks.pop()() is True
    worker.join(2)
    assert not worker.is_alive()
    assert any(event["event_type"] == "run.completed" for event in result["value"].events)


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
