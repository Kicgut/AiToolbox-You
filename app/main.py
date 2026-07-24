from __future__ import annotations

import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

# features/<slug>/ modules are not installed packages; make the enabled
# feature importable by adding its directory to sys.path before importing.
# See docs/adr/0002-workbench-root-and-feature-module-layout.md pattern A.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "features" / "proxy-traffic-monitor"))

from app.api import ai_workbench  # noqa: E402
import proxy_traffic_monitor  # noqa: E402


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with proxy_traffic_monitor.lifespan(app):
        yield


app = FastAPI(lifespan=lifespan)
app.mount("/static", StaticFiles(directory="app/static"), name="static")
app.include_router(ai_workbench.router)
proxy_traffic_monitor.mount(app)


@app.get("/workbench", response_class=HTMLResponse)
async def workbench():
    return open("app/static/workbench/index.html", encoding="utf-8").read()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8899)
