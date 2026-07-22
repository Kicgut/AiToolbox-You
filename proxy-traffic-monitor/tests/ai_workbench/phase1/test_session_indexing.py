from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.ai_workbench.indexing.profiles import discover_profiles
from app.ai_workbench.indexing.scanner import get_session_detail, list_sessions, scan_sessions
from app.ai_workbench.storage import connect_workbench_db


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

    assert row["value"] == "1"


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
