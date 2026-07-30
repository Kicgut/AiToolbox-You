from app.ai_workbench.statistics import utc_bucket, record_rollup_invalidation
from app.ai_workbench.storage import connect_workbench_db
from app.ai_workbench.statistics import rebuild_rollups
import app.ai_workbench.statistics as statistics


def _api_client(monkeypatch, db_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api import ai_workbench
    monkeypatch.setattr(ai_workbench, "default_workbench_paths", lambda *_args, **_kwargs: type("P", (), {"db_path": db_path})())
    app = FastAPI(); app.include_router(ai_workbench.router)
    return TestClient(app)


def test_statistics_tables_are_created_for_new_db(tmp_path):
    with connect_workbench_db(tmp_path / "workbench.db") as conn:
        tables = {
            row["name"] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
    assert {"observations", "usage_records", "daily_rollups", "pricing_snapshots",
            "rollup_invalidations", "observation_links", "rebuild_jobs"} <= tables


def test_statistics_tables_are_added_to_existing_v2_db(tmp_path):
    db = tmp_path / "workbench.db"
    with connect_workbench_db(db) as conn:
        conn.execute("DROP TABLE observations")
        conn.commit()
    with connect_workbench_db(db) as conn:
        assert conn.execute("SELECT 1 FROM sqlite_master WHERE name='observations'").fetchone()


def test_dst_bucket_uses_real_utc_bounds():
    assert utc_bucket("2026-03-08", "America/Los_Angeles") == (
        "2026-03-08T08:00:00Z", "2026-03-09T07:00:00Z"
    )


def test_dst_fall_back_bucket_is_25_hours():
    assert utc_bucket("2026-11-01", "America/Los_Angeles") == (
        "2026-11-01T07:00:00Z", "2026-11-02T08:00:00Z"
    )


def test_invalid_timezone_is_rejected():
    try:
        utc_bucket("2026-03-08", "Not/AZone")
    except ValueError:
        pass
    else:
        raise AssertionError("invalid timezone must be rejected")


def test_failed_rebuild_keeps_previous_active_rollup(tmp_path, monkeypatch):
    db = tmp_path / "db.sqlite"
    with connect_workbench_db(db) as conn:
        conn.execute("INSERT INTO daily_rollups(bucket_date,timezone,bucket_start_utc,bucket_end_utc,source,quality,request_count,input_tokens,output_tokens,source_watermark,rollup_version,rebuilt_at) VALUES('2026-01-01','UTC','2026-01-01T00:00:00Z','2026-01-02T00:00:00Z','old','exact',7,70,8,'old','rollup-v1','2026-01-01T00:00:00Z')")
        conn.execute("INSERT INTO observations(id,observation_kind,source,tool,model,provider,observed_at,payload_hash,quality,parser_version,parse_status,created_at) VALUES('obs','session','codex_jsonl','codex','m','p','2026-01-01T00:00:00Z','hash','exact','current','parsed','2026-01-01T00:00:00Z')")
        conn.execute("INSERT INTO usage_records(id,observation_id,dedup_key,event_kind,input_tokens,output_tokens,counter_scope,event_at,recorded_at,source,quality,parser_version,created_at) VALUES('usage','obs','dedup','request_delta',1,1,'request','2026-01-01T00:00:00Z','2026-01-01T00:00:00Z','codex_jsonl','exact','current','2026-01-01T00:00:00Z')")
        conn.commit()
        monkeypatch.setattr(statistics, "utc_bucket", lambda *_: (_ for _ in ()).throw(RuntimeError("build failed")))
        result = rebuild_rollups(conn)
        assert result["status"] == "failed"
        row = conn.execute("SELECT request_count,input_tokens,source_watermark FROM daily_rollups WHERE rollup_version='rollup-v1'").fetchone()
        assert tuple(row) == (7, 70, "old")


def test_rebuild_is_idempotent(tmp_path):
    db = tmp_path / "db.sqlite"
    with connect_workbench_db(db) as conn:
        conn.execute("INSERT INTO observations(id,observation_kind,source,tool,model,provider,observed_at,payload_hash,quality,parser_version,parse_status,created_at) VALUES('obs','session','codex_jsonl','codex','m','p','2026-01-01T00:00:00Z','hash','exact','current','parsed','2026-01-01T00:00:00Z')")
        conn.execute("INSERT INTO usage_records(id,observation_id,dedup_key,event_kind,input_tokens,output_tokens,counter_scope,event_at,recorded_at,source,quality,parser_version,created_at) VALUES('usage','obs','dedup','request_delta',1,NULL,'request','2026-01-01T00:00:00Z','2026-01-01T00:00:00Z','codex_jsonl','exact','current','2026-01-01T00:00:00Z')")
        first = rebuild_rollups(conn)
        snapshot = [tuple(row) for row in conn.execute("SELECT bucket_date,request_count,input_tokens,output_tokens FROM daily_rollups")]
        second = rebuild_rollups(conn)
        assert first["status"] == second["status"] == "completed"
        assert snapshot == [tuple(row) for row in conn.execute("SELECT bucket_date,request_count,input_tokens,output_tokens FROM daily_rollups")]


def test_usage_record_provenance_is_joinable_to_observation(tmp_path):
    with connect_workbench_db(tmp_path / "db.sqlite") as conn:
        conn.execute("INSERT INTO observations(id,observation_kind,source,tool,observed_at,payload_hash,quality,parser_version,parse_status,created_at) VALUES('obs','session','fixture','codex','2026-01-01T00:00:00Z','hash','estimated','parser-v7','parsed','2026-01-01T00:00:00Z')")
        conn.execute("INSERT INTO usage_records(id,observation_id,dedup_key,event_kind,counter_scope,recorded_at,source,quality,parser_version,created_at) VALUES('usage','obs','dedup','request_delta','request','2026-01-01T00:00:00Z','fixture','estimated','parser-v7','2026-01-01T00:00:00Z')")
        row = conn.execute("SELECT u.observation_id,o.source,o.quality,o.observed_at,o.parser_version FROM usage_records u JOIN observations o ON o.id=u.observation_id").fetchone()
        assert tuple(row) == ('obs', 'fixture', 'estimated', '2026-01-01T00:00:00Z', 'parser-v7')


def test_rebuild_records_timezone_and_parser_invalidations(tmp_path):
    from app.ai_workbench.statistics import rebuild_rollups
    with connect_workbench_db(tmp_path / "db.sqlite") as conn:
        conn.execute("INSERT INTO observations(id,observation_kind,source,tool,model,observed_at,payload_hash,quality,parser_version,parse_status,created_at) VALUES('o','session','fixture','codex','m','2026-01-01T00:00:00Z','h','exact','usage-v1','parsed','2026-01-01T00:00:00Z')")
        conn.execute("INSERT INTO usage_records(id,observation_id,dedup_key,event_kind,input_tokens,counter_scope,event_at,recorded_at,source,quality,parser_version,created_at) VALUES('u','o','d','request_delta',1,'request','2026-01-01T00:00:00Z','2026-01-01T00:00:00Z','fixture','exact','usage-v1','2026-01-01T00:00:00Z')")
        rebuild_rollups(conn, timezone_name="UTC", parser_version="current")
        rebuild_rollups(conn, timezone_name="America/Los_Angeles", parser_version="current")
        reasons = {r[0] for r in conn.execute("SELECT reason FROM rollup_invalidations")}
        assert {"parser_version_changed", "timezone_changed"} <= reasons


def test_raw_usage_change_marks_exact_bucket_pending(tmp_path):
    """A newly ingested raw fact creates a pending invalidation for its bucket."""
    from app.ai_workbench.statistics import record_rollup_invalidation
    with connect_workbench_db(tmp_path / "db.sqlite") as conn:
        record_rollup_invalidation(conn, "raw_changed", bucket_date="2026-01-02", observed_at="2026-01-02T03:00:00Z")
        row = conn.execute("SELECT bucket_date, status, reason FROM rollup_invalidations").fetchone()
        assert tuple(row) == ("2026-01-02", "pending", "raw_changed")


def test_merge_algorithm_change_invalidates_rollup(tmp_path, monkeypatch):
    """A changed merge algorithm is recorded as a pending invalidation."""
    import app.ai_workbench.statistics as statistics
    with connect_workbench_db(tmp_path / "db.sqlite") as conn:
        monkeypatch.setattr(statistics, "MERGE_ALGORITHM_VERSION", "merge-v2")
        statistics.rebuild_rollups(conn)
        assert conn.execute("SELECT reason FROM rollup_invalidations WHERE reason='merge_algorithm_changed'").fetchone()


def test_statistics_api_contracts_and_quality_fields_are_end_to_end(tmp_path, monkeypatch):
    db = tmp_path / "db.sqlite"
    with connect_workbench_db(db) as conn:
        conn.execute("INSERT INTO observations(id,observation_kind,source,tool,model,provider,observed_at,payload_hash,quality,parser_version,parse_status,created_at) VALUES('o','session','fixture','codex','m','p','2026-01-01T00:00:00Z','h','exact','v','parsed','2026-01-01T00:00:00Z')")
        conn.execute("INSERT INTO usage_records(id,observation_id,dedup_key,event_kind,input_tokens,counter_scope,event_at,recorded_at,source,quality,parser_version,created_at) VALUES('u','o','d','request_delta',0,'request','2026-01-01T00:00:00Z','2026-01-01T00:00:00Z','fixture','exact','v','2026-01-01T00:00:00Z')")
        rebuild_rollups(conn)
    with _api_client(monkeypatch, db) as client:
        contracts = {
            "/api/ai-workbench/statistics/overview": client.get,
            "/api/ai-workbench/statistics/timeseries": client.get,
            "/api/ai-workbench/statistics/breakdown": client.get,
            "/api/ai-workbench/statistics/reliability": client.get,
            "/api/ai-workbench/statistics/data-quality": client.get,
        }
        responses = {path: request(path + "?start=2026-01-01&end=2026-01-01") for path, request in contracts.items()}
        assert all(response.status_code == 200 for response in responses.values())
        overview = responses["/api/ai-workbench/statistics/overview"].json()
        assert overview["metrics"]["input_tokens"]["value"] == 0
        assert overview["metrics"]["input_tokens"]["availability"] == "available"
        assert {"availability", "quality", "source"} <= set(overview["metrics"]["input_tokens"])
        assert responses["/api/ai-workbench/statistics/timeseries"].json()["data"][0]["metrics"]["input_tokens"]["value"] == 0
        assert isinstance(responses["/api/ai-workbench/statistics/reliability"].json(), dict)
        assert "data" in responses["/api/ai-workbench/statistics/data-quality"].json()


def test_statistics_api_remains_available_when_cc_switch_is_off_and_marks_stale(tmp_path, monkeypatch):
    db = tmp_path / "db.sqlite"
    with connect_workbench_db(db) as conn:
        record_rollup_invalidation(conn, "raw_changed", bucket_date="2026-01-01")
    with _api_client(monkeypatch, db) as client:
        overview = client.get("/api/ai-workbench/statistics/overview")
        timeseries = client.get("/api/ai-workbench/statistics/timeseries")
        assert overview.status_code == timeseries.status_code == 200
        assert overview.json()["rollup_status"] == "stale"


def test_rebuild_job_state_survives_reopening_database_and_audit_is_read_only(tmp_path):
    db = tmp_path / "db.sqlite"
    with connect_workbench_db(db) as conn:
        result = rebuild_rollups(conn, job_id="persisted-job")
        assert result["audit"]["external_files_modified"] == []
        assert result["audit"]["cc_switch_db_modified"] is False
    with connect_workbench_db(db) as reopened:
        row = reopened.execute("SELECT status,audit_json FROM rebuild_jobs WHERE id='persisted-job'").fetchone()
        assert row["status"] == "completed"
        assert '"external_files_modified": []' in row["audit_json"]


def test_rebuild_request_reuses_running_job(tmp_path, monkeypatch):
    from app.ai_workbench.statistics import enqueue_rebuild
    db = tmp_path / "db.sqlite"
    with connect_workbench_db(db) as conn:
        conn.execute("INSERT INTO rebuild_jobs(id,scope,status,requested_at,checkpoint) VALUES('running-job','workbench_usage_and_rollup','running','2026-01-01T00:00:00Z','running')")
    assert enqueue_rebuild(db) == "running-job"


def test_rebuild_audit_endpoint_returns_persisted_summary(tmp_path, monkeypatch):
    import json
    db = tmp_path / "db.sqlite"
    audit = {"before": {"c": 1}, "after": {"c": 1}, "delta": {"count": 0}}
    with connect_workbench_db(db) as conn:
        conn.execute("INSERT INTO rebuild_jobs(id,scope,status,requested_at,audit_json) VALUES(?,?,?,?,?)",
                     ("audit-job", "workbench_usage_and_rollup", "completed", "2026-01-01T00:00:00Z", json.dumps(audit)))
    with _api_client(monkeypatch, db) as client:
        response = client.get("/api/ai-workbench/statistics/rebuild/audit-job/audit")
    assert response.status_code == 200
    assert response.json() == audit


def test_rebuild_cancel_transitions_through_cancelling_before_cancelled(tmp_path, monkeypatch):
    db = tmp_path / "db.sqlite"
    with connect_workbench_db(db) as conn:
        conn.execute("INSERT INTO rebuild_jobs(id,scope,status,requested_at) VALUES(?,?,?,?)",
                     ("cancel-job", "workbench_usage_and_rollup", "running", "2026-01-01T00:00:00Z"))
    with _api_client(monkeypatch, db) as client:
        response = client.post("/api/ai-workbench/statistics/rebuild/cancel-job/cancel")
    assert response.json()["status"] == "cancelling"
    with connect_workbench_db(db) as conn:
        assert conn.execute("SELECT status FROM rebuild_jobs WHERE id='cancel-job'").fetchone()[0] == "cancelling"
        result = rebuild_rollups(conn, job_id="cancel-job")
        assert result["status"] == "cancelled"
        assert conn.execute("SELECT status FROM rebuild_jobs WHERE id='cancel-job'").fetchone()[0] == "cancelled"
