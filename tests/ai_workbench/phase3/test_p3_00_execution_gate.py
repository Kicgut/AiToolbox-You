import json

import pytest

from app.ai_workbench.execution.authorization import AuthorizationError, consume_p3_10_authorization, load_p3_10_approval
from app.ai_workbench.execution.runtime_coordinator import RuntimeCoordinator
from app.ai_workbench.execution.runtime_baseline import record_runtime_baseline
from app.ai_workbench.models import CapabilityStatus, ToolCapabilities, ToolKind
from app.ai_workbench.storage import connect_workbench_db


def _approval(path, **overrides):
    document = {
        "nonce": "one-time-nonce", "request_body_hash": "request-hash", "expires_at": "2099-01-01T00:00:00Z",
        "allowed_tools": ["codex"], "model": "gpt-test", "budget_policy": {"max_duration_seconds": 60},
        "max_uses": 1,
    }
    document.update(overrides)
    path.write_text(json.dumps(document), encoding="utf-8")


def test_p3_10_authorization_is_exact_and_single_use(tmp_path):
    artifact = tmp_path / "approval.json"; _approval(artifact)
    with connect_workbench_db(tmp_path / "workbench.db") as conn:
        row = load_p3_10_approval(conn, artifact)
        assert row["consumed_uses"] == 0
        consume_p3_10_authorization(conn, nonce="one-time-nonce", request_body_hash="request-hash", tool="codex", model="gpt-test", budget_policy={"max_duration_seconds": 60})
        with pytest.raises(AuthorizationError, match="already been consumed"):
            consume_p3_10_authorization(conn, nonce="one-time-nonce", request_body_hash="request-hash", tool="codex", model="gpt-test", budget_policy={"max_duration_seconds": 60})


def test_p3_10_authorization_rejects_changed_request(tmp_path):
    artifact = tmp_path / "approval.json"; _approval(artifact)
    with connect_workbench_db(tmp_path / "workbench.db") as conn:
        load_p3_10_approval(conn, artifact)
        with pytest.raises(AuthorizationError, match="does not match"):
            consume_p3_10_authorization(conn, nonce="one-time-nonce", request_body_hash="other", tool="codex", model="gpt-test", budget_policy={"max_duration_seconds": 60})
        with pytest.raises(AuthorizationError, match="does not permit this tool"):
            consume_p3_10_authorization(conn, nonce="one-time-nonce", request_body_hash="request-hash", tool="claude", model="gpt-test", budget_policy={"max_duration_seconds": 60})


def test_real_execution_is_closed_by_default_and_fake_executor_is_explicit(monkeypatch, tmp_path):
    monkeypatch.delenv("AI_WORKBENCH_REAL_EXECUTION", raising=False)
    coordinator = RuntimeCoordinator(tmp_path / "workbench.db")
    assert coordinator.real_execution_enabled is False and coordinator.execution_available is False
    monkeypatch.setenv("AI_WORKBENCH_REAL_EXECUTION", "0")
    assert coordinator.real_execution_enabled is False
    fake = RuntimeCoordinator(tmp_path / "fake.db", executor=lambda _run, _step: None)
    assert fake.execution_available is True and fake.real_execution_enabled is False
    monkeypatch.setenv("AI_WORKBENCH_REAL_EXECUTION", "1")
    assert coordinator.real_execution_enabled is True


def test_startup_baseline_records_only_safe_read_only_capability_metadata(tmp_path):
    codex = ToolCapabilities(ToolKind.CODEX, CapabilityStatus.AVAILABLE, executable="codex.exe", version="codex 1", features={"app_server": True})
    claude = ToolCapabilities(ToolKind.CLAUDE, CapabilityStatus.AVAILABLE, executable="claude.exe", version="claude 1", features={"resume": True})
    with connect_workbench_db(tmp_path / "workbench.db") as conn:
        snapshot = record_runtime_baseline(conn, codex_probe=lambda: codex, claude_probe=lambda: claude, schema_hasher=lambda: "schema-hash")
        persisted = json.loads(conn.execute("SELECT payload_json FROM runtime_capability_baselines").fetchone()[0])
    assert snapshot == persisted
    assert persisted["codex_app_server_schema_sha256"] == "schema-hash"
    assert "token" not in json.dumps(persisted).lower()


def test_real_runtime_start_records_baseline_but_fake_runtime_does_not(tmp_path):
    real_calls, fake_calls = [], []
    real = RuntimeCoordinator(tmp_path / "real.db", baseline_recorder=lambda conn: real_calls.append(conn))
    real.start(); real.stop()
    fake = RuntimeCoordinator(tmp_path / "fake.db", executor=lambda _run, _step: None, baseline_recorder=lambda conn: fake_calls.append(conn))
    fake.start(); fake.stop()
    assert len(real_calls) == 1
    assert fake_calls == []
