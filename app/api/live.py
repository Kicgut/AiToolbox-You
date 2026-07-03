from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Request

router = APIRouter()


@router.websocket("/ws/live")
async def ws_live(websocket: WebSocket, request: Request):
    await websocket.accept()
    collector = request.app.state.collector
    try:
        while True:
            await websocket.send_json(collector.get_live_snapshot())
            await asyncio.sleep(1)
    except WebSocketDisconnect:
        pass
