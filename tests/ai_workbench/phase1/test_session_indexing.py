from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.ai_workbench.indexing.profiles import discover_profiles
from app.ai_workbench.indexing.scanner import (
    add_manual_profile,
    clear_fts,
    fts_status,
    get_session_detail,
    list_sessions,
    record_fts_consent,
    rebuild_fts,
    reconcile_sessions,
    scan_sessions,
)
from app.ai_workbench.storage import FTS_NOTICE_VERSION, SCHEMA_VERSION, connect_workbench_db
from app.ai_workbench.indexing.scanner import _native_session_id
from app.ai_workbench.models import ToolKind


def test_discover_profiles_from_env(monkeypatch, tmp_path):
    codex_home = tmp_path / "codex-home"
    claude_home = tmp_path / "claude-home"
    (codex_home / "sessions").mkdir(parents=True)
    (claude_home / "projects").mkdir(parents=True)
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(claude_home))

    profiles = discover_profiles()

    assert {profile.tool.value for profile in profiles if profile.valid} == {"codex", "claude"}


def test_scan_indexes_codex_jsonl_and_ignores_incomplete_tail(monkeypatch, tmp_path):
    codex_home = tmp_path / "codex-home"
    session_dir = codex_home / "sessions" / "2026" / "07"
    session_dir.mkdir(parents=True)
    transcript = session_dir / "session-abc.jsonl"
    transcript.write_text(
        '{"type":"message","role":"user","content":"hello"}\n'
        '{"type":"tool_call","name":"shell"}\n'
        '{"type":',
        encoding="utf-8",
    )
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "empty-claude-home"))
    conn = connect_workbench_db(tmp_path / "workbench.db")

    summary = scan_sessions(conn)
    sessions = list_sessions(conn)["data"]
    detail = get_session_detail(conn, sessions[0]["id"])

    assert summary.sessions_indexed == 1
    assert summary.events_indexed == 2
    assert sessions[0]["title"] == "hello"
    assert detail is not None
    assert [event["event_type"] for event in detail["events"]] == ["user.message", "tool.started"]


def test_reconcile_only_indexes_changed_files(monkeypatch, tmp_path):
    codex_home = tmp_path / "codex-home"
    session_dir = codex_home / "sessions"
    session_dir.mkdir(parents=True)
    transcript = session_dir / "session-abc.jsonl"
    transcript.write_text('{"type":"message","role":"user","content":"first"}\n', encoding="utf-8")
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "empty-claude-home"))
    conn = connect_workbench_db(tmp_path / "workbench.db")

    first = scan_sessions(conn)
    second = reconcile_sessions(conn)
    transcript.write_text(
        '{"type":"message","role":"user","content":"first"}\n{"type":"message","role":"assistant","content":"second"}\n',
        encoding="utf-8",
    )
    third = reconcile_sessions(conn)

    assert first.sessions_indexed == 1
    assert second.sessions_indexed == 0
    assert third.sessions_indexed == 1
    assert list_sessions(conn)["data"][0]["event_count"] == 2


def test_scan_indexes_claude_project_path(monkeypatch, tmp_path):
    claude_home = tmp_path / "claude-home"
    project_dir = claude_home / "projects" / "-E-statistics-toolbox-You"
    project_dir.mkdir(parents=True)
    (project_dir / "51876741-4a6c-473f-98b3-aba079730091.jsonl").write_text(
        '{"type":"message","role":"assistant","content":"done"}\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "empty-codex-home"))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(claude_home))
    conn = connect_workbench_db(tmp_path / "workbench.db")

    summary = scan_sessions(conn)
    sessions = list_sessions(conn, tool="claude")["data"]

    assert summary.sessions_indexed == 1
    assert sessions[0]["tool"] == "claude"
    assert sessions[0]["event_count"] == 1


def test_schema_version_is_recorded(tmp_path):
    conn = connect_workbench_db(tmp_path / "workbench.db")

    row = conn.execute("SELECT value FROM schema_meta WHERE key = 'schema_version'").fetchone()

    assert row["value"] == str(SCHEMA_VERSION)


def test_manual_profile_and_fts_lifecycle(monkeypatch, tmp_path):
    codex_home = tmp_path / "manual-codex"
    session_dir = codex_home / "sessions"
    session_dir.mkdir(parents=True)
    sensitive_marker = "password" + "=hidden"
    (session_dir / "session-manual.jsonl").write_text(
        '{"type":"message","role":"user","content":"searchable ' + sensitive_marker + '"}\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "empty-codex-home"))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "empty-claude-home"))
    conn = connect_workbench_db(tmp_path / "workbench.db")

    add_manual_profile(conn, tool="codex", config_root=codex_home)
    scan_sessions(conn)
    record_fts_consent(conn, decision="accept", notice_version=FTS_NOTICE_VERSION)
    rebuilt = rebuild_fts(conn)
    stored_text = conn.execute("SELECT text_content FROM events_fts").fetchone()["text_content"]
    cleared = clear_fts(conn)

    assert rebuilt["indexed_events"] == 1
    assert sensitive_marker not in stored_text
    assert fts_status(conn)["indexed_events"] == 0
    assert cleared["cleared_events"] == 1


def test_divergent_copies_return_diff_summary(monkeypatch, tmp_path):
    root_a = tmp_path / "codex-a"
    root_b = tmp_path / "codex-b"
    (root_a / "sessions").mkdir(parents=True)
    (root_b / "sessions").mkdir(parents=True)
    for root, suffix in [(root_a, "a"), (root_b, "b")]:
        (root / "sessions" / "copy.jsonl").write_text(
            '{"type":"message","role":"user","content":"same","session_id":"shared-session"}\n'
            f'{{"type":"message","role":"assistant","content":"{suffix}"}}\n',
            encoding="utf-8",
        )
    monkeypatch.setenv("CODEX_HOME", f"{root_a}{__import__('os').pathsep}{root_b}")
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "empty-claude-home"))
    conn = connect_workbench_db(tmp_path / "workbench.db")

    scan_sessions(conn)
    sessions = list_sessions(conn)["data"]
    detail = get_session_detail(conn, sessions[0]["id"])

    assert len(sessions) == 2
    assert {session["divergence_status"] for session in sessions} == {"diverged"}
    assert detail is not None
    assert detail["diffSummary"]["copies"] == 2
    assert detail["diffSummary"]["common_prefix_events"] == 1


def test_codex_thread_id_is_used_for_resume_instead_of_rollout_filename(tmp_path):
    event = type("Event", (), {"raw": {"type": "session_meta", "payload": {"session_id": "019fb3f8-a3a9-7eb2-a77e-62a1aa321c87"}}})()

    assert _native_session_id(ToolKind.CODEX, tmp_path / "rollout-2026.jsonl", [event]) == event.raw["payload"]["session_id"]


def test_api_routes_are_registered(monkeypatch, tmp_path):
    from app.api import ai_workbench

    db_path = tmp_path / "workbench.db"
    monkeypatch.setattr(ai_workbench, "default_workbench_paths", lambda *_args, **_kwargs: type("P", (), {"db_path": db_path})())
    app = FastAPI()
    app.include_router(ai_workbench.router)

    with TestClient(app) as client:
        response = client.get("/api/ai-workbench/sessions")

    assert response.status_code == 200
    assert response.json()["data"] == []
