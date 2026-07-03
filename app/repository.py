from __future__ import annotations

from typing import Dict, List, Optional, Tuple

import aiosqlite


async def upsert_minute_stats(db: aiosqlite.Connection, agg: Dict[Tuple[int, str, str], List[int]]) -> None:
    if not agg:
        return
    rows = [(minute_ts, process_name, direction, up, down) for (minute_ts, process_name, direction), (up, down) in agg.items()]
    await db.executemany(
        """        INSERT INTO traffic_minute_app (minute_ts, process_name, direction, upload_bytes, download_bytes)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(minute_ts, process_name, direction)
        DO UPDATE SET
            upload_bytes = upload_bytes + excluded.upload_bytes,
            download_bytes = download_bytes + excluded.download_bytes;
        """,
        rows,
    )
    await db.commit()


async def upsert_connection_log(
    db: aiosqlite.Connection,
    live_map,
    conn_states,
) -> None:
    rows = []
    for cid, conn in live_map.items():
        state = conn_states.get(cid)
        rows.append((
            cid,
            conn.process_name,
            conn.host,
            conn.dest_port,
            conn.network,
            conn.direction,
            conn.chain,
            conn.rule,
            conn.start_ts,
            int(conn.start_ts),
            getattr(state, 'last_upload', conn.total_up),
            getattr(state, 'last_download', conn.total_down),
        ))
    if rows:
        await db.executemany(
            """            INSERT INTO connection_log (id, process_name, host, dest_port, network, direction, chain, rule, start_ts, last_seen_ts, upload_bytes, download_bytes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                last_seen_ts=excluded.last_seen_ts,
                upload_bytes=excluded.upload_bytes,
                download_bytes=excluded.download_bytes,
                direction=excluded.direction,
                chain=excluded.chain,
                rule=excluded.rule;
            """,
            rows,
        )
        await db.commit()


async def query_timeseries(
    db: aiosqlite.Connection,
    granularity: str,
    start_ts: int,
    end_ts: int,
    direction: Optional[str],
    app: Optional[str],
) -> List[Dict]:
    group_expr = {
        'hour': "(minute_ts / 3600) * 3600",
        'day': "date(minute_ts, 'unixepoch', 'localtime')",
        'week': "strftime('%Y-%W', minute_ts, 'unixepoch', 'localtime')",
    }[granularity]
    sql = f"""
        SELECT {group_expr} AS bucket,
               SUM(CASE WHEN direction='direct' THEN upload_bytes ELSE 0 END) AS direct_upload,
               SUM(CASE WHEN direction='direct' THEN download_bytes ELSE 0 END) AS direct_download,
               SUM(CASE WHEN direction='proxy' THEN upload_bytes ELSE 0 END) AS proxy_upload,
               SUM(CASE WHEN direction='proxy' THEN download_bytes ELSE 0 END) AS proxy_download
        FROM traffic_minute_app
        WHERE minute_ts BETWEEN ? AND ?
    """
    params: list = [start_ts, end_ts]
    if direction:
        sql += " AND direction = ?"
        params.append(direction)
    if app:
        sql += " AND process_name = ?"
        params.append(app)
    sql += " GROUP BY bucket ORDER BY bucket;"
    async with db.execute(sql, params) as cur:
        rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def query_top_apps(
    db: aiosqlite.Connection,
    start_ts: int,
    end_ts: int,
    direction: Optional[str],
    sort: str,
    limit: int,
) -> List[Dict]:
    order = {
        'upload': 'SUM(upload_bytes) DESC',
        'download': 'SUM(download_bytes) DESC',
        'total': 'SUM(upload_bytes + download_bytes) DESC',
    }[sort]
    sql = f"""
        SELECT process_name,
               SUM(upload_bytes) AS upload_bytes,
               SUM(download_bytes) AS download_bytes
        FROM traffic_minute_app
        WHERE minute_ts BETWEEN ? AND ?
    """
    params: list = [start_ts, end_ts]
    if direction:
        sql += " AND direction = ?"
        params.append(direction)
    sql += f" GROUP BY process_name ORDER BY {order} LIMIT ?;"
    params.append(limit)
    async with db.execute(sql, params) as cur:
        rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def query_top_connections(
    db: aiosqlite.Connection,
    start_ts: int,
    end_ts: int,
    direction: Optional[str],
    sort: str,
    limit: int,
) -> List[Dict]:
    order = {
        'upload': 'upload_bytes DESC',
        'download': 'download_bytes DESC',
        'total': '(upload_bytes + download_bytes) DESC',
    }[sort]
    sql = f"""
        SELECT id, process_name, host, direction, chain, upload_bytes, download_bytes, start_ts, last_seen_ts
        FROM connection_log
        WHERE last_seen_ts BETWEEN ? AND ?
    """
    params: list = [start_ts, end_ts]
    if direction:
        sql += " AND direction = ?"
        params.append(direction)
    sql += f" ORDER BY {order} LIMIT ?;"
    params.append(limit)
    async with db.execute(sql, params) as cur:
        rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def query_distinct_apps(db: aiosqlite.Connection) -> List[str]:
    async with db.execute("SELECT DISTINCT process_name FROM traffic_minute_app ORDER BY process_name") as cur:
        rows = await cur.fetchall()
    return [r[0] for r in rows]


async def delete_older_than(db: aiosqlite.Connection, retention_days: int) -> None:
    cutoff = int(asyncio.get_event_loop().time()) - retention_days * 86400
    await db.execute("DELETE FROM traffic_minute_app WHERE minute_ts < ?", (cutoff,))
    await db.execute("DELETE FROM connection_log WHERE last_seen_ts < ?", (cutoff,))
    await db.commit()
