import 'package:flutter/material.dart';

import '../brand.dart';
import '../controller.dart';
import '../localization.dart';
import '../models.dart';
import '../path_rules.dart';

class SectionCard extends StatelessWidget {
  const SectionCard({
    required this.title,
    required this.child,
    this.subtitle,
    this.trailing,
    super.key,
  });

  final String title;
  final String? subtitle;
  final Widget child;
  final Widget? trailing;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    return Card(
      margin: EdgeInsets.zero,
      color: colors.surfaceContainerLow,
      shape: continuousShape(radius: 22),
      child: Padding(
        padding: const EdgeInsets.all(18),
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
                      Text(title, style: Theme.of(context).textTheme.titleMedium),
                      if (subtitle != null) ...<Widget>[
                        const SizedBox(height: 4),
                        Text(
                          subtitle!,
                          style: Theme.of(context).textTheme.bodySmall
                              ?.copyWith(color: colors.onSurfaceVariant),
                        ),
                      ],
                    ],
                  ),
                ),
                if (trailing != null) ...<Widget>[
                  const SizedBox(width: 10),
                  trailing!,
                ],
              ],
            ),
            const SizedBox(height: 16),
            child,
          ],
        ),
      ),
    );
  }
}

class NoticeBox extends StatelessWidget {
  const NoticeBox({
    required this.title,
    required this.message,
    this.icon = Icons.info_outline,
    this.isWarning = false,
    super.key,
  });

  final String title;
  final String message;
  final IconData icon;
  final bool isWarning;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    final foreground = isWarning
        ? colors.onTertiaryContainer
        : colors.onSecondaryContainer;
    final background = isWarning
        ? colors.tertiaryContainer
        : colors.secondaryContainer;
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(14),
      decoration: ShapeDecoration(
        color: background,
        shape: continuousShape(radius: 16),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Icon(icon, color: foreground, size: 20),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: <Widget>[
                Text(
                  title,
                  style: TextStyle(
                    color: foreground,
                    fontWeight: FontWeight.w600,
                  ),
                ),
                const SizedBox(height: 3),
                Text(message, style: TextStyle(color: foreground)),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class CapabilityStatusPill extends StatelessWidget {
  const CapabilityStatusPill({required this.availability, super.key});

  final CapabilityAvailability availability;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    final l10n = context.l10n;
    final (label, icon, foreground, background) = switch (availability) {
      CapabilityAvailability.detected => (
        l10n.detected,
        Icons.check_circle_outline,
        colors.onSecondaryContainer,
        colors.secondaryContainer,
      ),
      CapabilityAvailability.missing => (
        l10n.notDetected,
        Icons.remove_circle_outline,
        colors.onErrorContainer,
        colors.errorContainer,
      ),
      CapabilityAvailability.unknown => (
        l10n.statusUnknown,
        Icons.help_outline,
        colors.onSurfaceVariant,
        colors.surfaceContainerHighest,
      ),
    };
    return Semantics(
      label: l10n.toolCapabilitySemantics(label),
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
            Text(
              label,
              style: Theme.of(
                context,
              ).textTheme.labelMedium?.copyWith(color: foreground),
            ),
          ],
        ),
      ),
    );
  }
}

class CapabilitiesPanel extends StatelessWidget {
  const CapabilitiesPanel({required this.controller, super.key});

  final AppController controller;

  @override
  Widget build(BuildContext context) {
    final data = controller.capabilities;
    final l10n = context.l10n;
    if (data == null) {
      return SectionCard(
        title: l10n.toolAvailability,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: <Widget>[
            if (controller.capabilitiesError != null)
              NoticeBox(
                title: l10n.capabilitiesUnavailable,
                message: localizedError(l10n, controller.capabilitiesError!),
                isWarning: true,
              )
            else if (controller.connectionState != AppConnectionState.ready)
              NoticeBox(
                title: l10n.toolStatusUnknown,
                message: l10n.capabilitiesNotProvided,
                isWarning: true,
              )
            else
              Row(
                children: <Widget>[
                  const SizedBox.square(
                    dimension: 18,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  ),
                  const SizedBox(width: 12),
                  Expanded(child: Text(l10n.waitingToolStatus)),
                ],
              ),
          ],
        ),
      );
    }
    final savedGyroflowPath = controller.preferences.toolPaths['gyroflow'];
    final gyroflowPathMatchesPreferences =
        controller.preferences.hasCompleteToolPaths &&
        isLocalAbsolutePath(savedGyroflowPath ?? '') &&
        localAbsolutePathsEqual(data.gyroflow.path, savedGyroflowPath);
    final profileGuardMatchesSavedPath =
        data.gyroflow.priorVerificationMatchesConfiguredPath &&
        gyroflowPathMatchesPreferences;

    return SectionCard(
      title: l10n.toolAvailabilityProvenance,
      subtitle: data.version == null ? null : l10n.workerVersion(data.version!),
      child: Column(
        children: <Widget>[
          _CapabilityLine(name: l10n.ffmpeg, capability: data.ffmpeg),
          const Divider(height: 20),
          _CapabilityLine(name: l10n.ffprobe, capability: data.ffprobe),
          const Divider(height: 20),
          _CapabilityLine(name: l10n.gyroflow, capability: data.gyroflow),
          if (data.gyroflow.detected == true) ...<Widget>[
            _FactLine(
              label: l10n.gyroflowBuild,
              value: data.gyroflow.buildId == null
                  ? l10n.unknown
                  : l10n.gyroflowBuildValue(data.gyroflow.buildId!),
            ),
            _FactLine(
              label: l10n.cliStatus,
              value: toolStatusLabel(l10n, data.gyroflow.cliStatus),
            ),
            _FactLine(
              label: l10n.priorCliInvocation,
              value: _reported(l10n, data.gyroflow.priorVerified),
            ),
            _FactLine(
              label: l10n.savedPathProfileGuard,
              value: _pathGuardStatus(
                l10n,
                data.gyroflow,
                savedGyroflowPath,
              ),
            ),
            _FactLine(
              label: l10n.latestExportValidation,
              value: toolStatusLabel(l10n, data.gyroflow.validationStatus),
            ),
            _FactLine(
              label: l10n.latestMediaExportVerified,
              value: _truth(l10n, data.gyroflow.exportVerified),
            ),
            _FactLine(
              label: l10n.latestTrimMappingVerified,
              value: _truth(l10n, data.gyroflow.trimMappingVerified),
            ),
            _FactLine(
              label: l10n.profileSafety,
              value: _requirement(l10n, data.gyroflow.profileSafetyRequired),
            ),
            if (data.gyroflow.profileSafetyRequired == true &&
                !profileGuardMatchesSavedPath)
              Padding(
                padding: const EdgeInsets.only(top: 8),
                child: NoticeBox(
                  title: l10n.exportHeldProfileSafety,
                  message: l10n.profileSafetyMismatchMessage,
                  isWarning: true,
                  icon: Icons.shield_outlined,
                ),
              ),
            if (data.gyroflow.validationStatus == 'needs_review')
              Padding(
                padding: const EdgeInsets.only(top: 8),
                child: NoticeBox(
                  title: l10n.boundedExportNeedsReview,
                  message: l10n.boundedExportNeedsReviewMessage,
                  isWarning: true,
                  icon: Icons.fact_check_outlined,
                ),
              ),
            Padding(
              padding: const EdgeInsets.only(top: 8),
              child: NoticeBox(
                title: l10n.exportNeedsVerification,
                message: l10n.exportVerificationMessage,
                isWarning: true,
                icon: Icons.fact_check_outlined,
              ),
            ),
          ],
          const Divider(height: 20),
          _CapabilityLine(name: l10n.catalyst, capability: data.catalyst),
          if (data.catalyst.detected == true) ...<Widget>[
            _FactLine(
              label: l10n.mode,
              value: capabilityModeLabel(l10n, data.catalyst.mode),
            ),
            _FactLine(
              label: l10n.uiAutomationVerification,
              value: _truth(l10n, data.catalyst.uiaVerified),
            ),
          ],
          Padding(
            padding: const EdgeInsets.only(top: 8),
            child: NoticeBox(
              title: l10n.catalystManualRequired,
              message: l10n.catalystManualRequiredMessage,
              isWarning: true,
              icon: Icons.pan_tool_alt_outlined,
            ),
          ),
          if (data.ffmpeg.detected != true ||
              data.ffprobe.detected != true ||
              data.gyroflow.detected != true ||
              data.catalyst.detected != true)
            Padding(
              padding: const EdgeInsets.only(top: 12),
              child: NoticeBox(
                title: l10n.someStagesUnavailable,
                message: l10n.missingToolsTruthful,
                isWarning: true,
              ),
            ),
        ],
      ),
    );
  }
}

class _CapabilityLine extends StatelessWidget {
  const _CapabilityLine({required this.name, required this.capability});

  final String name;
  final ToolCapability capability;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    final l10n = context.l10n;
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: <Widget>[
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: <Widget>[
              Text(name, style: Theme.of(context).textTheme.titleSmall),
              if (capability.path != null) ...<Widget>[
                const SizedBox(height: 3),
                SelectableText(
                  l10n.configuredPath(capability.path!),
                  style: Theme.of(context).textTheme.bodySmall?.copyWith(
                    color: colors.onSurfaceVariant,
                  ),
                ),
              ],
              if (capability.mode != null) ...<Widget>[
                const SizedBox(height: 2),
                Text(
                  l10n.modeValue(capabilityModeLabel(l10n, capability.mode)),
                  style: Theme.of(context).textTheme.bodySmall?.copyWith(
                    color: colors.onSurfaceVariant,
                  ),
                ),
              ],
            ],
          ),
        ),
        const SizedBox(width: 8),
        CapabilityStatusPill(availability: capability.availability),
      ],
    );
  }
}

class _FactLine extends StatelessWidget {
  const _FactLine({required this.label, required this.value});

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.only(top: 7),
    child: Row(
      children: <Widget>[
        Expanded(child: Text(label, style: Theme.of(context).textTheme.bodySmall)),
        Text(value, style: Theme.of(context).textTheme.labelMedium),
      ],
    ),
  );
}

String _truth(AppLocalizations l10n, bool? value) => switch (value) {
  true => l10n.verified,
  false => l10n.notVerified,
  null => l10n.unknown,
};

String _reported(AppLocalizations l10n, bool? value) => switch (value) {
  true => l10n.reportedTrue,
  false => l10n.reportedFalse,
  null => l10n.unknown,
};

String _requirement(AppLocalizations l10n, bool? value) => switch (value) {
  true => l10n.required,
  false => l10n.notRequired,
  null => l10n.unknown,
};

String _pathGuardStatus(
  AppLocalizations l10n,
  ToolCapability capability,
  String? savedPath,
) {
  if (capability.detected != true) return l10n.unknown;
  if (capability.priorVerified != true) return l10n.notVerified;
  if (!isLocalAbsolutePath(savedPath ?? '') ||
      !localAbsolutePathsEqual(capability.path, savedPath)) {
    return l10n.savedPathMismatch;
  }
  return capability.priorVerificationMatchesConfiguredPath
      ? l10n.verifiedForSavedPath
      : l10n.cliProfileGuardUnavailable;
}
