import 'package:flutter/material.dart';

import '../app.dart';
import '../controller.dart';
import '../localization.dart';
import '../platform/media_platform.dart';
import '../widgets/common_widgets.dart';
import '../widgets/job_detail.dart';
import '../widgets/job_widgets.dart';

class JobsScreen extends StatelessWidget {
  const JobsScreen({
    required this.controller,
    required this.platform,
    this.active = true,
    super.key,
  });

  final AppController controller;
  final MediaPlatformAdapter platform;
  final bool active;

  @override
  Widget build(BuildContext context) => Column(
    children: <Widget>[
      ScreenHeader(
        title: context.l10n.navJobs,
        subtitle: context.l10n.screenJobsSubtitle,
        trailing: IconButton(
          tooltip: context.l10n.refreshJobs,
          onPressed: controller.isApiReady ? controller.refreshJobs : null,
          icon: const Icon(Icons.refresh),
        ),
      ),
      Expanded(
        child: JobsContent(
          controller: controller,
          platform: platform,
          active: active,
        ),
      ),
    ],
  );
}

/// 工作台内嵌列与任务页共享内容和控制器，不创建轮询或复制选中状态。
class JobsContent extends StatelessWidget {
  const JobsContent({
    required this.controller,
    required this.platform,
    required this.active,
    this.scrollKey = const PageStorageKey<String>('jobs-list'),
    this.padding = const EdgeInsets.fromLTRB(20, 0, 20, 20),
    super.key,
  });

  final AppController controller;
  final MediaPlatformAdapter platform;
  final bool active;
  final Key scrollKey;
  final EdgeInsets padding;

  void _showError(BuildContext context, String message) {
    if (!context.mounted) return;
    ScaffoldMessenger.of(
      context,
    ).showSnackBar(SnackBar(content: Text(message)));
  }

  @override
  Widget build(BuildContext context) => AnimatedBuilder(
    animation: controller,
    builder: (context, _) {
      final l10n = context.l10n;
      final jobs = controller.jobs;
      return ListView(
        key: scrollKey,
        padding: padding,
        children: <Widget>[
          ConnectionStatusNotice(controller: controller),
          if (controller.connectionState != AppConnectionState.ready)
            const SizedBox(height: 14),
          if (controller.jobsError != null) ...<Widget>[
            NoticeBox(
              title: l10n.queueLoadFailed,
              message: localizedError(l10n, controller.jobsError!),
              isWarning: true,
            ),
            const SizedBox(height: 14),
          ],
          if (jobs == null && controller.jobsError == null)
            controller.isApiReady
                ? SectionCard(
                    title: l10n.waitingQueueData,
                    child: Row(
                      children: <Widget>[
                        const SizedBox.square(
                          dimension: 18,
                          child: CircularProgressIndicator(strokeWidth: 2),
                        ),
                        const SizedBox(width: 12),
                        Expanded(child: Text(l10n.serviceNoJobList)),
                      ],
                    ),
                  )
                : SectionCard(
                    title: l10n.queueUnavailable,
                    child: Text(l10n.queueUnknownNotEmpty),
                  )
          else if (jobs != null && jobs.isEmpty)
            SectionCard(
              title: l10n.noJobsYet,
              child: Text(l10n.emptyQueueDescription),
            )
          else if (jobs != null)
            for (final job in jobs) ...<Widget>[
              JobListTile(
                key: ValueKey<String>('job-tile-${job.id}'),
                job: job,
                selected: job.id == controller.selectedJobId,
                onTap: () => controller.selectJob(job.id),
                onCancel: job.canCancel && !controller.isCancellingJob(job.id)
                    ? () async {
                        try {
                          await controller.cancelJob(job.id);
                        } catch (error) {
                          _showError(context, localizedError(l10n, error));
                        }
                      }
                    : null,
              ),
              const SizedBox(height: 10),
            ],
          if (controller.selectedJob != null) ...<Widget>[
            const SizedBox(height: 8),
            JobDetailPanel(
              key: ValueKey<String>('job-detail-${controller.selectedJobId}'),
              job: controller.selectedJob!,
              controller: controller,
              platform: platform,
              previewEnabled: active,
              onError: (message) => _showError(context, message),
            ),
          ],
          if (controller.selectedJobError != null) ...<Widget>[
            const SizedBox(height: 10),
            NoticeBox(
              title: l10n.latestJobDetailsUnavailable,
              message: localizedError(l10n, controller.selectedJobError!),
              isWarning: true,
            ),
          ],
          if (controller.capabilitiesError != null) ...<Widget>[
            const SizedBox(height: 18),
            NoticeBox(
              title: l10n.capabilitiesUnavailable,
              message: localizedError(l10n, controller.capabilitiesError!),
              isWarning: true,
            ),
          ],
        ],
      );
    },
  );
}
