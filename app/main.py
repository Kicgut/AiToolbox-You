from __future__ import annotations

import asyncio

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from app.api import live, stats, status
from app.clash_client import ClashClient
from app.collector import Collector
from app.config import load_config
from app.db import init_db

app = FastAPI()
app.mount("/static", StaticFiles(directory="app/static"), name="static")
app.include_router(live.router)
app.include_router(stats.router)
app.include_router(status.router)


@app.get("/", response_class=HTMLResponse)
async def index():
    return open("app/static/index.html", encoding="utf-8").read()


@app.on_event("startup")
async def startup():
    cfg = load_config()
    db = await init_db(cfg.storage.db_path)
    clash = ClashClient(cfg.clash_api.base_url, cfg.clash_api.secret)
    collector = Collector(clash, db, cfg)
    app.state.cfg = cfg
    app.state.db = db
    app.state.collector = collector
    asyncio.create_task(collector.run())


@app.on_event("shutdown")
async def shutdown():
    collector: Collector = app.state.collector
    await collector.stop()
    await app.state.db.close()


if __name__ == "__main__":
    import uvicorn

    cfg = load_config()
    uvicorn.run(app, host="127.0.0.1", port=cfg.server.listen_port)
