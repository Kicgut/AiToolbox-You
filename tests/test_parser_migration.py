import pytest

from app.ai_workbench.statistics import migrate_parser_version
from app.ai_workbench.storage import connect_workbench_db


def test_parser_migration_updates_known_versions(tmp_path):
    with connect_workbench_db(tmp_path / "db.sqlite") as conn:
        conn.execute("INSERT INTO observations(id,observation_kind,source,tool,observed_at,payload_hash,quality,parser_version,parse_status,created_at) VALUES('o','session','codex_jsonl','codex','2026-01-01T00:00:00Z','h','exact','codex-jsonl-v1','parsed','2026-01-01T00:00:00Z')")
        conn.execute("INSERT INTO usage_records(id,observation_id,dedup_key,event_kind,counter_scope,recorded_at,source,quality,parser_version,created_at) VALUES('u','o','d','request_delta','request','2026-01-01T00:00:00Z','codex_jsonl','exact','codex-jsonl-v1','2026-01-01T00:00:00Z')")
        result = migrate_parser_version(conn, "current")
        assert result["migrated_records"] == 1
        assert conn.execute("SELECT parser_version FROM usage_records").fetchone()[0] == "current"


def test_unknown_parser_migration_is_rejected(tmp_path):
    with connect_workbench_db(tmp_path / "db.sqlite") as conn:
        with pytest.raises(ValueError):
            migrate_parser_version(conn, "future")
