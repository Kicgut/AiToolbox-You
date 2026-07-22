from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any


def iter_jsonl_records(lines: Iterable[str], *, max_line_length: int = 1_000_000) -> Iterable[tuple[int, dict[str, Any] | None, str | None]]:
    offset = 0
    for line in lines:
        raw_line = line.rstrip("\r\n")
        start_offset = offset
        offset += len(line.encode("utf-8", errors="replace"))
        if not raw_line:
            continue
        if len(raw_line) > max_line_length:
            yield start_offset, None, "line_too_long"
            continue
        try:
            parsed = json.loads(raw_line)
        except json.JSONDecodeError as exc:
            yield start_offset, None, f"invalid_json:{exc.msg}"
            continue
        if not isinstance(parsed, dict):
            yield start_offset, None, "not_object"
            continue
        yield start_offset, parsed, None

