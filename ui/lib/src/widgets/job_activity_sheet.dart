import 'package:flutter/material.dart';

import '../controller.dart';
import '../localization.dart';
import '../platform/media_platform.dart';
import 'common_widgets.dart';
import 'job_detail.dart';
import 'job_widgets.dart';

const _jobActivitySnapSizes = <double>[0.30, 0.60, 0.94];

class JobActivitySheet extends StatefulWidget {
  const JobActivitySheet({
    required this.controller,
    required this.platform,
    required this.onError,
    this.desktopHandle = false,
    super.key,
  });

  final AppController controller;
  final MediaPlatformAdapter platform;
  final ValueChanged<String> onError;
  final bool desktopHandle;

  @override
  State<JobActivitySheet> createState() => _JobActivitySheetState();
}

class _JobActivitySheetState extends State<JobActivitySheet> {
  final DraggableScrollableController _sheetController =
      DraggableScrollableController();
  double _dragStartSize = 0.3;
  double _dragTotalDy = 0;

  Future<void> _snapTo(double size) async {
    if (!_sheetController.isAttached) return;
    if (MediaQuery.of(context).disableAnimations) {
      _sheetController.jumpTo(size);
    } else {
      await _sheetController.animateTo(
        size,
        duration: const Duration(milliseconds: 220),
        curve: Curves.easeOutCubic,
      );
    }
  }

  void _handleDragStart(DragStartDetails details) {
    if (_sheetController.isAttached) {
      _dragStartSize = _sheetController.size;
      _dragTotalDy = 0;
    }
  }

  void _handleDragUpdate(DragUpdateDetails details) {
    if (!_sheetController.isAttached) return;
    _dragTotalDy += details.delta.dy;
    final height = MediaQuery.sizeOf(context).height;
    final next = (_dragStartSize - _dragTotalDy / height)
        .clamp(_jobActivitySnapSizes.first, _jobActivitySnapSizes.last)
        .toDouble();
    _sheetController.jumpTo(next);
  }

  Future<void> _snapToNearest() async {
    if (!_sheetController.isAttached) return;
    final current = _sheetController.size;
    final nearest = _jobActivitySnapSizes.reduce(
      (a, b) => (a - current).abs() <= (b - current).abs() ? a : b,
    );
    await _snapTo(nearest);
  }

  @override
  Widget build(BuildContext context) => DraggableScrollableSheet(
    controller: _sheetController,
    initialChildSize: 0.30,
    minChildSize: 0.30,
    maxChildSize: 0.94,
    snap: true,
    snapSizes: _jobActivitySnapSizes,
    builder: (context, scrollController) => Material(
      color: Theme.of(context).colorScheme.surfaceContainerLow,
      elevation: 8,
      clipBehavior: Clip.antiAlias,
      shape: ContinuousRectangleBorder(
        borderRadius: BorderRadius.circular(28),
        side: BorderSide(color: Theme.of(context).colorScheme.outlineVariant),
      ),
      child: Column(
        children: <Widget>[
          _SheetHeader(
            controller: widget.controller,
            desktopHandle: widget.desktopHandle,
            onDragStart: _handleDragStart,
            onDragUpdate: _handleDragUpdate,
            onDragEnd: (_) => _snapToNearest(),
            onSnap: _snapTo,
          ),
          Expanded(
            child: _SheetContents(
              controller: widget.controller,
              platform: widget.platform,
              onError: widget.onError,
              scrollController: scrollController,
            ),
          ),
        ],
      ),
    ),
  );
}

class _SheetHeader extends StatelessWidget {
  const _SheetHeader({
    required this.controller,
    required this.desktopHandle,
    required this.onDragStart,
    required this.onDragUpdate,
    required this.onDragEnd,
    required this.onSnap,
  });

  final AppController controller;
  final bool desktopHandle;
  final GestureDragStartCallback onDragStart;
  final GestureDragUpdateCallback onDragUpdate;
  final GestureDragEndCallback onDragEnd;
  final ValueChanged<double> onSnap;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    final l10n = context.l10n;
    return Column(
      mainAxisSize: MainAxisSize.min,
      children: <Widget>[
        MouseRegion(
          cursor: desktopHandle
              ? SystemMouseCursors.resizeUpDown
              : SystemMouseCursors.basic,
          child: GestureDetector(
            behavior: HitTestBehavior.opaque,
            onVerticalDragStart: onDragStart,
            onVerticalDragUpdate: onDragUpdate,
            onVerticalDragEnd: onDragEnd,
            child: Semantics(
              label: desktopHandle
                  ? l10n.resizeJobActivityPanel
                  : l10n.resizeJobSheet,
              child: Padding(
                padding: const EdgeInsets.only(top: 10, bottom: 8),
                child: Center(
                  child: Container(
                    width: 42,
                    height: 5,
                    decoration: ShapeDecoration(
                      color: colors.outlineVariant,
                      shape: const StadiumBorder(),
                    ),
                  ),
                ),
              ),
            ),
          ),
        ),
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 0, 12, 8),
          child: Row(
            children: <Widget>[
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: <Widget>[
                    Text(
                      l10n.jobActivity,
                      style: Theme.of(context).textTheme.titleMedium,
                    ),
                    Text(
                      controller.jobs == null
                          ? l10n.waitingLocalQueue
                          : l10n.realJobsCount(controller.jobs!.length),
                      style: Theme.of(context).textTheme.bodySmall?.copyWith(
                        color: colors.onSurfaceVariant,
                      ),
                    ),
                  ],
                ),
              ),
              for (final size in _jobActivitySnapSizes)
                Padding(
                  padding: const EdgeInsets.only(left: 2),
                  child: TextButton(
                    onPressed: () => onSnap(size),
                    style: TextButton.styleFrom(
                      minimumSize: const Size(44, 40),
                      padding: const EdgeInsets.symmetric(horizontal: 7),
                    ),
                    child: Text('${(size * 100).round()}%'),
                  ),
                ),
              IconButton(
                tooltip: l10n.refreshJobs,
                onPressed: controller.isApiReady
                    ? () => controller.refreshJobs()
                    : null,
                icon: const Icon(Icons.refresh),
              ),
            ],
          ),
        ),
        const Divider(height: 1),
      ],
    );
  }
}

class _SheetContents extends StatelessWidget {
  const _SheetContents({
    required this.controller,
    required this.platform,
    required this.onError,
    required this.scrollController,
  });

  final AppController controller;
  final MediaPlatformAdapter platform;
  final ValueChanged<String> onError;
  final ScrollController scrollController;

  @override
  Widget build(BuildContext context) {
    final l10n = context.l10n;
    final currentJobs = controller.jobs;
    final selected = controller.selectedJob;
    return ListView(
      controller: scrollController,
      padding: const EdgeInsets.all(14),
      children: <Widget>[
        if (controller.jobsError != null) ...<Widget>[
          NoticeBox(
            title: l10n.queueCouldNotRefresh,
            message: localizedError(l10n, controller.jobsError!),
            isWarning: true,
          ),
          const SizedBox(height: 12),
        ],
        if (currentJobs == null && controller.jobsError == null)
          controller.isApiReady
              ? Padding(
                  padding: const EdgeInsets.all(18),
                  child: Center(
                    child: CircularProgressIndicator(
                      semanticsLabel: l10n.loadingLocalJobs,
                    ),
                  ),
                )
              : NoticeBox(
                  title: l10n.queueUnavailable,
                  message: l10n.queueUnknownNotEmpty,
                  isWarning: true,
                )
        else if (currentJobs != null && currentJobs.isEmpty)
          NoticeBox(
            title: l10n.queueEmpty,
            message: l10n.noJobsReturned,
            icon: Icons.inbox_outlined,
          ),
        if (selected != null) ...<Widget>[
          JobDetailPanel(
            job: selected,
            controller: controller,
            platform: platform,
            onError: onError,
          ),
          if (controller.selectedJobError != null) ...<Widget>[
            const SizedBox(height: 8),
            NoticeBox(
              title: l10n.latestJobDetailsUnavailable,
              message: localizedError(l10n, controller.selectedJobError!),
              isWarning: true,
            ),
          ],
          const SizedBox(height: 12),
        ],
        if (currentJobs != null)
          for (var index = 0; index < currentJobs.length; index++) ...<Widget>[
            JobListTile(
              job: currentJobs[index],
              selected: currentJobs[index].id == controller.selectedJobId,
              onTap: () => controller.selectJob(currentJobs[index].id),
              onCancel: currentJobs[index].canCancel
                  ? () async {
                      try {
                        await controller.cancelJob(currentJobs[index].id);
                      } catch (error) {
                        onError(localizedError(l10n, error));
                      }
                    }
                  : null,
            ),
            if (index != currentJobs.length - 1) const SizedBox(height: 10),
          ],
      ],
    );
  }
}
