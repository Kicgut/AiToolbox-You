"""Provider-neutral usage extraction from native JSONL events.

The parser is deliberately tolerant: unknown records are skipped with a
diagnostic instead of invalidating an entire transcript.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, asdict
from typing import Any, Iterable


@dataclass(frozen=True)
class UsageEvent:
    tool: str
    native_session_id: str | None
    native_event_id: str | None
    request_id: str | None
    turn_id: str | None
    branch_id: str | None
    workflow_id: str | None
    event_at: str | None
    input_tokens: int | None
    output_tokens: int | None
    cache_read_tokens: int | None
    cache_creation_tokens: int | None
    reasoning_tokens: int | None
    total_tokens: int | None
    source_locator: str
    parser_version: str
    quality: str = "exact"
    counter_reset: bool = False
    dedup_key: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def parse_usage_lines(lines: Iterable[str], *, tool: str, source: str,
                      native_session_id: str | None = None,
                      parser_version: str = "usage-v1") -> tuple[list[UsageEvent], list[str]]:
    if tool not in {"codex", "claude"}:
        raise ValueError("tool must be codex or claude")
    if tool == "codex":
        return _parse_codex(lines, source, native_session_id, parser_version)
    return _parse_claude(lines, source, native_session_id, parser_version)


def crosscheck_stats_cache(events: Iterable[UsageEvent], cache_payload: dict[str, Any] | None) -> dict[str, Any]:
    """Compare Claude's optional cache summary without changing native facts."""
    if cache_payload is None:
        return {"status": "unavailable", "reason_code": "stats_cache_missing"}
    native = {key: sum((getattr(event, key) or 0) for event in events) for key in ("input_tokens", "output_tokens", "cache_read_tokens", "cache_creation_tokens")}
    cache_tokens = _find_tokens(cache_payload)
    mismatches = {key: {"native": value, "cache": cache_tokens[key]} for key, value in native.items() if cache_tokens[key] is not None and value != cache_tokens[key]}
    return {"status": "match" if not mismatches else "mismatch", "mismatches": mismatches, "quality": "estimated" if mismatches else "exact", "source": "stats-cache-crosscheck"}


def _tokens(value: Any) -> dict[str, int | None]:
    if not isinstance(value, dict):
        return {k: None for k in ("input_tokens", "output_tokens", "cache_read_tokens", "cache_creation_tokens", "reasoning_tokens", "total_tokens")}
    aliases = {
        "input_tokens": ("input_tokens", "input", "prompt_tokens"),
        "output_tokens": ("output_tokens", "output", "completion_tokens"),
        "cache_read_tokens": ("cache_read_tokens", "cache_read_input_tokens"),
        "cache_creation_tokens": ("cache_creation_tokens", "cache_creation_input_tokens"),
        "reasoning_tokens": ("reasoning_tokens",),
        "total_tokens": ("total_tokens",),
    }
    result: dict[str, int | None] = {}
    for key, names in aliases.items():
        result[key] = next((int(value[n]) for n in names if isinstance(value.get(n), (int, float)) and value[n] >= 0), None)
    if result["total_tokens"] is None and result["input_tokens"] is not None and result["output_tokens"] is not None:
        result["total_tokens"] = result["input_tokens"] + result["output_tokens"]
    return result


def _find_tokens(record: dict[str, Any]) -> dict[str, int | None]:
    for key in ("usage", "token_usage", "tokens", "usage_snapshot", "usageSnapshot"):
        if isinstance(record.get(key), dict):
            return _tokens(record[key])
    return _tokens(record)


def _parse_codex(lines: Iterable[str], source: str, session: str | None, version: str) -> tuple[list[UsageEvent], list[str]]:
    output: list[UsageEvent] = []
    diagnostics: list[str] = []
    previous: dict[tuple[str | None, str | None, str | None], dict[str, int | None]] = {}
    seen: set[str] = set()
    for offset, line in enumerate(lines):
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            diagnostics.append(f"line {offset + 1}: invalid json")
            continue
        if not isinstance(record, dict):
            continue
        raw = _find_tokens(record)
        if not any(v is not None for v in raw.values()):
            continue
        turn = record.get("turn_id") or record.get("turnId")
        branch = record.get("branch_id") or record.get("branchId") or "main"
        scope = (session, turn, branch)
        old = previous.get(scope)
        if old is not None and all(raw.get(key) == old.get(key) for key in raw):
            continue
        values: dict[str, int | None] = {}
        reset = False
        for key, current in raw.items():
            if current is None:
                values[key] = None
            elif old and old.get(key) is not None and current < old[key]:
                values[key] = None
                reset = True
            else:
                values[key] = current if old is None or old.get(key) is None else current - old[key]
        previous[scope] = raw
        identity = record.get("request_id") or record.get("requestId") or record.get("event_id") or record.get("id")
        fingerprint = json.dumps(values, sort_keys=True, separators=(",", ":"))
        dedup = hashlib.sha256(f"codex|{session}|{branch}|{turn}|{identity}|{fingerprint}|{offset}".encode()).hexdigest()
        stable = hashlib.sha256(f"codex|{session}|{branch}|{turn}|{identity}|{fingerprint}".encode()).hexdigest()
        if identity and stable in seen:
            continue
        if identity:
            seen.add(stable)
        output.append(UsageEvent("codex", session, str(record.get("event_id") or record.get("id")) if record.get("event_id") or record.get("id") else None,
            str(record.get("request_id") or record.get("requestId")) if record.get("request_id") or record.get("requestId") else None,
            str(turn) if turn is not None else None, str(branch), None, record.get("event_at") or record.get("timestamp"),
            values["input_tokens"], values["output_tokens"], values["cache_read_tokens"], values["cache_creation_tokens"], values["reasoning_tokens"], values["total_tokens"],
            f"{source}:{offset}", version, "estimated" if reset else "exact", reset, dedup))
    return output, diagnostics


def _parse_claude(lines: Iterable[str], source: str, session: str | None, version: str) -> tuple[list[UsageEvent], list[str]]:
    output: list[UsageEvent] = []
    diagnostics: list[str] = []
    seen: set[str] = set()
    for offset, line in enumerate(lines):
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            diagnostics.append(f"line {offset + 1}: invalid json")
            continue
        if not isinstance(record, dict):
            continue
        tokens = _find_tokens(record)
        if not any(v is not None for v in tokens.values()):
            continue
        message_id = record.get("message_id") or record.get("messageId") or record.get("id")
        role = record.get("role") or record.get("message", {}).get("role") if isinstance(record.get("message"), dict) else record.get("role")
        body = record.get("content") or record.get("message", {}).get("content", "") if isinstance(record.get("message"), dict) else record.get("content", "")
        fingerprint = hashlib.sha256(str(body).encode("utf-8", errors="replace")).hexdigest()
        tuple_text = json.dumps(tokens, sort_keys=True, separators=(",", ":"))
        key = hashlib.sha256(f"claude|{message_id}|{role}|{fingerprint}|{tuple_text}".encode()).hexdigest()
        if message_id and key in seen:
            continue
        if message_id:
            seen.add(key)
        output.append(UsageEvent("claude", session, str(message_id) if message_id else None,
            str(record.get("request_id") or record.get("requestId")) if record.get("request_id") or record.get("requestId") else None,
            None, None, str(record.get("workflow_id")) if record.get("workflow_id") else None, record.get("timestamp") or record.get("event_at"),
            tokens["input_tokens"], tokens["output_tokens"], tokens["cache_read_tokens"], tokens["cache_creation_tokens"], tokens["reasoning_tokens"], tokens["total_tokens"],
            f"{source}:{offset}", version, "exact" if message_id else "estimated", False, key))
    return output, diagnostics
