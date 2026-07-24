from app.ai_workbench.adapters import capabilities
from app.ai_workbench.adapters.capabilities import probe_claude, probe_codex
from app.ai_workbench.models import CapabilityStatus


def test_codex_probe_reports_missing_for_unknown_executable():
    result = probe_codex("definitely-not-a-real-codex-binary")

    assert result.status == CapabilityStatus.MISSING
    assert result.supports("app_server") is False


def test_claude_probe_reports_missing_for_unknown_executable():
    result = probe_claude("definitely-not-a-real-claude-binary")

    assert result.status == CapabilityStatus.MISSING
    assert result.supports("stream_json") is False


def test_codex_probe_detects_expected_features(monkeypatch):
    monkeypatch.setattr(capabilities.shutil, "which", lambda _: "codex-test")

    def fake_run(command):
        if command.argv[-1] == "--version":
            return CapabilityStatus.AVAILABLE, "codex-cli 0.144.4"
        if command.argv[-2:] == ("app-server", "--help"):
            return CapabilityStatus.AVAILABLE, "Usage: codex app-server"
        return CapabilityStatus.AVAILABLE, "Commands: exec resume\nOptions: --json"

    monkeypatch.setattr(capabilities, "_run_text", fake_run)

    result = probe_codex()

    assert result.status == CapabilityStatus.AVAILABLE
    assert result.version == "codex-cli 0.144.4"
    assert result.supports("resume")
    assert result.supports("exec_json")
    assert result.supports("app_server")


def test_claude_probe_preserves_timeout_status(monkeypatch):
    monkeypatch.setattr(capabilities.shutil, "which", lambda _: "claude-test")
    monkeypatch.setattr(capabilities, "_run_text", lambda command: (CapabilityStatus.TIMEOUT, "timeout"))

    result = probe_claude()

    assert result.status == CapabilityStatus.TIMEOUT
    assert result.message == "timeout"
