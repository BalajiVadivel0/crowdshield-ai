"""
Crowd Intelligence Service.

Aggregates zone-level observations, risks, and predictions into a unified
event-level safety picture.
"""

from typing import List, Dict
from datetime import datetime, timezone

from app.schemas.crowd_reading import CrowdReadingCreate
from app.ai.risk_engine.models import RiskAssessment, RiskLevel, RiskType
from app.ai.prediction_engine.models import PredictionResult, TrendDirection
from app.schemas.crowd_intelligence import EventCrowdIntelligence, ZoneSummary, PropagationStatus


class CrowdIntelligenceService:
    """
    Stateless orchestrator that aggregates zone data into an event-level snapshot.
    """

    def aggregate(
        self,
        event_id: int,
        readings: List[CrowdReadingCreate],
        assessments: List[RiskAssessment],
        predictions: List[PredictionResult]
    ) -> EventCrowdIntelligence:
        """
        Produce a unified event-level intelligence object from current zone states.
        
        Gracefully handles empty lists (e.g. at event start).
        """
        now = datetime.now(timezone.utc)
        
        if not readings or not assessments or not predictions:
            return self._build_empty_intelligence(event_id, now)

        # Map by zone_id for easy correlation
        r_map = {r.zone_id: r for r in readings}
        a_map = {a.zone_id: a for a in assessments}
        p_map = {p.zone_id: p for p in predictions}
        
        valid_zone_ids = set(r_map.keys()) & set(a_map.keys()) & set(p_map.keys())
        if not valid_zone_ids:
            return self._build_empty_intelligence(event_id, now)
            
        zone_summaries = []
        
        # Counters and aggregates
        total_people = 0
        sum_density = 0.0
        max_density = 0.0
        sum_speed = 0.0
        
        congestion_zones = 0
        critical_zones = 0
        high_risk_zones = 0
        worsening_zones = 0
        improving_zones = 0
        
        flags = set()
        
        for z_id in valid_zone_ids:
            r = r_map[z_id]
            a = a_map[z_id]
            p = p_map[z_id]
            
            # Aggregate metrics
            total_people += r.person_count
            sum_density += r.density_percent
            max_density = max(max_density, r.density_percent)
            sum_speed += r.average_speed
            
            if r.congestion_score >= 70.0:
                congestion_zones += 1
            if a.level == RiskLevel.CRITICAL:
                critical_zones += 1
                flags.add("CRITICAL_ZONE_PRESENT")
            elif a.level == RiskLevel.HIGH:
                high_risk_zones += 1
                
            if p.trend_direction == TrendDirection.WORSENING:
                worsening_zones += 1
            elif p.trend_direction == TrendDirection.IMPROVING:
                improving_zones += 1
                
            if p.time_to_critical_minutes is not None and p.time_to_critical_minutes < 10.0:
                flags.add("RAPID_RISK_ESCALATION")
                
            if r.reverse_flow_indicator:
                flags.add("REVERSE_FLOW_DETECTED")
            if r.surge_indicator:
                flags.add("CROWD_SURGE_DETECTED")
            
            # Compute urgency score (higher is more urgent)
            urgency = self._compute_urgency(r, a, p)
            
            # Extract forecasts (assuming 5, 10, 15 horizons are present, otherwise fallback)
            f_5 = next((f.predicted_score for f in p.forecasts if f.horizon_minutes == 5), a.score)
            f_10 = next((f.predicted_score for f in p.forecasts if f.horizon_minutes == 10), a.score)
            f_15 = next((f.predicted_score for f in p.forecasts if f.horizon_minutes == 15), a.score)
            
            summary = ZoneSummary(
                zone_id=z_id,
                current_score=a.score,
                current_level=a.level,
                current_risk_type=a.risk_type,
                person_count=r.person_count,
                density_percent=r.density_percent,
                average_speed=r.average_speed,
                congestion_score=r.congestion_score,
                surge_active=r.surge_indicator,
                reverse_flow_active=r.reverse_flow_indicator,
                bottleneck_active=r.bottleneck_indicator,
                trend=p.trend_direction,
                confidence=p.confidence,
                predicted_5m_score=f_5,
                predicted_10m_score=f_10,
                predicted_15m_score=f_15,
                time_to_critical=p.time_to_critical_minutes,
                urgency_score=urgency
            )
            zone_summaries.append(summary)
            
        # Sort zones by urgency descending
        zone_summaries.sort(key=lambda x: x.urgency_score, reverse=True)
        priority_zones = [z.zone_id for z in zone_summaries]
        
        # Compute overall event risk
        # Strategy: Max zone score + weighted contribution from other zones
        scores = [z.current_score for z in zone_summaries]
        max_score = scores[0] if scores else 0.0
        other_scores = scores[1:]
        
        if other_scores:
            contribution = (sum(other_scores) / len(other_scores)) * 0.15
        else:
            contribution = 0.0
            
        overall_score = min(100.0, max_score + contribution)
        overall_level = self._score_to_level(overall_score)
        
        highest_summary = zone_summaries[0]
        
        # Event Trend
        if worsening_zones > improving_zones:
            event_trend = TrendDirection.WORSENING
        elif improving_zones > worsening_zones:
            event_trend = TrendDirection.IMPROVING
        else:
            event_trend = TrendDirection.STABLE
            
        # Cross-zone patterns
        if congestion_zones > 1:
            flags.add("MULTI_ZONE_CONGESTION")
            
        propagation = PropagationStatus.NONE
        if worsening_zones >= 2 or "REVERSE_FLOW_DETECTED" in flags:
            propagation = PropagationStatus.DEVELOPING
            
        if congestion_zones > 1 and worsening_zones >= 2:
            propagation = PropagationStatus.ELEVATED
            flags.add("RISK_PROPAGATION_DETECTED")
            
        if critical_zones >= 2 and worsening_zones >= 2:
            propagation = PropagationStatus.SEVERE
            flags.add("RISK_PROPAGATION_DETECTED")
            
        num_zones = len(valid_zone_ids)
        
        return EventCrowdIntelligence(
            event_id=event_id,
            generated_at=now,
            overall_risk_score=round(overall_score, 2),
            overall_risk_level=overall_level,
            event_trend=event_trend,
            highest_risk_zone=highest_summary.zone_id,
            highest_risk_type=highest_summary.current_risk_type,
            total_people=total_people,
            average_density=round(sum_density / num_zones, 2),
            highest_density=round(max_density, 2),
            average_speed=round(sum_speed / num_zones, 2),
            congestion_zone_count=congestion_zones,
            critical_zone_count=critical_zones,
            high_risk_zone_count=high_risk_zones,
            worsening_zone_count=worsening_zones,
            propagation_status=propagation,
            event_flags=sorted(list(flags)),
            zone_summaries=zone_summaries,
            priority_zones=priority_zones
        )
        
    def _compute_urgency(self, r: CrowdReadingCreate, a: RiskAssessment, p: PredictionResult) -> float:
        """
        Computes a scalar urgency score used solely for ranking priority zones.
        """
        urgency = a.score
        
        # Penalize worsening trends
        if p.trend_direction == TrendDirection.WORSENING:
            urgency += 10.0
            
        # Urgency spikes if time to critical is low
        if p.time_to_critical_minutes is not None:
            # e.g. 5 minutes -> +20 urgency, 30 minutes -> +0 urgency
            urgency += max(0.0, 25.0 - p.time_to_critical_minutes)
            
        # Physical factors
        urgency += (r.density_percent * 0.1)
        urgency += (r.congestion_score * 0.1)
        
        return urgency

    def _score_to_level(self, score: float) -> RiskLevel:
        if score >= 80.0:
            return RiskLevel.CRITICAL
        elif score >= 60.0:
            return RiskLevel.HIGH
        elif score >= 35.0:
            return RiskLevel.MEDIUM
        return RiskLevel.LOW
        
    def _build_empty_intelligence(self, event_id: int, now: datetime) -> EventCrowdIntelligence:
        return EventCrowdIntelligence(
            event_id=event_id,
            generated_at=now,
            overall_risk_score=0.0,
            overall_risk_level=RiskLevel.LOW,
            event_trend=TrendDirection.STABLE,
            highest_risk_zone=None,
            highest_risk_type=None,
            total_people=0,
            average_density=0.0,
            highest_density=0.0,
            average_speed=0.0,
            congestion_zone_count=0,
            critical_zone_count=0,
            high_risk_zone_count=0,
            worsening_zone_count=0,
            propagation_status=PropagationStatus.NONE,
            event_flags=[],
            zone_summaries=[],
            priority_zones=[]
        )
