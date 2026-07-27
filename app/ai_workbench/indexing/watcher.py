from __future__ import annotations

import asyncio
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from app.ai_workbench.indexing.scanner import ScanSummary, reconcile_sessions
from app.ai_workbench.storage import connect_workbench_db


@dataclass
class PollingWatcher:
    db_path: Path
    interval_seconds: float = 15.0
    running: bool = False
    last_summary: ScanSummary | None = None
    _retry_delays: dict[str, float] | None = None
    _file_retry_delays: dict[str, float] | None = None

    async def run_once(self) -> ScanSummary:
        with connect_workbench_db(self.db_path) as conn:
            self.last_summary = reconcile_sessions(conn)
            return self.last_summary

    async def run_forever(self) -> None:
        self.running = True
        self._retry_delays = {}
        self._file_retry_delays = {}
        try:
            while self.running:
                try:
                    await self.run_once()
                    errors = self.last_summary.errors if self.last_summary else []
                    failed_paths = {error.split(": ", 1)[0] for error in errors}
                    for path in failed_paths:
                        previous = self._file_retry_delays.get(path, 0.0)
                        self._file_retry_delays[path] = min(self.interval_seconds, 1.0 if previous == 0 else previous * 2)
                    for path in set(self._file_retry_delays) - failed_paths:
                        self._file_retry_delays.pop(path, None)
                    self._retry_delays.clear()
                except (sqlite3.Error, OSError) as exc:
                    key = type(exc).__name__
                    delay = min(self.interval_seconds, max(1.0, self._retry_delays.get(key, 1.0) * 2))
                    self._retry_delays[key] = delay
                    await asyncio.sleep(delay)
                    continue
                delay = max((self._file_retry_delays or {}).values(), default=self.interval_seconds)
                await asyncio.sleep(delay)
        finally:
            self.running = False

    def stop(self) -> None:
        self.running = False
