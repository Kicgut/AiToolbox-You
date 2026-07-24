from __future__ import annotations

import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
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


def _workbench_index() -> str:
    """Return the built Workbench SPA shell as HTML text."""
    return open("app/static/workbench/index.html", encoding="utf-8").read()


def _accepts_html(request: Request) -> bool:
    """Return whether Accept contains an exact, case-insensitive text/html media type."""
    return any(
        item.split(";", 1)[0].strip().lower() == "text/html"
        for item in request.headers.get("accept", "").split(",")
    )


def _is_workbench_history_path(spa_path: str) -> bool:
    """Return whether a path is eligible for the constrained SPA history fallback."""
    segments = [segment for segment in spa_path.split("/") if segment]
    if not segments or segments[0].lower() in {"api", "static", "traffic", "ws"}:
        return False
    return not Path(segments[-1]).suffix


@app.get("/workbench")
async def workbench():
    """Redirect the legacy Workbench bookmark to the Session Center route."""
    return RedirectResponse(url="/sessions", status_code=307)


@app.api_route("/", methods=["GET", "HEAD"], response_class=HTMLResponse)
async def workbench_root():
    """Serve the Workbench SPA shell at its explicit root route."""
    return _workbench_index()


@app.api_route("/{spa_path:path}", methods=["GET", "HEAD"], response_class=HTMLResponse)
async def workbench_history_fallback(spa_path: str, request: Request):
    """Serve eligible HTML history routes and preserve real 404s for all other paths."""
    if not _accepts_html(request) or not _is_workbench_history_path(spa_path):
        raise HTTPException(status_code=404, detail="Not Found")
    return _workbench_index()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8899)
