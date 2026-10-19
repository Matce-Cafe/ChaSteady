import 'package:flutter/material.dart';

import '../brand.dart';
import '../localization.dart';
import '../models.dart';

class JobStateLabel extends StatelessWidget {
  const JobStateLabel({required this.job, super.key});

  final JobSummary job;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    final label = jobStateLabel(context.l10n, job.state);
    final (icon, foreground, background) = switch (job.state) {
      'queued' => (
        Icons.schedule_outlined,
        colors.onSurfaceVariant,
        colors.surfaceContainerHighest,
      ),
      'running' => (
        Icons.sync,
        colors.onSecondaryContainer,
        colors.secondaryContainer,
      ),
      'needs_manual' || 'needs_review' => (
        Icons.fact_check_outlined,
        colors.onTertiaryContainer,
        colors.tertiaryContainer,
      ),
      'failed' => (
        Icons.error_outline,
        colors.onErrorContainer,
        colors.errorContainer,
      ),
      'cancelled' => (
        Icons.cancel_outlined,
        colors.onSurfaceVariant,
        colors.surfaceContainerHighest,
      ),
      'verified_media' => (
        Icons.verified_outlined,
        colors.onSecondaryContainer,
        colors.secondaryContainer,
      ),
      _ => (
        Icons.help_outline,
        colors.onSurfaceVariant,
        colors.surfaceContainerHighest,
      ),
    };

    return Semantics(
      label: label,
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
        decoration: ShapeDecoration(
          color: background,
          shape: continuousShape(radius: 14),
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: <Widget>[
            Icon(icon, size: 16, color: foreground),
            const SizedBox(width: 6),
            Flexible(
              child: Text(
                label,
                style: Theme.of(
                  context,
                ).textTheme.labelMedium?.copyWith(color: foreground),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class JobProgressFeedback extends StatelessWidget {
  const JobProgressFeedback({required this.job, super.key});

  final JobSummary job;

  @override
  Widget build(BuildContext context) {
    if (!job.isActive) return const SizedBox.shrink();
    final l10n = context.l10n;
    final stage = workerStageLabel(l10n, job.stage);
    final progress = job.progress;
    final semantics = progress == null
        ? l10n.stageProgressUnknown(stage)
        : l10n.stageProgressPercent(stage, (progress * 100).round());

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: <Widget>[
        if (progress == null) ...<Widget>[
          Text(
            l10n.progressNotReported,
            style: Theme.of(context).textTheme.labelMedium,
          ),
          const SizedBox(height: 4),
        ],
        Semantics(
          label: semantics,
          value: progress == null ? l10n.indeterminateProgress : null,
          child: LinearProgressIndicator(
            value: progress,
            semanticsLabel: semantics,
          ),
        ),
        if (progress == null) ...<Widget>[
          const SizedBox(height: 4),
          Text(
            l10n.noWorkerPercentage,
            style: Theme.of(context).textTheme.bodySmall,
          ),
        ],
      ],
    );
  }
}

class JobListTile extends StatelessWidget {
  const JobListTile({
    required this.job,
    required this.onTap,
    this.onCancel,
    this.selected = false,
    super.key,
  });

  final JobSummary job;
  final VoidCallback onTap;
  final VoidCallback? onCancel;
  final bool selected;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    final l10n = context.l10n;
    return Card(
      margin: EdgeInsets.zero,
      color: selected ? colors.secondaryContainer : colors.surfaceContainerLow,
      shape: continuousShape(radius: 18),
      child: InkWell(
        onTap: onTap,
        customBorder: continuousShape(radius: 18),
        child: Padding(
          padding: const EdgeInsets.all(14),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: <Widget>[
              Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: <Widget>[
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: <Widget>[
                        Text(
                          jobKindLabel(l10n, job.kind),
                          style: Theme.of(context).textTheme.titleSmall,
                        ),
                        const SizedBox(height: 6),
                        Text(
                          job.id,
                          style: Theme.of(context).textTheme.bodySmall
                              ?.copyWith(color: colors.onSurfaceVariant),
                        ),
                      ],
                    ),
                  ),
                  const SizedBox(width: 8),
                  Flexible(child: JobStateLabel(job: job)),
                ],
              ),
              if (job.message != null || job.messageKey != null) ...<Widget>[
                const SizedBox(height: 9),
                Text(localizedWorkerText(l10n, job.workerMessage)),
              ],
              if (job.stage != null) ...<Widget>[
                const SizedBox(height: 5),
                Text(
                  l10n.stageValue(workerStageLabel(l10n, job.stage)),
                  style: Theme.of(context).textTheme.bodySmall?.copyWith(
                    color: colors.onSurfaceVariant,
                  ),
                ),
              ],
              if (job.isActive) ...<Widget>[
                const SizedBox(height: 10),
                JobProgressFeedback(job: job),
              ],
              if (job.workerError != null) ...<Widget>[
                const SizedBox(height: 8),
                Text(
                  '${job.errorCode == null ? '' : '${l10n.jobErrorCode(job.errorCode!)}\n'}${localizedWorkerText(l10n, job.workerError!, kind: WorkerTextKind.error)}',
                  style: TextStyle(color: colors.error),
                ),
              ],
              if (job.warnings.isNotEmpty) ...<Widget>[
                const SizedBox(height: 8),
                Text(
                  l10n.warningCount(job.warnings.length),
                  style: Theme.of(context).textTheme.labelMedium,
                ),
              ],
              if (onCancel != null && job.canCancel) ...<Widget>[
                const SizedBox(height: 8),
                Align(
                  alignment: Alignment.centerRight,
                  child: TextButton.icon(
                    onPressed: onCancel,
                    icon: const Icon(Icons.stop_circle_outlined),
                    label: Text(l10n.cancelJob),
                  ),
                ),
              ],
            ],
          ),
        ),
      ),
    );
  }
}
