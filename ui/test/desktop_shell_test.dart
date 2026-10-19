import 'dart:async';
import 'dart:ui' show PointerDeviceKind;

import 'package:cha_stabilizer_ui/src/app.dart';
import 'package:cha_stabilizer_ui/src/models.dart';
import 'package:cha_stabilizer_ui/src/platform/media_platform.dart';
import 'package:cha_stabilizer_ui/src/widgets/desktop_sidebar.dart';
import 'package:cha_stabilizer_ui/src/widgets/desktop_window_chrome.dart';
import 'package:cha_stabilizer_ui/src/widgets/job_activity_sheet.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';

import 'test_fakes.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  setUp(() {
    TestWidgetsFlutterBinding.instance.platformDispatcher.localesTestValue =
        const <Locale>[Locale('en', 'US')];
  });
  tearDown(() {
    TestWidgetsFlutterBinding.instance.platformDispatcher
        .clearLocalesTestValue();
    debugDefaultTargetPlatformOverride = null;
  });

  test('Window geometry rejects invalid client rectangles', () {
    const valid = DesktopWindowGeometry(
      titleBarHeight: 40,
      controlsLeft: 716,
      clientWidth: 900,
      maximizeButton: Rect.fromLTWH(808, 0, 46, 40),
    );
    expect(valid.isValid, isTrue);
    expect(
      const DesktopWindowGeometry(
        titleBarHeight: 40,
        controlsLeft: 716,
        clientWidth: 900,
        maximizeButton: Rect.fromLTWH(808, 0, 100, 40),
      ).isValid,
      isFalse,
    );
    expect(
      const DesktopWindowGeometry(
        titleBarHeight: 40,
        controlsLeft: double.nan,
        clientWidth: 900,
        maximizeButton: Rect.fromLTWH(808, 0, 46, 40),
      ).isValid,
      isFalse,
    );
  });

  testWidgets(
    'Sidebar intent, bottom Settings, shortcuts and IndexedStack drafts survive resize and locale',
    (tester) async {
      final platform = TestPlatformAdapter(
        nativeDesktop: true,
        managedShutdown: true,
      );
      await _pumpApp(tester, platform: platform, size: const Size(1440, 1000));
      expect(_sidebar(tester).expanded, isTrue);
      expect(_sidebar(tester).labelsPreferred, isTrue);
      expect(
        tester.getTopLeft(_key('sidebar-destination-2')).dy,
        greaterThan(700),
      );
      expect(
        tester.getTopLeft(_key('sidebar-label-toggle')).dy,
        greaterThan(tester.getTopLeft(_key('sidebar-destination-2')).dy),
      );
      final original = find.byWidgetPredicate(
        (widget) =>
            widget is TextField &&
            widget.decoration?.labelText == 'Original video',
      );
      await tester.enterText(original, r'D:\draft\original.mp4');
      await tester.tap(_key('sidebar-label-toggle'));
      await tester.pump();
      expect(_sidebar(tester).expanded, isFalse);
      expect(_sidebar(tester).labelsPreferred, isFalse);

      for (final width in <double>[799, 800, 801, 900, 1100, 1440]) {
        tester.view.physicalSize = Size(width, 1000);
        await _settle(tester);
        if (width < 800) {
          expect(find.byType(DesktopSidebar), findsNothing);
          expect(find.byType(NavigationBar), findsOneWidget);
        } else {
          expect(_sidebar(tester).expanded, isFalse);
          expect(_sidebar(tester).labelsPreferred, isFalse);
          expect(find.byType(NavigationBar), findsNothing);
        }
      }
      await _shortcut(tester, LogicalKeyboardKey.digit2);
      expect(_sidebar(tester).selectedIndex, 1);
      await _shortcut(tester, LogicalKeyboardKey.digit3);
      expect(_sidebar(tester).selectedIndex, 2);
      await tester.tap(_key('settings-language-zh'));
      await _settle(tester);
      expect(find.byTooltip('显示导航文字'), findsOneWidget);
      expect(_sidebar(tester).labelsPreferred, isFalse);

      tester.view.physicalSize = const Size(900, 1000);
      await _settle(tester);
      await tester.tap(_key('sidebar-label-toggle'));
      await tester.pump();
      expect(_sidebar(tester).labelsPreferred, isTrue);
      expect(_sidebar(tester).expanded, isTrue);
      tester.view.physicalSize = const Size(799, 1000);
      await _settle(tester);
      expect(find.byType(DesktopSidebar), findsNothing);
      tester.view.physicalSize = const Size(1600, 1000);
      await _settle(tester);
      expect(_sidebar(tester).expanded, isTrue);
      expect(find.byTooltip('隐藏导航文字'), findsOneWidget);
      await _shortcut(tester, LogicalKeyboardKey.digit1);
      expect(_sidebar(tester).selectedIndex, 0);
      final fields = tester.widgetList<TextField>(find.byType(TextField));
      expect(
        fields.any(
          (field) => field.controller?.text == r'D:\draft\original.mp4',
        ),
        isTrue,
      );
      expect(find.byType(JobActivitySheet), findsNothing);
      expect(find.byType(DraggableScrollableSheet), findsNothing);
      expect(tester.takeException(), isNull);
    },
  );

  testWidgets(
    'Language chips immediately patch only language despite incomplete paths and retain other drafts',
    (tester) async {
      final api = TestApiService(
        preferences: const AppPreferences(
          themeMode: ThemeMode.system,
          seedColor: 0xFF55766D,
          toolPaths: <String, String?>{},
          toolPathsLoaded: false,
        ),
      );
      final platform = TestPlatformAdapter(
        nativeDesktop: true,
        managedShutdown: true,
      );
      await _pumpApp(tester, api: api, platform: platform);
      final controller = tester
          .widget<AppShell>(find.byType(AppShell))
          .controller;
      controller.updatePreferenceDraft(
        controller.draftPreferences.copyWith(
          themeMode: ThemeMode.dark,
          toolPaths: const <String, String?>{
            'ffmpeg': r'D:\unsaved\ffmpeg.exe',
          },
        ),
      );
      await tester.pump();
      await _shortcut(tester, LogicalKeyboardKey.digit3);
      expect(
        tester
            .widget<FilledButton>(
              find.widgetWithText(FilledButton, 'Save preferences'),
            )
            .onPressed,
        isNull,
      );
      await tester.tap(_key('settings-language-zh'));
      await _settle(tester);
      expect(api.preferencePatches, <Map<String, dynamic>>[
        {'language_mode': 'zh'},
      ]);
      expect(controller.draftPreferences.themeMode, ThemeMode.dark);
      expect(
        controller.draftPreferences.toolPaths['ffmpeg'],
        r'D:\unsaved\ffmpeg.exe',
      );
      expect(
        api.preferences.toolPaths['ffmpeg'],
        isNull,
        reason: 'The language patch must not save the local tool-path draft',
      );
      expect(api.preferences.themeMode, ThemeMode.system);
      expect(
        tester.widget<MaterialApp>(find.byType(MaterialApp)).locale,
        const Locale('zh'),
      );
      expect(find.byTooltip('隐藏导航文字'), findsOneWidget);

      await tester.tap(_key('settings-language-system'));
      await _settle(tester);
      expect(
        tester.widget<MaterialApp>(find.byType(MaterialApp)).locale,
        isNull,
      );
      expect(find.byTooltip('Hide navigation labels'), findsOneWidget);
      tester.binding.platformDispatcher.localesTestValue = const <Locale>[
        Locale('zh', 'TW'),
      ];
      await _settle(tester);
      expect(find.byTooltip('隐藏导航文字'), findsOneWidget);
      await tester.tap(_key('settings-language-en'));
      await _settle(tester);
      expect(find.byTooltip('Hide navigation labels'), findsOneWidget);
      expect(
        api.preferencePatches.map((patch) => patch.keys.single),
        everyElement('language_mode'),
      );
      expect(controller.draftPreferences.themeMode, ThemeMode.dark);
      expect(
        controller.draftPreferences.toolPaths['ffmpeg'],
        r'D:\unsaved\ffmpeg.exe',
      );
    },
  );

  testWidgets(
    'Caption waits for native acceptance and measures exact rects again on resize and DPI change',
    (tester) async {
      final gate = Completer<void>();
      final platform = TestPlatformAdapter(
        nativeDesktop: true,
        managedShutdown: true,
        windowState: const DesktopWindowState(supported: true),
      )..configureGate = gate.future;
      await _pumpApp(tester, platform: platform, size: const Size(900, 900));
      expect(platform.configureCalls, hasLength(1));
      final maximize = find.byTooltip('Maximize');
      final opacity = find
          .ancestor(of: maximize, matching: find.byType(Opacity))
          .first;
      expect(tester.widget<Opacity>(opacity).opacity, 0);
      final first = platform.configureCalls.single!;
      expect(first.isValid, isTrue);
      expect(first.titleBarHeight, 40);
      expect(
        first.controlsLeft,
        tester.getRect(find.byTooltip('Keep window on top')).left,
      );
      expect(first.maximizeButton, tester.getRect(maximize));
      expect(first.clientWidth, 900);
      gate.complete();
      await _settle(tester);
      expect(tester.widget<Opacity>(opacity).opacity, 1);

      tester.view.physicalSize = const Size(1600, 1000);
      await _settle(tester);
      expect(platform.configureCalls.last!.clientWidth, 1600);
      expect(
        platform.configureCalls.last!.maximizeButton,
        tester.getRect(maximize),
      );
      final beforeDpi = platform.configureCalls.length;
      tester.view.devicePixelRatio = 2;
      tester.view.physicalSize = const Size(1800, 1800);
      await _settle(tester);
      expect(platform.configureCalls.length, greaterThan(beforeDpi));
      expect(platform.configureCalls.last!.clientWidth, 900);
      expect(
        platform.configureCalls.last!.maximizeButton,
        tester.getRect(maximize),
      );
      final resizeGate = Completer<void>();
      platform.configureGate = resizeGate.future;
      tester.view.physicalSize = const Size(3200, 1800);
      await _settle(tester);
      expect(platform.configureCalls.last!.clientWidth, 1600);
      // Return to the last accepted size while the larger size is in flight.
      // It must not be dropped just because it equals the previously sent rect.
      tester.view.physicalSize = const Size(1800, 1800);
      await _settle(tester);
      resizeGate.complete();
      await _settle(tester);
      expect(platform.configureCalls.last!.clientWidth, 900);
      expect(
        platform.configureCalls.last!.maximizeButton,
        tester.getRect(maximize),
      );
      expect(platform.windowCommands, isEmpty);
      expect(tester.takeException(), isNull);
    },
  );

  testWidgets(
    'Caption uses authoritative state, localized semantics and keyboard actions without mouse-event toggles',
    (tester) async {
      final semantics = tester.ensureSemantics();
      try {
        final platform = TestPlatformAdapter(
          nativeDesktop: true,
          managedShutdown: true,
          windowState: const DesktopWindowState(supported: true),
        );
        await _pumpApp(tester, platform: platform);
        final chromeBefore = tester.state(find.byType(DesktopWindowChrome));
        final geometryBefore = platform.configureCalls.last!;
        final configurationCountBefore = platform.configureCalls.length;
        final original = find.byWidgetPredicate(
          (widget) =>
              widget is TextField &&
              widget.decoration?.labelText == 'Original video',
        );
        await tester.enterText(original, r'D:\caption-draft\original.mp4');
        await tester.tap(_key('sidebar-label-toggle'));
        await _settle(tester);
        final hover = await _showCaptionTooltip(tester, 'Minimize');
        await _hideCaptionTooltip(tester, hover, 'Minimize');
        expect(
          platform.windowCommands,
          isEmpty,
          reason: 'Tooltip hover is not a window command',
        );
        expect(find.bySemanticsLabel('Keep window on top'), findsOneWidget);
        await tester.tap(find.byTooltip('Keep window on top'));
        await tester.tap(find.byTooltip('Minimize'));
        await tester.pump();
        expect(platform.alwaysOnTopValues, <bool>[true]);
        expect(
          find.byTooltip('Keep window on top'),
          findsOneWidget,
          reason: 'Dart must not optimistically flip native state',
        );
        platform.emitWindowState(
          const DesktopWindowState(
            supported: true,
            customFrameEnabled: true,
            maximized: true,
            alwaysOnTop: true,
            maximizeButtonHovered: true,
            maximizeButtonPressed: true,
          ),
        );
        await _settle(tester);
        expect(find.byTooltip('Restore'), findsOneWidget);
        expect(find.byTooltip('Stop keeping window on top'), findsOneWidget);
        expect(platform.windowCommands, <String>[
          'setAlwaysOnTop',
          'minimizeWindow',
        ]);
        Focus.of(tester.element(find.byIcon(Icons.filter_none))).requestFocus();
        await tester.pump();
        for (final (key, index) in <(LogicalKeyboardKey, int)>[
          (LogicalKeyboardKey.digit2, 1),
          (LogicalKeyboardKey.digit3, 2),
          (LogicalKeyboardKey.digit1, 0),
        ]) {
          await _shortcut(tester, key);
          expect(
            _sidebar(tester).selectedIndex,
            index,
            reason: 'Caption keyboard focus must retain main-shell shortcuts',
          );
        }
        await tester.sendKeyEvent(LogicalKeyboardKey.enter);
        await tester.pump();
        expect(
          platform.windowCommands.where(
            (name) => name == 'toggleMaximizeWindow',
          ),
          hasLength(1),
        );
        final controller = tester
            .widget<AppShell>(find.byType(AppShell))
            .controller;
        await controller.saveLanguageMode(AppLanguageMode.zh);
        controller.updatePreferenceDraft(
          controller.draftPreferences.copyWith(
            themeMode: ThemeMode.dark,
            seedColor: 0xFF607D8B,
          ),
        );
        await _routeTransition(tester);
        expect(find.byTooltip('还原'), findsOneWidget);
        expect(find.bySemanticsLabel('关闭'), findsOneWidget);
        expect(find.bySemanticsLabel('取消窗口置顶'), findsOneWidget);
        expect(
          identical(
            tester.state(find.byType(DesktopWindowChrome)),
            chromeBefore,
          ),
          isTrue,
        );
        expect(
          platform.configureCalls.length,
          configurationCountBefore,
          reason:
              'Locale/theme rebuilds must not recreate chrome or reset geometry',
        );
        expect(platform.configureCalls.last, geometryBefore);
        expect(
          tester.getRect(find.byTooltip('还原')),
          geometryBefore.maximizeButton,
        );
        expect(_sidebar(tester).selectedIndex, 0);
        expect(_sidebar(tester).labelsPreferred, isFalse);
        expect(
          tester
              .widgetList<TextField>(find.byType(TextField))
              .any(
                (field) =>
                    field.controller?.text == r'D:\caption-draft\original.mp4',
              ),
          isTrue,
        );
        final localizedHover = await _showCaptionTooltip(tester, '还原');
        await _hideCaptionTooltip(tester, localizedHover, '还原');
        final hoverDuringDispose = await _showCaptionTooltip(tester, '关闭');
        await tester.pumpWidget(const SizedBox.shrink());
        await _routeTransition(tester);
        expect(find.byType(Overlay, skipOffstage: false), findsNothing);
        expect(
          find.byType(DesktopWindowChrome, skipOffstage: false),
          findsNothing,
        );
        expect(
          find.text('关闭'),
          findsNothing,
          reason:
              'Disposing the app must also remove a visible caption tooltip',
        );
        await hoverDuringDispose.removePointer();
        await tester.pump(const Duration(seconds: 2));
        expect(tester.takeException(), isNull);
      } finally {
        semantics.dispose();
      }
    },
  );

  testWidgets(
    'Custom-frame failure restores stock once but native narrow sidebar and managed exit remain',
    (tester) async {
      final platform = TestPlatformAdapter(
        nativeDesktop: true,
        managedShutdown: true,
        nativePicker: false,
        windowState: const DesktopWindowState(supported: true),
      )..configureError = PlatformException(code: 'window_chrome_failed');
      await _pumpApp(tester, platform: platform, size: const Size(390, 900));
      expect(platform.configureCalls, hasLength(2));
      expect(platform.configureCalls.first, isNotNull);
      expect(platform.configureCalls.last, isNull);
      expect(find.byTooltip('Maximize'), findsNothing);
      expect(find.byType(DesktopSidebar), findsNothing);
      expect(find.byType(NavigationBar), findsOneWidget);
      expect(
        tester.widget<PopScope<Object?>>(find.byType(PopScope<Object?>)).canPop,
        isFalse,
      );
      tester.view.physicalSize = const Size(1440, 1000);
      await _settle(tester);
      expect(
        platform.configureCalls,
        hasLength(2),
        reason: 'No per-frame retry loop',
      );
      await _shortcut(tester, LogicalKeyboardKey.digit3);
      final exit = _key('settings-exit');
      await _revealSetting(tester, exit);
      await tester.tap(exit);
      await _settle(tester);
      expect(find.text('Close ChaSteady?'), findsOneWidget);
      await tester.tap(find.text('Cancel'));
      await _settle(tester);
      expect(platform.shutdownCount, 0);
    },
  );

  testWidgets(
    'A declined native custom frame stays stock without a retry loop',
    (tester) async {
      final platform = TestPlatformAdapter(
        nativeDesktop: true,
        managedShutdown: true,
        windowState: const DesktopWindowState(supported: true),
      )..rejectCustomFrame = true;
      await _pumpApp(tester, platform: platform);
      expect(platform.configureCalls, hasLength(2));
      expect(platform.configureCalls.last, isNull);
      expect(find.byTooltip('Maximize'), findsNothing);
      await _shortcut(tester, LogicalKeyboardKey.digit3);
      await _settle(tester);
      expect(platform.configureCalls, hasLength(2));
      expect(platform.managedShutdown, isTrue);
      expect(tester.takeException(), isNull);
    },
  );

  testWidgets(
    'Unsupported native window controls retain stock frame and independent normal shutdown',
    (tester) async {
      final platform = TestPlatformAdapter(
        nativeDesktop: true,
        managedShutdown: true,
      );
      await _pumpApp(tester, platform: platform, size: const Size(390, 900));
      expect(platform.configureCalls, isEmpty);
      expect(find.byTooltip('Maximize'), findsNothing);
      expect(find.byType(DesktopSidebar), findsNothing);
      expect(find.byType(NavigationBar), findsOneWidget);
      final result = platform.closeRequestHandler!();
      await _settle(tester);
      await tester.tap(
        find.widgetWithText(FilledButton, 'Stop work and close'),
      );
      await _settle(tester);
      expect(await result, isTrue);
      expect(platform.shutdownCount, 1);
    },
  );

  testWidgets(
    'Windows-themed Web never gains pseudo window controls, managed exit or native layout',
    (tester) async {
      debugDefaultTargetPlatformOverride = TargetPlatform.windows;
      try {
        final platform = TestPlatformAdapter(
          nativePicker: true,
          windowState: const DesktopWindowState(
            supported: true,
            customFrameEnabled: true,
          ),
        );
        await _pumpApp(tester, platform: platform, size: const Size(390, 900));
        expect(find.byType(NavigationBar), findsOneWidget);
        expect(find.byType(DesktopSidebar), findsNothing);
        expect(find.byTooltip('Maximize'), findsNothing);
        expect(find.byTooltip('Minimize'), findsNothing);
        expect(find.byTooltip('Keep window on top'), findsNothing);
        expect(find.byTooltip('Close'), findsNothing);
        expect(platform.configureCalls, isEmpty);
        expect(
          tester
              .widget<PopScope<Object?>>(find.byType(PopScope<Object?>))
              .canPop,
          isTrue,
        );
        await _shortcut(tester, LogicalKeyboardKey.digit3);
        await _revealSetting(tester, find.text('Application'));
        expect(_key('settings-exit'), findsNothing);
        expect(_key('settings-open-web'), findsNothing);
        tester.view.physicalSize = const Size(1600, 1000);
        await _settle(tester);
        expect(find.byType(DesktopSidebar), findsOneWidget);
        expect(platform.configureCalls, isEmpty);
        expect(platform.windowCommands, isEmpty);
        expect(platform.openWebCount, 0);
      } finally {
        debugDefaultTargetPlatformOverride = null;
      }
    },
  );

  testWidgets(
    'Every old menu action is in Settings, including licenses, without startup openWeb',
    (tester) async {
      final platform = TestPlatformAdapter(
        nativeDesktop: true,
        managedShutdown: true,
        webAvailable: true,
      );
      await _pumpApp(tester, platform: platform);
      expect(find.byType(MenuBar), findsNothing);
      expect(find.byType(SubmenuButton), findsNothing);
      expect(find.byType(MenuItemButton), findsNothing);
      expect(platform.openWebCount, 0);
      await _shortcut(tester, LogicalKeyboardKey.digit3);
      expect(platform.openWebCount, 0);
      for (final mode in <String>['system', 'zh', 'en']) {
        expect(_key('settings-language-$mode'), findsOneWidget);
      }
      for (final index in <int>[0, 1, 2]) {
        final page = _key('settings-page-$index');
        await _revealSetting(tester, page);
        await tester.tap(page);
        await _settle(tester);
        expect(_sidebar(tester).selectedIndex, index);
        await _shortcut(tester, LogicalKeyboardKey.digit3);
      }
      final openWeb = _key('settings-open-web');
      await _revealSetting(tester, openWeb);
      await tester.tap(openWeb);
      await tester.pump();
      expect(platform.openWebCount, 1);
      expect(tester.widget<ListTile>(_key('settings-exit')).onTap, isNotNull);
      for (final action in <String>['about', 'licenses', 'quality']) {
        final tile = _key('settings-$action');
        await _revealSetting(tester, tile);
        await tester.tap(tile);
        await _settle(tester);
        if (action == 'about') {
          expect(find.byType(AboutDialog), findsOneWidget);
          expect(
            find.textContaining('local-first video stabilization'),
            findsOneWidget,
          );
        } else if (action == 'licenses') {
          expect(find.byType(LicensePage), findsOneWidget);
        } else {
          expect(find.byType(AlertDialog), findsOneWidget);
          expect(
            find.textContaining(
              'not a quality or full-field-of-view certificate',
            ),
            findsOneWidget,
          );
        }
        tester.state<NavigatorState>(find.byType(Navigator).first).pop();
        await _settle(tester);
      }
      expect(platform.openWebCount, 1);
    },
  );

  testWidgets(
    'Close requests share the entire confirmation and shutdown Future; cancellation can retry',
    (tester) async {
      final shutdown = Completer<void>();
      final platform = TestPlatformAdapter(
        nativeDesktop: true,
        managedShutdown: true,
        windowState: const DesktopWindowState(supported: true),
      )..shutdownGate = shutdown.future;
      await _pumpApp(tester, platform: platform);
      await _shortcut(tester, LogicalKeyboardKey.digit3);
      await _revealSetting(tester, _key('settings-exit'));
      final request = platform.closeRequestHandler!;
      await tester.tap(_key('settings-exit'));
      final first = request();
      final duplicate = request();
      expect(identical(first, duplicate), isTrue);
      await _settle(tester);
      expect(find.byType(AlertDialog), findsOneWidget);
      await tester.tap(find.text('Cancel'));
      await _settle(tester);
      expect(await first, isFalse);
      expect(await duplicate, isFalse);
      expect(platform.shutdownCount, 0);

      final retry = request();
      expect(identical(retry, first), isFalse);
      await _settle(tester);
      await tester.tap(
        find.widgetWithText(FilledButton, 'Stop work and close'),
      );
      await _settle(tester);
      final duringShutdown = request();
      await tester.tap(_captionButton('Close'));
      expect(identical(retry, duringShutdown), isTrue);
      expect(platform.shutdownCount, 1);
      expect(find.byType(AlertDialog), findsNothing);
      expect(
        tester
            .widget<DesktopWindowChrome>(find.byType(DesktopWindowChrome))
            .busy,
        isTrue,
      );
      expect(
        tester.widget<IconButton>(_captionButton('Close')).onPressed,
        isNull,
      );
      await _shortcut(tester, LogicalKeyboardKey.digit1);
      expect(
        _sidebar(tester).selectedIndex,
        2,
        reason: 'Closing still blocks global navigation',
      );
      expect(find.textContaining('Stopping processing.'), findsOneWidget);
      var finished = false;
      unawaited(duringShutdown.then((_) => finished = true));
      await tester.pump();
      expect(finished, isFalse);
      shutdown.complete();
      await _settle(tester);
      expect(await retry, isTrue);
      expect(await duringShutdown, isTrue);
      expect(platform.shutdownCount, 1);
    },
  );

  testWidgets(
    'Window command and worker-shutdown failures do not lock normal exit or its retry',
    (tester) async {
      final platform = TestPlatformAdapter(
        nativeDesktop: true,
        managedShutdown: true,
        windowState: const DesktopWindowState(supported: true),
      )..windowCommandError = PlatformException(code: 'window_command_failed');
      await _pumpApp(tester, platform: platform);
      await tester.tap(find.byTooltip('Minimize'));
      await _settle(tester);
      expect(platform.managedShutdown, isTrue);
      platform.shutdownError = PlatformException(
        code: 'worker_shutdown_failed',
      );
      final first = platform.closeRequestHandler!();
      await _settle(tester);
      await tester.tap(
        find.widgetWithText(FilledButton, 'Stop work and close'),
      );
      await _settle(tester);
      expect(await first, isFalse);
      expect(platform.shutdownRequested, isFalse);
      expect(platform.shutdownCount, 1);
      expect(
        tester.widget<IconButton>(_captionButton('Close')).onPressed,
        isNotNull,
      );
      platform.shutdownError = null;
      final retry = platform.closeRequestHandler!();
      expect(identical(first, retry), isFalse);
      await _settle(tester);
      expect(find.text('Close ChaSteady?'), findsOneWidget);
      await tester.tap(
        find.widgetWithText(FilledButton, 'Stop work and close'),
      );
      await _settle(tester);
      expect(await retry, isTrue);
      expect(platform.shutdownRequested, isTrue);
      expect(platform.shutdownCount, 2);
    },
  );

  testWidgets(
    'Settings license route preserves root caption and close delegation',
    (tester) async {
      await _exerciseLicenseRoute(tester, viaAbout: false);
    },
  );

  testWidgets(
    'About built-in license route preserves root caption and close delegation',
    (tester) async {
      await _exerciseLicenseRoute(tester, viaAbout: true);
    },
  );

  testWidgets('Startup failure leaves the operating-system caption alone', (
    tester,
  ) async {
    await tester.pumpWidget(
      const StartupFailureApp(error: 'bounded startup failure'),
    );
    await _settle(tester);
    expect(find.byType(DesktopWindowChrome), findsNothing);
    expect(find.byTooltip('Maximize'), findsNothing);
    expect(find.text('ChaSteady could not start'), findsOneWidget);
  });

  testWidgets(
    'Native and Web shells fit narrow/wide widths, scaled text and light/dark themes',
    (tester) async {
      tester.binding.platformDispatcher.textScaleFactorTestValue = 1.4;
      addTearDown(
        tester.binding.platformDispatcher.clearTextScaleFactorTestValue,
      );
      for (final native in <bool>[false, true]) {
        for (final theme in <ThemeMode>[ThemeMode.light, ThemeMode.dark]) {
          final platform = TestPlatformAdapter(
            nativeDesktop: native,
            managedShutdown: native,
            windowState: DesktopWindowState(supported: native),
          );
          final api = TestApiService();
          api.preferences = api.preferences.copyWith(themeMode: theme);
          await _pumpApp(
            tester,
            platform: platform,
            api: api,
            size: const Size(360, 1000),
          );
          for (final width in <double>[360, 799, 800, 801, 900, 1100, 1440]) {
            tester.view.physicalSize = Size(width, 1000);
            await _shortcut(tester, LogicalKeyboardKey.digit3);
            await _settle(tester);
            expect(
              tester
                  .widget<IndexedStack>(find.byType(IndexedStack).first)
                  .index,
              2,
            );
            expect(
              tester.takeException(),
              isNull,
              reason: '$native / $theme / $width',
            );
            expect(
              find.byType(NavigationBar),
              width >= 800 ? findsNothing : findsOneWidget,
            );
            await _shortcut(tester, LogicalKeyboardKey.digit1);
            expect(
              tester.takeException(),
              isNull,
              reason: 'Workbench $native / $theme / $width',
            );
          }
          await tester.pumpWidget(const SizedBox.shrink());
          await tester.pump();
        }
      }
    },
  );
}

Future<void> _exerciseLicenseRoute(
  WidgetTester tester, {
  required bool viaAbout,
}) async {
  final platform = TestPlatformAdapter(
    nativeDesktop: true,
    managedShutdown: true,
    windowState: const DesktopWindowState(supported: true),
  );
  await _pumpApp(
    tester,
    platform: platform,
    size: Size(viaAbout ? 1440 : 900, 1000),
  );
  final original = find.byWidgetPredicate(
    (widget) =>
        widget is TextField && widget.decoration?.labelText == 'Original video',
  );
  await tester.enterText(original, r'D:\route-draft\original.mp4');
  await tester.tap(_key('sidebar-label-toggle'));
  await _shortcut(tester, LogicalKeyboardKey.digit3);
  final entry = _key(viaAbout ? 'settings-about' : 'settings-licenses');
  await _revealSetting(tester, entry);
  final configurationsBeforeRoute = platform.configureCalls.length;
  await tester.tap(entry);
  await _routeTransition(tester);
  if (viaAbout) {
    final about = find.byType(AboutDialog);
    expect(about, findsOneWidget);
    final label = MaterialLocalizations.of(
      tester.element(about),
    ).viewLicensesButtonLabel;
    await tester.tap(find.widgetWithText(TextButton, label));
    await _routeTransition(tester);
  }

  final license = find.byType(LicensePage);
  expect(license, findsOneWidget);
  expect(
    find.byType(DesktopWindowChrome),
    findsOneWidget,
    reason: 'A full-screen route must not put the only caption offstage',
  );
  expect(find.byType(DesktopWindowChrome, skipOffstage: false), findsOneWidget);
  expect(find.byTooltip('Maximize'), findsOneWidget);
  expect(
    find.byTooltip('Maximize').hitTestable(),
    findsOneWidget,
    reason:
        'The caption must be visible and interactive above the pushed route',
  );
  final geometry = platform.configureCalls.last!;
  expect(
    tester.getTopLeft(license).dy,
    greaterThanOrEqualTo(geometry.titleBarHeight),
  );
  final back = find.byType(BackButton).first;
  expect(
    tester.getRect(back).top,
    greaterThanOrEqualTo(geometry.titleBarHeight),
    reason: 'License back button must remain outside native HTCAPTION',
  );
  for (final scaffold
      in find
          .descendant(of: license, matching: find.byType(Scaffold))
          .evaluate()) {
    expect(
      tester.getTopLeft(find.byWidget(scaffold.widget)).dy,
      greaterThanOrEqualTo(geometry.titleBarHeight),
    );
  }
  expect(platform.configureCalls.length, configurationsBeforeRoute);
  expect(
    platform.configureCalls,
    isNot(contains(null)),
    reason:
        'Pushing routes must not dispose/recreate chrome or toggle stock frame',
  );

  Focus.of(tester.element(find.byIcon(Icons.crop_square))).requestFocus();
  await tester.pump();
  await _shortcut(tester, LogicalKeyboardKey.digit1);
  expect(find.byType(LicensePage), findsOneWidget);
  expect(
    tester
        .widget<DesktopSidebar>(
          find.byType(DesktopSidebar, skipOffstage: false),
        )
        .selectedIndex,
    2,
    reason: 'Global shortcuts must not navigate behind a pushed page',
  );

  platform.windowCommandError = PlatformException(code: 'route_window_failed');
  await tester.tap(find.byTooltip('Minimize'));
  await _settle(tester);
  expect(
    find.textContaining('route_window_failed'),
    findsWidgets,
    reason: 'Root chrome must retain localized ScaffoldMessenger access',
  );
  platform.windowCommandError = null;
  final captionClose = tester
      .widget<DesktopWindowChrome>(find.byType(DesktopWindowChrome))
      .onClose;
  final closeOnRoute = captionClose();
  final nativeCloseOnRoute = platform.closeRequestHandler!();
  expect(identical(closeOnRoute, nativeCloseOnRoute), isTrue);
  await _routeTransition(tester);
  expect(find.byType(AlertDialog), findsOneWidget);
  expect(
    tester.getTopLeft(find.byType(AlertDialog)).dy,
    greaterThanOrEqualTo(geometry.titleBarHeight),
  );
  await tester.tap(find.text('Cancel'));
  await _routeTransition(tester);
  expect(await closeOnRoute, isFalse);
  expect(await nativeCloseOnRoute, isFalse);
  expect(find.byType(LicensePage), findsOneWidget);

  await tester.tap(back);
  await _routeTransition(tester);
  expect(find.byType(LicensePage), findsNothing);
  if (viaAbout) {
    final about = find.byType(AboutDialog);
    expect(about, findsOneWidget);
    final label = MaterialLocalizations.of(
      tester.element(about),
    ).closeButtonLabel;
    await tester.tap(find.widgetWithText(TextButton, label));
    await _routeTransition(tester);
  }
  expect(_sidebar(tester).selectedIndex, 2);
  expect(_sidebar(tester).labelsPreferred, isFalse);
  expect(platform.configureCalls.length, configurationsBeforeRoute);
  expect(find.byType(DesktopWindowChrome), findsOneWidget);
  final retry = platform.closeRequestHandler!();
  final captionRetry = tester
      .widget<DesktopWindowChrome>(find.byType(DesktopWindowChrome))
      .onClose();
  expect(identical(retry, captionRetry), isTrue);
  expect(identical(retry, closeOnRoute), isFalse);
  await _routeTransition(tester);
  await tester.tap(find.text('Cancel'));
  await _routeTransition(tester);
  expect(await retry, isFalse);
  expect(platform.shutdownCount, 0);
  await _shortcut(tester, LogicalKeyboardKey.digit1);
  expect(_sidebar(tester).selectedIndex, 0);
  expect(
    tester
        .widgetList<TextField>(find.byType(TextField))
        .any(
          (field) => field.controller?.text == r'D:\route-draft\original.mp4',
        ),
    isTrue,
  );
  expect(tester.takeException(), isNull);
}

Future<TestGesture> _showCaptionTooltip(
  WidgetTester tester,
  String label,
) async {
  expect(find.text(label), findsNothing);
  final mouse = await tester.createGesture(kind: PointerDeviceKind.mouse);
  await mouse.addPointer(location: const Offset(600, 100));
  await mouse.moveTo(tester.getCenter(_captionButton(label)));
  await tester.pump();
  await tester.pump(const Duration(milliseconds: 600));
  expect(
    find.text(label),
    findsOneWidget,
    reason: 'Mouse hover must render the caption tooltip in the root overlay',
  );
  return mouse;
}

Future<void> _hideCaptionTooltip(
  WidgetTester tester,
  TestGesture mouse,
  String label,
) async {
  await mouse.moveTo(const Offset(600, 100));
  await tester.pump();
  await tester.pump(const Duration(milliseconds: 300));
  // The exit timer starts the reverse animation; give that animation a frame
  // and its own duration rather than checking on its first tick.
  await tester.pump(const Duration(milliseconds: 100));
  expect(
    find.text(label),
    findsNothing,
    reason: 'Leaving the caption must hide its tooltip overlay',
  );
  await mouse.removePointer();
}

Future<void> _routeTransition(WidgetTester tester) async {
  await tester.pump();
  // Flutter 3.47's default Android page transition takes 450 ms; license
  // master/detail transitions can take 500 ms. Complete both before hit tests.
  await tester.pump(const Duration(milliseconds: 600));
  await tester.pump();
}

Finder _key(String value) => find.byKey(ValueKey<String>(value));
Finder _captionButton(String label) => find
    .ancestor(of: find.byTooltip(label), matching: find.byType(IconButton))
    .first;
Future<void> _revealSetting(WidgetTester tester, Finder finder) async {
  await tester.scrollUntilVisible(
    finder,
    250,
    scrollable: _settingsScrollable(),
  );
  await _settle(tester);
  await tester.ensureVisible(finder);
  await _settle(tester);
}

DesktopSidebar _sidebar(WidgetTester tester) =>
    tester.widget<DesktopSidebar>(find.byType(DesktopSidebar));
Finder _settingsScrollable() => find
    .descendant(of: _key('settings-list'), matching: find.byType(Scrollable))
    .first;

Future<void> _shortcut(WidgetTester tester, LogicalKeyboardKey key) async {
  await tester.sendKeyDownEvent(LogicalKeyboardKey.controlLeft);
  await tester.sendKeyEvent(key);
  await tester.sendKeyUpEvent(LogicalKeyboardKey.controlLeft);
  await _settle(tester);
}

Future<void> _pumpApp(
  WidgetTester tester, {
  required TestPlatformAdapter platform,
  TestApiService? api,
  Size size = const Size(1440, 1000),
}) async {
  tester.view.devicePixelRatio = 1;
  tester.view.physicalSize = size;
  addTearDown(tester.view.resetDevicePixelRatio);
  addTearDown(tester.view.resetPhysicalSize);
  await tester.pumpWidget(
    ChaSteadyApp(
      api: api ?? TestApiService(),
      platform: platform,
      sessionNonce: 'test-only-session',
    ),
  );
  await _settle(tester);
}

Future<void> _settle(WidgetTester tester) async {
  await tester.pump();
  await tester.pump(const Duration(milliseconds: 80));
  await tester.pump(const Duration(milliseconds: 80));
}
