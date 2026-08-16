from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from app.services.websocket_manager import manager
import logging

logger = logging.getLogger(__name__)

router = APIRouter()

@router.websocket("/{client_id}")
async def websocket_endpoint(
    websocket: WebSocket, 
    client_id: str, 
    role: str = Query("CITIZEN", description="AUTHORITY or CITIZEN"),
    zone_id: int = Query(None, description="Optional zone ID for targeted citizen alerts")
):
    await manager.connect(websocket, client_id, role, zone_id)
    try:
        while True:
            # We don't necessarily expect incoming messages, but we need to keep the connection open
            # and handle pings or client-side disconnects.
            data = await websocket.receive_text()
            # Can add ping/pong logic or simple echo here if needed for testing
            # await websocket.send_text(f"Message text was: {data}")
    except WebSocketDisconnect:
        manager.disconnect(client_id)
    except Exception as e:
        logger.error(f"WebSocket error for {client_id}: {e}")
        manager.disconnect(client_id)
