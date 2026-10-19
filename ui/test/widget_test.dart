import 'package:cha_stabilizer_ui/src/app.dart';
import 'package:cha_stabilizer_ui/src/controller.dart';
import 'package:cha_stabilizer_ui/src/localization.dart';
import 'package:cha_stabilizer_ui/src/models.dart';
import 'package:cha_stabilizer_ui/src/path_rules.dart';
import 'package:cha_stabilizer_ui/src/widgets/desktop_sidebar.dart';
import 'package:cha_stabilizer_ui/src/widgets/job_activity_sheet.dart';
import 'package:cha_stabilizer_ui/src/widgets/job_detail.dart';
import 'package:cha_stabilizer_ui/src/widgets/job_widgets.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'test_fakes.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized()
      .platformDispatcher
      .localesTestValue = const <Locale>[
    Locale('en', 'US'),
  ];

  group('local path validation', () {
    test(
      'accepts absolute drive and POSIX paths but rejects URLs and relatives',
      () {
        expect(isLocalAbsolutePath(r'N:\media\source.mp4'), isTrue);
        expect(isLocalAbsolutePath('/mnt/media/source.mp4'), isTrue);
        expect(isLocalAbsolutePath('relative/source.mp4'), isFalse);
        expect(
          isLocalAbsolutePath('https://example.invalid/source.mp4'),
          isFalse,
        );
      },
    );
  });

  group('reference FOV validation', () {
    test(
      'accepts the supported analysis range and rejects render assumptions',
      () {
        expect(parseReferenceFov('1'), 1);
        expect(parseReferenceFov('2.0'), 2);
        expect(parseReferenceFov('4'), 4);
        expect(parseReferenceFov('0'), isNull);
        expect(parseReferenceFov('4.01'), isNull);
        expect(parseReferenceFov('NaN'), isNull);
      },
    );
  });

  group('fusion source window validation', () {
    test(
      'requires a valid source window independently of reference intervals',
      () {
        expect(validateSourceWindow('', '').isValid, isFalse);
        final window = validateSourceWindow('212', '228');
        expect(window.isValid, isTrue);
        expect(window.ranges.single.start, 212.0);
        expect(validateIntervals(const <(String, String)>[]).ranges, isEmpty);
      },
    );
  });

  group('manual interval validation', () {
    test('accepts reviewed chronological, non-overlapping ranges', () {
      final result = validateIntervals(<(String, String)>[
        ('153.0', '156.0'),
        ('231.8', '235.5'),
      ]);

      expect(result.isValid, isTrue);
      expect(result.ranges.first.start, 153.0);
      expect(result.ranges.last.end, 235.5);
    });

    test(
      'rejects missing, malformed, reversed, overlapping, and unsorted ranges',
      () {
        expect(validateIntervals(const <(String, String)>[]).isValid, isTrue);
        expect(
          validateIntervals([('', '2')]).code,
          IntervalValidationCode.nonNumeric,
        );
        expect(
          validateIntervals([('4', '4')]).code,
          IntervalValidationCode.endNotAfterStart,
        );
        expect(
          validateIntervals([('1', '4'), ('3', '5')]).code,
          IntervalValidationCode.overlap,
        );
        expect(
          validateIntervals([('5', '6'), ('1', '2')]).code,
          IntervalValidationCode.chronologicalOrder,
        );
      },
    );
  });

  testWidgets(
    'job preview and scope stay ahead of collapsed warning and result details',
    (tester) async {
      tester.view.devicePixelRatio = 1;
      tester.view.physicalSize = const Size(1440, 1400);
      addTearDown(tester.view.resetDevicePixelRatio);
      addTearDown(tester.view.resetPhysicalSize);

      final job = JobSummary.fromJson(<String, dynamic>{
        'id': 'job-result-preview-order',
        'kind': 'gyroflow_export',
        'state': 'needs_review',
        'stage': 'validation',
        'progress': null,
        'message': 'The owned export is retained for review.',
        'artifacts': <dynamic>[
          <String, dynamic>{
            'id': 'audit-manifest',
            'label': 'Export audit manifest',
            'kind': 'diagnostic_manifest',
            'url': '',
            'mime': 'application/json',
            'warnings': <String>['Manifest evidence is incomplete.'],
          },
          <String, dynamic>{
            'id': 'review-video',
            'label': 'Gyroflow export requiring review',
            'kind': 'preview',
            'url': '/api/artifacts/review-video/content',
            'mime': 'video/mp4',
            'validation_scope': 'full decode passed; trim mapping not verified',
            'media_metadata': <String, dynamic>{
              'video_codec': 'h264',
              'audio_codec': 'aac',
            },
            'warnings': <String>[
              'The measured frame count differs from source selection.',
            ],
          },
        ],
        'warnings': <String>[
          'Output PTS sequence requires review.',
          'Content correspondence was not verified.',
        ],
        'result': <String, dynamic>{
          'audit_marker': 'RESULT_JSON_COLLAPSED_MARKER',
          'evidence_rows': List<String>.generate(
            100,
            (index) => 'Worker evidence row $index',
          ),
        },
      });
      final platform = TestPlatformAdapter();
      final controller = AppController(
        api: TestApiService(),
        platform: platform,
        sessionNonce: 'test-only-session',
      );
      addTearDown(controller.dispose);

      await tester.pumpWidget(
        MaterialApp(
          locale: const Locale('en'),
          localizationsDelegates: AppLocalizations.localizationsDelegates,
          supportedLocales: AppLocalizations.supportedLocales,
          home: Scaffold(
            body: SingleChildScrollView(
              child: Padding(
                padding: const EdgeInsets.all(16),
                child: JobDetailPanel(
                  job: job,
                  controller: controller,
                  platform: platform,
                  onError: (_) {},
                ),
              ),
            ),
          ),
        ),
      );
      await tester.pumpAndSettle();

      final scope = find.textContaining(
        'Reported scope: full decode passed; trim mapping not verified.',
      );
      final reviewNotice = find.text('Review before continuing');
      final preview = find.textContaining('Local H.264/AAC preview.');
      final artifactWarnings = find.text('Artifact warnings · 1');
      final workerWarnings = find.text('Worker warnings · 2');
      final resultDetails = find.text('Worker result details');
      expect(reviewNotice, findsOneWidget);
      expect(scope, findsOneWidget);
      expect(preview, findsOneWidget);
      expect(artifactWarnings, findsNWidgets(2));
      expect(workerWarnings, findsOneWidget);
      expect(find.textContaining('RESULT_JSON_COLLAPSED_MARKER'), findsNothing);
      expect(
        find.byIcon(Icons.warning_amber_outlined),
        findsAtLeastNWidgets(2),
      );
      expect(
        tester.getTopLeft(reviewNotice).dy,
        lessThan(tester.getTopLeft(preview).dy),
      );
      expect(
        tester.getTopLeft(scope).dy,
        lessThan(tester.getTopLeft(preview).dy),
      );
      expect(
        tester.getTopLeft(preview).dy,
        lessThan(tester.getTopLeft(artifactWarnings.first).dy),
      );
      expect(
        tester.getTopLeft(artifactWarnings.first).dy,
        lessThan(tester.getTopLeft(workerWarnings).dy),
      );
      expect(
        tester.getTopLeft(workerWarnings).dy,
        lessThan(tester.getTopLeft(resultDetails).dy),
      );

      await tester.ensureVisible(resultDetails);
      await tester.tap(resultDetails);
      await tester.pumpAndSettle();
      expect(
        find.textContaining('RESULT_JSON_COLLAPSED_MARKER'),
        findsOneWidget,
      );
      final resultScroll = find.descendant(
        of: find.byKey(
          const ValueKey<String>('worker-result-job-result-preview-order'),
        ),
        matching: find.byType(SingleChildScrollView),
      );
      expect(tester.getSize(resultScroll).height, lessThanOrEqualTo(300));
    },
  );

  testWidgets(
    'fresh fusion keeps the source window independent of an empty list',
    (tester) async {
      tester.view.devicePixelRatio = 1;
      tester.view.physicalSize = const Size(1600, 1000);
      addTearDown(tester.view.resetDevicePixelRatio);
      addTearDown(tester.view.resetPhysicalSize);
      final api = TestApiService(
        capabilities: const Capabilities(
          ffmpeg: ToolCapability(detected: true),
          ffprobe: ToolCapability(detected: true),
          gyroflow: ToolCapability(detected: false),
          catalyst: ToolCapability(detected: false),
          presetCatalog: <PresetRecord>[],
          nativePicker: false,
        ),
      );
      await tester.pumpWidget(
        ChaSteadyApp(
          api: api,
          platform: TestPlatformAdapter(),
          sessionNonce: 'test-only-session',
        ),
      );
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 80));
      await tester.pump(const Duration(milliseconds: 80));

      for (final (label, path) in <(String, String)>[
        ('Original video', r'N:\manual\original.mp4'),
        ('CTB input video', r'N:\manual\ctb.mp4'),
        ('Gyroflow reference video', r'N:\manual\reference.mp4'),
      ]) {
        if (label == 'CTB input video') await _openResearch(tester);
        final field = find.byWidgetPredicate(
          (widget) =>
              widget is TextField && widget.decoration?.labelText == label,
        );
        await tester.scrollUntilVisible(
          field,
          240,
          scrollable: _workbenchScrollable(),
        );
        await tester.enterText(field, path);
        await tester.pump();
      }

      for (final (label, value) in <(String, String)>[
        ('Start (s)', '212'),
        ('End (s)', '228'),
      ]) {
        final field = find.byWidgetPredicate(
          (widget) =>
              widget is TextField && widget.decoration?.labelText == label,
        );
        await tester.scrollUntilVisible(
          field,
          240,
          scrollable: _workbenchScrollable(),
        );
        await tester.enterText(field, value);
        await tester.pump();
      }

      final review = find.text(
        'I reviewed the reference-interval list, including an empty list, against this request.',
      );
      await tester.scrollUntilVisible(
        review,
        240,
        scrollable: _workbenchScrollable(),
      );
      await _scrollToHit(tester, review);
      await tester.tap(review);
      await tester.pump();
      final createJob = find.widgetWithText(FilledButton, 'Create fusion job');
      await _scrollToHit(tester, createJob);
      expect(tester.widget<FilledButton>(createJob).onPressed, isNotNull);
      await tester.tap(createJob);
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 50));

      expect(api.submittedRequests, hasLength(1));
      expect(api.submittedRequests.single.$1, 'fusion');
      final request = api.submittedRequests.single.$2;
      expect(request['start'], 212.0);
      expect(request['end'], 228.0);
      expect(request['reference_intervals'], isEmpty);
      expect(request['mode'], 'fresh');
    },
  );

  testWidgets(
    'Web navigation adapts from phone to sidebar without a home activity overlay',
    (tester) async {
      tester.view.devicePixelRatio = 1;
      tester.view.physicalSize = const Size(390, 844);
      addTearDown(tester.view.resetDevicePixelRatio);
      addTearDown(tester.view.resetPhysicalSize);

      final api = TestApiService();
      await tester.pumpWidget(
        ChaSteadyApp(
          api: api,
          platform: TestPlatformAdapter(),
          sessionNonce: 'test-only-session',
        ),
      );
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 80));
      await tester.pump(const Duration(milliseconds: 80));

      expect(find.byType(NavigationBar), findsOneWidget);
      expect(find.byType(DesktopSidebar), findsNothing);
      expect(
        tester
            .widget<MaterialApp>(find.byType(MaterialApp))
            .theme!
            .useMaterial3,
        isTrue,
      );

      await tester.tap(
        find.descendant(
          of: find.byType(NavigationBar),
          matching: find.text('Settings'),
        ),
      );
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 50));
      await tester.tap(
        find.descendant(
          of: find.byType(SegmentedButton<ThemeMode>),
          matching: find.text('Dark'),
        ),
      );
      await tester.pump();
      expect(
        tester.widget<MaterialApp>(find.byType(MaterialApp)).themeMode,
        ThemeMode.dark,
      );

      tester.view.physicalSize = const Size(900, 900);
      await tester.pump();
      expect(find.byType(DesktopSidebar), findsOneWidget);
      expect(find.byType(NavigationBar), findsNothing);
      await tester.tap(
        find.descendant(
          of: find.byType(DesktopSidebar),
          matching: find.byIcon(Icons.video_library_outlined),
        ),
      );
      await tester.pump();

      tester.view.physicalSize = const Size(1600, 1000);
      await tester.pump();
      expect(find.byType(DesktopSidebar), findsOneWidget);
      expect(find.byType(JobActivitySheet), findsNothing);
      expect(find.byType(DraggableScrollableSheet), findsNothing);
      expect(find.text('Job activity'), findsNothing);
    },
  );

  testWidgets(
    'home omits activity overlay while Jobs keeps progress and cancellation',
    (tester) async {
      tester.view.devicePixelRatio = 1;
      tester.view.physicalSize = const Size(390, 844);
      addTearDown(tester.view.resetDevicePixelRatio);
      addTearDown(tester.view.resetPhysicalSize);

      final running = JobSummary.fromJson(<String, dynamic>{
        'id': 'running-overlay-regression',
        'kind': 'preview',
        'state': 'running',
        'stage': 'encoding',
        'progress': 0.4,
        'message': 'Encoding test artifact.',
        'artifacts': <dynamic>[],
        'warnings': <dynamic>[],
      });
      final api = TestApiService(jobs: <JobSummary>[running]);
      await tester.pumpWidget(
        ChaSteadyApp(
          api: api,
          platform: TestPlatformAdapter(),
          sessionNonce: 'test-only-session',
        ),
      );
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 80));
      await tester.pump(const Duration(milliseconds: 80));

      expect(find.byType(JobActivitySheet), findsNothing);
      expect(find.byType(DraggableScrollableSheet), findsNothing);
      expect(find.text('Job activity'), findsNothing);

      tester.view.physicalSize = const Size(1600, 1000);
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 80));
      expect(find.byType(JobActivitySheet), findsNothing);
      expect(find.byType(DraggableScrollableSheet), findsNothing);
      expect(find.text('Job activity'), findsNothing);

      await tester.tap(
        find.descendant(
          of: find.byType(DesktopSidebar),
          matching: find.text('Jobs'),
        ),
      );
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 80));

      expect(find.byType(JobActivitySheet), findsNothing);
      expect(find.byType(JobListTile), findsOneWidget);
      expect(find.text('Running'), findsOneWidget);
      final progress = tester.widget<LinearProgressIndicator>(
        find.byType(LinearProgressIndicator).first,
      );
      expect(progress.value, 0.4);
      expect(find.text('Cancel job'), findsOneWidget);

      await tester.tap(find.text('Cancel job'));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 80));

      expect(api.jobs.single.state, 'cancelled');
      expect(find.text('Cancelled'), findsOneWidget);
      expect(find.text('Cancel job'), findsNothing);
    },
  );

  testWidgets(
    'unknown job progress is indeterminate and worker errors stay explicit',
    (tester) async {
      tester.view.devicePixelRatio = 1;
      tester.view.physicalSize = const Size(390, 844);
      addTearDown(tester.view.resetDevicePixelRatio);
      addTearDown(tester.view.resetPhysicalSize);

      final running = JobSummary.fromJson(<String, dynamic>{
        'id': 'test-running',
        'kind': 'preview',
        'state': 'running',
        'stage': 'encoding',
        'progress': null,
        'message': 'Encoding test artifact.',
        'artifacts': <dynamic>[],
        'warnings': <dynamic>[],
      });
      final failed = JobSummary.fromJson(<String, dynamic>{
        'id': 'test-failed',
        'kind': 'preview',
        'state': 'failed',
        'stage': 'ffmpeg',
        'progress': null,
        'message': 'Preview did not start.',
        'error': <String, dynamic>{
          'code': 'missing_tool',
          'message': 'FFmpeg was not detected.',
        },
        'artifacts': <dynamic>[],
        'warnings': <dynamic>[],
      });

      await tester.pumpWidget(
        ChaSteadyApp(
          api: TestApiService(jobs: <JobSummary>[running, failed]),
          platform: TestPlatformAdapter(),
          sessionNonce: 'test-only-session',
        ),
      );
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 80));
      await tester.pump(const Duration(milliseconds: 80));
      await tester.tap(
        find.descendant(
          of: find.byType(NavigationBar),
          matching: find.text('Jobs'),
        ),
      );
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 80));

      expect(find.text('Progress not reported'), findsOneWidget);
      expect(
        find.text('The worker has not reported a percentage for this stage.'),
        findsWidgets,
      );
      expect(find.textContaining('Error code: missing_tool'), findsOneWidget);
      expect(find.textContaining('FFmpeg was not detected.'), findsOneWidget);
      final progress = tester.widget<LinearProgressIndicator>(
        find.byType(LinearProgressIndicator).first,
      );
      expect(progress.value, isNull);
      expect(
        progress.semanticsLabel,
        'Original worker stage: encoding progress unknown',
      );
    },
  );

  testWidgets(
    'capability truth states remain distinct and Catalyst stays manual',
    (tester) async {
      tester.view.devicePixelRatio = 1;
      tester.view.physicalSize = const Size(390, 844);
      addTearDown(tester.view.resetDevicePixelRatio);
      addTearDown(tester.view.resetPhysicalSize);

      final capabilities = const Capabilities(
        ffmpeg: ToolCapability(detected: false),
        gyroflow: ToolCapability(detected: null),
        catalyst: ToolCapability(
          detected: true,
          mode: 'assisted',
          uiaVerified: false,
        ),
        presetCatalog: <PresetRecord>[],
        nativePicker: false,
      );
      await tester.pumpWidget(
        ChaSteadyApp(
          api: TestApiService(capabilities: capabilities),
          platform: TestPlatformAdapter(),
          sessionNonce: 'test-only-session',
        ),
      );
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 80));
      await tester.pump(const Duration(milliseconds: 80));

      await tester.tap(
        find.descendant(
          of: find.byType(NavigationBar),
          matching: find.text('Settings'),
        ),
      );
      await tester.pump();
      await tester.scrollUntilVisible(
        find.text('Not detected'),
        300,
        scrollable: find
            .descendant(
              of: find.byKey(const ValueKey<String>('settings-list')),
              matching: find.byType(Scrollable),
            )
            .first,
      );
      expect(find.text('Not detected'), findsOneWidget);
      expect(find.text('Status unknown'), findsWidgets);
      expect(find.text('Not verified'), findsOneWidget);
      expect(
        find.text('Catalyst assisted export · manual required'),
        findsOneWidget,
      );

      await tester.tap(
        find.descendant(
          of: find.byType(NavigationBar),
          matching: find.text('Workbench'),
        ),
      );
      await tester.pump();
      await _openResearch(tester);
      await tester.scrollUntilVisible(
        find.text('Request Catalyst manual steps'),
        280,
        scrollable: _workbenchScrollable(),
      );
      expect(
        find.text('Catalyst assisted export · needs manual steps'),
        findsOneWidget,
      );
      expect(
        find.textContaining('This UI never starts Catalyst automation.'),
        findsOneWidget,
      );
      expect(find.text('Request Catalyst manual steps'), findsOneWidget);
      expect(find.text('Run Catalyst automatically'), findsNothing);
    },
  );
}

Future<void> _scrollToHit(WidgetTester tester, Finder target) async {
  for (
    var step = 0;
    step < 60 && target.hitTestable().evaluate().isEmpty;
    step++
  ) {
    final above =
        target.evaluate().isNotEmpty && tester.getCenter(target).dy < 100;
    await tester.drag(_workbenchScrollable(), Offset(0, above ? 260 : -260));
    await tester.pump(const Duration(milliseconds: 80));
  }
  expect(target.hitTestable(), findsOneWidget);
}

Future<void> _openResearch(WidgetTester tester) async {
  final research = find.text('Advanced research · explicit inputs and history');
  await tester.scrollUntilVisible(
    research,
    240,
    scrollable: _workbenchScrollable(),
  );
  await tester.ensureVisible(research);
  await tester.tap(research);
  await tester.pump(const Duration(milliseconds: 250));
}

Finder _workbenchScrollable() => find
    .descendant(
      of: find.byKey(const ValueKey<String>('workbench-list')),
      matching: find.byType(Scrollable),
    )
    .first;
