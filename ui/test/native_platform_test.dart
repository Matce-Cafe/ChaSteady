import 'dart:async';
import 'dart:io';
import 'dart:ui' as ui;

import 'package:cha_stabilizer_ui/l10n/app_localizations.dart';
import 'package:cha_stabilizer_ui/src/platform/media_platform.dart';
import 'package:cha_stabilizer_ui/src/platform/platform_adapter_windows.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  const channel = MethodChannel('chasteady/native');
  final messenger =
      TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;
  const first = '11111111-1111-4111-8111-111111111111';
  const second = '22222222-2222-4222-8222-222222222222';
  const origin = 'http://127.0.0.1:48001';
  const bearer = 'abcdefghijklmnopqrstuvwxyz0123456789_session';

  tearDown(() => messenger.setMockMethodCallHandler(channel, null));

  Future<dynamic> receiveNative(String method, [Object? arguments]) async {
    const codec = StandardMethodCodec();
    final reply = Completer<ByteData?>();
    ui.channelBuffers.push(
      channel.name,
      codec.encodeMethodCall(MethodCall(method, arguments)),
      reply.complete,
    );
    final envelope = await reply.future;
    return codec.decodeEnvelope(envelope!);
  }

  test(
    'Windows bootstrap supplies a one-time in-memory HTTP session',
    () async {
      messenger.setMockMethodCallHandler(channel, (call) async {
        if (call.method == 'bootstrap')
          return {'origin': origin, 'bearer': bearer};
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
      expect(platform.isNativeDesktop, isTrue);
      expect(platform.managedShutdown, isTrue);
      expect(platform.desktopWindowState.value.supported, isFalse);
      await platform.dispose();
    },
    skip: !Platform.isWindows,
  );

  Map<String, bool> windowState({
    bool customFrameEnabled = false,
    bool maximized = false,
    bool alwaysOnTop = false,
    bool hovered = false,
    bool pressed = false,
  }) => <String, bool>{
    'supported': true,
    'customFrameEnabled': customFrameEnabled,
    'maximized': maximized,
    'alwaysOnTop': alwaysOnTop,
    'maximizeButtonHovered': hovered,
    'maximizeButtonPressed': pressed,
  };

  test(
    'Window capability queries are separate from validated worker bootstrap',
    () async {
      final calls = <MethodCall>[];
      messenger.setMockMethodCallHandler(channel, (call) async {
        calls.add(call);
        if (call.method == 'bootstrap')
          return {'origin': origin, 'bearer': bearer};
        if (call.method == 'getWindowState') return windowState();
        return null;
      });
      final platform = createPlatformAdapter();
      await platform.initialize();
      expect(calls.map((call) => call.method), ['bootstrap', 'getWindowState']);
      expect(calls.last.arguments, isNull);
      expect(platform.desktopWindowState.value.supported, isTrue);
      expect(platform.desktopWindowState.value.customFrameEnabled, isFalse);
      expect(platform.managedShutdown, isTrue);
      await platform.dispose();
    },
    skip: !Platform.isWindows,
  );

  test(
    'Missing, failed and malformed window queries preserve stock frame and managed exit',
    () async {
      for (final failure in <Object>[
        MissingPluginException(),
        PlatformException(code: 'window_query_failed'),
        <String, Object>{'supported': 'not a boolean'},
      ]) {
        final calls = <String>[];
        messenger.setMockMethodCallHandler(channel, (call) async {
          calls.add(call.method);
          if (call.method == 'bootstrap')
            return {'origin': origin, 'bearer': bearer};
          if (call.method == 'getWindowState') {
            if (failure is Map) return failure;
            throw failure;
          }
          return null;
        });
        final platform = createPlatformAdapter();
        await platform.initialize();
        expect(platform.desktopWindowState.value, const DesktopWindowState());
        expect(platform.managedShutdown, isTrue);
        expect(platform.supportsLocalServer, isTrue);
        await platform.requestShutdown();
        expect(calls, ['bootstrap', 'getWindowState', 'requestShutdown']);
        await platform.dispose();
      }
    },
    skip: !Platform.isWindows,
  );

  test(
    'Window commands and geometry use only the agreed native channel contract',
    () async {
      final calls = <MethodCall>[];
      messenger.setMockMethodCallHandler(channel, (call) async {
        calls.add(call);
        if (call.method == 'bootstrap')
          return {'origin': origin, 'bearer': bearer};
        if (call.method == 'getWindowState') return windowState();
        if (call.method == 'configureWindowChrome') {
          return windowState(
            customFrameEnabled: (call.arguments as Map)['enabled'] == true,
          );
        }
        return null;
      });
      final platform = createPlatformAdapter();
      await platform.initialize();
      const geometry = DesktopWindowGeometry(
        titleBarHeight: 40,
        controlsLeft: 716,
        clientWidth: 900,
        maximizeButton: Rect.fromLTWH(808, 0, 46, 40),
      );
      expect(
        (await platform.configureWindowChrome(geometry)).customFrameEnabled,
        isTrue,
      );
      expect(calls.last.arguments, <String, Object>{
        'enabled': true,
        'titleBarHeight': 40.0,
        'controlsLeft': 716.0,
        'clientWidth': 900.0,
        'maximizeButton': <String, double>{
          'left': 808,
          'top': 0,
          'width': 46,
          'height': 40,
        },
      });
      await platform.minimizeWindow();
      await platform.toggleMaximizeWindow();
      await platform.startWindowDrag();
      await platform.setAlwaysOnTop(true);
      expect(calls.skip(3).map((call) => call.method), [
        'minimizeWindow',
        'toggleMaximizeWindow',
        'startWindowDrag',
        'setAlwaysOnTop',
      ]);
      expect(
        calls.sublist(3, 6).every((call) => call.arguments == null),
        isTrue,
      );
      expect(calls.last.arguments, <String, bool>{'value': true});
      // No optimistic state flips; only native state responses/notifications count.
      expect(platform.desktopWindowState.value.maximized, isFalse);
      expect(platform.desktopWindowState.value.alwaysOnTop, isFalse);
      await receiveNative(
        'windowStateChanged',
        windowState(
          customFrameEnabled: true,
          maximized: true,
          alwaysOnTop: true,
          hovered: true,
          pressed: true,
        ),
      );
      expect(platform.desktopWindowState.value.maximized, isTrue);
      expect(platform.desktopWindowState.value.alwaysOnTop, isTrue);
      expect(platform.desktopWindowState.value.maximizeButtonHovered, isTrue);
      expect(platform.desktopWindowState.value.maximizeButtonPressed, isTrue);
      final count = calls.length;
      await receiveNative('windowStateChanged', <String, Object>{
        'supported': 7,
      });
      expect(platform.desktopWindowState.value.maximized, isTrue);
      expect(
        calls.length,
        count,
        reason: 'State notifications never toggle the window',
      );
      await platform.configureWindowChrome(null);
      expect(calls.last.arguments, <String, bool>{'enabled': false});
      expect(platform.desktopWindowState.value.customFrameEnabled, isFalse);
      await platform.dispose();
    },
    skip: !Platform.isWindows,
  );

  test(
    'Window command failures leave worker shutdown independent and retryable',
    () async {
      messenger.setMockMethodCallHandler(channel, (call) async {
        if (call.method == 'bootstrap')
          return {'origin': origin, 'bearer': bearer};
        if (call.method == 'getWindowState') return windowState();
        if (call.method == 'configureWindowChrome' ||
            call.method == 'minimizeWindow') {
          throw PlatformException(code: 'window_command_failed');
        }
        return null;
      });
      final platform = createPlatformAdapter();
      await platform.initialize();
      await expectLater(
        platform.minimizeWindow(),
        throwsA(isA<PlatformException>()),
      );
      await expectLater(
        platform.configureWindowChrome(null),
        throwsA(isA<PlatformException>()),
      );
      expect(platform.managedShutdown, isTrue);
      await platform.requestShutdown();
      expect(platform.managedShutdown, isFalse);
      await platform.dispose();
    },
    skip: !Platform.isWindows,
  );

  test('Windows bootstrap rejects a non-loopback origin', () async {
    final calls = <String>[];
    messenger.setMockMethodCallHandler(channel, (call) async {
      calls.add(call.method);
      return {'origin': 'http://192.0.2.1:48001', 'bearer': bearer};
    });
    final platform = createPlatformAdapter();
    await expectLater(platform.initialize(), throwsA(isA<PlatformException>()));
    expect(calls, <String>[
      'bootstrap',
    ], reason: 'Window query starts only after a valid bootstrap');
    expect(platform.supportsLocalServer, isFalse);
    expect(platform.managedShutdown, isFalse);
    expect(platform.desktopWindowState.value.supported, isFalse);
    await platform.dispose();
  }, skip: !Platform.isWindows);

  test(
    'Malformed native bootstrap fields become typed errors without exposing credentials',
    () async {
      for (final malformedOrigin in [
        37,
        null,
        'http://127.0.0.1',
        'http://127.0.0.1:65536',
      ]) {
        messenger.setMockMethodCallHandler(
          channel,
          (call) async => {'origin': malformedOrigin, 'bearer': bearer},
        );
        final platform = createPlatformAdapter();
        await expectLater(
          platform.initialize(),
          throwsA(
            isA<PlatformException>().having(
              (error) => error.code,
              'code',
              'invalid_native_bootstrap',
            ),
          ),
        );
        expect(platform.supportsLocalServer, isFalse);
        expect(platform.consumeSessionNonce(), isNull);
        await platform.dispose();
      }
    },
    skip: !Platform.isWindows,
  );

  test(
    'Native playback accepts artifact IDs only, never original paths or query credentials',
    () async {
      final calls = <String>[];
      messenger.setMockMethodCallHandler(channel, (call) async {
        calls.add(call.method);
        if (call.method == 'bootstrap')
          return {'origin': origin, 'bearer': bearer};
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
        expect(
          () => platform.buildVideoPreview(uri),
          throwsA(isA<PlatformException>()),
        );
      }
      expect(calls, ['bootstrap', 'getWindowState']);
      await platform.dispose();
    },
    skip: !Platform.isWindows,
  );

  test(
    'A shutdown request is idempotent and disables new native entry actions',
    () async {
      final calls = <String>[];
      messenger.setMockMethodCallHandler(channel, (call) async {
        calls.add(call.method);
        if (call.method == 'bootstrap')
          return {'origin': origin, 'bearer': bearer};
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
    },
    skip: !Platform.isWindows,
  );

  test(
    'Concurrent shutdown callers await the same terminal native cleanup',
    () async {
      final cleanup = Completer<void>();
      var shutdownCalls = 0;
      messenger.setMockMethodCallHandler(channel, (call) async {
        if (call.method == 'bootstrap')
          return {'origin': origin, 'bearer': bearer};
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
      final joined = Future.wait([
        firstShutdown,
        secondShutdown,
      ]).then((_) => completed = true);
      await Future<void>.delayed(Duration.zero);
      expect(shutdownCalls, 1);
      expect(completed, isFalse);
      cleanup.complete();
      await joined;
      expect(completed, isTrue);
      expect(platform.supportsLocalServer, isFalse);
      await platform.dispose();
    },
    skip: !Platform.isWindows,
  );

  test(
    'A failed native shutdown can be retried without reporting successful cleanup',
    () async {
      var shutdownCalls = 0;
      messenger.setMockMethodCallHandler(channel, (call) async {
        if (call.method == 'bootstrap')
          return {'origin': origin, 'bearer': bearer};
        if (call.method == 'requestShutdown' && ++shutdownCalls == 1) {
          throw PlatformException(code: 'worker_shutdown_failed');
        }
        return null;
      });
      final platform = createPlatformAdapter();
      await platform.initialize();
      await expectLater(
        platform.requestShutdown(),
        throwsA(isA<PlatformException>()),
      );
      expect(platform.supportsLocalServer, isTrue);
      await platform.requestShutdown();
      expect(shutdownCalls, 2);
      expect(platform.supportsLocalServer, isFalse);
      await platform.dispose();
    },
    skip: !Platform.isWindows,
  );

  test(
    'An early native close shuts down owned bootstrap instead of locking the window',
    () async {
      final calls = <String>[];
      messenger.setMockMethodCallHandler(channel, (call) async {
        calls.add(call.method);
        if (call.method == 'bootstrap')
          return {'origin': origin, 'bearer': bearer};
        return null;
      });
      final platform = createPlatformAdapter();
      await platform.initialize();
      expect(await receiveNative('requestClose'), isTrue);
      expect(calls, ['bootstrap', 'getWindowState', 'requestShutdown']);
      await platform.dispose();
    },
    skip: !Platform.isWindows,
  );

  test(
    'Native shutdown-warning acknowledgment is awaited, not a second close confirmation',
    () async {
      messenger.setMockMethodCallHandler(channel, (call) async {
        if (call.method == 'bootstrap')
          return {'origin': origin, 'bearer': bearer};
        return null;
      });
      final platform = createPlatformAdapter();
      await platform.initialize();
      final acknowledgment = Completer<void>();
      platform.setShutdownWarningHandler(() => acknowledgment.future);
      var replied = false;
      final result = receiveNative('shutdownWarning').then((value) {
        replied = true;
        return value;
      });
      await Future<void>.delayed(Duration.zero);
      expect(replied, isFalse);
      acknowledgment.complete();
      expect(await result, isNull);
      expect(replied, isTrue);
      await platform.dispose();
    },
    skip: !Platform.isWindows,
  );

  testWidgets(
    'Native preview switches leases and fits narrow controls; channel mock is not decoder evidence',
    (tester) async {
      final created = <String>[];
      final disposed = <String>[];
      messenger.setMockMethodCallHandler(channel, (call) async {
        final arguments = call.arguments is Map
            ? call.arguments as Map
            : const {};
        if (call.method == 'bootstrap')
          return {'origin': origin, 'bearer': bearer};
        if (call.method == 'createPreview') {
          final artifact = arguments['artifact_id'] as String;
          created.add(artifact);
          return {
            'player_id': artifact,
            'texture_id': 0,
            'width': 1382,
            'height': 808,
            'state': {
              'ready': true,
              'can_play': true,
              'muted': true,
              'duration_seconds': 16.0,
            },
          };
        }
        if (call.method == 'playerState') {
          return {
            'player_id': arguments['player_id'],
            'ready': true,
            'can_play': true,
            'playing': false,
            'muted': true,
            'volume': 1.0,
            'position_seconds': 0.0,
            'duration_seconds': 16.0,
            'error_code': '',
          };
        }
        if (call.method == 'disposePreview')
          disposed.add(arguments['player_id'] as String);
        return null;
      });
      final platform = createPlatformAdapter();
      await platform.initialize();
      Widget host(String artifact) => MaterialApp(
        locale: const Locale('en'),
        localizationsDelegates: AppLocalizations.localizationsDelegates,
        supportedLocales: AppLocalizations.supportedLocales,
        home: Scaffold(
          body: Center(
            child: SizedBox(
              width: 294,
              height: 270,
              child: platform.buildVideoPreview(
                Uri.parse('$origin/api/artifacts/$artifact/content'),
              ),
            ),
          ),
        ),
      );
      await tester.pumpWidget(host(first));
      await tester.pump();
      expect(tester.takeException(), isNull);
      expect(created, [first]);
      await receiveNative('windowStateChanged', <String, Object>{
        ...windowState(maximized: true),
        'player_id': first,
        'ready': false,
      });
      await tester.pump();
      expect(platform.desktopWindowState.value.maximized, isTrue);
      expect(
        find.text('Loading preview'),
        findsNothing,
        reason: 'A window notification must not overwrite player state',
      );
      await tester.pumpWidget(host(second));
      await tester.pump();
      expect(tester.takeException(), isNull);
      expect(created, [first, second]);
      expect(disposed, contains(first));
      await tester.pumpWidget(const SizedBox.shrink());
      await tester.pump();
      await platform.dispose();
      expect(disposed, contains(second));
    },
    skip: !Platform.isWindows,
  );
}
