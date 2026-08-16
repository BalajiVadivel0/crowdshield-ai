"""
Shared pytest fixtures for CrowdShield backend tests.

Since tests in this suite do not require a database connection, there is
no DB fixture here. All tested modules are pure Python (no async, no ORM).

If DB integration tests are added later, an async session fixture should
be added here using pytest-asyncio and a test database URL.
"""

import sys
import os
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from fastapi.testclient import TestClient

# Ensure the backend/ root is on sys.path so that `from app.xxx import yyy` works
# when pytest is invoked from the backend/ directory.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.database import Base
from app.api.dependencies import get_db, get_current_user
import app.models  # Ensure all models are registered
from app.main import app as _app
from app.models.user import User, UserRole

# Use in-memory SQLite for testing
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

engine = create_async_engine(
    TEST_DATABASE_URL,
    echo=False,
    future=True
)

TestingSessionLocal = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)

@pytest_asyncio.fixture
async def db_session():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    
    async with TestingSessionLocal() as session:
        yield session

@pytest.fixture
def async_client():
    # Wait, the tests actually use a synchronous TestClient now.
    pass

@pytest.fixture
def app(db_session):
    async def override_get_db():
        yield db_session
        
    async def override_get_current_user():
        # Mock an AUTHORITY user for legacy tests
        user = User(
            id=1,
            email="test_authority@example.com",
            hashed_password="mocked_hash",
            role=UserRole.AUTHORITY
        )
        return user

    _app.dependency_overrides[get_db] = override_get_db
    _app.dependency_overrides[get_current_user] = override_get_current_user
    yield _app
    _app.dependency_overrides.clear()

