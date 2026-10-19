import 'dart:async';

import 'package:cha_stabilizer_ui/src/app.dart';
import 'package:cha_stabilizer_ui/src/brand.dart';
import 'package:cha_stabilizer_ui/src/controller.dart';
import 'package:cha_stabilizer_ui/src/models.dart';
import 'package:cha_stabilizer_ui/src/platform/media_platform.dart';
import 'package:cha_stabilizer_ui/src/widgets/desktop_sidebar.dart';
import 'package:cha_stabilizer_ui/src/widgets/source_path_field.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'test_fakes.dart';

const supported = Capabilities(
  ffmpeg: ToolCapability(detected: true),
  ffprobe: ToolCapability(detected: true),
  gyroflow: ToolCapability(detected: true),
  catalyst: ToolCapability(detected: true, uiaVerified: false),
  presetCatalog: <PresetRecord>[],
  nativePicker: false,
  version: 'worker-test-component',
  stabilize: <String, dynamic>{
    'workflow_version': 1,
    'available': false,
    'ctb_automatic': false,
    'automatic_ctb_exports': 0,
    'continuation_supported': true,
  },
);

JobSummary workflowJob(
  String id,
  String state, {
  bool preview = false,
  String? parent,
}) => JobSummary.fromJson({
  'id': id,
  'kind': parent == null ? 'stabilize' : 'stabilize_continue',
  'state': state,
  'stage': state == 'needs_manual' ? 'capability_preflight' : state,
  'message_key': state == 'needs_manual'
      ? 'job.error.ctbExecutorUnavailable'
      : null,
  'error': state == 'failed'
      ? {'code': 'test_failure', 'message': 'simulated failure retained'}
      : null,
  'artifacts': preview
      ? <dynamic>[
          {
            'id': '33333333-3333-4333-8333-333333333333',
            'label': 'simulated owned preview',
            'kind': 'preview',
            'mime': 'video/mp4',
            'media_metadata': {'video_codec': 'h264', 'audio_codec': 'aac'},
            'validation_scope': 'simulated test scope only',
          },
        ]
      : <dynamic>[],
  'warnings': <dynamic>[],
  'workflow': {
    'schema_version': 1,
    'name': 'stabilize-v1',
    'profile': 'recommended-v1',
    'attempt': 1,
    'parent_job_id': parent,
    'ctb_origin': parent == null ? 'unavailable' : 'manual_import',
    'stages': <dynamic>[
      {'id': 'source_acceptance', 'state': 'passed', 'attempts': <dynamic>[]},
      {
        'id': 'capability_preflight',
        'state': state == 'needs_manual' ? 'blocked' : 'passed',
        'attempts': <dynamic>[],
      },
      {
        'id': 'ctb',
        'state': state == 'needs_manual' ? 'pending' : 'passed',
        'attempts': <dynamic>[],
      },
    ],
    'preview': {
      'state': preview ? 'ready' : 'not_requested',
      'job_id': preview ? '44444444-4444-4444-8444-444444444444' : null,
      'artifact_id': preview ? '33333333-3333-4333-8333-333333333333' : null,
    },
  },
});

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  setUp(() {
    TestWidgetsFlutterBinding.instance.platformDispatcher.localesTestValue =
        const <Locale>[Locale('en')];
    WidgetController.hitTestWarningShouldBeFatal = true;
  });
  tearDown(() {
    TestWidgetsFlutterBinding.instance.platformDispatcher
        .clearLocalesTestValue();
    WidgetController.hitTestWarningShouldBeFatal = false;
  });

  testWidgets(
    'embedded tasks use actual workspace threshold ±1 for both sidebar choices',
    (tester) async {
      final api = TestApiService(
        capabilities: supported,
        jobs: [workflowJob('threshold-job', 'running')],
      );
      await pumpApp(tester, api: api, size: const Size(1236, 900));
      final original = sourceField();
      await tester.enterText(original, r'D:\draft\中文 原片.mp4');
      for (final width in <double>[1236, 1237, 1238]) {
        tester.view.physicalSize = Size(width, 900);
        await settle(tester);
        expect(
          find.byKey(const ValueKey<String>('workbench-task-column')),
          width >= 1237 ? findsOneWidget : findsNothing,
        );
        if (width >= 1237) {
          final column = tester
              .getSize(
                find.byKey(const ValueKey<String>('workbench-task-column')),
              )
              .width;
          expect(column, inInclusiveRange(360, 440));
          expect(
            tester
                .getSize(find.byKey(const ValueKey<String>('workbench-list')))
                .width,
            greaterThanOrEqualTo(600),
          );
        }
        expect(
          tester.widget<TextField>(sourceField()).controller!.text,
          r'D:\draft\中文 原片.mp4',
        );
      }
      await tester.tap(
        find.byKey(const ValueKey<String>('sidebar-label-toggle')),
      );
      for (final width in <double>[1088, 1089, 1090]) {
        tester.view.physicalSize = Size(width, 900);
        await settle(tester);
        expect(
          find.byKey(const ValueKey<String>('workbench-task-column')),
          width >= 1089 ? findsOneWidget : findsNothing,
        );
      }
      final task = find.byKey(const ValueKey<String>('job-tile-threshold-job'));
      await tester.tap(task);
      await settle(tester);
      expect(controller(tester).selectedJobId, 'threshold-job');
      final right = taskScrollable();
      final leftPosition = tester
          .state<ScrollableState>(workbenchScrollable())
          .position;
      final rightPosition = tester.state<ScrollableState>(right).position;
      final leftBefore = leftPosition.pixels;
      await tester.drag(right, const Offset(0, -350));
      await settle(tester);
      expect(leftPosition.pixels, leftBefore);
      expect(rightPosition.pixels, greaterThan(0));
      final rightBefore = rightPosition.pixels;
      await tester.drag(workbenchScrollable(), const Offset(0, -300));
      await settle(tester);
      expect(rightPosition.pixels, rightBefore);
      await reveal(tester, find.text('Cancel job'), right);
      await tester.tap(find.text('Cancel job'));
      await settle(tester);
      expect(api.cancelCalls, 1);
      expect(controller(tester).selectedJob!.state, 'cancelled');
      expect(api.listCalls, 1, reason: '两个宿主不各自建立轮询');
      expect(tester.takeException(), isNull);
    },
  );

  testWidgets(
    'short sidebar remains reachable at large text and recovers intent after bottom navigation',
    (tester) async {
      tester.binding.platformDispatcher.textScaleFactorTestValue = 1.8;
      addTearDown(
        tester.binding.platformDispatcher.clearTextScaleFactorTestValue,
      );
      await pumpApp(tester, size: const Size(900, 300));
      final sidebarScroll = find.descendant(
        of: find.byKey(const ValueKey<String>('sidebar-scroll')),
        matching: find.byType(Scrollable),
      );
      final toggle = find.byKey(const ValueKey<String>('sidebar-label-toggle'));
      await reveal(tester, toggle, sidebarScroll);
      await tester.tap(toggle);
      await settle(tester);
      expect(
        tester.widget<DesktopSidebar>(find.byType(DesktopSidebar)).expanded,
        isFalse,
      );
      final settings = find.byKey(
        const ValueKey<String>('sidebar-destination-2'),
      );
      await reveal(tester, settings, sidebarScroll);
      await tester.tap(settings);
      await settle(tester);
      expect(
        controller(tester).draftPreferences.languageMode,
        AppLanguageMode.system,
      );
      tester.view.physicalSize = const Size(799, 500);
      await settle(tester);
      expect(find.byType(NavigationBar), findsOneWidget);
      tester.view.physicalSize = const Size(800, 500);
      await settle(tester);
      expect(
        tester.widget<DesktopSidebar>(find.byType(DesktopSidebar)).expanded,
        isFalse,
      );
      expect(tester.takeException(), isNull);
    },
  );

  testWidgets(
    'default original workflow submits recommended-v1 once and preserves manual blocker through linked continuation and close',
    (tester) async {
      const parentId = '11111111-1111-4111-8111-111111111111';
      const childId = '22222222-2222-4222-8222-222222222222';
      final api = TestApiService(capabilities: supported);
      final platform = TestPlatformAdapter(
        nativeDesktop: true,
        managedShutdown: true,
      );
      final pending = Completer<JobSummary>();
      api.createHandler = (_, _) => pending.future;
      await pumpApp(
        tester,
        api: api,
        platform: platform,
        size: const Size(1000, 900),
      );
      expect(find.text('Recommended · recommended-v1'), findsOneWidget);
      expect(find.text('CTB input video'), findsNothing);
      await tester.enterText(sourceField(), r'D:\原片\中文 空格.mp4');
      final start = find.byKey(const ValueKey<String>('start-stabilize'));
      await reveal(tester, start, workbenchScrollable());
      await tester.tap(start);
      await tester.tap(start);
      await settle(tester);
      expect(api.createCalls, 1);
      expect(api.submittedRequests.single.$1, 'stabilize');
      expect(api.submittedRequests.single.$2, {
        'original': r'D:\原片\中文 空格.mp4',
        'profile': 'recommended-v1',
        'full_source': true,
        'parameters': {
          'quiet_sigma_seconds': 1.3,
          'reference_fov': 1.0,
          'alignment_tau_seconds': 0.12,
          'minimum_weight_transition_seconds': 0.30,
          'weight_corner_speed': 12.5,
          'anchor_corner_speed': 5.0,
        },
      });
      final parent = workflowJob(parentId, 'needs_manual');
      api.jobs.add(parent);
      pending.complete(parent);
      await settle(tester);
      await tester.tap(
        find.byKey(const ValueKey<String>('workbench-open-jobs')),
      );
      await settle(tester);
      final manual = find.byKey(const ValueKey<String>('manual-continue'));
      await reveal(tester, manual, jobsScrollable());
      expect(
        find.textContaining('No validated lawful unattended CTB exporter'),
        findsWidgets,
      );
      await tester.tap(manual);
      await settle(tester);
      final manualPath = find.byWidgetPredicate(
        (widget) =>
            widget is TextField &&
            widget.decoration?.labelText == 'Manual CTB video',
      );
      await tester.enterText(manualPath, r'D:\manual\人工 CTB.mp4');
      await tester.tap(
        find.byKey(const ValueKey<String>('declare-manual-ctb')),
      );
      await settle(tester);
      api.createHandler = (kind, request) async {
        final child = workflowJob(childId, 'needs_review', parent: parentId);
        api.jobs.insert(0, child);
        return child;
      };
      await tester.tap(
        find.byKey(const ValueKey<String>('submit-manual-continuation')),
      );
      await settle(tester);
      final request = api.submittedRequests.last;
      expect(request.$1, 'stabilize_continue');
      expect(request.$2.keys.toSet(), {'parent_job_id', 'manual_ctb'});
      expect(request.$2['parent_job_id'], parentId);
      final manualCtb = request.$2['manual_ctb'] as Map;
      expect(manualCtb['source'], r'D:\manual\人工 CTB.mp4');
      expect(manualCtb['origin_seconds'], 0.0);
      expect(DateTime.parse(manualCtb['declared_at'] as String).isUtc, isTrue);
      expect(
        api.jobs.firstWhere((job) => job.id == parentId).state,
        'needs_manual',
      );
      expect(controller(tester).selectedJobId, childId);
      await tester.tap(
        find.byKey(const ValueKey<String>('sidebar-destination-2')),
      );
      await settle(tester);
      final exit = find.byKey(const ValueKey<String>('settings-exit'));
      await reveal(tester, exit, settingsScrollable());
      await tester.tap(exit);
      await settle(tester);
      await tester.tap(
        find.widgetWithText(FilledButton, 'Stop work and close'),
      );
      await settle(tester);
      expect(platform.shutdownCount, 1);
      expect(platform.shutdownRequested, isTrue);
      expect(platform.activePreviews, 0);
      expect(tester.takeException(), isNull);
    },
  );

  testWidgets(
    'simulated UI success, preview, host switches, failure and cancellation remain distinct',
    (tester) async {
      final api = TestApiService(capabilities: supported);
      final platform = TestPlatformAdapter();
      var nextState = 'verified_media';
      api.createHandler = (_, _) async {
        final job = workflowJob(
          'job-${api.createCalls}',
          nextState,
          preview: nextState == 'verified_media',
        );
        api.jobs.insert(0, job);
        if (nextState == 'verified_media') {
          api.jobs.insert(
            0,
            JobSummary(
              id: '44444444-4444-4444-8444-444444444444',
              kind: 'preview',
              state: 'verified_media',
              stage: 'verify',
              progress: null,
              message: 'simulated independent preview job',
              artifacts: job.artifacts,
              warnings: const <String>[],
            ),
          );
        }
        return job;
      };
      await pumpApp(
        tester,
        api: api,
        platform: platform,
        size: const Size(1440, 1100),
      );
      await tester.enterText(sourceField(), r'D:\source.mp4');
      final start = find.byKey(const ValueKey<String>('start-stabilize'));
      await reveal(tester, start, workbenchScrollable());
      await tester.tap(start);
      await settle(tester);
      expect(
        platform.activePreviews,
        0,
        reason: '父 stabilize 任务即使含预览描述，也不能取租约',
      );
      final openPreviewJob = find.text('Open preview job');
      await reveal(tester, openPreviewJob, taskScrollable());
      await tester.tap(openPreviewJob);
      await settle(tester);
      expect(controller(tester).selectedJob!.kind, 'preview');
      final previewText = find.textContaining('Local H.264/AAC preview.');
      await reveal(tester, previewText, taskScrollable());
      await settle(tester);
      expect(platform.activePreviews, 1);
      await tester.tap(
        find.byKey(const ValueKey<String>('workbench-open-jobs')),
      );
      await settle(tester);
      await reveal(tester, previewText, jobsScrollable());
      await settle(tester);
      expect(platform.activePreviews, 1);
      expect(platform.maxActivePreviews, 1, reason: '这是模拟宿主租约；原生异步租约另测');
      final open = find.text('Open local output');
      await reveal(tester, open, jobsScrollable());
      await tester.tap(open);
      await settle(tester);
      expect(api.openedArtifacts, ['33333333-3333-4333-8333-333333333333']);
      await tester.tap(
        find.byKey(const ValueKey<String>('sidebar-destination-2')),
      );
      await settle(tester);
      expect(platform.activePreviews, 0);
      await tester.tap(
        find.byKey(const ValueKey<String>('sidebar-destination-0')),
      );
      await settle(tester);
      nextState = 'failed';
      await reveal(tester, start, workbenchScrollable());
      await tester.tap(start);
      await settle(tester);
      expect(controller(tester).selectedJob!.state, 'failed');
      expect(platform.activePreviews, 0);
      nextState = 'running';
      await tester.tap(start);
      await settle(tester);
      final cancel = find.text('Cancel job');
      await reveal(tester, cancel, taskScrollable());
      await tester.tap(cancel);
      await settle(tester);
      expect(controller(tester).selectedJob!.state, 'cancelled');
      expect(api.cancelCalls, 1);
      expect(api.jobs.where((job) => job.state == 'failed'), hasLength(1));
      expect(
        api.jobs.where(
          (job) => job.kind == 'stabilize' && job.state == 'verified_media',
        ),
        hasLength(1),
      );
      expect(tester.takeException(), isNull);
    },
  );

  testWidgets(
    'source type, picker and simulated drop share invalidation and reject late inspect/picker/drop',
    (tester) async {
      final api = TestApiService(capabilities: supported);
      final platform = TestPlatformAdapter(
        nativePicker: true,
        nativeDrop: true,
        nativeDesktop: true,
        managedShutdown: true,
      );
      final inspectionA = Completer<MediaInfo>();
      api.inspectHandler = (path) async => path.endsWith('a.mp4')
          ? await inspectionA.future
          : MediaInfo(path: path, name: 'current B metadata');
      await pumpApp(
        tester,
        api: api,
        platform: platform,
        size: const Size(1000, 1000),
      );
      await tester.enterText(sourceField(), r'D:\a.mp4');
      await tester.tap(find.text('Inspect original metadata'));
      await settle(tester);
      platform.simulateDrop(r'D:\中文 空格 b.mp4');
      await settle(tester);
      expect(
        tester.widget<TextField>(sourceField()).controller!.text,
        r'D:\中文 空格 b.mp4',
      );
      await tester.tap(find.text('Inspect original metadata'));
      await settle(tester);
      inspectionA.complete(
        const MediaInfo(path: r'D:\a.mp4', name: 'stale A metadata'),
      );
      await settle(tester);
      expect(find.textContaining('current B metadata'), findsOneWidget);
      expect(find.textContaining('stale A metadata'), findsNothing);
      final choose = find.descendant(
        of: find.byKey(const ValueKey<String>('original-source-field')),
        matching: find.byType(IconButton),
      );
      final picker = Completer<String?>();
      platform.pickerGate = picker.future;
      await tester.tap(choose);
      await tester.pump();
      await tester.enterText(sourceField(), r'D:\typed-new.mp4');
      picker.complete(r'D:\late-picker.mp4');
      await settle(tester);
      expect(
        tester.widget<TextField>(sourceField()).controller!.text,
        r'D:\typed-new.mp4',
      );
      platform.pickerGate = null;
      platform.pickerPath = r'D:\picker-current.mp4';
      await tester.tap(choose);
      await settle(tester);
      expect(
        tester.widget<TextField>(sourceField()).controller!.text,
        r'D:\picker-current.mp4',
      );
      expect(find.textContaining('current B metadata'), findsNothing);
      final beforeClose = platform.dropTargets.length;
      final beforeCloseDrop = platform.dropHandler!;
      final close = platform.closeRequestHandler!();
      await settle(tester);
      expect(platform.dropTargets.last, isNull);
      await tester.tap(find.text('Cancel'));
      await settle(tester);
      expect(await close, isFalse);
      expect(platform.dropTargets.length, greaterThan(beforeClose));
      expect(
        platform.dropTargets.last,
        isNotNull,
        reason: '取消关闭且没有 resize 时仍必须重新注册',
      );
      beforeCloseDrop(r'D:\late-close-drop.mp4');
      await settle(tester);
      expect(
        tester.widget<TextField>(sourceField()).controller!.text,
        r'D:\picker-current.mp4',
      );
      final lateDrop = platform.dropHandler!;
      await tester.tap(
        find.byKey(const ValueKey<String>('sidebar-destination-2')),
      );
      await settle(tester);
      expect(platform.dropTargets.last, isNull);
      lateDrop(r'D:\late-drop.mp4');
      await tester.tap(
        find.byKey(const ValueKey<String>('sidebar-destination-0')),
      );
      await settle(tester);
      expect(
        tester.widget<TextField>(sourceField()).controller!.text,
        r'D:\picker-current.mp4',
      );
      platform.simulateDrop(r'C:\fakepath\browser.mp4');
      await settle(tester);
      expect(
        tester.widget<TextField>(sourceField()).controller!.text,
        r'D:\picker-current.mp4',
      );
      tester.view.physicalSize = const Size(1000, 650);
      await settle(tester);
      await tester.drag(workbenchScrollable(), const Offset(0, -700));
      await settle(tester);
      expect(platform.dropTargets.last, isNull);
      expect(tester.takeException(), isNull);
    },
  );

  testWidgets(
    'visible inactive keeps a target and simulated external drop invalidates source inspection',
    (tester) async {
      final platform = TestPlatformAdapter(
        nativeDrop: true,
        nativeDesktop: true,
        managedShutdown: true,
      );
      final api = TestApiService(capabilities: supported);
      await pumpApp(
        tester,
        api: api,
        platform: platform,
        size: const Size(1000, 1200),
      );
      addTearDown(() {
        final state = tester.binding.lifecycleState;
        if (state == AppLifecycleState.paused)
          tester.binding.handleAppLifecycleStateChanged(
            AppLifecycleState.hidden,
          );
        if (tester.binding.lifecycleState == AppLifecycleState.hidden)
          tester.binding.handleAppLifecycleStateChanged(
            AppLifecycleState.inactive,
          );
        if (tester.binding.lifecycleState != AppLifecycleState.resumed)
          tester.binding.handleAppLifecycleStateChanged(
            AppLifecycleState.resumed,
          );
      });
      await tester.enterText(sourceField(), r'D:\before-external-drop.mp4');
      await settle(tester);
      await tester.tap(find.text('Inspect original metadata'));
      await settle(tester);
      expect(find.textContaining('Name: test-only media'), findsOneWidget);
      final listsBeforeInactive = api.listCalls;
      tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.inactive);
      await settle(tester);
      expect(controller(tester).isForeground, isFalse);
      expect(
        platform.dropTargets.last,
        isNotNull,
        reason: '外部自有源窗口在前台时，可见工作台仍须接受 OLE；此处仅模拟事件',
      );
      platform.simulateDrop(r'D:\可见失焦\外部 原片.mp4');
      await settle(tester);
      expect(
        tester.widget<TextField>(sourceField()).controller!.text,
        r'D:\可见失焦\外部 原片.mp4',
      );
      expect(
        find.textContaining('Name: test-only media'),
        findsNothing,
        reason: '拖入仍必须经过源变更失效链',
      );
      await tester.pump(const Duration(seconds: 16));
      expect(api.listCalls, listsBeforeInactive, reason: '拖入可用不等于恢复前台任务轮询');
      final late = platform.dropHandler!;
      for (final state in <AppLifecycleState>[
        AppLifecycleState.hidden,
        AppLifecycleState.paused,
        AppLifecycleState.detached,
      ]) {
        tester.binding.handleAppLifecycleStateChanged(state);
        await settle(tester);
        expect(platform.dropTargets.last, isNull);
        late(r'D:\late-hidden-drop.mp4');
        expect(
          tester.widget<TextField>(sourceField()).controller!.text,
          r'D:\可见失焦\外部 原片.mp4',
        );
      }
      tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
      await settle(tester);
      expect(platform.dropTargets.last, isNotNull);
      expect(tester.takeException(), isNull);
    },
  );

  testWidgets(
    'drop visibility stays revoked for chooser modal page lock and confirmed close',
    (tester) async {
      final platform = TestPlatformAdapter(
        nativePicker: true,
        nativeDrop: true,
        nativeDesktop: true,
        managedShutdown: true,
        windowState: const DesktopWindowState(supported: true),
      );
      final api = TestApiService(capabilities: supported);
      await pumpApp(
        tester,
        api: api,
        platform: platform,
        size: const Size(1000, 1400),
      );
      addTearDown(() {
        if (tester.binding.lifecycleState == AppLifecycleState.inactive)
          tester.binding.handleAppLifecycleStateChanged(
            AppLifecycleState.resumed,
          );
      });
      await tester.enterText(sourceField(), r'D:\drop-guard-base.mp4');
      await settle(tester);
      final beforeChooser = platform.dropHandler!;
      final picker = Completer<String?>();
      platform.pickerGate = picker.future;
      final choose = find.descendant(
        of: find.byKey(const ValueKey<String>('original-source-field')),
        matching: find.byType(IconButton),
      );
      await tester.tap(choose);
      await tester.pump();
      expect(platform.dropTargets.last, isNull, reason: '选择器尚未结束时即使可见也不能接拖入');
      tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.inactive);
      await settle(tester);
      expect(platform.dropTargets.last, isNull);
      beforeChooser(r'D:\late-chooser-drop.mp4');
      expect(
        tester.widget<TextField>(sourceField()).controller!.text,
        r'D:\drop-guard-base.mp4',
      );
      tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
      await settle(tester);
      expect(platform.dropTargets.last, isNull, reason: '恢复前台不能提前解锁仍未完成的选择器');
      picker.complete(r'D:\picked-guard-base.mp4');
      await settle(tester);
      expect(platform.dropTargets.last, isNotNull);
      expect(
        tester.widget<TextField>(sourceField()).controller!.text,
        r'D:\picked-guard-base.mp4',
      );
      final beforeModal = platform.dropHandler!;
      await tester.tap(find.byTooltip('Close'));
      await settle(tester);
      expect(platform.dropTargets.last, isNull);
      beforeModal(r'D:\late-modal-drop.mp4');
      expect(
        tester.widget<TextField>(sourceField()).controller!.text,
        r'D:\picked-guard-base.mp4',
      );
      await tester.tap(find.text('Cancel'));
      await settle(tester);
      expect(platform.dropTargets.last, isNotNull);
      tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.inactive);
      await settle(tester);
      final beforePage = platform.dropHandler!;
      await tester.tap(
        find.byKey(const ValueKey<String>('sidebar-destination-2')),
      );
      await settle(tester);
      expect(platform.dropTargets.last, isNull);
      beforePage(r'D:\late-page-drop.mp4');
      await tester.tap(
        find.byKey(const ValueKey<String>('sidebar-destination-0')),
      );
      await settle(tester);
      expect(
        tester.widget<TextField>(sourceField()).controller!.text,
        r'D:\picked-guard-base.mp4',
      );
      expect(
        platform.dropTargets.last,
        isNotNull,
        reason: '失焦但可见的工作台恢复后允许外部拖入',
      );
      final beforeLock = platform.dropHandler!;
      final creating = Completer<JobSummary>();
      api.createHandler = (_, _) => creating.future;
      final start = find.byKey(const ValueKey<String>('start-stabilize'));
      await reveal(tester, start, workbenchScrollable());
      await tester.tap(start);
      await settle(tester);
      expect(tester.widget<TextField>(sourceField()).enabled, isFalse);
      expect(platform.dropTargets.last, isNull);
      beforeLock(r'D:\late-locked-drop.mp4');
      expect(
        tester.widget<TextField>(sourceField()).controller!.text,
        r'D:\picked-guard-base.mp4',
      );
      final created = workflowJob('locked-drop-job', 'needs_manual');
      api.jobs.add(created);
      creating.complete(created);
      await settle(tester);
      expect(tester.widget<TextField>(sourceField()).enabled, isTrue);
      expect(platform.dropTargets.last, isNotNull);
      final beforeClose = platform.dropHandler!;
      final shutdown = Completer<void>();
      platform.shutdownGate = shutdown.future;
      await tester.tap(find.byTooltip('Close'));
      await settle(tester);
      await tester.tap(
        find.widgetWithText(FilledButton, 'Stop work and close'),
      );
      await settle(tester);
      expect(platform.dropTargets.last, isNull);
      beforeClose(r'D:\late-closing-drop.mp4');
      expect(
        tester.widget<TextField>(sourceField()).controller!.text,
        r'D:\picked-guard-base.mp4',
      );
      shutdown.complete();
      await settle(tester);
      expect(platform.shutdownRequested, isTrue);
      expect(tester.takeException(), isNull);
    },
  );

  testWidgets(
    'shared CTB picker cancellation rearms unchanged source target and rejects old drop callback',
    (tester) async {
      final platform = TestPlatformAdapter(
        nativePicker: true,
        nativeDrop: true,
        nativeDesktop: true,
        managedShutdown: true,
      )..simulateNativePickerClearsDrop = true;
      final api = TestApiService(capabilities: supported);
      await pumpApp(
        tester,
        api: api,
        platform: platform,
        size: const Size(1000, 2400),
      );
      await tester.enterText(sourceField(), r'D:\source-before-ctb-picker.mp4');
      await settle(tester);
      final research = find.text(
        'Advanced research · explicit inputs and history',
      );
      await reveal(tester, research, workbenchScrollable());
      await tester.tap(research);
      await settle(tester);
      final ctb = find.byWidgetPredicate(
        (widget) =>
            widget is TextField &&
            widget.decoration?.labelText == 'CTB input video',
      );
      expect(sourceField().hitTestable(), findsOneWidget);
      expect(ctb.hitTestable(), findsOneWidget);
      final beforeTarget = platform.dropTargets.last!;
      final beforeCallback = platform.dropHandler!;
      final beforeOffset = tester
          .state<ScrollableState>(workbenchScrollable())
          .position
          .pixels;
      final beforeSize = tester.view.physicalSize;
      final picker = Completer<String?>();
      platform.pickerGate = picker.future;
      final ctbHost = find
          .ancestor(of: ctb, matching: find.byType(SourcePathField))
          .first;
      final ctbChoose = find.descendant(
        of: ctbHost,
        matching: find.byType(IconButton),
      );
      await tester.tap(ctbChoose);
      await settle(tester);
      expect(
        platform.dropHandler,
        isNull,
        reason: '模拟原生 owner disabled 已清除实际目标',
      );
      picker.complete(null);
      await settle(tester);
      beforeCallback(r'D:\late-before-ctb-picker.mp4');
      await settle(tester);
      expect(
        tester.widget<TextField>(sourceField()).controller!.text,
        r'D:\source-before-ctb-picker.mp4',
        reason: '其他字段的选择器也必须使旧 source 回调失效',
      );
      expect(
        tester.state<ScrollableState>(workbenchScrollable()).position.pixels,
        beforeOffset,
      );
      expect(tester.view.physicalSize, beforeSize);
      expect(
        platform.dropTargets.last,
        beforeTarget,
        reason: '无需 resize 或滚动，相同几何也必须重新注册',
      );
      expect(platform.dropHandler, isNotNull);
      expect(identical(platform.dropHandler, beforeCallback), isFalse);
      platform.simulateDrop(r'D:\source-after-ctb-cancel.mp4');
      await settle(tester);
      expect(
        tester.widget<TextField>(sourceField()).controller!.text,
        r'D:\source-after-ctb-cancel.mp4',
      );
      expect(tester.widget<TextField>(ctb).controller!.text, isEmpty);
      final beforeErrorCallback = platform.dropHandler!;
      final failingPicker = Completer<String?>();
      platform.pickerGate = failingPicker.future;
      await tester.tap(ctbChoose);
      await settle(tester);
      expect(platform.nativePickerActive.value, isTrue);
      expect(platform.dropHandler, isNull);
      failingPicker.completeError(
        StateError('simulated native picker failure'),
      );
      await settle(tester);
      expect(platform.nativePickerActive.value, isFalse);
      beforeErrorCallback(r'D:\late-before-ctb-error.mp4');
      await settle(tester);
      expect(
        tester.widget<TextField>(sourceField()).controller!.text,
        r'D:\source-after-ctb-cancel.mp4',
      );
      expect(platform.dropHandler, isNotNull, reason: '共享选择器抛错也必须结束全局忙状态并重配');
      expect(
        tester.state<ScrollableState>(workbenchScrollable()).position.pixels,
        beforeOffset,
      );
      expect(tester.view.physicalSize, beforeSize);
      expect(tester.takeException(), isNull);
    },
  );

  testWidgets(
    'simulated native picker survives selection-only and inactive/resumed changes',
    (tester) async {
      final platform = TestPlatformAdapter(
        nativePicker: true,
        nativeDrop: true,
        nativeDesktop: true,
        managedShutdown: true,
      );
      final api = TestApiService(capabilities: supported);
      await pumpApp(
        tester,
        api: api,
        platform: platform,
        size: const Size(1000, 1000),
      );
      await tester.enterText(sourceField(), r'D:\before-picker.mp4');
      await settle(tester);
      final input = tester.widget<TextField>(sourceField()).controller!;
      final picker = Completer<String?>();
      platform.pickerGate = picker.future;
      final choose = find.descendant(
        of: find.byKey(const ValueKey<String>('original-source-field')),
        matching: find.byType(IconButton),
      );
      await tester.tap(choose);
      await tester.pump();
      // 模拟原生对话框只改变焦点与编辑选择，不等同于用户修改来源文本。
      input.selection = const TextSelection.collapsed(offset: 1);
      tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.inactive);
      await settle(tester);
      expect(platform.dropTargets.last, isNull);
      tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
      await settle(tester);
      picker.complete(r'D:\picked-after-focus.mp4');
      await settle(tester);
      expect(
        tester.widget<TextField>(sourceField()).controller!.text,
        r'D:\picked-after-focus.mp4',
      );
      expect(platform.dropTargets.last, isNotNull);
      expect(tester.takeException(), isNull);
    },
  );

  testWidgets(
    'advanced values use bounds, Web is explicit and About separates product and Worker',
    (tester) async {
      final api = TestApiService(capabilities: supported);
      await pumpApp(tester, api: api, size: const Size(1000, 1000));
      expect(
        find.textContaining('No fakepath or media upload'),
        findsOneWidget,
      );
      await tester.enterText(sourceField(), r'C:\fakepath\source.mp4');
      final start = find.byKey(const ValueKey<String>('start-stabilize'));
      await reveal(tester, start, workbenchScrollable());
      expect(tester.widget<FilledButton>(start).onPressed, isNull);
      await reveal(tester, sourceField(), workbenchScrollable());
      await tester.enterText(sourceField(), r'D:\source.mp4');
      final advanced = find.text('Advanced parameters');
      await reveal(tester, advanced, workbenchScrollable());
      await tester.tap(advanced);
      await settle(tester);
      final tau = find.byKey(
        const ValueKey<String>('stabilize-parameter-alignment_tau_seconds'),
      );
      await reveal(tester, tau, workbenchScrollable());
      await tester.enterText(tau, '0');
      await settle(tester);
      await reveal(tester, start, workbenchScrollable());
      expect(tester.widget<FilledButton>(start).onPressed, isNull);
      await tester.tap(
        find.byKey(const ValueKey<String>('sidebar-destination-2')),
      );
      await settle(tester);
      final about = find.byKey(const ValueKey<String>('settings-about'));
      await reveal(tester, about, settingsScrollable());
      await tester.tap(about);
      await settle(tester);
      const expectedVersion = String.fromEnvironment(
        'CHASTEADY_PRODUCT_VERSION',
        defaultValue: 'development',
      );
      const expectedBuild = String.fromEnvironment('CHASTEADY_BUILD_NUMBER');
      final expectedLabel = expectedBuild.isEmpty
          ? expectedVersion
          : '$expectedVersion+$expectedBuild';
      expect(find.text(expectedLabel), findsOneWidget);
      expect(productVersionLabel, expectedLabel);
      expect(productVersion, expectedVersion);
      expect(productBuildNumber, expectedBuild);
      expect(
        find.text('Worker component: worker-test-component'),
        findsOneWidget,
      );
      expect(tester.takeException(), isNull);
    },
  );
}

Finder sourceField() => find.byWidgetPredicate(
  (widget) =>
      widget is TextField && widget.decoration?.labelText == 'Original video',
);
AppController controller(WidgetTester tester) =>
    tester.widget<AppShell>(find.byType(AppShell)).controller;
Finder workbenchScrollable() => find
    .descendant(
      of: find.byKey(const ValueKey<String>('workbench-list')),
      matching: find.byType(Scrollable),
    )
    .first;
Finder taskScrollable() => find
    .descendant(
      of: find.byKey(const PageStorageKey<String>('workbench-jobs-list')),
      matching: find.byType(Scrollable),
    )
    .first;
Finder jobsScrollable() => find
    .descendant(
      of: find.byKey(const PageStorageKey<String>('jobs-list')),
      matching: find.byType(Scrollable),
    )
    .first;
Finder settingsScrollable() => find
    .descendant(
      of: find.byKey(const ValueKey<String>('settings-list')),
      matching: find.byType(Scrollable),
    )
    .first;

Future<void> settle(WidgetTester tester) async {
  await tester.pump();
  await tester.pump(const Duration(milliseconds: 300));
  await tester.pump();
}

Future<void> reveal(
  WidgetTester tester,
  Finder target,
  Finder scrollable,
) async {
  await tester.pump();
  for (
    var step = 0;
    step < 70 && target.hitTestable().evaluate().isEmpty;
    step++
  ) {
    final above =
        target.evaluate().isNotEmpty && tester.getCenter(target.first).dy < 100;
    await tester.drag(scrollable, Offset(0, above ? 250 : -250));
    await tester.pump(const Duration(milliseconds: 60));
  }
  expect(target.hitTestable(), findsOneWidget);
}

Future<void> pumpApp(
  WidgetTester tester, {
  TestApiService? api,
  TestPlatformAdapter? platform,
  Size size = const Size(1440, 1000),
}) async {
  tester.view.devicePixelRatio = 1;
  tester.view.physicalSize = size;
  addTearDown(tester.view.resetDevicePixelRatio);
  addTearDown(tester.view.resetPhysicalSize);
  await tester.pumpWidget(
    ChaSteadyApp(
      api: api ?? TestApiService(capabilities: supported),
      platform: platform ?? TestPlatformAdapter(),
      sessionNonce: 'test-only-session',
    ),
  );
  await settle(tester);
}
