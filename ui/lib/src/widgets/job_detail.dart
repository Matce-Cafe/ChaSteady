import 'dart:convert';

import 'package:flutter/material.dart';

import '../controller.dart';
import '../localization.dart';
import '../models.dart';
import '../path_rules.dart';
import '../platform/media_platform.dart';
import 'common_widgets.dart';
import 'job_widgets.dart';
import 'source_path_field.dart';

class JobDetailPanel extends StatelessWidget {
  const JobDetailPanel({
    required this.job,
    required this.controller,
    required this.platform,
    required this.onError,
    this.previewEnabled = true,
    super.key,
  });

  final JobSummary job;
  final AppController controller;
  final MediaPlatformAdapter platform;
  final ValueChanged<String> onError;
  final bool previewEnabled;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    final l10n = context.l10n;
    final artifacts = _artifactsPreviewFirst(job.artifacts);
    // 单原片工作流只从关联的独立预览任务取租约，不把父任务中间产物当预览。
    final isWorkflow =
        job.kind == 'stabilize' || job.kind == 'stabilize_continue';
    final previewArtifactId = isWorkflow
        ? null
        : artifacts.where(_canPreviewArtifact).firstOrNull?.id;
    return SectionCard(
      title: l10n.jobDetails,
      subtitle: job.id,
      trailing: JobStateLabel(job: job),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Text(
            jobKindLabel(l10n, job.kind),
            style: Theme.of(context).textTheme.titleSmall,
          ),
          if (job.stage != null) ...<Widget>[
            const SizedBox(height: 8),
            Text(l10n.stageValue(workerStageLabel(l10n, job.stage))),
          ],
          if (job.message != null || job.messageKey != null) ...<Widget>[
            const SizedBox(height: 6),
            Text(localizedWorkerText(l10n, job.workerMessage)),
          ],
          if (job.workflow != null) ...<Widget>[
            const SizedBox(height: 12),
            _WorkflowDetails(job: job, controller: controller),
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
            if ((job.kind == 'stabilize' || job.kind == 'stabilize_continue') &&
                controller.capabilities?.supportsStabilizeContinuation == true)
              _ManualContinuationButton(
                job: job,
                controller: controller,
                platform: platform,
                onError: onError,
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
            Text(
              l10n.ownedOutputs,
              style: Theme.of(context).textTheme.titleSmall,
            ),
            const SizedBox(height: 8),
            for (var index = 0; index < artifacts.length; index++) ...<Widget>[
              _ArtifactCard(
                key: ValueKey<String>('artifact-${artifacts[index].id}'),
                artifact: artifacts[index],
                previewEnabled:
                    previewEnabled && artifacts[index].id == previewArtifactId,
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
              leading: Icon(
                Icons.warning_amber_outlined,
                color: colors.tertiary,
              ),
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
    required this.previewEnabled,
    super.key,
  });

  final ArtifactRecord artifact;
  final bool previewEnabled;
  final AppController controller;
  final MediaPlatformAdapter platform;
  final ValueChanged<String> onError;

  @override
  Widget build(BuildContext context) {
    final l10n = context.l10n;
    final canPreview = _canPreviewArtifact(artifact);
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
      Text(
        l10n.artifactFormat(
          _artifactKindLabel(l10n, artifact.kind),
          artifact.mime,
        ),
      ),
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
      if (canPreview && previewEnabled) ...<Widget>[
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
        Text(
          l10n.artifactPreview,
          style: Theme.of(context).textTheme.bodySmall,
        ),
      ] else if (artifact.isBrowserPreview && !canPreview) ...<Widget>[
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

class _WorkflowDetails extends StatelessWidget {
  const _WorkflowDetails({required this.job, required this.controller});
  final JobSummary job;
  final AppController controller;

  @override
  Widget build(BuildContext context) {
    final l10n = context.l10n;
    final workflow = job.workflow!;
    final stages = workflow['stages'];
    final preview = workflow['preview'];
    final parent = workflow['parent_job_id'];
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: <Widget>[
        Text(l10n.workflowProfile(workflow['profile']?.toString() ?? '—')),
        Text(l10n.workflowAttempt(workflow['attempt']?.toString() ?? '—')),
        if (parent is String) Text(l10n.workflowParent(parent)),
        if (workflow['ctb_origin'] == 'manual_import')
          Text(l10n.manualContinuationProvenance),
        if (stages is List)
          for (final stage in stages.whereType<Map>())
            Padding(
              padding: const EdgeInsets.only(top: 6),
              child: Text(
                l10n.workflowStageStatus(
                  workerStageLabel(l10n, stage['id']?.toString()),
                  workflowStateLabel(l10n, stage['state']?.toString()),
                ),
              ),
            ),
        if (preview is Map) ...<Widget>[
          const SizedBox(height: 8),
          Text(
            l10n.workflowPreviewStatus(
              workflowStateLabel(l10n, preview['state']?.toString()),
            ),
          ),
          if (preview['job_id'] is String)
            TextButton.icon(
              onPressed: () =>
                  controller.selectJob(preview['job_id'] as String),
              icon: const Icon(Icons.movie_outlined),
              label: Text(l10n.openWorkflowPreviewJob),
            ),
        ],
      ],
    );
  }
}

class _ManualContinuationButton extends StatefulWidget {
  const _ManualContinuationButton({
    required this.job,
    required this.controller,
    required this.platform,
    required this.onError,
  });
  final JobSummary job;
  final AppController controller;
  final MediaPlatformAdapter platform;
  final ValueChanged<String> onError;

  @override
  State<_ManualContinuationButton> createState() =>
      _ManualContinuationButtonState();
}

class _ManualContinuationButtonState extends State<_ManualContinuationButton> {
  bool _busy = false;

  Future<void> _continue() async {
    if (_busy || widget.controller.isCreatingJob) return;
    setState(() => _busy = true);
    final source = TextEditingController();
    final origin = TextEditingController(text: '0');
    var declaredManual = false;
    try {
      final selected = await showDialog<(String, double)>(
        context: context,
        builder: (dialogContext) => StatefulBuilder(
          builder: (context, updateDialog) {
            final seconds = double.tryParse(origin.text.trim());
            final valid =
                isLocalAbsolutePath(source.text) &&
                seconds != null &&
                seconds.isFinite &&
                seconds >= 0 &&
                declaredManual;
            return AlertDialog(
              title: Text(context.l10n.manualContinueTitle),
              content: SizedBox(
                width: 500,
                child: SingleChildScrollView(
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    children: <Widget>[
                      Text(context.l10n.manualContinuationProvenance),
                      const SizedBox(height: 12),
                      SourcePathField(
                        label: context.l10n.manualCtbPath,
                        helper: context.l10n.ctbInputHelper,
                        kind: 'video',
                        pathController: source,
                        appController: widget.controller,
                        platform: widget.platform,
                        onChanged: (_) => updateDialog(() {}),
                        onError: widget.onError,
                      ),
                      const SizedBox(height: 12),
                      TextField(
                        key: const ValueKey<String>('manual-ctb-origin'),
                        controller: origin,
                        keyboardType: const TextInputType.numberWithOptions(
                          decimal: true,
                        ),
                        decoration: InputDecoration(
                          labelText: context.l10n.manualCtbOrigin,
                          border: const OutlineInputBorder(),
                        ),
                        onChanged: (_) => updateDialog(() {}),
                      ),
                      CheckboxListTile(
                        key: const ValueKey<String>('declare-manual-ctb'),
                        contentPadding: EdgeInsets.zero,
                        value: declaredManual,
                        onChanged: (value) =>
                            updateDialog(() => declaredManual = value ?? false),
                        title: Text(context.l10n.declareManualCtb),
                      ),
                    ],
                  ),
                ),
              ),
              actions: <Widget>[
                TextButton(
                  onPressed: () => Navigator.of(dialogContext).pop(),
                  child: Text(context.l10n.cancelAction),
                ),
                FilledButton(
                  key: const ValueKey<String>('submit-manual-continuation'),
                  onPressed: valid
                      ? () => Navigator.of(
                          dialogContext,
                        ).pop((source.text.trim(), seconds))
                      : null,
                  child: Text(context.l10n.createContinuationJob),
                ),
              ],
            );
          },
        ),
      );
      if (selected == null || !mounted) return;
      await widget.controller.createJob(<String, dynamic>{
        'kind': 'stabilize_continue',
        'request': <String, dynamic>{
          'parent_job_id': widget.job.id,
          'manual_ctb': <String, dynamic>{
            'source': selected.$1,
            'origin_seconds': selected.$2,
            'declared_at': DateTime.now().toUtc().toIso8601String(),
          },
        },
      });
    } catch (error) {
      if (mounted) widget.onError(localizedError(context.l10n, error));
    } finally {
      // 对话框退场后再释放文本控制器，避免退场动画仍访问已释放资源。
      await Future<void>.delayed(const Duration(milliseconds: 250));
      source.dispose();
      origin.dispose();
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.only(top: 10),
    child: OutlinedButton.icon(
      key: const ValueKey<String>('manual-continue'),
      onPressed: _busy || widget.controller.isCreatingJob ? null : _continue,
      icon: const Icon(Icons.input_outlined),
      label: Text(context.l10n.manualContinueTitle),
    ),
  );
}

bool _canPreviewArtifact(ArtifactRecord artifact) =>
    artifact.isBrowserPreview &&
    _hasCodec(artifact.mediaMetadata['video_codec'], const <String>[
      'h264',
      'h.264',
      'avc1',
    ]) &&
    _hasCodec(artifact.mediaMetadata['audio_codec'], const <String>['aac']);

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
