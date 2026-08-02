"""Read-only CLI capability baseline captured when the interactive runtime starts."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from app.ai_workbench.adapters.capabilities import probe_claude, probe_codex


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _schema_hash() -> str | None:
    configured = os.environ.get("AI_WORKBENCH_CODEX_SCHEMA_PATH")
    candidate = Path(configured) if configured else Path(".artifacts/tmp/protocol/codex-app-server.schema.json/codex_app_server_protocol.v2.schemas.json")
    try:
        with candidate.open("rb") as handle:
            digest = hashlib.sha256()
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()
    except OSError:
        return None


def _dto(capability: Any) -> dict[str, Any]:
    """Persist only safe, read-only capability metadata; never probe output."""
    return {
        "tool": capability.tool.value,
        "status": capability.status.value,
        "executable": capability.executable,
        "version": capability.version,
        "features": dict(capability.features),
    }


def record_runtime_baseline(
    conn: Any,
    *,
    codex_probe: Callable[[], Any] = probe_codex,
    claude_probe: Callable[[], Any] = probe_claude,
    schema_hasher: Callable[[], str | None] = _schema_hash,
) -> dict[str, Any]:
    """Store one safe startup snapshot using only version/help probes.

    The probe functions invoke CLI ``--version``/``--help`` only; no prompt,
    credentials, profile environment, or raw help output is retained.
    """
    snapshot = {
        "codex": _dto(codex_probe()),
        "claude": _dto(claude_probe()),
        "codex_app_server_schema_sha256": schema_hasher(),
    }
    conn.execute(
        "INSERT INTO runtime_capability_baselines(observed_at,payload_json) VALUES(?,?)",
        (_now(), json.dumps(snapshot, sort_keys=True)),
    )
    conn.commit()
    return snapshot
