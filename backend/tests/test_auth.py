import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.models.user import UserRole
from app.api.dependencies import get_current_user
import json

@pytest.fixture
def clean_app(app):
    # Remove the mock get_current_user dependency specifically for auth tests
    if get_current_user in app.dependency_overrides:
        del app.dependency_overrides[get_current_user]
    yield app

@pytest.mark.asyncio
async def test_register_user(clean_app, db_session):
    async with AsyncClient(transport=ASGITransport(app=clean_app), base_url="http://test") as ac:
        response = await ac.post("/api/v1/auth/register", json={
            "email": "citizen@example.com",
            "password": "strongpassword",
            "role": "CITIZEN"
        })
    
    assert response.status_code == 201
    data = response.json()
    assert data["email"] == "citizen@example.com"
    assert data["role"] == "CITIZEN"
    assert "id" in data
    
@pytest.mark.asyncio
async def test_register_duplicate_user(clean_app, db_session):
    async with AsyncClient(transport=ASGITransport(app=clean_app), base_url="http://test") as ac:
        await ac.post("/api/v1/auth/register", json={
            "email": "duplicate@example.com",
            "password": "strongpassword",
            "role": "CITIZEN"
        })
        
        response = await ac.post("/api/v1/auth/register", json={
            "email": "duplicate@example.com",
            "password": "anotherpassword",
            "role": "AUTHORITY"
        })
        
    assert response.status_code == 400
    assert "already exists" in response.json()["detail"]

@pytest.mark.asyncio
async def test_login_user(clean_app, db_session):
    async with AsyncClient(transport=ASGITransport(app=clean_app), base_url="http://test") as ac:
        await ac.post("/api/v1/auth/register", json={
            "email": "login@example.com",
            "password": "strongpassword",
            "role": "AUTHORITY"
        })
        
        response = await ac.post("/api/v1/auth/login", json={
            "email": "login@example.com",
            "password": "strongpassword"
        })
        
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"

@pytest.mark.asyncio
async def test_login_invalid_password(clean_app, db_session):
    async with AsyncClient(transport=ASGITransport(app=clean_app), base_url="http://test") as ac:
        await ac.post("/api/v1/auth/register", json={
            "email": "badpass@example.com",
            "password": "strongpassword",
            "role": "AUTHORITY"
        })
        
        response = await ac.post("/api/v1/auth/login", json={
            "email": "badpass@example.com",
            "password": "wrongpassword"
        })
        
    assert response.status_code == 401
