import 'dart:async';

import 'package:cha_stabilizer_ui/src/api/api_service.dart';
import 'package:cha_stabilizer_ui/src/controller.dart';
import 'package:cha_stabilizer_ui/src/models.dart';
import 'package:flutter_test/flutter_test.dart';

import 'test_fakes.dart';

JobSummary job(String id, {String state = 'queued', String? message}) =>
    JobSummary.fromJson({
      'id': id,
      'kind': 'stabilize',
      'state': state,
      'stage': state,
      'message': message,
      'artifacts': <dynamic>[],
      'warnings': <dynamic>[],
    });

void main() {
  test(
    'older list cannot erase a new create, detail or cancellation',
    () async {
      final original = job('old', state: 'running');
      final api = TestApiService(jobs: [original]);
      final controller = AppController(
        api: api,
        platform: TestPlatformAdapter(),
        sessionNonce: 'test-only-session',
      );
      addTearDown(controller.dispose);
      await controller.initialize();
      final list = Completer<List<JobSummary>>();
      api.listHandler = () => list.future;
      final refreshing = controller.refreshJobs();
      final created = await controller.createJob({
        'kind': 'stabilize',
        'request': {'original': r'D:\source.mp4'},
      });
      await controller.selectJob('old');
      await controller.cancelJob('old');
      list.complete([original]);
      await refreshing;
      expect(controller.jobs!.map((value) => value.id), contains(created.id));
      expect(
        controller.jobs!.firstWhere((value) => value.id == 'old').state,
        'cancelled',
      );
      expect(controller.selectedJobId, 'old');
      expect(api.listCalls, 2);
    },
  );

  test('detail completed after refresh began wins over that refresh', () async {
    final old = job('detail', message: 'old');
    final api = TestApiService(jobs: [old]);
    final controller = AppController(
      api: api,
      platform: TestPlatformAdapter(),
      sessionNonce: 'test-only-session',
    );
    addTearDown(controller.dispose);
    await controller.initialize();
    final list = Completer<List<JobSummary>>();
    final detail = Completer<JobSummary>();
    api.listHandler = () => list.future;
    api.detailHandler = (_) => detail.future;
    final refreshing = controller.refreshJobs();
    final selecting = controller.selectJob('detail');
    detail.complete(
      job('detail', state: 'needs_manual', message: 'new detail'),
    );
    await selecting;
    list.complete([old]);
    await refreshing;
    expect(controller.selectedJob!.message, 'new detail');
    expect(controller.selectedJob!.state, 'needs_manual');
  });

  test(
    'late select success and error cannot pollute a newer selection or create',
    () async {
      final api = TestApiService(jobs: [job('a'), job('b')]);
      final controller = AppController(
        api: api,
        platform: TestPlatformAdapter(),
        sessionNonce: 'test-only-session',
      );
      addTearDown(controller.dispose);
      await controller.initialize();
      final first = Completer<JobSummary>();
      api.detailHandler = (id) async =>
          id == 'a' ? await first.future : job(id, message: 'current');
      final selectingFirst = controller.selectJob('a');
      await controller.selectJob('b');
      first.completeError(StateError('old selection failure'));
      await selectingFirst;
      expect(controller.selectedJobId, 'b');
      expect(controller.selectedJobError, isNull);
      final late = Completer<JobSummary>();
      api.detailHandler = (_) => late.future;
      final selectingLate = controller.selectJob('a');
      final created = await controller.createJob({
        'kind': 'preview',
        'source': r'D:\source.mp4',
      });
      late.complete(job('a', state: 'failed'));
      await selectingLate;
      expect(controller.selectedJobId, created.id);
      expect(controller.selectedJobError, isNull);
    },
  );

  test(
    'list and detail failures are isolated from each other and local writes',
    () async {
      final api = TestApiService(jobs: [job('a'), job('b')]);
      final controller = AppController(
        api: api,
        platform: TestPlatformAdapter(),
        sessionNonce: 'test-only-session',
      );
      addTearDown(controller.dispose);
      await controller.initialize();
      final listError = StateError('list failure');
      final detailError = StateError('detail failure');
      api.listHandler = () => Future.error(listError);
      await controller.refreshJobs();
      api.detailHandler = (_) => Future.error(detailError);
      await controller.selectJob('a');
      expect(controller.jobsError, same(listError));
      expect(controller.selectedJobError, same(detailError));
      await controller.cancelJob('b');
      expect(controller.jobsError, same(listError));
      expect(controller.selectedJobError, same(detailError));
      api.listHandler = null;
      await controller.refreshJobs();
      expect(controller.jobsError, isNull);
      expect(controller.selectedJobError, same(detailError));
      api.listHandler = () => Future.error(listError);
      await controller.refreshJobs();
      await controller.createJob({
        'kind': 'preview',
        'source': r'D:\source.mp4',
      });
      expect(controller.jobsError, same(listError));
    },
  );

  test(
    'pending create and cancellation are deduplicated and retry after failure',
    () async {
      final api = TestApiService(jobs: [job('cancel')]);
      final controller = AppController(
        api: api,
        platform: TestPlatformAdapter(),
        sessionNonce: 'test-only-session',
      );
      addTearDown(controller.dispose);
      await controller.initialize();
      final create = Completer<JobSummary>();
      api.createHandler = (_, _) => create.future;
      final payload = <String, dynamic>{
        'kind': 'stabilize',
        'request': {'original': r'D:\source.mp4'},
      };
      final first = controller.createJob(payload);
      final duplicate = controller.createJob(payload);
      expect(identical(first, duplicate), isTrue);
      expect(controller.isCreatingJob, isTrue);
      await expectLater(
        controller.createJob({'kind': 'preview', 'source': r'D:\other.mp4'}),
        throwsA(isA<ApiException>()),
      );
      expect(api.createCalls, 1);
      create.completeError(StateError('create failed'));
      await expectLater(first, throwsStateError);
      expect(controller.isCreatingJob, isFalse);
      api.createHandler = null;
      await controller.createJob(payload);
      expect(api.createCalls, 2);
      final cancel = Completer<JobSummary>();
      api.cancelHandler = (_) => cancel.future;
      final cancelling = controller.cancelJob('cancel');
      final cancellingAgain = controller.cancelJob('cancel');
      expect(identical(cancelling, cancellingAgain), isTrue);
      expect(controller.isCancellingJob('cancel'), isTrue);
      expect(api.cancelCalls, 1);
      cancel.complete(job('cancel', state: 'cancelled'));
      await cancelling;
      expect(controller.isCancellingJob('cancel'), isFalse);
    },
  );

  testWidgets('one poller uses idle 15s, active 3s and refreshes on focus', (
    tester,
  ) async {
    final api = TestApiService();
    final controller = AppController(
      api: api,
      platform: TestPlatformAdapter(),
      sessionNonce: 'test-only-session',
    );
    addTearDown(controller.dispose);
    await controller.initialize();
    expect(api.listCalls, 1);
    await tester.pump(const Duration(seconds: 14));
    expect(api.listCalls, 1);
    await tester.pump(const Duration(seconds: 1));
    expect(api.listCalls, 2);
    await controller.createJob({
      'kind': 'stabilize',
      'request': {'original': r'D:\source.mp4'},
    });
    await tester.pump(const Duration(seconds: 2));
    expect(api.listCalls, 2);
    await tester.pump(const Duration(seconds: 1));
    expect(api.listCalls, 3);
    controller.setForeground(false);
    await tester.pump(const Duration(seconds: 45));
    expect(api.listCalls, 3);
    controller.setForeground(true);
    await tester.pump();
    expect(api.listCalls, 4);
    final pending = Completer<List<JobSummary>>();
    api.listHandler = () => pending.future;
    final refreshing = controller.refreshJobs();
    final duplicate = controller.refreshJobs();
    expect(identical(refreshing, duplicate), isTrue);
    expect(api.listCalls, 5);
    await tester.pump(const Duration(seconds: 30));
    expect(api.listCalls, 5);
    controller.setForeground(false);
    controller.setForeground(true);
    api.listHandler = null;
    pending.complete(List.of(api.jobs));
    await refreshing;
    await tester.pump();
    expect(api.listCalls, 6, reason: '恢复焦点时，旧请求结束后还需取得新列表');
    controller.setForeground(false);
    await tester.pump(const Duration(seconds: 30));
    expect(api.listCalls, 6);
  });
}
