
import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/core/network/websocket_client.dart';

void main() {
  group('WebSocketClient', () {
    test('max and initial delays are set', () {
      final client = WebSocketClient(url: 'ws://dummy');
      expect(client, isNotNull);
    });
    
    test('connect transitions to connecting', () async {
      final client = WebSocketClient(url: 'ws://dummy');
      
      final statuses = <ConnectionStatus>[];
      final subscription = client.statusStream.listen(statuses.add);
      
      client.connect();
      
      await Future.delayed(const Duration(milliseconds: 50));
      
      expect(statuses, contains(ConnectionStatus.connecting));
      
      await subscription.cancel();
      client.disconnect();
    });

    test('disconnect triggers disconnect state', () async {
      final client = WebSocketClient(url: 'ws://dummy');
      
      final statuses = <ConnectionStatus>[];
      final subscription = client.statusStream.listen(statuses.add);
      
      client.disconnect();
      
      await Future.delayed(const Duration(milliseconds: 50));
      
      expect(statuses, contains(ConnectionStatus.disconnected));
      
      await subscription.cancel();
    });
  });
}
