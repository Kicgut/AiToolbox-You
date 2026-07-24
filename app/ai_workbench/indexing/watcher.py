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

    async def run_once(self) -> ScanSummary:
        with connect_workbench_db(self.db_path) as conn:
            self.last_summary = reconcile_sessions(conn)
            return self.last_summary

    async def run_forever(self) -> None:
        self.running = True
        try:
            while self.running:
                try:
                    await self.run_once()
                except sqlite3.Error:
                    pass
                await asyncio.sleep(self.interval_seconds)
        finally:
            self.running = False

    def stop(self) -> None:
        self.running = False

