import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:mobile/features/digital_twin/data/digital_twin_models.dart';
import 'package:mobile/features/digital_twin/providers/twin_state_provider.dart';
import 'package:mobile/features/digital_twin/providers/venue_provider.dart';
import 'package:mobile/features/authority/providers/event_intelligence_provider.dart';
import 'package:mobile/features/authority/providers/interventions_provider.dart';
import 'package:mobile/features/authority/data/authority_models.dart';

class MockEventIntelligenceNotifier extends EventIntelligenceNotifier {
  final EventCrowdIntelligence mockData;
  MockEventIntelligenceNotifier(this.mockData);

  @override
  Future<EventCrowdIntelligence?> build() async => mockData;
}

class MockInterventionsNotifier extends InterventionsNotifier {
  @override
  Future<List<InterventionResponse>> build() async => [];
}

void main() {
  test('Digital Twin computes circular layout', () async {
    final zones = [
      Zone(id: 1, eventId: 1, name: 'A', capacity: 100, status: 'ACTIVE', isExit: false),
      Zone(id: 2, eventId: 1, name: 'B', capacity: 100, status: 'ACTIVE', isExit: false),
      Zone(id: 3, eventId: 1, name: 'Exit', capacity: 100, status: 'ACTIVE', isExit: true),
    ];

    final venueData = VenueData(zones, []);
    final intelligence = EventCrowdIntelligence(
      eventId: 1,
      generatedAt: DateTime.now(),
      overallRiskScore: 0,
      overallRiskLevel: 'LOW',
      eventTrend: 'STABLE',
      totalPeople: 0,
      averageDensity: 0,
      highestDensity: 0,
      averageSpeed: 0,
      congestionZoneCount: 0,
      criticalZoneCount: 0,
      highRiskZoneCount: 0,
      worseningZoneCount: 0,
      propagationStatus: '',
      eventFlags: [],
      zoneSummaries: [
        ZoneSummary(
          zoneId: 1,
          currentScore: 0,
          currentLevel: 'LOW',
          currentRiskType: 'CROWD',
          personCount: 10,
          densityPercent: 0.1,
          averageSpeed: 1.0,
          congestionScore: 0,
          surgeActive: false,
          reverseFlowActive: false,
          bottleneckActive: false,
          trend: 'STABLE',
          confidence: 0.9,
          predicted5mScore: 0,
          predicted10mScore: 0,
          predicted15mScore: 0,
          urgencyScore: 0,
        ),
      ],
      priorityZones: [],
    );

    final container = ProviderContainer(
      overrides: [
        venueProvider(1).overrideWith((ref) => venueData),
        eventIntelligenceProvider.overrideWith(() => MockEventIntelligenceNotifier(intelligence)),
        interventionsProvider.overrideWith(() => MockInterventionsNotifier()),
      ],
    );

    final state = await container.read(twinStateProvider(1).future);

    expect(state.nodes.length, 3);
    
    final nodeA = state.nodes.firstWhere((n) => n.zone.id == 1);
    final nodeExit = state.nodes.firstWhere((n) => n.zone.id == 3);
    
    // Exit should be placed on a larger radius than normal zones
    final radiusA = (nodeA.x * nodeA.x + nodeA.y * nodeA.y);
    final radiusExit = (nodeExit.x * nodeExit.x + nodeExit.y * nodeExit.y);
    expect(radiusExit > radiusA, isTrue);

    // Intelligence joined
    final summary = state.intelligence.zoneSummaries.first;
    expect(summary.zoneId, 1);
    expect(summary.personCount, 10);
  });
}
