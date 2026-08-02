"""Minimal, reviewable contract for the generated Codex App Server schema."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


_MANIFEST = Path(__file__).with_name("codex_app_server_manifest.json")


def load_codex_app_server_manifest() -> dict[str, Any]:
    """Read only the checked-in, non-sensitive protocol contract."""
    value = json.loads(_MANIFEST.read_text(encoding="utf-8"))
    if value.get("experimental_enabled") is not False:
        raise ValueError("experimental App Server contract is not permitted")
    if not isinstance(value.get("client_methods"), list) or not isinstance(value.get("server_request_methods"), list):
        raise ValueError("invalid App Server contract manifest")
    return value


def validate_method_params(method: str, params: dict[str, Any]) -> None:
    """Validate required fields from the reviewed protocol manifest."""
    if not isinstance(params, dict):
        raise ValueError(f"{method} params must be an object")
    required = load_codex_app_server_manifest().get("required_params", {}).get(method, [])
    missing = [name for name in required if name not in params]
    if missing:
        raise ValueError(f"{method} missing required params: {', '.join(missing)}")
