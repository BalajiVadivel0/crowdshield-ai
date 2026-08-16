from typing import List, Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.models.incident import IncidentReport, IncidentStatus
from app.schemas.incident import IncidentReportCreate, IncidentStatusUpdate
from app.services.location_service import LocationService


class IncidentService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_incident(self, data: IncidentReportCreate) -> IncidentReport:
        """Create a new incident report."""
        zone_id = data.zone_id
        
        # If no zone is provided but we have coordinates, resolve the zone automatically
        if zone_id is None and data.latitude is not None and data.longitude is not None:
            zone_id = LocationService.resolve_zone(data.latitude, data.longitude)

        incident = IncidentReport(
            event_id=data.event_id,
            user_id=data.user_id,
            zone_id=zone_id,
            incident_type=data.incident_type,
            description=data.description,
            latitude=data.latitude,
            longitude=data.longitude,
            severity=data.severity,
            status=IncidentStatus.OPEN
        )
        
        self.session.add(incident)
        await self.session.commit()
        await self.session.refresh(incident)
        return incident

    async def get_incident(self, incident_id: int) -> Optional[IncidentReport]:
        """Fetch a single incident by ID."""
        query = select(IncidentReport).where(IncidentReport.id == incident_id)
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def list_incidents(self, event_id: Optional[int] = None, zone_id: Optional[int] = None) -> List[IncidentReport]:
        """List incidents with optional filtering."""
        query = select(IncidentReport)
        
        if event_id is not None:
            query = query.where(IncidentReport.event_id == event_id)
        if zone_id is not None:
            query = query.where(IncidentReport.zone_id == zone_id)
            
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def update_status(self, incident_id: int, status_update: IncidentStatusUpdate) -> IncidentReport:
        """Update incident status enforcing state transition rules."""
        incident = await self.get_incident(incident_id)
        if not incident:
            raise ValueError("Incident not found")

        current_status = incident.status
        new_status = status_update.status
        
        # Terminal states
        if current_status in (IncidentStatus.RESOLVED, IncidentStatus.REJECTED):
            raise ValueError(f"Cannot transition from terminal state {current_status.value}")

        # Strict forward transitions
        if current_status == IncidentStatus.OPEN:
            if new_status not in (IncidentStatus.ACKNOWLEDGED, IncidentStatus.INVESTIGATING, IncidentStatus.REJECTED, IncidentStatus.RESOLVED):
                raise ValueError(f"Invalid transition from {current_status.value} to {new_status.value}")
                
        elif current_status == IncidentStatus.ACKNOWLEDGED:
            if new_status not in (IncidentStatus.INVESTIGATING, IncidentStatus.RESOLVED, IncidentStatus.REJECTED):
                raise ValueError(f"Invalid transition from {current_status.value} to {new_status.value}")
                
        elif current_status == IncidentStatus.INVESTIGATING:
            if new_status not in (IncidentStatus.RESOLVED, IncidentStatus.REJECTED):
                raise ValueError(f"Invalid transition from {current_status.value} to {new_status.value}")

        incident.status = new_status
        await self.session.commit()
        await self.session.refresh(incident)
        
        return incident
