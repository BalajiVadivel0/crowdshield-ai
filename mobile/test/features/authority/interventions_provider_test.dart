import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:mobile/features/authority/providers/interventions_provider.dart';
import 'package:mobile/features/authority/data/authority_models.dart';
import 'package:mobile/features/authority/data/authority_repository.dart';

class MockAuthorityRepository implements AuthorityRepository {
  List<InterventionResponse> mockInterventions = [];

  @override
  Future<List<InterventionResponse>> getInterventions(int eventId) async {
    return mockInterventions;
  }

  @override
  Future<InterventionResponse> requestApproval(int interventionId) async {
    final idx = mockInterventions.indexWhere((i) => i.id == interventionId);
    if (idx != -1) {
      mockInterventions[idx] = InterventionResponse(
        id: mockInterventions[idx].id,
        eventId: mockInterventions[idx].eventId,
        zoneId: mockInterventions[idx].zoneId,
        status: 'PENDING_APPROVAL',
        actions: mockInterventions[idx].actions,
        affectedZones: mockInterventions[idx].affectedZones,
        beforeRiskScore: mockInterventions[idx].beforeRiskScore,
        createdAt: mockInterventions[idx].createdAt,
        updatedAt: DateTime.now(),
      );
      return mockInterventions[idx];
    }
    throw Exception('Not found');
  }

  @override
  Future<InterventionResponse> approveIntervention(int interventionId, int approvedBy, String notes, {String? scenario, String? expectedEffect}) async {
     final idx = mockInterventions.indexWhere((i) => i.id == interventionId);
    if (idx != -1) {
      mockInterventions[idx] = InterventionResponse(
        id: mockInterventions[idx].id,
        eventId: mockInterventions[idx].eventId,
        zoneId: mockInterventions[idx].zoneId,
        status: 'APPROVED',
        actions: mockInterventions[idx].actions,
        affectedZones: mockInterventions[idx].affectedZones,
        beforeRiskScore: mockInterventions[idx].beforeRiskScore,
        createdAt: mockInterventions[idx].createdAt,
        updatedAt: DateTime.now(),
      );
      return mockInterventions[idx];
    }
    throw Exception('Not found');
  }

  // Define other methods as needed, throwing for unmet interactions
  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}

void main() {
  test('InterventionsProvider requests approval correctly', () async {
    final mockRepo = MockAuthorityRepository();
    final intervention = InterventionResponse(
      id: 1,
      eventId: 1,
      status: 'PROPOSED',
      actions: [],
      affectedZones: [],
      beforeRiskScore: 0.5,
      createdAt: DateTime.now(),
      updatedAt: DateTime.now(),
    );
    mockRepo.mockInterventions = [intervention];

    final container = ProviderContainer(
      overrides: [
        authorityRepositoryProvider.overrideWithValue(mockRepo),
      ],
    );

    // Initial load
    var list = await container.read(interventionsProvider.future);
    expect(list.length, 1);
    expect(list.first.status, 'PROPOSED');

    // Request approval
    await container.read(interventionsProvider.notifier).requestApproval(1);

    // Verify state updated
    list = await container.read(interventionsProvider.future);
    expect(list.first.status, 'PENDING_APPROVAL');
  });
}
