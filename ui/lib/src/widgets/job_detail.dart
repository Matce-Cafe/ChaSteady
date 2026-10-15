import 'dart:convert';

import 'package:flutter/material.dart';

import '../controller.dart';
import '../localization.dart';
import '../models.dart';
import '../platform/media_platform.dart';
import 'common_widgets.dart';
import 'job_widgets.dart';

class JobDetailPanel extends StatelessWidget {
  const JobDetailPanel({
    required this.job,
    required this.controller,
    required this.platform,
    required this.onError,
    super.key,
  });

  final JobSummary job;
  final AppController controller;
  final MediaPlatformAdapter platform;
  final ValueChanged<String> onError;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    final l10n = context.l10n;
    final artifacts = _artifactsPreviewFirst(job.artifacts);
    return SectionCard(
      title: l10n.jobDetails,
      subtitle: job.id,
      trailing: JobStateLabel(job: job),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Text(jobKindLabel(l10n, job.kind), style: Theme.of(context).textTheme.titleSmall),
          if (job.stage != null) ...<Widget>[
            const SizedBox(height: 8),
            Text(l10n.stageValue(workerStageLabel(l10n, job.stage))),
          ],
          if (job.message != null || job.messageKey != null) ...<Widget>[
            const SizedBox(height: 6),
            Text(localizedWorkerText(l10n, job.workerMessage)),
          ],
          if (job.isActive) ...<Widget>[
            const SizedBox(height: 12),
            JobProgressFeedback(job: job),
          ],
          if (job.workerError != null) ...<Widget>[
            const SizedBox(height: 12),
            NoticeBox(
              title: job.errorCode == null
                  ? l10n.jobError
                  : l10n.jobErrorCode(job.errorCode!),
              message: localizedWorkerText(
                l10n,
                job.workerError!,
                kind: WorkerTextKind.error,
              ),
              isWarning: true,
              icon: Icons.error_outline,
            ),
          ],
          if (job.state == 'needs_manual') ...<Widget>[
            const SizedBox(height: 12),
            NoticeBox(
              title: l10n.manualActionRequired,
              message: l10n.manualActionMessage,
              isWarning: true,
              icon: Icons.pan_tool_alt_outlined,
            ),
          ],
          if (job.state == 'needs_review') ...<Widget>[
            const SizedBox(height: 12),
            NoticeBox(
              title: l10n.reviewBeforeContinue,
              message: l10n.reviewPerceptualFovMessage,
              isWarning: true,
              icon: Icons.fact_check_outlined,
            ),
          ],
          if (job.state == 'verified_media') ...<Widget>[
            const SizedBox(height: 12),
            NoticeBox(
              title: l10n.evidenceScopeLimited,
              message: l10n.verifiedMediaScopeMessage,
            ),
          ],
          if (job.kind == 'fusion') ...<Widget>[
            const SizedBox(height: 12),
            NoticeBox(
              title: l10n.interpretationLimits,
              message: l10n.fusionScopeMessage,
              icon: Icons.crop_free,
            ),
          ] else if (job.kind == 'gyroflow_export') ...<Widget>[
            const SizedBox(height: 12),
            NoticeBox(
              title: l10n.exportVerificationRequired,
              message: l10n.exportVerificationDetails,
              isWarning: true,
              icon: Icons.fact_check_outlined,
            ),
          ],
          if (job.artifacts.isNotEmpty) ...<Widget>[
            const SizedBox(height: 16),
            Text(l10n.ownedOutputs, style: Theme.of(context).textTheme.titleSmall),
            const SizedBox(height: 8),
            for (var index = 0; index < artifacts.length; index++) ...<Widget>[
              _ArtifactCard(
                artifact: artifacts[index],
                controller: controller,
                platform: platform,
                onError: onError,
              ),
              if (index != artifacts.length - 1) const SizedBox(height: 10),
            ],
          ],
          if (job.warnings.isNotEmpty) ...<Widget>[
            const SizedBox(height: 14),
            ExpansionTile(
              key: ValueKey<String>('worker-warnings-${job.id}'),
              tilePadding: EdgeInsets.zero,
              leading: Icon(Icons.warning_amber_outlined, color: colors.tertiary),
              title: Text(l10n.workerWarningsCount(job.warnings.length)),
              children: <Widget>[
                for (final warning in job.workerWarnings)
                  Padding(
                    padding: const EdgeInsets.fromLTRB(16, 0, 8, 8),
                    child: Row(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: <Widget>[
                        Icon(
                          Icons.warning_amber_outlined,
                          size: 18,
                          color: colors.tertiary,
                        ),
                        const SizedBox(width: 8),
                        Expanded(
                          child: Text(
                            localizedWorkerText(
                              l10n,
                              warning,
                              kind: WorkerTextKind.warning,
                            ),
                          ),
                        ),
                      ],
                    ),
                  ),
              ],
            ),
          ],
          if (job.result != null && job.result!.isNotEmpty) ...<Widget>[
            const SizedBox(height: 8),
            ExpansionTile(
              key: ValueKey<String>('worker-result-${job.id}'),
              tilePadding: EdgeInsets.zero,
              title: Text(l10n.workerResultDetails),
              children: <Widget>[
                ConstrainedBox(
                  constraints: const BoxConstraints(maxHeight: 300),
                  child: SingleChildScrollView(
                    padding: const EdgeInsets.only(bottom: 12),
                    child: SelectableText(
                      const JsonEncoder.withIndent('  ').convert(job.result),
                    ),
                  ),
                ),
              ],
            ),
          ],
        ],
      ),
    );
  }
}

List<ArtifactRecord> _artifactsPreviewFirst(List<ArtifactRecord> artifacts) =>
    <ArtifactRecord>[
      ...artifacts.where((artifact) => artifact.isBrowserPreview),
      ...artifacts.where((artifact) => !artifact.isBrowserPreview),
    ];

class _ArtifactCard extends StatelessWidget {
  const _ArtifactCard({
    required this.artifact,
    required this.controller,
    required this.platform,
    required this.onError,
  });

  final ArtifactRecord artifact;
  final AppController controller;
  final MediaPlatformAdapter platform;
  final ValueChanged<String> onError;

  @override
  Widget build(BuildContext context) {
    final l10n = context.l10n;
    final canPreview =
        artifact.isBrowserPreview &&
        _hasCodec(artifact.mediaMetadata['video_codec'], const <String>[
          'h264',
          'h.264',
          'avc1',
        ]) &&
        _hasCodec(artifact.mediaMetadata['audio_codec'], const <String>['aac']);
    final canOpen = artifact.mime.toLowerCase().startsWith('video/');
    final reportedFov = _formatReportedFov(
      artifact.mediaMetadata['reference_fov'],
    );
    final children = <Widget>[
      Text(
        artifact.label.isEmpty
            ? l10n.unnamedArtifact
            : l10n.originalArtifactLabel(artifact.label),
        style: Theme.of(context).textTheme.titleSmall,
      ),
      const SizedBox(height: 4),
      Text(l10n.artifactFormat(_artifactKindLabel(l10n, artifact.kind), artifact.mime)),
      if (reportedFov != null) ...<Widget>[
        const SizedBox(height: 6),
        Text(l10n.reportedReferenceFov(reportedFov)),
        const SizedBox(height: 6),
        NoticeBox(
          title: l10n.fovNotCropGuarantee,
          message: l10n.fovNoCropDetails,
          isWarning: true,
          icon: Icons.crop_free,
        ),
      ],
      if (artifact.validationScope != null) ...<Widget>[
        const SizedBox(height: 8),
        NoticeBox(
          title: l10n.artifactValidationScope,
          message: l10n.reportedScope(artifact.validationScope!),
          isWarning: true,
          icon: Icons.fact_check_outlined,
        ),
      ],
      if (canPreview) ...<Widget>[
        const SizedBox(height: 12),
        ClipRRect(
          borderRadius: BorderRadius.circular(14),
          child: AspectRatio(
            aspectRatio: 16 / 9,
            child: Semantics(
              label: l10n.localPreviewSemantics,
              child: platform.buildVideoPreview(
                controller.artifactContentUri(artifact),
              ),
            ),
          ),
        ),
        const SizedBox(height: 6),
        Text(l10n.artifactPreview, style: Theme.of(context).textTheme.bodySmall),
      ] else if (artifact.isBrowserPreview) ...<Widget>[
        const SizedBox(height: 8),
        Text(l10n.previewCodecUnknown),
      ],
      if (artifact.warnings.isNotEmpty) ...<Widget>[
        const SizedBox(height: 8),
        Material(
          type: MaterialType.transparency,
          child: ExpansionTile(
            key: ValueKey<String>('artifact-warnings-${artifact.id}'),
            tilePadding: EdgeInsets.zero,
            leading: Icon(
              Icons.warning_amber_outlined,
              color: Theme.of(context).colorScheme.tertiary,
            ),
            title: Text(l10n.artifactWarningsCount(artifact.warnings.length)),
            children: <Widget>[
              for (final warning in artifact.workerWarnings)
                Padding(
                  padding: const EdgeInsets.fromLTRB(16, 0, 8, 8),
                  child: Align(
                    alignment: Alignment.centerLeft,
                    child: Text(
                      localizedWorkerText(
                        l10n,
                        warning,
                        kind: WorkerTextKind.artifactWarning,
                      ),
                    ),
                  ),
                ),
            ],
          ),
        ),
      ],
      if (canOpen) ...<Widget>[
        const SizedBox(height: 8),
        Align(
          alignment: Alignment.centerRight,
          child: OutlinedButton.icon(
            onPressed: () async {
              try {
                await controller.openArtifact(artifact);
              } catch (error) {
                onError(localizedError(l10n, error));
              }
            },
            icon: const Icon(Icons.open_in_new),
            label: Text(l10n.openLocalOutput),
          ),
        ),
      ],
    ];

    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(14),
      decoration: ShapeDecoration(
        color: Theme.of(context).colorScheme.surfaceContainerHigh,
        shape: ContinuousRectangleBorder(
          borderRadius: BorderRadius.circular(18),
          side: BorderSide(color: Theme.of(context).colorScheme.outlineVariant),
        ),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: children,
      ),
    );
  }
}

String _artifactKindLabel(AppLocalizations l10n, String kind) => switch (kind) {
  'preview' => l10n.jobKindPreview,
  'fusion' => l10n.jobKindFusion,
  'gyroflow_export' => l10n.jobKindGyroflowExport,
  'catalyst_assisted' => l10n.jobKindCatalyst,
  'validate' => l10n.jobKindValidate,
  _ => l10n.artifactKindUnknown(kind),
};

bool _hasCodec(dynamic value, List<String> supported) {
  if (value is! String) return false;
  final codec = value.toLowerCase();
  return supported.any(codec.contains);
}

String? _formatReportedFov(dynamic value) {
  final parsed = value is num
      ? value.toDouble()
      : double.tryParse(value?.toString() ?? '');
  if (parsed == null || !parsed.isFinite || parsed < 1 || parsed > 4) {
    return null;
  }
  return parsed.toString();
}
