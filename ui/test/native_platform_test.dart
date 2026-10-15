import 'dart:async';
import 'dart:io';
import 'dart:ui' as ui;

import 'package:cha_stabilizer_ui/l10n/app_localizations.dart';
import 'package:cha_stabilizer_ui/src/platform/platform_adapter_windows.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  const channel = MethodChannel('chasteady/native');
  final messenger = TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;
  const first = '11111111-1111-4111-8111-111111111111';
  const second = '22222222-2222-4222-8222-222222222222';
  const origin = 'http://127.0.0.1:48001';
  const bearer = 'abcdefghijklmnopqrstuvwxyz0123456789_session';

  tearDown(() => messenger.setMockMethodCallHandler(channel, null));

  Future<dynamic> receiveNative(String method) async {
    const codec = StandardMethodCodec();
    final reply = Completer<ByteData?>();
    ui.channelBuffers.push(channel.name, codec.encodeMethodCall(MethodCall(method)), reply.complete);
    final envelope = await reply.future;
    return codec.decodeEnvelope(envelope!);
  }

  test('Windows bootstrap supplies a one-time in-memory HTTP session', () async {
    messenger.setMockMethodCallHandler(channel, (call) async {
      if (call.method == 'bootstrap') return {'origin': origin, 'bearer': bearer};
      return null;
    });
    final platform = createPlatformAdapter();
    await platform.initialize();
    expect(platform.supportsLocalServer, isTrue);
    expect(platform.apiOrigin, Uri.parse(origin));
    expect(platform.consumeSessionNonce(), bearer);
    expect(platform.consumeSessionNonce(), isNull);
    expect(platform.supportsNativePicker, isTrue);
    expect(platform.canOpenWeb, isTrue);
    await platform.dispose();
  }, skip: !Platform.isWindows);

  test('Windows bootstrap rejects a non-loopback origin', () async {
    messenger.setMockMethodCallHandler(channel, (call) async =>
        {'origin': 'http://192.0.2.1:48001', 'bearer': bearer});
    final platform = createPlatformAdapter();
    await expectLater(platform.initialize(), throwsA(isA<PlatformException>()));
    expect(platform.supportsLocalServer, isFalse);
    await platform.dispose();
  }, skip: !Platform.isWindows);

  test('Malformed native bootstrap fields become typed errors without exposing credentials', () async {
    for (final malformedOrigin in [37, null, 'http://127.0.0.1', 'http://127.0.0.1:65536']) {
      messenger.setMockMethodCallHandler(channel, (call) async =>
          {'origin': malformedOrigin, 'bearer': bearer});
      final platform = createPlatformAdapter();
      await expectLater(platform.initialize(), throwsA(isA<PlatformException>().having(
        (error) => error.code, 'code', 'invalid_native_bootstrap',
      )));
      expect(platform.supportsLocalServer, isFalse);
      expect(platform.consumeSessionNonce(), isNull);
      await platform.dispose();
    }
  }, skip: !Platform.isWindows);

  test('Native playback accepts artifact IDs only, never original paths or query credentials', () async {
    final calls = <String>[];
    messenger.setMockMethodCallHandler(channel, (call) async {
      calls.add(call.method);
      if (call.method == 'bootstrap') return {'origin': origin, 'bearer': bearer};
      return null;
    });
    final platform = createPlatformAdapter();
    await platform.initialize();
    for (final uri in [
      Uri.parse('file:///D:/original.mp4'),
      Uri.parse('$origin/api/artifacts/$first/content?token=secret'),
      Uri.parse('http://127.0.0.1:48002/api/artifacts/$first/content'),
      Uri.parse('$origin/api/arbitrary/D:/original.mp4'),
    ]) {
      expect(() => platform.buildVideoPreview(uri), throwsA(isA<PlatformException>()));
    }
    expect(calls, ['bootstrap']);
    await platform.dispose();
  }, skip: !Platform.isWindows);

  test('A shutdown request is idempotent and disables new native entry actions', () async {
    final calls = <String>[];
    messenger.setMockMethodCallHandler(channel, (call) async {
      calls.add(call.method);
      if (call.method == 'bootstrap') return {'origin': origin, 'bearer': bearer};
      return null;
    });
    final platform = createPlatformAdapter();
    await platform.initialize();
    await platform.requestShutdown();
    await platform.requestShutdown();
    expect(calls.where((value) => value == 'requestShutdown').length, 1);
    expect(platform.supportsLocalServer, isFalse);
    expect(platform.canOpenWeb, isFalse);
    await platform.dispose();
  }, skip: !Platform.isWindows);

  test('Concurrent shutdown callers await the same terminal native cleanup', () async {
    final cleanup = Completer<void>();
    var shutdownCalls = 0;
    messenger.setMockMethodCallHandler(channel, (call) async {
      if (call.method == 'bootstrap') return {'origin': origin, 'bearer': bearer};
      if (call.method == 'requestShutdown') {
        shutdownCalls++;
        await cleanup.future;
      }
      return null;
    });
    final platform = createPlatformAdapter();
    await platform.initialize();
    final firstShutdown = platform.requestShutdown();
    final secondShutdown = platform.requestShutdown();
    expect(identical(firstShutdown, secondShutdown), isTrue);
    var completed = false;
    final joined = Future.wait([firstShutdown, secondShutdown]).then((_) => completed = true);
    await Future<void>.delayed(Duration.zero);
    expect(shutdownCalls, 1);
    expect(completed, isFalse);
    cleanup.complete();
    await joined;
    expect(completed, isTrue);
    expect(platform.supportsLocalServer, isFalse);
    await platform.dispose();
  }, skip: !Platform.isWindows);

  test('A failed native shutdown can be retried without reporting successful cleanup', () async {
    var shutdownCalls = 0;
    messenger.setMockMethodCallHandler(channel, (call) async {
      if (call.method == 'bootstrap') return {'origin': origin, 'bearer': bearer};
      if (call.method == 'requestShutdown' && ++shutdownCalls == 1) {
        throw PlatformException(code: 'worker_shutdown_failed');
      }
      return null;
    });
    final platform = createPlatformAdapter();
    await platform.initialize();
    await expectLater(platform.requestShutdown(), throwsA(isA<PlatformException>()));
    expect(platform.supportsLocalServer, isTrue);
    await platform.requestShutdown();
    expect(shutdownCalls, 2);
    expect(platform.supportsLocalServer, isFalse);
    await platform.dispose();
  }, skip: !Platform.isWindows);

  test('An early native close shuts down owned bootstrap instead of locking the window', () async {
    final calls = <String>[];
    messenger.setMockMethodCallHandler(channel, (call) async {
      calls.add(call.method);
      if (call.method == 'bootstrap') return {'origin': origin, 'bearer': bearer};
      return null;
    });
    final platform = createPlatformAdapter();
    await platform.initialize();
    expect(await receiveNative('requestClose'), isTrue);
    expect(calls, ['bootstrap', 'requestShutdown']);
    await platform.dispose();
  }, skip: !Platform.isWindows);

  test('Native shutdown-warning acknowledgment is awaited, not a second close confirmation', () async {
    messenger.setMockMethodCallHandler(channel, (call) async {
      if (call.method == 'bootstrap') return {'origin': origin, 'bearer': bearer};
      return null;
    });
    final platform = createPlatformAdapter();
    await platform.initialize();
    final acknowledgment = Completer<void>();
    platform.setShutdownWarningHandler(() => acknowledgment.future);
    var replied = false;
    final result = receiveNative('shutdownWarning').then((value) { replied = true; return value; });
    await Future<void>.delayed(Duration.zero);
    expect(replied, isFalse);
    acknowledgment.complete();
    expect(await result, isNull);
    expect(replied, isTrue);
    await platform.dispose();
  }, skip: !Platform.isWindows);

  testWidgets('Native preview switches leases and fits narrow controls; channel mock is not decoder evidence', (tester) async {
    final created = <String>[];
    final disposed = <String>[];
    messenger.setMockMethodCallHandler(channel, (call) async {
      final arguments = call.arguments is Map ? call.arguments as Map : const {};
      if (call.method == 'bootstrap') return {'origin': origin, 'bearer': bearer};
      if (call.method == 'createPreview') {
        final artifact = arguments['artifact_id'] as String;
        created.add(artifact);
        return {'player_id': artifact, 'texture_id': 0, 'width': 1382, 'height': 808,
          'state': {'ready': true, 'can_play': true, 'muted': true, 'duration_seconds': 16.0}};
      }
      if (call.method == 'playerState') {
        return {'player_id': arguments['player_id'], 'ready': true, 'can_play': true,
          'playing': false, 'muted': true, 'volume': 1.0, 'position_seconds': 0.0,
          'duration_seconds': 16.0, 'error_code': ''};
      }
      if (call.method == 'disposePreview') disposed.add(arguments['player_id'] as String);
      return null;
    });
    final platform = createPlatformAdapter();
    await platform.initialize();
    Widget host(String artifact) => MaterialApp(
      locale: const Locale('en'),
      localizationsDelegates: AppLocalizations.localizationsDelegates,
      supportedLocales: AppLocalizations.supportedLocales,
      home: Scaffold(body: Center(child: SizedBox(width: 294, height: 270,
        child: platform.buildVideoPreview(Uri.parse('$origin/api/artifacts/$artifact/content'))))),
    );
    await tester.pumpWidget(host(first));
    await tester.pump();
    expect(tester.takeException(), isNull);
    expect(created, [first]);
    await tester.pumpWidget(host(second));
    await tester.pump();
    expect(tester.takeException(), isNull);
    expect(created, [first, second]);
    expect(disposed, contains(first));
    await tester.pumpWidget(const SizedBox.shrink());
    await tester.pump();
    await platform.dispose();
    expect(disposed, contains(second));
  }, skip: !Platform.isWindows);
}
