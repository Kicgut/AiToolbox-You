from __future__ import annotations

import asyncio
import pathlib

import aiosqlite

DDL = [
    """
    CREATE TABLE IF NOT EXISTS traffic_minute_app (
        minute_ts INTEGER,
        process_name TEXT,
        direction TEXT,
        upload_bytes INTEGER NOT NULL DEFAULT 0,
        download_bytes INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (minute_ts, process_name, direction)
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_minute ON traffic_minute_app(minute_ts);",
    """
    CREATE TABLE IF NOT EXISTS connection_log (
        id TEXT PRIMARY KEY,
        process_name TEXT,
        host TEXT,
        dest_port INTEGER,
        network TEXT,
        direction TEXT,
        chain TEXT,
        rule TEXT,
        start_ts INTEGER,
        last_seen_ts INTEGER,
        upload_bytes INTEGER NOT NULL DEFAULT 0,
        download_bytes INTEGER NOT NULL DEFAULT 0
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_conn_lastseen ON connection_log(last_seen_ts);",
]

write_lock = asyncio.Lock()


async def init_db(path: str) -> aiosqlite.Connection:
    pathlib.Path(path).parent.mkdir(parents=True, exist_ok=True)
    db = await aiosqlite.connect(path)
    db.row_factory = aiosqlite.Row
    for stmt in DDL:
        await db.execute(stmt)
    await db.commit()
    return db
