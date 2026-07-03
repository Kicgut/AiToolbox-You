from fastapi import APIRouter

router = APIRouter()


@router.get("/api/timeseries")
async def timeseries():
    raise NotImplementedError


@router.get("/api/top")
async def top():
    raise NotImplementedError


@router.get("/api/apps")
async def apps():
    raise NotImplementedError


@router.get("/api/export")
async def export():
    raise NotImplementedError
