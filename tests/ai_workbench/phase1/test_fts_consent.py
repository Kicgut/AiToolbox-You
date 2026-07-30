import sqlite3

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.ai_workbench.indexing import scanner
from app.ai_workbench.storage import FTS_NOTICE_VERSION, SCHEMA_VERSION, connect_workbench_db


def _legacy_v1_database(path, *, indexed_events: int) -> None:
    """Create the minimum observable schema-v1 database used by migration tests."""
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    conn.execute("INSERT INTO schema_meta(key, value) VALUES('schema_version', '1')")
    conn.execute(
        """
        CREATE VIRTUAL TABLE events_fts USING fts5(
            session_copy_id UNINDEXED,
            event_id UNINDEXED,
            text_content,
            tokenize = 'unicode61'
        )
        """
    )
    for index in range(indexed_events):
        conn.execute(
            "INSERT INTO events_fts(session_copy_id, event_id, text_content) VALUES(?, ?, ?)",
            ("copy", f"event-{index}", f"legacy text {index}"),
        )
    conn.commit()
    conn.close()


def _api_client(monkeypatch, db_path) -> TestClient:
    """Create an isolated API client whose Workbench database lives under tmp_path."""
    from app.api import ai_workbench

    monkeypatch.setattr(
        ai_workbench,
        "default_workbench_paths",
        lambda *_args, **_kwargs: type("P", (), {"db_path": db_path})(),
    )
    app = FastAPI()
    app.include_router(ai_workbench.router)
    return TestClient(app)


@pytest.mark.parametrize("precreate_empty_file", [False, True])
def test_new_instance_starts_recommended_but_disabled(tmp_path, precreate_empty_file):
    db_path = tmp_path / "workbench.db"
    if precreate_empty_file:
        sqlite3.connect(db_path).close()

    conn = connect_workbench_db(db_path)
    status = scanner.fts_status(conn)
    schema_version = conn.execute(
        "SELECT value FROM schema_meta WHERE key = 'schema_version'"
    ).fetchone()["value"]

    assert schema_version == str(SCHEMA_VERSION)
    assert status == {
        "consent_state": "recommended_pending",
        "indexing_enabled": False,
        "recommended": True,
        "notice_version": 0,
        "indexed_events": 0,
    }


@pytest.mark.parametrize(
    ("indexed_events", "expected_enabled"),
    [(0, False), (2, True)],
)
def test_v1_upgrade_preserves_legacy_index_state(tmp_path, indexed_events, expected_enabled):
    db_path = tmp_path / "workbench.db"
    _legacy_v1_database(db_path, indexed_events=indexed_events)

    conn = connect_workbench_db(db_path)
    status = scanner.fts_status(conn)
    settings = conn.execute("SELECT * FROM fts_settings WHERE id = 1").fetchone()

    assert status["consent_state"] == "legacy_preserved"
    assert status["indexing_enabled"] is expected_enabled
    assert status["indexed_events"] == indexed_events
    assert status["recommended"] is False
    assert settings["notice_version"] == 0
    assert settings["decision_at"] is None
    assert settings["origin_schema_version"] == 1


def test_existing_business_table_without_schema_meta_is_legacy_install(tmp_path):
    db_path = tmp_path / "workbench.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE VIRTUAL TABLE events_fts USING fts5(
            session_copy_id UNINDEXED,
            event_id UNINDEXED,
            text_content
        )
        """
    )
    conn.commit()
    conn.close()

    migrated = connect_workbench_db(db_path)
    settings = migrated.execute("SELECT * FROM fts_settings WHERE id = 1").fetchone()

    assert settings["consent_state"] == "legacy_preserved"
    assert settings["indexing_enabled"] == 0
    assert settings["origin_schema_version"] is None


def test_closed_legacy_install_requires_explicit_acceptance_to_enable(tmp_path):
    db_path = tmp_path / "workbench.db"
    _legacy_v1_database(db_path, indexed_events=0)
    conn = connect_workbench_db(db_path)

    with pytest.raises(scanner.FtsConsentRequiredError):
        scanner.set_fts_indexing_enabled(conn, enabled=True)

    enabled = scanner.record_fts_consent(
        conn,
        decision="accept",
        notice_version=FTS_NOTICE_VERSION,
    )
    assert enabled["consent_state"] == "user_enabled"
    assert enabled["indexing_enabled"] is True


def test_consent_accept_disable_reenable_and_clear_preserve_state(tmp_path):
    conn = connect_workbench_db(tmp_path / "workbench.db")

    accepted = scanner.record_fts_consent(
        conn,
        decision="accept",
        notice_version=FTS_NOTICE_VERSION,
    )
    conn.execute(
        "INSERT INTO events_fts(session_copy_id, event_id, text_content) VALUES('copy', 'event', 'text')"
    )
    conn.commit()
    disabled = scanner.set_fts_indexing_enabled(conn, enabled=False)

    assert accepted["consent_state"] == "user_enabled"
    assert accepted["indexing_enabled"] is True
    assert disabled["consent_state"] == "user_enabled"
    assert disabled["indexing_enabled"] is False
    assert disabled["indexed_events"] == 1
    with pytest.raises(scanner.FtsIndexingDisabledError):
        scanner.rebuild_fts(conn)

    enabled = scanner.set_fts_indexing_enabled(conn, enabled=True)
    before_clear = scanner.fts_status(conn)
    cleared = scanner.clear_fts(conn)
    after_clear = scanner.fts_status(conn)

    assert enabled["indexing_enabled"] is True
    assert cleared == {"cleared_events": 1}
    assert after_clear == {**before_clear, "indexed_events": 0}


def test_decline_requires_explicit_consent_before_enabling(tmp_path):
    conn = connect_workbench_db(tmp_path / "workbench.db")

    declined = scanner.record_fts_consent(
        conn,
        decision="decline",
        notice_version=FTS_NOTICE_VERSION,
    )

    assert declined["consent_state"] == "user_declined"
    assert declined["indexing_enabled"] is False
    with pytest.raises(scanner.FtsConsentRequiredError):
        scanner.set_fts_indexing_enabled(conn, enabled=True)
    with pytest.raises(scanner.FtsConsentRequiredError):
        scanner.rebuild_fts(conn)

    accepted = scanner.record_fts_consent(
        conn,
        decision="accept",
        notice_version=FTS_NOTICE_VERSION,
    )
    assert accepted["consent_state"] == "user_enabled"
    assert accepted["indexing_enabled"] is True


def test_notice_version_upgrade_requires_new_acceptance(monkeypatch, tmp_path):
    conn = connect_workbench_db(tmp_path / "workbench.db")
    scanner.record_fts_consent(
        conn,
        decision="accept",
        notice_version=FTS_NOTICE_VERSION,
    )
    scanner.set_fts_indexing_enabled(conn, enabled=False)
    monkeypatch.setattr(scanner, "FTS_NOTICE_VERSION", FTS_NOTICE_VERSION + 1)

    status = scanner.fts_status(conn)
    assert status["recommended"] is True
    with pytest.raises(scanner.FtsConsentRequiredError):
        scanner.set_fts_indexing_enabled(conn, enabled=True)
    with pytest.raises(scanner.FtsConsentRequiredError):
        scanner.rebuild_fts(conn)

    renewed = scanner.record_fts_consent(
        conn,
        decision="accept",
        notice_version=FTS_NOTICE_VERSION + 1,
    )
    assert renewed["notice_version"] == FTS_NOTICE_VERSION + 1
    assert renewed["indexing_enabled"] is True


def test_api_enforces_consent_and_distinct_rebuild_errors(monkeypatch, tmp_path):
    client = _api_client(monkeypatch, tmp_path / "workbench.db")

    pending = client.get("/api/ai-workbench/search/status")
    blocked = client.post("/api/ai-workbench/search/rebuild")
    declined = client.post(
        "/api/ai-workbench/search/consent",
        json={"decision": "decline", "notice_version": FTS_NOTICE_VERSION},
    )
    enable_without_consent = client.patch(
        "/api/ai-workbench/search/settings",
        json={"indexing_enabled": True},
    )
    accepted = client.post(
        "/api/ai-workbench/search/consent",
        json={"decision": "accept", "notice_version": FTS_NOTICE_VERSION},
    )
    disabled = client.patch(
        "/api/ai-workbench/search/settings",
        json={"indexing_enabled": False},
    )
    disabled_rebuild = client.post("/api/ai-workbench/search/rebuild")
    before_clear = client.get("/api/ai-workbench/search/status").json()
    cleared = client.post("/api/ai-workbench/search/clear")
    after_clear = client.get("/api/ai-workbench/search/status").json()

    assert pending.json()["consent_state"] == "recommended_pending"
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["code"] == "fts_consent_required"
    assert declined.json()["consent_state"] == "user_declined"
    assert enable_without_consent.status_code == 409
    assert enable_without_consent.json()["detail"]["code"] == "fts_consent_required"
    assert accepted.json()["consent_state"] == "user_enabled"
    assert disabled.json()["indexing_enabled"] is False
    assert disabled_rebuild.status_code == 409
    assert disabled_rebuild.json()["detail"]["code"] == "fts_indexing_disabled"
    assert cleared.status_code == 200
    assert after_clear == {**before_clear, "indexed_events": 0}


def test_connect_workbench_db_skips_rerunning_migration_when_schema_current(tmp_path):
    """Regression test: connect_workbench_db used to re-run the full DDL list and
    an unconditional schema_meta upsert on every call, which could contend for a
    write lock with a concurrent writer (e.g. an in-progress scan) and surface as
    `sqlite3.OperationalError: database is locked`. A second connection against an
    already-migrated database must not attempt any write at all."""
    db_path = tmp_path / "workbench.db"

    first = connect_workbench_db(db_path)
    first.close()

    second = connect_workbench_db(db_path)
    try:
        # total_changes counts rows affected by INSERT/UPDATE/DELETE on this
        # connection; if migration (DDL + schema_meta upsert) reran, this would
        # be greater than zero even though nothing logically changed.
        assert second.total_changes == 0
    finally:
        second.close()


def test_concurrent_writer_does_not_block_an_already_migrated_connection(tmp_path):
    """A connection holding an open write transaction (simulating an in-progress
    scan) must not prevent a second, already-migrated connection from opening and
    performing a trivial read."""
    db_path = tmp_path / "workbench.db"
    connect_workbench_db(db_path).close()

    writer = sqlite3.connect(db_path, timeout=0.5)
    writer.execute("BEGIN IMMEDIATE")
    writer.execute(
        "INSERT INTO manual_profile_roots(id, tool, config_root, created_at) "
        "VALUES ('regression-test', 'codex', '/tmp/regression', 0)"
    )
    try:
        second = connect_workbench_db(db_path)
        assert second.execute("SELECT 1").fetchone()[0] == 1
        second.close()
    finally:
        writer.rollback()
        writer.close()
