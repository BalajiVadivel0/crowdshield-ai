from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from jose import jwt, JWTError
from app.services.websocket_manager import manager
from app.core.config import settings
from app.models.user import User, UserRole
from app.api.dependencies import get_db
import logging

logger = logging.getLogger(__name__)

router = APIRouter()

@router.websocket("/{client_id}")
async def websocket_endpoint(
    websocket: WebSocket, 
    client_id: str, 
    token: str = Query(..., description="JWT token for authentication"),
    db: AsyncSession = Depends(get_db)
):
    # Authenticate and extract role from token
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
        role_str = payload.get("role")
        user_id_str = payload.get("sub")
        if role_str is None or user_id_str is None:
            await websocket.close(code=1008, reason="Invalid token payload")
            return
        user_id = int(user_id_str)
    except (JWTError, ValueError):
        await websocket.close(code=1008, reason="Invalid token")
        return
        
    role = role_str.upper()
    if role not in [UserRole.CITIZEN.value, UserRole.AUTHORITY.value, UserRole.ADMIN.value]:
        await websocket.close(code=1008, reason="Invalid role")
        return
        
    user = await db.get(User, user_id)
    if not user:
        await websocket.close(code=1008, reason="User not found")
        return
        
    zone_id = None
    if role == UserRole.CITIZEN.value:
        zone_id = user.assigned_zone_id
        
    await manager.connect(websocket, client_id, role, zone_id)
    try:
        while True:
            # We don't necessarily expect incoming messages, but we need to keep the connection open
            # and handle pings or client-side disconnects.
            data = await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(client_id)
    except Exception as e:
        logger.error(f"WebSocket error for {client_id}: {e}")
        manager.disconnect(client_id)
