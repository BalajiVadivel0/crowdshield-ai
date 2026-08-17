import 'package:flutter_test/flutter_test.dart';
import '../../../lib/features/authority/data/authority_models.dart';
import '../../../lib/features/authority/data/recommendation_models.dart';

void main() {
  group('Authority Models Parsing', () {
    test('ZoneConnection parses correctly with status', () {
      final json = {
        'id': 1,
        'source_zone_id': 10,
        'dest_zone_id': 20,
        'distance': 15.5,
        'capacity': 1000,
        'is_bidirectional': true,
        'status': 'RESTRICTED'
      };

      final conn = ZoneConnection.fromJson(json);

      expect(conn.id, 1);
      expect(conn.sourceZoneId, 10);
      expect(conn.status, 'RESTRICTED');
    });

    test('ZoneConnection defaults to OPEN if status is missing', () {
      final json = {
        'id': 1,
        'source_zone_id': 10,
        'dest_zone_id': 20,
        'distance': 15.5,
        'capacity': 1000,
        'is_bidirectional': true,
      };

      final conn = ZoneConnection.fromJson(json);

      expect(conn.status, 'OPEN');
    });

    test('ZoneSummary parses networkImpacts', () {
      final json = {
        'zone_id': 1,
        'current_score': 85.0,
        'current_level': 'HIGH',
        'current_risk_type': 'CONGESTION',
        'person_count': 500,
        'density_percent': 80.0,
        'average_speed': 0.5,
        'congestion_score': 70.0,
        'trend': 'STABLE',
        'confidence': 90.0,
        'predicted_5m_score': 88.0,
        'predicted_10m_score': 90.0,
        'predicted_15m_score': 92.0,
        'urgency_score': 10.0,
        'network_impacts': [
          {
            'source_zone_id': '1',
            'destination_zone_id': '2',
            'estimated_flow': 50.0,
            'propagation_time': 2.0,
            'source_pressure': 80.0,
            'destination_pressure_change': 15.0,
            'reason': 'High pressure in Zone 1 pushing to Zone 2'
          }
        ]
      };

      final summary = ZoneSummary.fromJson(json);

      expect(summary.networkImpacts.length, 1);
      expect(summary.networkImpacts.first.destinationZoneId, '2');
      expect(summary.networkImpacts.first.destinationPressureChange, 15.0);
    });

    test('RecommendationSimulationResponse parses fully supported simulation metrics', () {
      final json = {
        'recommendation_id': 1,
        'simulated': true,
        'baseline_peak_network_risk': 95.0,
        'scenario_peak_network_risk': 70.0,
        'risk_reduction_delta': 25.0,
        'risk_reduction_percentage': 26.3,
        'critical_zone_count': 0,
        'high_risk_zone_count': 1,
        'scenario_score': 85.0,
        'simulation_horizon_minutes': 15,
        'explanation': 'Redirecting flow reduces congestion by 26%'
      };

      final res = RecommendationSimulationResponse.fromJson(json);

      expect(res.recommendationId, 1);
      expect(res.simulated, true);
      expect(res.baselinePeakNetworkRisk, 95.0);
      expect(res.scenarioPeakNetworkRisk, 70.0);
      expect(res.explanation, 'Redirecting flow reduces congestion by 26%');
    });

    test('RecommendationSimulationResponse parses nullable unsupported simulation', () {
      final json = {
        'recommendation_id': 2,
        'simulated': false,
      };

      final res = RecommendationSimulationResponse.fromJson(json);

      expect(res.recommendationId, 2);
      expect(res.simulated, false);
      expect(res.baselinePeakNetworkRisk, isNull);
      expect(res.scenarioPeakNetworkRisk, isNull);
      expect(res.explanation, isNull);
    });
  });
}
