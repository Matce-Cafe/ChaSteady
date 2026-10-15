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
    super.key,
  });

  final AppController controller;
  final MediaPlatformAdapter platform;

  void _showError(BuildContext context, String message) {
    ScaffoldMessenger.of(
      context,
    ).showSnackBar(SnackBar(content: Text(message)));
  }

  @override
  Widget build(BuildContext context) {
    final l10n = context.l10n;
    return Column(
      children: <Widget>[
        ScreenHeader(
          title: l10n.navJobs,
          subtitle: l10n.screenJobsSubtitle,
          trailing: IconButton(
            tooltip: l10n.refreshJobs,
            onPressed: controller.isApiReady ? controller.refreshJobs : null,
            icon: const Icon(Icons.refresh),
          ),
        ),
        Expanded(
          child: ListView(
            padding: const EdgeInsets.fromLTRB(20, 0, 20, 20),
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
              if (controller.jobs == null && controller.jobsError == null)
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
              else if (controller.jobs != null && controller.jobs!.isEmpty)
                SectionCard(
                  title: l10n.noJobsYet,
                  child: Text(l10n.emptyQueueDescription),
                )
              else if (controller.jobs != null && controller.jobs!.isNotEmpty)
                for (var index = 0; index < controller.jobs!.length; index++) ...<Widget>[
                  JobListTile(
                    job: controller.jobs![index],
                    selected:
                        controller.jobs![index].id == controller.selectedJobId,
                    onTap: () => controller.selectJob(controller.jobs![index].id),
                    onCancel: controller.jobs![index].canCancel
                        ? () async {
                            try {
                              await controller.cancelJob(
                                controller.jobs![index].id,
                              );
                            } catch (error) {
                              _showError(context, localizedError(l10n, error));
                            }
                          }
                        : null,
                  ),
                  if (index != controller.jobs!.length - 1)
                    const SizedBox(height: 10),
                ],
              if (controller.selectedJob != null) ...<Widget>[
                const SizedBox(height: 18),
                JobDetailPanel(
                  job: controller.selectedJob!,
                  controller: controller,
                  platform: platform,
                  onError: (message) => _showError(context, message),
                ),
                if (controller.selectedJobError != null) ...<Widget>[
                  const SizedBox(height: 10),
                  NoticeBox(
                    title: l10n.latestJobDetailsUnavailable,
                    message: localizedError(l10n, controller.selectedJobError!),
                    isWarning: true,
                  ),
                ],
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
          ),
        ),
      ],
    );
  }
}
