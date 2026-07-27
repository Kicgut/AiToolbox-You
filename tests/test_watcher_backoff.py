import asyncio
from pathlib import Path

from app.ai_workbench.indexing.watcher import PollingWatcher
from app.ai_workbench.indexing.scanner import ScanSummary


def test_watcher_tracks_failed_file_paths(monkeypatch, tmp_path):
    watcher = PollingWatcher(tmp_path / "db.sqlite", interval_seconds=10)
    summaries = [ScanSummary(0, 0, 1, 0, 0, ["C:/busy/session.jsonl: transcript locked"]), ScanSummary(0, 0, 1, 0, 0, [])]

    async def fake_run_once():
        watcher.last_summary = summaries.pop(0)
        if not summaries:
            watcher.stop()
        return watcher.last_summary

    monkeypatch.setattr(watcher, "run_once", fake_run_once)
    sleeps = []
    async def fake_sleep(delay):
        sleeps.append(delay)
    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    asyncio.run(watcher.run_forever())
    assert sleeps[0] == 1.0
    assert watcher._file_retry_delays == {}
