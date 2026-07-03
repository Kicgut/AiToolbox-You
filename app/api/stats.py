from __future__ import annotations

import csv
import io
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from app import repository

router = APIRouter()


def _default_range(granularity: str):
    now = datetime.now(timezone.utc)
    if granularity == 'hour':
        return int((now - timedelta(hours=24)).timestamp()), int(now.timestamp())
    if granularity == 'day':
        return int((now - timedelta(days=7)).timestamp()), int(now.timestamp())
    if granularity == 'week':
        return int((now - timedelta(weeks=8)).timestamp()), int(now.timestamp())
    raise ValueError('invalid granularity')


def _parse_range(range_str: str):
    now = datetime.now(timezone.utc)
    if range_str == '1h':
        return int((now - timedelta(hours=1)).timestamp()), int(now.timestamp())
    if range_str == 'today':
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        return int(start.timestamp()), int(now.timestamp())
    if range_str == '7d':
        return int((now - timedelta(days=7)).timestamp()), int(now.timestamp())
    if range_str == '30d':
        return int((now - timedelta(days=30)).timestamp()), int(now.timestamp())
    raise ValueError('invalid range')


@router.get("/api/timeseries")
async def timeseries(
    request: Request,
    granularity: str = 'hour',
    start: Optional[int] = None,
    end: Optional[int] = None,
    direction: Optional[str] = None,
    app: Optional[str] = None,
):
    if start is None or end is None:
        start, end = _default_range(granularity)
    buckets = await repository.query_timeseries(request.app.state.db, granularity, start, end, direction, app)
    return {"buckets": buckets}


@router.get("/api/top")
async def top(
    request: Request,
    dimension: str = 'app',
    range: str = '1h',
    direction: Optional[str] = None,
    sort: str = 'total',
    limit: int = 20,
):
    start, end = _parse_range(range)
    if dimension == 'app':
        data = await repository.query_top_apps(request.app.state.db, start, end, direction, sort, limit)
    elif dimension == 'connection':
        data = await repository.query_top_connections(request.app.state.db, start, end, direction, sort, limit)
    elif dimension == 'chain':
        data = await repository.query_top_chains(request.app.state.db, start, end, direction, sort, limit)
    elif dimension == 'host':
        data = await repository.query_top_hosts(request.app.state.db, start, end, direction, sort, limit)
    else:
        data = []
    return {"data": data}


@router.get("/api/apps")
async def apps(request: Request):
    return await repository.query_distinct_apps(request.app.state.db)


@router.get("/api/export")
async def export(
    request: Request,
    kind: str = 'timeseries',
    granularity: str = 'hour',
    start: Optional[int] = None,
    end: Optional[int] = None,
    direction: Optional[str] = None,
    app: Optional[str] = None,
    dimension: str = 'app',
    range: str = '1h',
    sort: str = 'total',
    limit: int = 100,
):
    if kind == 'timeseries':
        if start is None or end is None:
            start, end = _default_range(granularity)
        rows = await repository.query_timeseries(request.app.state.db, granularity, start, end, direction, app)
    else:
        start, end = _parse_range(range)
        if dimension == 'app':
            rows = await repository.query_top_apps(request.app.state.db, start, end, direction, sort, limit)
        elif dimension == 'connection':
            rows = await repository.query_top_connections(request.app.state.db, start, end, direction, sort, limit)
        elif dimension == 'chain':
            rows = await repository.query_top_chains(request.app.state.db, start, end, direction, sort, limit)
        elif dimension == 'host':
            rows = await repository.query_top_hosts(request.app.state.db, start, end, direction, sort, limit)
        else:
            rows = []
    buf = io.StringIO()
    writer = csv.writer(buf)
    if rows:
        writer.writerow(rows[0].keys())
        writer.writerows([r.values() for r in rows])
    buf.seek(0)
    return StreamingResponse(buf, media_type="text/csv")