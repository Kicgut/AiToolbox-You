from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from app.ai_workbench.events.jsonl import iter_jsonl_records
from app.ai_workbench.models import NormalizedEvent, NormalizedEventType, SourceProvenance, ToolKind


def normalize_jsonl(lines: Iterable[str], *, tool: ToolKind, source: str, cli_version: str | None = None) -> list[NormalizedEvent]:
    events: list[NormalizedEvent] = []
    for offset, record, error in iter_jsonl_records(lines):
        seq = len(events) + 1
        if error is not None or record is None:
            events.append(
                NormalizedEvent(
                    event_type=NormalizedEventType.UNKNOWN,
                    sequence_no=seq,
                    provenance=SourceProvenance(tool=tool, source=source, raw_event_type=error, cli_version=cli_version, offset=offset),
                    text=error,
                    raw={"line_error": error},
                )
            )
            continue
        events.append(_normalize_record(record, seq, tool, source, cli_version, offset))
    return events


def _normalize_record(
    record: dict[str, Any],
    sequence_no: int,
    tool: ToolKind,
    source: str,
    cli_version: str | None,
    offset: int,
) -> NormalizedEvent:
    raw_type = str(record.get("type") or record.get("event") or record.get("kind") or "unknown")
    provenance = SourceProvenance(tool=tool, source=source, raw_event_type=raw_type, cli_version=cli_version, offset=offset)

    role = _as_role(record.get("role"))
    text = _extract_text(record)

    if raw_type in {"user", "user_message", "message"} and role == "user":
        return NormalizedEvent(NormalizedEventType.USER_MESSAGE, sequence_no, provenance, role="user", text=text, raw=record)
    if raw_type in {"assistant", "assistant_message", "message"} and role == "assistant":
        return NormalizedEvent(NormalizedEventType.ASSISTANT_MESSAGE, sequence_no, provenance, role="assistant", text=text, raw=record)
    if raw_type in {"tool_call", "tool_started", "tool_use"}:
        return NormalizedEvent(NormalizedEventType.TOOL_STARTED, sequence_no, provenance, role="tool", text=text, structured=record, raw=record)
    if raw_type in {"tool_result", "tool_completed"}:
        return NormalizedEvent(NormalizedEventType.TOOL_COMPLETED, sequence_no, provenance, role="tool", text=text, structured=record, raw=record)
    if raw_type in {"command_output", "exec_output"}:
        return NormalizedEvent(NormalizedEventType.COMMAND_OUTPUT, sequence_no, provenance, role="tool", text=text, structured=record, raw=record)
    if raw_type in {"file_changed", "file_change", "diff"}:
        return NormalizedEvent(NormalizedEventType.FILE_CHANGED, sequence_no, provenance, structured=record, raw=record)
    if raw_type in {"usage", "usage_snapshot"} or "usage" in record:
        return NormalizedEvent(NormalizedEventType.USAGE_SNAPSHOT, sequence_no, provenance, structured=record.get("usage", record), raw=record)
    if raw_type in {"error", "failed"}:
        return NormalizedEvent(NormalizedEventType.ERROR, sequence_no, provenance, text=text, structured=record, raw=record)
    return NormalizedEvent(NormalizedEventType.UNKNOWN, sequence_no, provenance, role=role, text=text, structured=record, raw=record)


def _as_role(value: object) -> str | None:
    if value in {"user", "assistant", "tool", "system"}:
        return str(value)
    return None


def _extract_text(record: dict[str, Any]) -> str | None:
    for key in ("text", "content", "message", "delta"):
        value = record.get(key)
        if isinstance(value, str):
            return value
    return None
