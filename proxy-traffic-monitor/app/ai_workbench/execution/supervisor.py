from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass


@dataclass(frozen=True)
class ProcessRunResult:
    argv: tuple[str, ...]
    exit_code: int | None
    stdout: str
    stderr: str
    status: str
    duration_seconds: float


def run_process(
    argv: tuple[str, ...],
    *,
    stdin_text: str | None = None,
    timeout_seconds: float = 10.0,
    max_output_chars: int = 1_000_000,
) -> ProcessRunResult:
    started = time.monotonic()
    process = subprocess.Popen(
        list(argv),
        stdin=subprocess.PIPE if stdin_text is not None else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    try:
        stdout, stderr = process.communicate(input=stdin_text, timeout=timeout_seconds)
        status = "completed" if process.returncode == 0 else "failed"
    except subprocess.TimeoutExpired:
        process.kill()
        stdout, stderr = process.communicate()
        status = "timeout"

    return ProcessRunResult(
        argv=argv,
        exit_code=process.returncode,
        stdout=_truncate(stdout, max_output_chars),
        stderr=_truncate(stderr, max_output_chars),
        status=status,
        duration_seconds=time.monotonic() - started,
    )


def _truncate(value: str, max_chars: int) -> str:
    if len(value) <= max_chars:
        return value
    return value[:max_chars] + "\n[truncated]"

