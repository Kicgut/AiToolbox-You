import csv
import io

from app.ai_workbench.statistics import statistics_csv, ROLLUP_ALGORITHM_VERSION
from app.ai_workbench.storage import connect_workbench_db


def test_csv_has_fixed_quality_and_cost_columns(tmp_path):
    with connect_workbench_db(tmp_path / "db.sqlite") as conn:
        text = statistics_csv(conn)
    header = next(csv.reader(io.StringIO(text)))
    assert "availability" in header
    assert "reason_code" in header
    assert "pricing_snapshot_id" in header
    assert "parser_version" in header
    assert "recorded_actual_amount_minor" in header


def test_csv_rows_match_header_and_preserve_dimensions_and_provenance(tmp_path):
    with connect_workbench_db(tmp_path / "db.sqlite") as conn:
        conn.execute("""INSERT INTO daily_rollups
            (bucket_date, timezone, bucket_start_utc, bucket_end_utc, tool, profile_ref,
             project_ref, model, provider, source, quality, request_count, input_tokens,
             output_tokens, recorded_cost_minor, estimated_cost_minor, rollup_version,
             parser_version, recorded_actual_currency, estimate_currency, source_watermark,
             rebuilt_at)
            VALUES ('2026-01-01','UTC','2026-01-01T00:00:00Z','2026-01-02T00:00:00Z',
             'codex','profile-a','project-a','model-a','provider-a','native','exact',1,2,3,
             123,456,?, ?, 'USD','USD','usage_records','2026-01-01T00:00:00Z')""",
            (ROLLUP_ALGORITHM_VERSION, "parser-v7"))
        text = statistics_csv(conn)
    rows = list(csv.reader(io.StringIO(text)))
    assert len(rows[0]) == len(rows[1]) == 34
    values = dict(zip(rows[0], rows[1]))
    assert values["tool"] == "codex"
    assert values["profile_ref"] == "profile-a"
    assert values["recorded_actual_currency"] == "USD"
    assert values["api_equivalent_estimate_currency"] == "USD"
    assert values["parser_version"] == "parser-v7"
    assert values["rollup_version"] == ROLLUP_ALGORITHM_VERSION
