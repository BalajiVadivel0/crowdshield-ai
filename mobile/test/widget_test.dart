import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:mobile/app/app.dart';

void main() {
  testWidgets('App smoke test', (WidgetTester tester) async {
    // Build our app and trigger a frame.
    await tester.pumpWidget(
      const ProviderScope(
        child: CrowdShieldApp(),
      ),
    );

    // Verify that the splash screen shows up
    expect(find.text('CrowdShield AI Splash'), findsOneWidget);
  });
}
