import pytest

from app.models.incident import IncidentType, IncidentSeverity, IncidentStatus
from app.schemas.incident import IncidentReportCreate, IncidentStatusUpdate
from app.services.incident_service import IncidentService


@pytest.fixture
def incident_service(db_session):
    return IncidentService(db_session)


@pytest.mark.asyncio
async def test_create_incident_with_zone(incident_service):
    data = IncidentReportCreate(
        event_id=1,
        user_id=1,
        zone_id=10,
        incident_type=IncidentType.CROWD_CONGESTION,
        description="Too many people at gate",
        severity=IncidentSeverity.MEDIUM
    )
    incident = await incident_service.create_incident(data)
    assert incident.id is not None
    assert incident.status == IncidentStatus.OPEN
    assert incident.zone_id == 10


@pytest.mark.asyncio
async def test_create_incident_with_location_resolution(incident_service):
    # Zone 10 is at 40.7128, -74.0060
    data = IncidentReportCreate(
        event_id=1,
        user_id=1,
        latitude=40.7128,
        longitude=-74.0060,
        incident_type=IncidentType.MEDICAL_EMERGENCY,
        description="Someone fainted",
        severity=IncidentSeverity.HIGH
    )
    incident = await incident_service.create_incident(data)
    assert incident.id is not None
    assert incident.zone_id == 10  # Resolved automatically


@pytest.mark.asyncio
async def test_invalid_state_transitions(incident_service):
    data = IncidentReportCreate(
        event_id=1, user_id=1, zone_id=10,
        incident_type=IncidentType.OTHER, description="Valid description"
    )
    incident = await incident_service.create_incident(data)
    
    # RESOLVED is terminal
    await incident_service.update_status(incident.id, IncidentStatusUpdate(status=IncidentStatus.RESOLVED))
    
    with pytest.raises(ValueError, match="terminal state"):
        await incident_service.update_status(incident.id, IncidentStatusUpdate(status=IncidentStatus.OPEN))


@pytest.mark.asyncio
async def test_valid_state_transitions(incident_service):
    data = IncidentReportCreate(
        event_id=1, user_id=1, zone_id=10,
        incident_type=IncidentType.OTHER, description="Valid description"
    )
    incident = await incident_service.create_incident(data)
    
    # OPEN -> INVESTIGATING
    incident = await incident_service.update_status(incident.id, IncidentStatusUpdate(status=IncidentStatus.INVESTIGATING))
    assert incident.status == IncidentStatus.INVESTIGATING
    
    # INVESTIGATING -> REJECTED
    incident = await incident_service.update_status(incident.id, IncidentStatusUpdate(status=IncidentStatus.REJECTED))
    assert incident.status == IncidentStatus.REJECTED


@pytest.mark.asyncio
async def test_retrieve_and_filter(incident_service):
    await incident_service.create_incident(IncidentReportCreate(
        event_id=1, user_id=1, zone_id=10, incident_type=IncidentType.OTHER, description="Test 1 description"
    ))
    await incident_service.create_incident(IncidentReportCreate(
        event_id=1, user_id=1, zone_id=20, incident_type=IncidentType.OTHER, description="Test 2 description"
    ))
    await incident_service.create_incident(IncidentReportCreate(
        event_id=2, user_id=1, zone_id=10, incident_type=IncidentType.OTHER, description="Test 3 description"
    ))
    
    # Filter by event
    ev1 = await incident_service.list_incidents(event_id=1)
    assert len(ev1) == 2
    
    # Filter by zone
    z10 = await incident_service.list_incidents(zone_id=10)
    assert len(z10) == 2
    
    # Filter by both
    both = await incident_service.list_incidents(event_id=1, zone_id=10)
    assert len(both) == 1
    assert both[0].description == "Test 1 description"
