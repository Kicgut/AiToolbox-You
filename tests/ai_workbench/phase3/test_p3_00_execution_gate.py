import json

import pytest

from app.ai_workbench.execution.authorization import AuthorizationError, consume_p3_10_authorization, load_p3_10_approval
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
