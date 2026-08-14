from fastapi import FastAPI
from app.core.config import settings

app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    openapi_url=f"{settings.API_V1_STR}/openapi.json"
)

@app.get("/")
def read_root():
    return {"message": "CrowdShield AI API is running"}

@app.get("/health")
def health_check():
    # In a real scenario, you could check db connectivity here.
    # For now, return basic application health status.
    return {
        "status": "healthy",
        "version": settings.VERSION,
        "environment": settings.APP_ENV
    }
