from fastapi import FastAPI
from app.core.config import settings
from app.api.v1.endpoints import interventions, incidents, ws, events, zones, crowd_readings, risk, intelligence

app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    openapi_url=f"{settings.API_V1_STR}/openapi.json"
)

app.include_router(events.router, prefix=f"{settings.API_V1_STR}/events", tags=["events"])
app.include_router(zones.router, prefix=f"{settings.API_V1_STR}/zones", tags=["zones"])
app.include_router(crowd_readings.router, prefix=f"{settings.API_V1_STR}/crowd-readings", tags=["crowd readings"])
app.include_router(risk.router, prefix=f"{settings.API_V1_STR}/risk", tags=["risk assessment"])
app.include_router(intelligence.router, prefix=f"{settings.API_V1_STR}/crowd-intelligence", tags=["crowd intelligence"])
app.include_router(interventions.router, prefix=f"{settings.API_V1_STR}/interventions", tags=["interventions"])
app.include_router(incidents.router, prefix=f"{settings.API_V1_STR}/incidents", tags=["incidents"])
app.include_router(ws.router, prefix=f"{settings.API_V1_STR}/ws", tags=["websocket"])

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
