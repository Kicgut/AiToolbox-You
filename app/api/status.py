from fastapi import APIRouter

router = APIRouter()


@router.get("/api/status")
async def status():
    raise NotImplementedError
