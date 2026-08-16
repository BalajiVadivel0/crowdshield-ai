from typing import List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.models.zone import Zone, ZoneStatus
from app.models.zone_connection import ZoneConnection
from app.models.risk_assessment import RiskAssessmentRecord
from app.ai.routing.engine import SafeRoutingEngine
from app.ai.routing.graph import VenueGraph
from app.ai.routing.models import VenueNode, NodeType, VenueEdge, RouteType, RoutingWeights, SafeRouteResult


class RoutingService:
    """
    Stateless service to bridge the database and SafeRoutingEngine.
    Retrieves zones, connectivity, and current risk data to build a VenueGraph.
    """

    @staticmethod
    async def build_venue_graph(db: AsyncSession, event_id: int) -> VenueGraph:
        """
        Builds a VenueGraph for the specified event from current database state.
        """
        graph = VenueGraph()

        # 1. Fetch Zones
        result_zones = await db.execute(select(Zone).where(Zone.event_id == event_id))
        zones = result_zones.scalars().all()
        
        if not zones:
            return graph
            
        zone_ids = [z.id for z in zones]

        # 2. Fetch Latest Risk Assessments for these zones
        # In a real app we might want the absolute latest, but here we can just order by created_at desc
        # Alternatively, assume the RiskEngine keeps the latest risk in some table.
        # For Phase 4 we will fetch the most recent RiskAssessmentRecord per zone.
        risk_scores = {}
        for zid in zone_ids:
            # Get latest risk assessment
            stmt = select(RiskAssessmentRecord).where(
                RiskAssessmentRecord.zone_id == zid
            ).order_by(RiskAssessmentRecord.created_at.desc()).limit(1)
            ra_res = await db.execute(stmt)
            ra = ra_res.scalars().first()
            if ra:
                risk_scores[zid] = ra.risk_score
            else:
                risk_scores[zid] = 0.0

        # Add Nodes to Graph
        for zone in zones:
            node_type = NodeType.EXIT if zone.is_exit else NodeType.ZONE
            available = zone.status == ZoneStatus.ACTIVE
            
            node = VenueNode(
                node_id=str(zone.id),
                name=zone.name,
                node_type=node_type,
                capacity=zone.capacity,
                current_crowd=0, # To be integrated with crowd readings if needed
                risk_score=risk_scores.get(zone.id, 0.0),
                predicted_risk_score=0.0,
                available=available
            )
            graph.add_node(node)

        # 3. Fetch Connections
        # Get connections where either source or dest is in our zones
        result_conn = await db.execute(
            select(ZoneConnection).where(ZoneConnection.source_zone_id.in_(zone_ids))
        )
        connections = result_conn.scalars().all()

        for conn in connections:
            edge = VenueEdge(
                source_id=str(conn.source_zone_id),
                dest_id=str(conn.dest_zone_id),
                distance=conn.distance,
                capacity=conn.capacity,
                current_crowd=0,
                risk_score=0.0, # Corridors inherit max risk of zones in Engine
                predicted_risk_score=0.0,
                available=True,
                bidirectional=conn.is_bidirectional
            )
            try:
                graph.add_edge(edge)
            except ValueError:
                # Node might not exist in this event (e.g. cross-event edge which is anomalous)
                pass

        return graph

    @classmethod
    async def get_safe_route(
        cls,
        db: AsyncSession,
        event_id: int,
        source_zone_id: int,
        dest_zone_id: int,
        avoid_zone_ids: Optional[List[int]] = None
    ) -> SafeRouteResult:
        graph = await cls.build_venue_graph(db, event_id)
        engine = SafeRoutingEngine()
        
        avoid_str = [str(z) for z in avoid_zone_ids] if avoid_zone_ids else []
        
        return engine.find_safe_route(
            graph=graph,
            source_id=str(source_zone_id),
            destination_id=str(dest_zone_id),
            route_type=RouteType.SAFE_EXIT,
            weights=RoutingWeights(),
            avoid_zone_ids=avoid_str
        )

    @classmethod
    async def get_safest_exit(
        cls,
        db: AsyncSession,
        event_id: int,
        source_zone_id: int,
        avoid_zone_ids: Optional[List[int]] = None
    ) -> SafeRouteResult:
        graph = await cls.build_venue_graph(db, event_id)
        engine = SafeRoutingEngine()
        
        avoid_str = [str(z) for z in avoid_zone_ids] if avoid_zone_ids else []
        
        return engine.find_safest_exit(
            graph=graph,
            source_id=str(source_zone_id),
            route_type=RouteType.SAFE_EXIT,
            weights=RoutingWeights(),
            avoid_zone_ids=avoid_str
        )
