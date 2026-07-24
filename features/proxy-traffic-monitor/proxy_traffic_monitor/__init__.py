"""Proxy traffic monitor: an auxiliary feature mounted onto the primary app.

Integration pattern A (in-process Python module) per
docs/adr/0002-workbench-root-and-feature-module-layout.md: this module
exposes `mount()` for routes/static assets and `lifespan()` for background
task lifecycle; the primary app registers both explicitly and owns nothing
about this feature's internals beyond that boundary.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from proxy_traffic_monitor.clash_client import ClashClient
from proxy_traffic_monitor.collector import Collector
from proxy_traffic_monitor.config import load_config
from proxy_traffic_monitor.db import init_db
from proxy_traffic_monitor.routes import live, stats, status

STATIC_DIR = "features/proxy-traffic-monitor/static"
STATIC_URL = "/features/proxy-traffic-monitor/static"


def mount(app: FastAPI) -> None:
    """Register this feature's routes and static assets onto the primary app.

    The feature page lives at `/traffic`; the Workbench SPA owns `/`.
    """
    app.mount(STATIC_URL, StaticFiles(directory=STATIC_DIR), name="proxy_traffic_monitor_static")
    app.include_router(live.router)
    app.include_router(stats.router)
    app.include_router(status.router)

    @app.get("/traffic", response_class=HTMLResponse)
    async def _proxy_traffic_monitor_index():
        return open(f"{STATIC_DIR}/index.html", encoding="utf-8").read()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Own Collector/ClashClient/db lifecycle for the process lifetime.

    The primary app's own lifespan composes this via
    `async with proxy_traffic_monitor.lifespan(app): ...` so this feature's
    background collector runs without the primary app depending on its
    internals (see main.py).
    """
    cfg = load_config()
    db = await init_db(cfg.storage.db_path)
    clash = ClashClient(cfg.clash_api.base_url, cfg.clash_api.secret)
    collector = Collector(clash, db, cfg)
    app.state.cfg = cfg
    app.state.db = db
    app.state.collector = collector
    asyncio.create_task(collector.run())
    try:
        yield
    finally:
        await collector.stop()
        await db.close()
