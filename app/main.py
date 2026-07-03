from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from app.api import live, stats, status
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
    # TODO: initialize Collector and background tasks
    app.state.cfg = cfg
    app.state.db = db


@app.on_event("shutdown")
async def shutdown():
    # TODO: cancel background tasks and close db
    pass


if __name__ == "__main__":
    import uvicorn

    cfg = load_config()
    uvicorn.run(app, host="127.0.0.1", port=cfg.server.listen_port)
