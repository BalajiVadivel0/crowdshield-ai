from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
import logging

from app.core.database import AsyncSessionLocal
from app.core.config import settings
from app.models.user import User, UserRole

logger = logging.getLogger(__name__)

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    Dependency function that yields an async database session.
    """
    async with AsyncSessionLocal() as session:
        yield session

security = HTTPBearer()

async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db)
) -> User:
    token = credentials.credentials
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    if token == "dummy_token_for_mvp":
        # Create a mock user for the MVP flutter app
        return User(id=1, email="demo@example.com", role=UserRole.AUTHORITY, is_active=True, assigned_event_id=1, assigned_zone_id=1)
    
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
        user_id: str = payload.get("sub")
        if user_id is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
        
    stmt = select(User).where(User.id == int(user_id))
    result = await db.execute(stmt)
    user = result.scalars().first()
    
    if user is None:
        raise credentials_exception
    if not user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")
        
    return user

class RequireRole:
    def __init__(self, required_roles: list[UserRole] | UserRole):
        if not isinstance(required_roles, list):
            required_roles = [required_roles]
        self.required_roles = required_roles

    async def __call__(self, current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in self.required_roles:
            if current_user.role != UserRole.ADMIN:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Not enough permissions"
                )
        return current_user

require_authority = RequireRole(UserRole.AUTHORITY)
require_citizen = RequireRole(UserRole.CITIZEN)

def verify_event_access(event_id: int, current_user: User = Depends(get_current_user)) -> int:
    if current_user.role != UserRole.ADMIN:
        if not current_user.assigned_event_id or current_user.assigned_event_id != event_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access to this event is forbidden"
            )
    return event_id

from app.models.zone import Zone

async def verify_zone_access(
    zone_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
) -> int:
    result = await db.execute(select(Zone).where(Zone.id == zone_id))
    zone = result.scalar_one_or_none()
    if not zone:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Zone not found")
    
    if current_user.role != UserRole.ADMIN:
        if not current_user.assigned_event_id or current_user.assigned_event_id != zone.event_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access to this zone is forbidden"
            )
    return zone_id
