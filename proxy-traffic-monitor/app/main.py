from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from app.api import ai_workbench, live, stats, status
from app.clash_client import ClashClient
from app.collector import Collector
from app.config import load_config
from app.db import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    cfg = load_config()
    db = await init_db(cfg.storage.db_path)
    clash = ClashClient(cfg.clash_api.base_url, cfg.clash_api.secret)
    collector = Collector(clash, db, cfg)
    app.state.cfg = cfg
    app.state.db = db
    app.state.collector = collector
    asyncio.create_task(collector.run())
    yield
    await collector.stop()
    await db.close()


app = FastAPI(lifespan=lifespan)
app.mount("/static", StaticFiles(directory="app/static"), name="static")
app.include_router(live.router)
app.include_router(stats.router)
app.include_router(status.router)
app.include_router(ai_workbench.router)


@app.get("/", response_class=HTMLResponse)
async def index():
    return open("app/static/index.html", encoding="utf-8").read()


@app.get("/workbench", response_class=HTMLResponse)
async def workbench():
    return open("app/static/workbench/index.html", encoding="utf-8").read()


if __name__ == "__main__":
    import uvicorn

    cfg = load_config()
    uvicorn.run(app, host="127.0.0.1", port=cfg.server.listen_port)
