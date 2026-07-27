import csv
import io

from app.ai_workbench.statistics import statistics_csv
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
