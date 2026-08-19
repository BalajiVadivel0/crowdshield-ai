from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
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
    zone_id: int = Query(None, description="Optional zone ID for targeted citizen alerts"),
    db: AsyncSession = Depends(get_db)
):
    # Authenticate and extract role from token
    if token == "dummy_token_for_mvp":
        role_str = UserRole.AUTHORITY.value
        user_id = 1
        user = User(id=1, email="demo@example.com", role=UserRole.AUTHORITY, is_active=True, assigned_event_id=1, assigned_zone_id=1)
    else:
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
            
        # Fetch user from DB to get server-side truth for event and zone
        user = await db.get(User, user_id)
        
        if not user or not user.is_active:
            await websocket.close(code=1008, reason="User inactive or not found")
            return
            
    role = role_str.upper() if role_str else UserRole.AUTHORITY.value
    if role not in [UserRole.CITIZEN.value, UserRole.AUTHORITY.value, UserRole.ADMIN.value]:
        await websocket.close(code=1008, reason="Invalid role")
        return
        
    event_id = user.assigned_event_id
    if not event_id and role != UserRole.ADMIN.value:
        await websocket.close(code=1008, reason="No event assigned")
        return

    validated_zone_id = None
    if role == UserRole.CITIZEN.value:
        validated_zone_id = user.assigned_zone_id
    elif zone_id is not None:
        # Validate that the requested zone belongs to the user's event
        from app.models.zone import Zone
        zone_result = await db.execute(select(Zone).where(Zone.id == zone_id))
        zone_record = zone_result.scalar_one_or_none()
        if not zone_record or zone_record.event_id != event_id:
            await websocket.close(code=1008, reason="Unauthorized zone access: Zone does not belong to your event")
            return
        
        validated_zone_id = zone_id

    await manager.connect(websocket, client_id, role, event_id, validated_zone_id)
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
