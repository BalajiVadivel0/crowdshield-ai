"""
Deterministic Near-Term Prediction Engine.

Forecasts crowd risk 5, 10, and 15 minutes into the future based on
recent history using simple linear extrapolation of key risk components.
"""

from datetime import datetime, timezone
from typing import List, Optional

from app.ai.risk_engine.models import (
    RiskAssessment,
    RiskLevel,
    RiskType,
    RISK_THRESHOLD_LOW,
    RISK_THRESHOLD_MEDIUM,
    RISK_THRESHOLD_HIGH,
    CROWD_CRUSH_DENSITY_THRESHOLD,
    DENSITY_RISK_HIGH_THRESHOLD,
)
from app.ai.prediction_engine.models import (
    ForecastPoint,
    PredictionResult,
    SupportingMetrics,
    TrendDirection,
)


class PredictionEngine:
    """
    Evaluates a time-series of RiskAssessments to forecast future risk.
    """

    def __init__(self, min_observations: int = 3, trend_deadband: float = 0.5):
        """
        Args:
            min_observations: Minimum number of historical points required to make a forecast.
            trend_deadband: Threshold (points per min) to consider a trend WORSENING or IMPROVING.
        """
        self.min_observations = min_observations
        self.trend_deadband = trend_deadband

    def predict(self, history: List[RiskAssessment]) -> PredictionResult:
        """
        Produce a PredictionResult from a chronological list of recent RiskAssessments.
        """
        if not history:
            return self._insufficient_data_result(
                event_id=0, zone_id=0, explanation="INSUFFICIENT_DATA: Empty history."
            )

        # 1. Sort history chronologically based on source_timestamp
        # Ignore items without a timestamp
        valid_history = []
        for r in history:
            if r.source_timestamp:
                try:
                    dt = datetime.fromisoformat(r.source_timestamp)
                    valid_history.append((dt, r))
                except ValueError:
                    pass
        
        valid_history.sort(key=lambda x: x[0])

        if len(valid_history) < self.min_observations:
            last = history[-1]
            return self._insufficient_data_result(
                event_id=last.event_id,
                zone_id=last.zone_id,
                explanation=f"INSUFFICIENT_DATA: Need at least {self.min_observations} valid observations.",
            )

        # Deduplicate timestamps if they are exactly the same
        unique_history = []
        seen = set()
        for dt, r in valid_history:
            if dt not in seen:
                seen.add(dt)
                unique_history.append((dt, r))

        if len(unique_history) < self.min_observations:
            last = unique_history[-1][1] if unique_history else history[-1]
            return self._insufficient_data_result(
                event_id=last.event_id,
                zone_id=last.zone_id,
                explanation=f"INSUFFICIENT_DATA: Not enough unique timestamps.",
            )

        # 2. Extract time series features
        # X-axis will be minutes relative to the first observation
        base_time = unique_history[0][0]
        x_mins = [(dt - base_time).total_seconds() / 60.0 for dt, r in unique_history]
        
        scores = [r.score for dt, r in unique_history]
        densities = [r.features.density_risk for dt, r in unique_history]
        speeds = [r.features.speed_reduction_risk for dt, r in unique_history]
        
        # 3. Calculate slopes (linear regression)
        score_slope = self._calc_slope(x_mins, scores)
        density_slope = self._calc_slope(x_mins, densities)
        speed_slope = self._calc_slope(x_mins, speeds)

        # 4. Determine trend direction
        if score_slope > self.trend_deadband:
            trend_dir = TrendDirection.WORSENING
        elif score_slope < -self.trend_deadband:
            trend_dir = TrendDirection.IMPROVING
        else:
            trend_dir = TrendDirection.STABLE

        # 5. Compute confidence
        confidence = self._compute_confidence(x_mins, scores, score_slope)

        # 6. Forecast horizons
        current_time = unique_history[-1][0]
        current_x = x_mins[-1]
        last_assessment = unique_history[-1][1]
        
        horizons = [5, 10, 15]
        forecasts = []
        for h in horizons:
            forecast_x = current_x + h
            # Extrapolate score
            projected_score = score_slope * (forecast_x - current_x) + last_assessment.score
            projected_score = max(0.0, min(100.0, projected_score))
            
            # Extrapolate components roughly to help determine risk type
            projected_density = max(0.0, min(100.0, density_slope * h + last_assessment.features.density_risk))
            projected_speed = max(0.0, min(100.0, speed_slope * h + last_assessment.features.speed_reduction_risk))
            
            p_level = self._score_to_level(projected_score)
            p_type = self._forecast_risk_type(
                last_assessment, projected_score, projected_density, projected_speed
            )
            
            forecasts.append(
                ForecastPoint(
                    horizon_minutes=h,
                    predicted_score=round(projected_score, 2),
                    predicted_level=p_level,
                    predicted_risk_type=p_type
                )
            )

        # 7. Time to critical
        time_to_critical = None
        # Only estimate time to critical if we have a definitely worsening trend
        if trend_dir == TrendDirection.WORSENING and last_assessment.score < RISK_THRESHOLD_HIGH:
            # How many minutes to reach RISK_THRESHOLD_HIGH + 0.01 (the CRITICAL threshold start)
            points_needed = (RISK_THRESHOLD_HIGH + 0.01) - last_assessment.score
            ttc = points_needed / score_slope
            # Cap it to a reasonable reporting horizon, e.g., if it's > 60 mins, we can still report it
            # but usually we want positive time.
            if ttc > 0:
                time_to_critical = round(ttc, 1)

        # 8. Explanation
        explanation = self._build_explanation(
            last_assessment, trend_dir, forecasts, time_to_critical, score_slope
        )
        
        metrics = SupportingMetrics(
            current_score=last_assessment.score,
            score_trend_slope=round(score_slope, 3),
            density_trend_slope=round(density_slope, 3),
            speed_trend_slope=round(speed_slope, 3),
            current_risk_type=last_assessment.risk_type
        )

        return PredictionResult(
            event_id=last_assessment.event_id,
            zone_id=last_assessment.zone_id,
            generated_at=datetime.now(timezone.utc),
            confidence=round(confidence, 1),
            trend_direction=trend_dir,
            forecasts=forecasts,
            time_to_critical_minutes=time_to_critical,
            explanation=explanation,
            supporting_metrics=metrics
        )

    def _insufficient_data_result(self, event_id: int, zone_id: int, explanation: str) -> PredictionResult:
        return PredictionResult(
            event_id=event_id,
            zone_id=zone_id,
            generated_at=datetime.now(timezone.utc),
            confidence=0.0,
            trend_direction=TrendDirection.STABLE,
            forecasts=[],
            time_to_critical_minutes=None,
            explanation=explanation,
        )

    def _calc_slope(self, x: List[float], y: List[float]) -> float:
        """Simple linear regression slope."""
        if len(x) < 2:
            return 0.0
        n = len(x)
        sum_x = sum(x)
        sum_y = sum(y)
        sum_xy = sum(xi * yi for xi, yi in zip(x, y))
        sum_xx = sum(xi * xi for xi in x)
        
        denominator = (n * sum_xx - sum_x * sum_x)
        if denominator == 0:
            return 0.0
        
        slope = (n * sum_xy - sum_x * sum_y) / denominator
        return slope

    def _compute_confidence(self, x: List[float], y: List[float], slope: float) -> float:
        """
        Estimate confidence in the trend based on R-squared like heuristic.
        Penalize highly irregular spacing or small sample sizes.
        """
        n = len(x)
        if n < self.min_observations:
            return 0.0
            
        # Base confidence from sample size (max out around 10 samples)
        base = min(100.0, (n / 10.0) * 100.0)
        
        # Compute mean squared error of the line
        if n >= 2:
            intercept = (sum(y) - slope * sum(x)) / n
            mse = sum((yi - (slope * xi + intercept)) ** 2 for xi, yi in zip(x, y)) / n
            
            # Heuristic penalty: higher MSE means more chaotic history -> lower confidence
            # A 100 MSE means avg deviation is 10 risk points off the trendline.
            penalty = min(base * 0.8, mse * 2.0)
            conf = base - penalty
        else:
            conf = 0.0
            
        return max(10.0, min(100.0, conf))

    def _score_to_level(self, score: float) -> RiskLevel:
        if score <= RISK_THRESHOLD_LOW:
            return RiskLevel.LOW
        if score <= RISK_THRESHOLD_MEDIUM:
            return RiskLevel.MEDIUM
        if score <= RISK_THRESHOLD_HIGH:
            return RiskLevel.HIGH
        return RiskLevel.CRITICAL

    def _forecast_risk_type(
        self,
        last_assessment: RiskAssessment,
        proj_score: float,
        proj_density: float,
        proj_speed: float
    ) -> RiskType:
        """
        Estimate the future risk type based on projected conditions and current active signals.
        """
        # 1. CROWD_CRUSH is the most critical. Check if projected conditions reach crush.
        # proj_speed is speed_reduction_risk. 100% reduction = 0 m/s. 
        # CROWD_CRUSH_SPEED_THRESHOLD is 0.25 m/s. That's a speed deficit of (2.0-0.25)/2.0 = 87.5%
        if proj_density >= CROWD_CRUSH_DENSITY_THRESHOLD and proj_speed >= 87.5:
            return RiskType.CROWD_CRUSH
            
        # 2. BOTTLENECK
        if last_assessment.features.bottleneck_signal:
            return RiskType.BOTTLENECK
            
        # 3. SURGE
        if last_assessment.risk_type == RiskType.CROWD_SURGE and proj_score > RISK_THRESHOLD_MEDIUM:
            return RiskType.CROWD_SURGE
            
        # 4. REVERSE_FLOW
        if last_assessment.features.reverse_flow_signal:
            return RiskType.REVERSE_FLOW
            
        # 5. HIGH_DENSITY
        if proj_density >= DENSITY_RISK_HIGH_THRESHOLD:
            return RiskType.HIGH_DENSITY
            
        # 6. CONGESTION / ANOMALY
        if proj_score > RISK_THRESHOLD_LOW:
            if last_assessment.features.congestion_signal or proj_density > 50.0:
                return RiskType.CONGESTION
            return RiskType.MOVEMENT_ANOMALY
            
        return RiskType.STABLE

    def _build_explanation(
        self,
        last_assessment: RiskAssessment,
        trend_dir: TrendDirection,
        forecasts: List[ForecastPoint],
        time_to_critical: Optional[float],
        score_slope: float
    ) -> str:
        lines = [
            f"Current Risk: {last_assessment.score:.0f} ({last_assessment.level.value})",
            f"Trend: {trend_dir.value} ({score_slope:+.1f} pts/min)"
        ]
        
        if forecasts:
            lines.append("Forecast:")
            for f in forecasts:
                lines.append(f"  +{f.horizon_minutes} min -> {f.predicted_score:.0f} {f.predicted_level.value}")
                
        if time_to_critical is not None:
            lines.append(f"Estimated critical threshold: ~{time_to_critical:.0f} minutes")
            
        # Simple qualitative explanation based on components
        reasons = []
        if score_slope > 0:
            if last_assessment.features.density_risk > 60:
                reasons.append("rising density")
            if last_assessment.features.growth_risk > 40:
                reasons.append("accelerating crowd growth")
            if last_assessment.features.speed_reduction_risk > 60:
                reasons.append("declining movement speed")
            if last_assessment.features.reverse_flow_signal:
                reasons.append("persistent reverse flow")
                
            if reasons:
                explanation_str = "Risk is increasing due to " + ", ".join(reasons) + "."
                lines.append(explanation_str)
                
        return "\n".join(lines)
