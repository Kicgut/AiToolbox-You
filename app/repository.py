from __future__ import annotations

from typing import Dict, List, Optional


async def upsert_minute_stats(db, agg: Dict) -> None:
    # TODO: implement upsert into traffic_minute_app
    raise NotImplementedError


async def upsert_connection_log(db, live_map, conn_states) -> None:
    # TODO: implement upsert into connection_log
    raise NotImplementedError


async def query_timeseries(
    db, granularity: str, start_ts: int, end_ts: int, direction: Optional[str], app: Optional[str]
) -> List[Dict]:
    raise NotImplementedError


async def query_top_apps(
    db, start_ts: int, end_ts: int, direction: Optional[str], sort: str, limit: int
) -> List[Dict]:
    raise NotImplementedError


async def query_top_connections(
    db, start_ts: int, end_ts: int, direction: Optional[str], sort: str, limit: int
) -> List[Dict]:
    raise NotImplementedError


async def query_distinct_apps(db) -> List[str]:
    raise NotImplementedError


async def delete_older_than(db, retention_days: int) -> None:
    raise NotImplementedError
