from fastapi import APIRouter

router = APIRouter()


@router.websocket("/ws/live")
async def ws_live():
    raise NotImplementedError
