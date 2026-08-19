from typing import List, Optional
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import or_

from app.api.dependencies import get_db, get_current_user
from app.models.user import User, UserRole
from app.models.alert import Alert, AlertRead
from pydantic import BaseModel

router = APIRouter()

class AlertResponse(BaseModel):
    id: int
    event_id: int
    zone_id: Optional[int]
    target_role: UserRole
    alert_type: str
    severity: str
    title: str
    message: str
    created_at: datetime
    expires_at: datetime
    is_read: bool

    class Config:
        from_attributes = True

@router.get("/", response_model=List[AlertResponse])
async def get_alerts(
    zone_id: Optional[int] = Query(None, description="Optional zone ID filter for citizens"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Retrieve active alerts targeted to the current user's role.
    Authorities get global AUTHORITY alerts.
    Citizens get CITIZEN alerts, optionally filtered by their current zone.
    """
    now = datetime.now(timezone.utc)
    
    # 1. Fetch active alerts based on role
    query = select(Alert).where(
        Alert.target_role == current_user.role,
        Alert.expires_at > now
    )
    
    if current_user.role != UserRole.ADMIN and current_user.assigned_event_id:
        query = query.where(Alert.event_id == current_user.assigned_event_id)
        
    query = query.order_by(Alert.created_at.desc())

    if current_user.role == UserRole.CITIZEN:
        if current_user.assigned_zone_id is not None:
            query = query.where(or_(Alert.zone_id == current_user.assigned_zone_id, Alert.zone_id.is_(None)))
        else:
            query = query.where(Alert.zone_id.is_(None))

    result = await db.execute(query)
    alerts = result.scalars().all()
    
    if not alerts:
        return []

    # 2. Fetch read states for these alerts for the current user
    alert_ids = [a.id for a in alerts]
    read_query = select(AlertRead.alert_id).where(
        AlertRead.user_id == current_user.id,
        AlertRead.alert_id.in_(alert_ids)
    )
    read_result = await db.execute(read_query)
    read_alert_ids = set(read_result.scalars().all())

    # 3. Construct response mapping `is_read`
    response = []
    for a in alerts:
        alert_dict = {
            "id": a.id,
            "event_id": a.event_id,
            "zone_id": a.zone_id,
            "target_role": a.target_role,
            "alert_type": a.alert_type.value,
            "severity": a.severity.value,
            "title": a.title,
            "message": a.message,
            "created_at": a.created_at,
            "expires_at": a.expires_at,
            "is_read": a.id in read_alert_ids
        }
        response.append(AlertResponse(**alert_dict))

    return response

@router.patch("/{alert_id}/read", status_code=status.HTTP_200_OK)
async def mark_alert_read(
    alert_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Marks a specific alert as read for the current user.
    """
    # Verify alert exists and is targeted to user role
    query = select(Alert).where(Alert.id == alert_id, Alert.target_role == current_user.role)
    if current_user.role != UserRole.ADMIN and current_user.assigned_event_id:
        query = query.where(Alert.event_id == current_user.assigned_event_id)
        
    result = await db.execute(query)
    alert = result.scalar_one_or_none()
    
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found or access denied")

    # Check if already read
    read_query = select(AlertRead).where(
        AlertRead.alert_id == alert_id,
        AlertRead.user_id == current_user.id
    )
    read_result = await db.execute(read_query)
    if read_result.scalar_one_or_none():
        return {"status": "ok"} # Already read

    new_read = AlertRead(
        alert_id=alert_id,
        user_id=current_user.id,
        read_at=datetime.now(timezone.utc)
    )
    db.add(new_read)
    await db.commit()
    
    return {"status": "ok"}

@router.patch("/read-all", status_code=status.HTTP_200_OK)
async def mark_all_alerts_read(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Marks all active alerts for the user's role as read.
    """
    now = datetime.now(timezone.utc)
    query = select(Alert.id).where(
        Alert.target_role == current_user.role,
        Alert.expires_at > now
    )
    
    if current_user.role != UserRole.ADMIN and current_user.assigned_event_id:
        query = query.where(Alert.event_id == current_user.assigned_event_id)
        
    result = await db.execute(query)
    active_alert_ids = result.scalars().all()
    
    if not active_alert_ids:
        return {"status": "ok", "marked_count": 0}

    # Find which ones are already read
    read_query = select(AlertRead.alert_id).where(
        AlertRead.user_id == current_user.id,
        AlertRead.alert_id.in_(active_alert_ids)
    )
    read_result = await db.execute(read_query)
    read_alert_ids = set(read_result.scalars().all())

    # Create AlertRead entries for unread ones
    unread_ids = [aid for aid in active_alert_ids if aid not in read_alert_ids]
    
    for aid in unread_ids:
        db.add(AlertRead(
            alert_id=aid,
            user_id=current_user.id,
            read_at=now
        ))

        await db.commit()
        
    return {"status": "ok", "marked_count": len(unread_ids)}

@router.get("/sync", response_model=List[AlertResponse])
async def sync_alerts(
    since_timestamp: datetime = Query(..., description="Fetch alerts created after this timestamp"),
    zone_id: Optional[int] = Query(None, description="Optional zone ID filter for citizens"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Catch-up endpoint for clients to fetch alerts missed during a WebSocket disconnection.
    """
    now = datetime.now(timezone.utc)
    
    # Ensure since_timestamp has timezone info
    if since_timestamp.tzinfo is None:
        since_timestamp = since_timestamp.replace(tzinfo=timezone.utc)
        
    query = select(Alert).where(
        Alert.target_role == current_user.role,
        Alert.created_at > since_timestamp,
        Alert.expires_at > now
    )
    
    if current_user.role != UserRole.ADMIN and current_user.assigned_event_id:
        query = query.where(Alert.event_id == current_user.assigned_event_id)
        
    query = query.order_by(Alert.created_at.desc())

    if current_user.role == UserRole.CITIZEN:
        if current_user.assigned_zone_id is not None:
            query = query.where(or_(Alert.zone_id == current_user.assigned_zone_id, Alert.zone_id.is_(None)))
        else:
            query = query.where(Alert.zone_id.is_(None))

    result = await db.execute(query)
    alerts = result.scalars().all()
    
    if not alerts:
        return []

    # Fetch read states
    alert_ids = [a.id for a in alerts]
    read_query = select(AlertRead.alert_id).where(
        AlertRead.user_id == current_user.id,
        AlertRead.alert_id.in_(alert_ids)
    )
    read_result = await db.execute(read_query)
    read_alert_ids = set(read_result.scalars().all())

    response = []
    for a in alerts:
        alert_dict = {
            "id": a.id,
            "event_id": a.event_id,
            "zone_id": a.zone_id,
            "target_role": a.target_role,
            "alert_type": a.alert_type.value,
            "severity": a.severity.value,
            "title": a.title,
            "message": a.message,
            "created_at": a.created_at,
            "expires_at": a.expires_at,
            "is_read": a.id in read_alert_ids
        }
        response.append(AlertResponse(**alert_dict))

    return response
