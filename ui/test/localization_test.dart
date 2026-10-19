import 'dart:convert';
import 'dart:io';

import 'package:cha_stabilizer_ui/src/app.dart';
import 'package:cha_stabilizer_ui/src/controller.dart';
import 'package:cha_stabilizer_ui/src/localization.dart';
import 'package:cha_stabilizer_ui/src/models.dart';
import 'package:cha_stabilizer_ui/src/widgets/desktop_sidebar.dart';
import 'package:cha_stabilizer_ui/src/widgets/job_activity_sheet.dart';
import 'package:cha_stabilizer_ui/src/widgets/job_widgets.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';

import 'test_fakes.dart';

void main() {
  test(
    'English and Simplified Chinese ARBs have equal keys and placeholders',
    () {
      final english =
          jsonDecode(File('lib/l10n/app_en.arb').readAsStringSync())
              as Map<String, dynamic>;
      final chinese =
          jsonDecode(File('lib/l10n/app_zh.arb').readAsStringSync())
              as Map<String, dynamic>;
      expect(english.keys.toSet(), chinese.keys.toSet());

      for (final key in english.keys.where(
        (key) => !key.startsWith('@') && !key.startsWith('@@'),
      )) {
        final englishPlaceholders =
            (english['@$key'] as Map<String, dynamic>?)?['placeholders'];
        final chinesePlaceholders =
            (chinese['@$key'] as Map<String, dynamic>?)?['placeholders'];
        expect(
          (englishPlaceholders as Map<String, dynamic>? ?? const {}).keys
              .toSet(),
          (chinesePlaceholders as Map<String, dynamic>? ?? const {}).keys
              .toSet(),
          reason: 'Placeholder parity for $key',
        );
      }
    },
  );

  test(
    'stabilize typed messages, stages and preview states localize in both languages',
    () async {
      for (final locale in const <Locale>[Locale('en'), Locale('zh')]) {
        final l10n = await AppLocalizations.delegate.load(locale);
        for (final key in <String>[
          'job.progress.sourceAcceptance',
          'job.progress.capabilityPreflight',
          'job.progress.ctb',
          'job.progress.gf',
          'job.progress.correspondence',
          'job.progress.freshMeasurement',
          'job.progress.finalValidation',
          'job.progress.gyroflowPreflight',
          'job.progress.gyroflowExport',
          'job.progress.gyroflowExportVerified',
          'job.progress.cancellationRequested',
          'job.error.ctbExecutorUnavailable',
          'job.error.fullContentCorrespondenceUnverified',
        ]) {
          expect(
            localizedWorkerText(l10n, WorkerText(messageKey: key)),
            isNot(contains(key)),
          );
        }
        for (final stage in <String>[
          'source_acceptance',
          'capability_preflight',
          'ctb',
          'gf',
          'correspondence',
          'fresh_measurement',
          'final_validation',
          'gyroflow_preflight',
          'gyroflow_export',
          'gyroflow_export_verified',
          'cancellation_requested',
        ]) {
          expect(
            workerStageLabel(l10n, stage),
            isNot(contains(l10n.originalWorkerStage(stage))),
          );
        }
        expect(jobKindLabel(l10n, 'stabilize'), l10n.jobKindStabilize);
        expect(
          jobKindLabel(l10n, 'stabilize_continue'),
          l10n.jobKindStabilizeContinue,
        );
        expect(workflowStateLabel(l10n, 'ready'), l10n.workflowReady);
        expect(workflowStateLabel(l10n, 'blocked'), l10n.blocked);
      }
    },
  );

  test(
    'old preference schema preserves theme and tool paths with system locale',
    () {
      final preferences = AppPreferences.fromJson(<String, dynamic>{
        'theme_mode': 'dark',
        'seed_color': 0xFF607D8B,
        'tool_paths': <String, dynamic>{
          'ffmpeg': r'D:\tools\ffmpeg.exe',
          'ffprobe': r'D:\tools\ffprobe.exe',
          'gyroflow': r'D:\tools\gyroflow.exe',
          'catalyst': null,
        },
      });

      expect(preferences.themeMode, ThemeMode.dark);
      expect(preferences.seedColor, 0xFF607D8B);
      expect(preferences.languageMode, AppLanguageMode.system);
      expect(preferences.toolPaths['ffmpeg'], r'D:\tools\ffmpeg.exe');
      expect(preferences.toolPaths['gyroflow'], r'D:\tools\gyroflow.exe');
      expect(preferences.hasCompleteToolPaths, isTrue);
    },
  );

  test(
    'locale resolution maps every zh family to zh and other locales to en',
    () {
      expect(preferredLocale(AppLanguageMode.system), isNull);
      expect(preferredLocale(AppLanguageMode.zh), const Locale('zh'));
      expect(preferredLocale(AppLanguageMode.en), const Locale('en'));
      expect(
        resolveSupportedLocale(const Locale('zh', 'TW')),
        const Locale('zh'),
      );
      expect(
        resolveSupportedLocale(
          const Locale.fromSubtags(
            languageCode: 'zh',
            scriptCode: 'Hans',
            countryCode: 'CN',
          ),
        ),
        const Locale('zh'),
      );
      expect(
        resolveSupportedLocale(const Locale('fr', 'FR')),
        const Locale('en'),
      );
      expect(resolveSupportedLocale(null), const Locale('en'));
    },
  );

  testWidgets('system language follows a Simplified Chinese device locale', (
    tester,
  ) async {
    tester.binding.platformDispatcher.localesTestValue = const <Locale>[
      Locale('zh', 'TW'),
    ];
    addTearDown(tester.binding.platformDispatcher.clearLocalesTestValue);
    await _pumpApp(tester, _testPreferences());

    expect(tester.widget<MaterialApp>(find.byType(MaterialApp)).locale, isNull);
    expect(find.byTooltip('工作台'), findsOneWidget);
    expect(
      find.descendant(
        of: find.byType(DesktopSidebar),
        matching: find.byTooltip('任务'),
      ),
      findsOneWidget,
    );
  });

  testWidgets(
    'manual Chinese and English override the operating-system locale',
    (tester) async {
      tester.binding.platformDispatcher.localesTestValue = const <Locale>[
        Locale('en', 'US'),
      ];
      addTearDown(tester.binding.platformDispatcher.clearLocalesTestValue);
      await _pumpApp(
        tester,
        _testPreferences(languageMode: AppLanguageMode.zh),
      );
      expect(find.byTooltip('工作台'), findsOneWidget);

      await tester.pumpWidget(const SizedBox.shrink());
      await tester.pump();
      tester.binding.platformDispatcher.localesTestValue = const <Locale>[
        Locale('zh', 'CN'),
      ];
      await _pumpApp(
        tester,
        _testPreferences(languageMode: AppLanguageMode.en),
      );
      expect(find.byTooltip('Workbench'), findsOneWidget);
    },
  );

  testWidgets(
    'Settings replaces File, View and Help menus and confirms native close',
    (tester) async {
      tester.binding.platformDispatcher.localesTestValue = const <Locale>[
        Locale('en', 'US'),
      ];
      addTearDown(tester.binding.platformDispatcher.clearLocalesTestValue);
      tester.view.devicePixelRatio = 1;
      tester.view.physicalSize = const Size(900, 900);
      addTearDown(tester.view.resetDevicePixelRatio);
      addTearDown(tester.view.resetPhysicalSize);
      final activeJob = JobSummary.fromJson(<String, dynamic>{
        'id': 'active-close-warning',
        'kind': 'fusion',
        'state': 'running',
        'stage': 'render',
        'progress': 0.4,
        'artifacts': <dynamic>[],
        'warnings': <dynamic>[],
      });
      final platform = TestPlatformAdapter(
        nativePicker: true,
        webAvailable: true,
        nativeDesktop: true,
        managedShutdown: true,
      );
      await tester.pumpWidget(
        ChaSteadyApp(
          api: TestApiService(jobs: <JobSummary>[activeJob]),
          platform: platform,
          sessionNonce: 'test-only-session',
        ),
      );
      await _settleInitial(tester);

      expect(find.byType(MenuBar), findsNothing);
      expect(find.byType(JobActivitySheet), findsNothing);
      expect(find.text('Job activity'), findsNothing);
      await tester.tap(
        find.byKey(const ValueKey<String>('sidebar-destination-1')),
      );
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 60));
      expect(find.byType(JobActivitySheet), findsNothing);
      expect(find.byType(JobListTile), findsOneWidget);
      expect(find.text('Running'), findsOneWidget);
      expect(
        tester
            .widget<LinearProgressIndicator>(
              find.byType(LinearProgressIndicator).first,
            )
            .value,
        0.4,
      );
      expect(find.text('Cancel job'), findsOneWidget);
      for (final menu in <String>['File', 'View', 'Help']) {
        expect(find.text(menu), findsNothing);
      }
      expect(platform.openWebCount, 0);
      await tester.tap(
        find.byKey(const ValueKey<String>('sidebar-destination-2')),
      );
      await tester.pump();
      final openWeb = find.byKey(const ValueKey<String>('settings-open-web'));
      await tester.scrollUntilVisible(
        openWeb,
        300,
        scrollable: _settingsScrollable(),
      );
      await _settleInitial(tester);
      await tester.ensureVisible(openWeb);
      await _settleInitial(tester);
      await tester.tap(openWeb);
      await tester.pump();
      expect(platform.openWebCount, 1);

      final closeHandler = platform.closeRequestHandler;
      expect(closeHandler, isNotNull);
      final cancelledClose = closeHandler!();
      await tester.pump(const Duration(milliseconds: 250));
      expect(find.text('Close ChaSteady?'), findsOneWidget);
      expect(find.textContaining('There is 1 active job'), findsOneWidget);
      expect(
        find.text(
          'The Web session will disconnect when the local service shuts down.',
        ),
        findsOneWidget,
      );
      await tester.tap(find.text('Cancel'));
      await tester.pump(const Duration(milliseconds: 250));
      expect(await cancelledClose, isFalse);
      expect(platform.shutdownRequested, isFalse);

      final confirmedClose = closeHandler();
      await tester.pump(const Duration(milliseconds: 250));
      await tester.tap(
        find.widgetWithText(FilledButton, 'Stop work and close'),
      );
      await tester.pump(const Duration(milliseconds: 250));
      expect(await confirmedClose, isTrue);
      expect(platform.shutdownRequested, isTrue);
    },
  );

  testWidgets(
    'forced shutdown warning stays localized and does not reconfirm close',
    (tester) async {
      tester.binding.platformDispatcher.localesTestValue = const <Locale>[
        Locale('en', 'US'),
      ];
      addTearDown(tester.binding.platformDispatcher.clearLocalesTestValue);
      tester.view.devicePixelRatio = 1;
      tester.view.physicalSize = const Size(900, 900);
      addTearDown(tester.view.resetDevicePixelRatio);
      addTearDown(tester.view.resetPhysicalSize);
      final platform = TestPlatformAdapter(
        nativePicker: true,
        webAvailable: true,
        nativeDesktop: true,
        managedShutdown: true,
      )..simulateShutdownWarning = true;
      await tester.pumpWidget(
        ChaSteadyApp(
          api: TestApiService(
            preferences: _testPreferences(languageMode: AppLanguageMode.en),
          ),
          platform: platform,
          sessionNonce: 'test-only-session',
        ),
      );
      await _settleInitial(tester);

      final closeHandler = platform.closeRequestHandler;
      expect(closeHandler, isNotNull);
      final closeResult = closeHandler!();
      await tester.pump(const Duration(milliseconds: 250));
      expect(find.text('Close ChaSteady?'), findsOneWidget);
      await tester.tap(
        find.widgetWithText(FilledButton, 'Stop work and close'),
      );
      await tester.pump(const Duration(milliseconds: 250));
      expect(find.textContaining('Stopping processing.'), findsOneWidget);

      expect(find.text('The worker required forced shutdown'), findsOneWidget);
      expect(
        find.textContaining('closed only its owned worker process tree'),
        findsOneWidget,
      );
      await tester.tap(find.text('Continue closing'));
      await tester.pump(const Duration(milliseconds: 250));
      expect(await closeResult, isTrue);
      expect(platform.shutdownRequested, isTrue);
      expect(find.text('Close ChaSteady?'), findsNothing);
    },
  );

  testWidgets(
    'localized semantics and layout remain usable at 360, 800 and 1440',
    (tester) async {
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetDevicePixelRatio);
      addTearDown(tester.view.resetPhysicalSize);
      final running = JobSummary.fromJson(<String, dynamic>{
        'id': 'semantic-running-job',
        'kind': 'render',
        'state': 'running',
        'stage': 'render',
        'progress': null,
        'artifacts': <dynamic>[],
        'warnings': <dynamic>[],
      });
      final app = ChaSteadyApp(
        api: TestApiService(
          jobs: <JobSummary>[running],
          preferences: _testPreferences(languageMode: AppLanguageMode.zh),
        ),
        platform: TestPlatformAdapter(),
        sessionNonce: 'test-only-session',
      );

      for (final size in <Size>[
        const Size(360, 900),
        const Size(800, 900),
        const Size(1440, 1000),
      ]) {
        tester.view.physicalSize = size;
        await tester.pumpWidget(app);
        await _settleInitial(tester);
        expect(tester.takeException(), isNull);
        expect(find.byType(MenuBar), findsNothing);
        if (size.width < 800) {
          expect(find.text('工作台'), findsOneWidget);
          expect(find.text('设置'), findsOneWidget);
        } else {
          expect(find.byTooltip('工作台'), findsOneWidget);
          expect(find.byTooltip('设置'), findsOneWidget);
          expect(
            tester.widget<DesktopSidebar>(find.byType(DesktopSidebar)).expanded,
            isTrue,
          );
        }
        expect(find.byType(JobActivitySheet), findsNothing);
        expect(find.byType(DraggableScrollableSheet), findsNothing);
        expect(find.text('任务活动'), findsNothing);
        expect(
          find.byWidgetPredicate(
            (widget) =>
                widget is Semantics &&
                const <String>[
                  '调整任务活动面板大小',
                  '调整任务面板大小',
                ].contains(widget.properties.label),
          ),
          findsNothing,
        );

        await tester.tap(
          size.width < 800
              ? find.descendant(
                  of: find.byType(NavigationBar),
                  matching: find.text('任务'),
                )
              : find.byKey(const ValueKey<String>('sidebar-destination-1')),
        );
        await tester.pump();
        await tester.pump(const Duration(milliseconds: 60));
        expect(find.byType(JobListTile), findsOneWidget);
        expect(find.text('运行中'), findsOneWidget);
        expect(
          find.byWidgetPredicate(
            (widget) =>
                widget is Semantics &&
                widget.properties.label == '渲染进度未知' &&
                widget.properties.value == '不确定进度',
          ),
          findsOneWidget,
        );
        expect(find.text('取消任务'), findsOneWidget);

        await tester.tap(find.byIcon(Icons.video_library_outlined));
        await tester.pump();
        await tester.pump(const Duration(milliseconds: 60));
        expect(tester.takeException(), isNull);
        expect(find.byType(JobActivitySheet), findsNothing);
        if (size.width < 800) {
          expect(find.text('工作台'), findsOneWidget);
        } else {
          expect(find.byTooltip('工作台'), findsOneWidget);
        }
      }
    },
  );

  test(
    'partial refresh preserves unsaved drafts and patches only changed fields',
    () async {
      final api = TestApiService(preferences: _testPreferences());
      final controller = AppController(
        api: api,
        platform: TestPlatformAdapter(),
        sessionNonce: 'test-only-session',
      );
      addTearDown(controller.dispose);
      await controller.initialize();

      final localPaths = Map<String, String?>.of(
        controller.draftPreferences.toolPaths,
      )..['ffmpeg'] = r'D:\local\ffmpeg.exe';
      controller.updatePreferenceDraft(
        controller.draftPreferences.copyWith(
          themeMode: ThemeMode.dark,
          toolPaths: Map<String, String?>.unmodifiable(localPaths),
        ),
      );
      final remotePaths = Map<String, String?>.of(api.preferences.toolPaths)
        ..['gyroflow'] = r'D:\remote\gyroflow.exe';
      api.preferences = api.preferences.copyWith(
        seedColor: 0xFF607D8B,
        languageMode: AppLanguageMode.zh,
        toolPaths: Map<String, String?>.unmodifiable(remotePaths),
      );

      await controller.refreshPreferences();
      expect(controller.draftPreferences.themeMode, ThemeMode.dark);
      expect(controller.draftPreferences.seedColor, 0xFF607D8B);
      expect(controller.draftPreferences.languageMode, AppLanguageMode.zh);
      expect(
        controller.draftPreferences.toolPaths['ffmpeg'],
        r'D:\local\ffmpeg.exe',
      );
      expect(
        controller.draftPreferences.toolPaths['gyroflow'],
        r'D:\remote\gyroflow.exe',
      );

      await controller.savePreferences();
      expect(api.preferencePatches, hasLength(1));
      expect(api.preferencePatches.single, <String, dynamic>{
        'theme_mode': 'dark',
        'tool_paths': <String, String?>{'ffmpeg': r'D:\local\ffmpeg.exe'},
      });
      expect(controller.preferences.languageMode, AppLanguageMode.zh);
      expect(controller.preferences.seedColor, 0xFF607D8B);
      expect(
        controller.preferences.toolPaths['gyroflow'],
        r'D:\remote\gyroflow.exe',
      );
    },
  );

  testWidgets(
    'native errors translate stable keys and retain original code/HRESULT',
    (tester) async {
      await tester.pumpWidget(
        MaterialApp(
          locale: const Locale('zh'),
          localizationsDelegates: AppLocalizations.localizationsDelegates,
          supportedLocales: AppLocalizations.supportedLocales,
          home: Builder(
            builder: (context) => Text(
              localizedPlatformError(
                context.l10n,
                PlatformException(
                  code: 'native_worker_timeout',
                  message: 'Worker process exit timed out.',
                  details: <String, dynamic>{
                    'message_key': 'nativeWorker.error.timeout',
                    'args': const <String, dynamic>{},
                    'hresult': '0x80070005',
                  },
                ),
              ),
            ),
          ),
        ),
      );
      await tester.pump();
      expect(find.textContaining('本地工作进程未能在超时前响应。'), findsOneWidget);
      expect(
        find.textContaining('平台错误代码：native_worker_timeout'),
        findsOneWidget,
      );
      expect(find.textContaining('原始 HRESULT：0x80070005'), findsOneWidget);
    },
  );

  test('localization models retain known worker keys and arguments', () {
    final job = JobSummary.fromJson(<String, dynamic>{
      'id': 'localized-progress',
      'kind': 'fusion',
      'state': 'running',
      'stage': 'render',
      'progress': null,
      'message_key': 'job.progress.render',
      'args': <String, dynamic>{'current': 11, 'total': 20},
      'artifacts': <dynamic>[],
      'warnings': <dynamic>[],
    });
    expect(job.workerMessage.messageKey, 'job.progress.render');
    expect(job.workerMessage.args, <String, dynamic>{
      'current': 11,
      'total': 20,
    });
  });
}

AppPreferences _testPreferences({
  AppLanguageMode languageMode = AppLanguageMode.system,
}) => AppPreferences(
  themeMode: ThemeMode.system,
  seedColor: 0xFF55766D,
  languageMode: languageMode,
  toolPaths: const <String, String?>{
    'ffmpeg': r'D:\tools\ffmpeg.exe',
    'ffprobe': r'D:\tools\ffprobe.exe',
    'gyroflow': null,
    'catalyst': null,
  },
  toolPathsLoaded: true,
);

Future<void> _pumpApp(WidgetTester tester, AppPreferences preferences) async {
  await tester.pumpWidget(
    ChaSteadyApp(
      api: TestApiService(preferences: preferences),
      platform: TestPlatformAdapter(),
      sessionNonce: 'test-only-session',
    ),
  );
  await _settleInitial(tester);
}

Finder _settingsScrollable() => find
    .descendant(
      of: find.byKey(const ValueKey<String>('settings-list')),
      matching: find.byType(Scrollable),
    )
    .first;

Future<void> _settleInitial(WidgetTester tester) async {
  await tester.pump();
  await tester.pump(const Duration(milliseconds: 60));
  await tester.pump(const Duration(milliseconds: 60));
}
