from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/api/status")
async def status(request: Request):
    return request.app.state.collector.get_status()
