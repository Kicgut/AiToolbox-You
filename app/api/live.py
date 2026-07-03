import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter()


@router.websocket("/ws/live")
async def ws_live(websocket: WebSocket):
    await websocket.accept()
    collector = websocket.app.state.collector
    try:
        while True:
            await websocket.send_json(collector.get_live_snapshot())
            await asyncio.sleep(1)
    except WebSocketDisconnect:
        pass
