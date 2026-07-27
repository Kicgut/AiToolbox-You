from app.ai_workbench.statistics import utc_bucket
from app.ai_workbench.storage import connect_workbench_db


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


def test_invalid_timezone_is_rejected():
    try:
        utc_bucket("2026-03-08", "Not/AZone")
    except ValueError:
        pass
    else:
        raise AssertionError("invalid timezone must be rejected")
