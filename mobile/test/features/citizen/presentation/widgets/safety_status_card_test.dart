import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/features/citizen/presentation/widgets/safety_status_card.dart';
import 'package:mobile/features/citizen/data/citizen_models.dart';

void main() {
  testWidgets('SafetyStatusCard shows loading state', (WidgetTester tester) async {
    await tester.pumpWidget(const MaterialApp(
      home: Scaffold(
        body: SafetyStatusCard(isLoading: true),
      ),
    ));

    expect(find.byType(CircularProgressIndicator), findsOneWidget);
  });

  testWidgets('SafetyStatusCard shows missing data state', (WidgetTester tester) async {
    await tester.pumpWidget(const MaterialApp(
      home: Scaffold(
        body: SafetyStatusCard(riskData: null),
      ),
    ));

    expect(find.text('Status Unavailable'), findsOneWidget);
  });

  testWidgets('SafetyStatusCard shows risk level accurately', (WidgetTester tester) async {
    final riskData = RiskAssessmentResponse(
      id: 1,
      eventId: 1,
      zoneId: 1,
      crowdReadingId: 1,
      timestamp: DateTime.now(),
      riskScore: 75.0,
      riskLevel: 'HIGH',
      riskType: 'CROWD_DENSITY',
      explanation: 'High crowd density detected.',
    );

    await tester.pumpWidget(MaterialApp(
      home: Scaffold(
        body: SafetyStatusCard(riskData: riskData),
      ),
    ));

    expect(find.text('HIGH RISK'), findsOneWidget);
    expect(find.text('High crowd density detected.'), findsOneWidget);
    expect(find.text('Zone 1'), findsOneWidget);
  });
}
