import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/core/utils/alert_localization_helper.dart';
import 'package:mobile/features/citizen/data/models/alert.dart';
import 'package:mobile/l10n/app_localizations.dart';

void main() {
  Widget createTestWidget(Locale locale, Widget child) {
    return MaterialApp(
      locale: locale,
      localizationsDelegates: AppLocalizations.localizationsDelegates,
      supportedLocales: AppLocalizations.supportedLocales,
      home: Scaffold(body: Builder(builder: (context) => child)),
    );
  }

  testWidgets('Renders localized template for known alert type in English', (tester) async {
    final alert = CitizenAlert(
      id: 1,
      eventId: 1,
      alertType: 'CRITICAL_DANGER',
      severity: 'CRITICAL',
      title: 'Danger',
      message: 'Raw backend message',
      targetAudience: 'ALL',
      targetZones: [],
      createdAt: DateTime.now().toIso8601String(),
    );

    late String localizedMessage;

    await tester.pumpWidget(createTestWidget(const Locale('en'), Builder(
      builder: (context) {
        localizedMessage = AlertLocalizationHelper.getLocalizedMessage(context, alert);
        return const SizedBox.shrink();
      },
    )));
    await tester.pumpAndSettle();

    expect(localizedMessage, 'CRITICAL DANGER: Please leave the area immediately.');
  });

  testWidgets('Renders localized template for known alert type in Tamil', (tester) async {
    final alert = CitizenAlert(
      id: 1,
      eventId: 1,
      alertType: 'CRITICAL_DANGER',
      severity: 'CRITICAL',
      title: 'Danger',
      message: 'Raw backend message',
      targetAudience: 'ALL',
      targetZones: [],
      createdAt: DateTime.now().toIso8601String(),
    );

    late String localizedMessage;

    await tester.pumpWidget(createTestWidget(const Locale('ta'), Builder(
      builder: (context) {
        localizedMessage = AlertLocalizationHelper.getLocalizedMessage(context, alert);
        return const SizedBox.shrink();
      },
    )));
    await tester.pumpAndSettle();

    expect(localizedMessage, 'கடுமையான ஆபத்து: தயவுசெய்து உடனடியாக பகுதியை விட்டு வெளியேறவும்.');
  });

  testWidgets('Renders fallback raw message for unknown alert type', (tester) async {
    final alert = CitizenAlert(
      id: 2,
      eventId: 1,
      alertType: 'UNKNOWN_NEW_TYPE',
      severity: 'INFO',
      title: 'Test',
      message: 'Raw backend fallback message',
      targetAudience: 'ALL',
      targetZones: [],
      createdAt: DateTime.now().toIso8601String(),
    );

    late String localizedMessage;

    await tester.pumpWidget(createTestWidget(const Locale('en'), Builder(
      builder: (context) {
        localizedMessage = AlertLocalizationHelper.getLocalizedMessage(context, alert);
        return const SizedBox.shrink();
      },
    )));
    await tester.pumpAndSettle();

    expect(localizedMessage, 'Raw backend fallback message');
  });

  testWidgets('Renders parameterized template for AVOID_ZONE fallback', (tester) async {
    final alert = CitizenAlert(
      id: 3,
      eventId: 1,
      alertType: 'UNKNOWN',
      severity: 'WARNING',
      title: 'Test',
      message: 'Raw backend fallback message',
      targetAudience: 'ALL',
      targetZones: [5],
      createdAt: DateTime.now().toIso8601String(),
    );

    late String localizedMessage;

    await tester.pumpWidget(createTestWidget(const Locale('hi'), Builder(
      builder: (context) {
        localizedMessage = AlertLocalizationHelper.getLocalizedMessage(context, alert);
        return const SizedBox.shrink();
      },
    )));
    await tester.pumpAndSettle();

    expect(localizedMessage, 'कृपया ज़ोन 5 से बचें और सुरक्षित मार्ग का पालन करें।');
  });
}
