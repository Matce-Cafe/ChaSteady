import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../l10n/app_localizations.dart';
import 'api/api_service.dart';
import 'models.dart';

export '../l10n/app_localizations.dart';

extension AppLocalizationsContext on BuildContext {
  AppLocalizations get l10n => AppLocalizations.of(this);
}

Locale? preferredLocale(AppLanguageMode mode) => switch (mode) {
  AppLanguageMode.system => null,
  AppLanguageMode.zh => const Locale('zh'),
  AppLanguageMode.en => const Locale('en'),
};

Locale resolveSupportedLocale(Locale? requested) {
  if (requested?.languageCode.toLowerCase() == 'zh') return const Locale('zh');
  return const Locale('en');
}

String? intervalValidationMessage(
  AppLocalizations l10n,
  IntervalValidation validation,
) {
  final row = validation.row ?? 1;
  return switch (validation.code) {
    null => null,
    IntervalValidationCode.nonNumeric => l10n.intervalNonNumeric(row),
    IntervalValidationCode.negativeStart => l10n.intervalNegativeStart(row),
    IntervalValidationCode.endNotAfterStart => l10n.intervalEndNotAfterStart(
      row,
    ),
    IntervalValidationCode.chronologicalOrder =>
      l10n.intervalChronologicalOrder,
    IntervalValidationCode.overlap => l10n.intervalOverlap(row),
    IntervalValidationCode.missingSourceWindow => l10n.sourceWindowInvalid,
  };
}

String localizedWorkerText(
  AppLocalizations l10n,
  WorkerText text, {
  WorkerTextKind kind = WorkerTextKind.message,
}) {
  final translated = _knownWorkerMessage(l10n, text);
  if (translated != null) {
    final original = text.original?.trim();
    if (original == null || original.isEmpty) return translated;
    final originalLabel = switch (kind) {
      WorkerTextKind.message => l10n.originalWorkerMessage(original),
      WorkerTextKind.warning => l10n.originalWorkerWarning(original),
      WorkerTextKind.artifactWarning => l10n.originalArtifactWarning(original),
      WorkerTextKind.error => l10n.originalServiceMessage(original),
    };
    return '$translated\n$originalLabel';
  }
  final original = text.original;
  if (original != null) {
    return switch (kind) {
      WorkerTextKind.message => l10n.originalWorkerMessage(original),
      WorkerTextKind.warning => l10n.originalWorkerWarning(original),
      WorkerTextKind.artifactWarning => l10n.originalArtifactWarning(original),
      WorkerTextKind.error => l10n.originalServiceMessage(original),
    };
  }
  final key = text.messageKey;
  if (key != null) return l10n.unknownWorkerCode(key);
  return l10n.genericOperationFailed;
}

enum WorkerTextKind { message, warning, artifactWarning, error }

String? _knownWorkerMessage(AppLocalizations l10n, WorkerText text) {
  final key = text.messageKey;
  if (key == null) return null;
  switch (key) {
    case 'job.progress.sourceAcceptance':
      return l10n.stageSourceAcceptance;
    case 'job.progress.capabilityPreflight':
      return l10n.stageCapabilityPreflight;
    case 'job.progress.ctb':
      return l10n.stageCtb;
    case 'job.progress.gf':
      return l10n.stageGf;
    case 'job.progress.correspondence':
      return l10n.stageCorrespondence;
    case 'job.progress.freshMeasurement':
      return l10n.stageFreshMeasurement;
    case 'job.progress.finalValidation':
      return l10n.stageFinalValidation;
    case 'job.progress.gyroflowPreflight':
      return l10n.stageCapabilityPreflight;
    case 'job.progress.gyroflowExport':
      return l10n.stageGf;
    case 'job.progress.gyroflowExportVerified':
      return l10n.gyroflowDeclaredChecksPassed;
    case 'job.progress.cancellationRequested':
      return l10n.cancellationRequested;
    case 'job.error.ctbExecutorUnavailable':
      return l10n.ctbExecutorUnavailable;
    case 'job.error.fullContentCorrespondenceUnverified':
      return l10n.fullContentCorrespondenceUnverified;
    case 'job.progress.queued':
      return l10n.workerQueued;
    case 'job.progress.starting':
      return l10n.workerStarting;
    case 'job.progress.inspect':
      return l10n.workerInspectFusionInputs;
    case 'job.progress.cachedTrajectory':
      return l10n.workerCachedTrajectory;
    case 'job.progress.fusion':
      return l10n.workerComputeFusion;
    case 'job.progress.render':
      return _countProgress(text, l10n.workerRenderProgress);
    case 'job.progress.verify':
      return l10n.workerVerifyOutput;
    case 'job.progress.registration':
      return _countProgress(text, l10n.workerRegistrationProgress);
    case 'job.progress.quietTracking':
      return _countProgress(text, l10n.workerQuietTrackingProgress);
    case 'job.progress.previewEncode':
      return l10n.workerPreviewEncode;
    case 'job.progress.mediaValidation':
      return l10n.workerValidateMedia;
    case 'job.progress.catalystManualHandoff':
      return l10n.workerCatalystManual;
    case 'job.progress.needsManual':
      return l10n.workerNeedsManual;
    case 'job.progress.needsReview':
      return l10n.workerNeedsReview;
    case 'job.progress.failed':
      return l10n.workerFailed;
    case 'job.progress.cancelled':
      return l10n.workerCancelled;
    case 'job.progress.verifiedMedia':
      return l10n.workerVerifiedMedia;
    case 'job.error.needsReview':
      return l10n.workerErrorNeedsReview;
    case 'job.error.needsManual':
      return l10n.workerErrorNeedsManual;
    case 'job.error.cancelled':
      return l10n.workerErrorCancelled;
    case 'job.error.workerInterrupted':
      return l10n.workerErrorInterrupted;
    case 'job.error.missingCapability':
      return l10n.workerErrorMissingCapability;
    case 'job.error.processingFailed':
      return l10n.workerErrorProcessingFailed;
    case 'nativeMedia.error.leaseUnavailable':
      return l10n.nativeLeaseUnavailable;
    case 'nativeProtocol.error.unsupportedAction':
      return l10n.nativeActionUnsupported;
    case 'nativeProtocol.error.unsupportedVersion':
      return l10n.nativeProtocolUnsupported;
    case 'nativeProtocol.error.generic':
      return l10n.nativeProtocolError;
    case 'nativeProtocol.error.invalidRequest':
      return l10n.nativeProtocolInvalidRequest;
    case 'nativeWorker.error.stopping':
      return l10n.nativeWorkerStopping;
    case 'nativeWorker.error.stopped':
      return l10n.nativeWorkerStopped;
    case 'nativeWorker.error.startup':
      return l10n.nativeWorkerStartup;
    case 'nativeWorker.error.bundle':
      return l10n.nativeWorkerBundle;
    case 'nativeWorker.error.dataRoot':
      return l10n.nativeWorkerDataRoot;
    case 'nativeWorker.error.alreadyRunning':
      return l10n.nativeWorkerAlreadyRunning;
    case 'nativeWorker.error.diagnostics':
      return l10n.nativeWorkerDiagnostics;
    case 'nativeWorker.error.pipe':
      return l10n.nativeWorkerPipe;
    case 'nativeWorker.error.job':
      return l10n.nativeWorkerJob;
    case 'nativeWorker.error.ready':
      return l10n.nativeWorkerReady;
    case 'nativeWorker.error.notReady':
      return l10n.nativeWorkerNotReady;
    case 'nativeWorker.error.requestLimit':
      return l10n.nativeWorkerRequestLimit;
    case 'nativeWorker.error.protocol':
      return l10n.nativeWorkerProtocol;
    case 'nativeWorker.error.exited':
      return l10n.nativeWorkerExited;
    case 'nativeWorker.error.timeout':
      return l10n.nativeWorkerTimeout;
    case 'nativePicker.error.invalidKind':
      return l10n.nativePickerInvalidKind;
    case 'nativePicker.error.failed':
      return l10n.nativePickerFailed;
    case 'nativeMedia.error.invalidArtifact':
      return l10n.nativeMediaInvalidArtifact;
    case 'nativeMedia.error.invalidLease':
      return l10n.nativeMediaInvalidLease;
    case 'nativeMedia.error.unavailable':
      return l10n.nativeMediaUnavailable;
    case 'nativeMedia.error.invalidPlayer':
      return l10n.nativeMediaInvalidPlayer;
    case 'nativeMedia.error.invalidPosition':
      return l10n.nativeMediaInvalidPosition;
    case 'nativeMedia.error.invalidVolume':
      return l10n.nativeMediaInvalidVolume;
    case 'nativeMedia.error.invalidMuted':
      return l10n.nativeMediaInvalidMuted;
    case 'nativeMedia.error.playerNotFound':
      return l10n.nativeMediaPlayerNotFound;
    case 'nativeMedia.error.disposeFailed':
      return l10n.nativeMediaDisposeFailed;
    case 'nativeMedia.error.playerAction':
      return l10n.nativeMediaPlayerAction;
    case 'nativeWeb.error.invalidSession':
      return l10n.nativeWebInvalidSession;
    case 'nativeWeb.error.openFailed':
      return l10n.nativeWebOpenFailed;
    case 'ui.error.invalidJobsList':
      return l10n.invalidJobsList;
    case 'ui.error.invalidPresetCatalog':
      return l10n.invalidPresetCatalog;
    case 'ui.error.unsupportedPlatform':
      return l10n.sessionUnsupported;
    case 'ui.error.sessionRequired':
      return l10n.openFromLauncher;
    case 'ui.error.connectionFailed':
      return l10n.localConnectionFailed(
        text.args['appName']?.toString() ?? l10n.appTitle,
      );
    case 'ui.error.invalidResponse':
      return l10n.invalidServiceResponse;
    case 'ui.error.invalidResourceId':
      return l10n.invalidLocalResourceId;
    case 'ui.error.jobRecordMissing':
      return l10n.missingJobRecord;
    case 'ui.error.jobCreatePending':
      return l10n.jobCreatePending;
    case 'ui.error.jobKindRequired':
      return l10n.invalidApiJobKind;
    case 'ui.error.jobFieldsNested':
      return l10n.apiJobFieldsNested;
    case 'ui.error.jobRequestInvalid':
      return l10n.apiJobRequestInvalid;
    case 'ui.error.invalidArtifact':
      return l10n.invalidArtifactPreview;
    case 'ui.error.httpStatus':
      final statusCode = _intArg(text.args['statusCode']);
      return statusCode == null ? null : l10n.serviceHttpError(statusCode);
    default:
      return null;
  }
}

String? _countProgress(
  WorkerText text,
  String Function(int current, int total) format,
) {
  final current = _intArg(text.args['current']);
  final total = _intArg(text.args['total']);
  if (current == null || total == null) return null;
  return format(current, total);
}

int? _intArg(dynamic value) {
  if (value is int) return value;
  if (value is num && value.isFinite && value == value.roundToDouble()) {
    return value.toInt();
  }
  if (value is String) return int.tryParse(value);
  return null;
}

String localizedError(AppLocalizations l10n, Object error) {
  if (error is ApiException) {
    if (error.messageKey != null) {
      final translated = _knownWorkerMessage(
        l10n,
        WorkerText(messageKey: error.messageKey, args: error.args),
      );
      if (translated != null) {
        final original = error.message.trim();
        if (error.messageKey!.startsWith('job.error.') && original.isNotEmpty) {
          return '$translated\n${l10n.originalServiceMessage(original)}';
        }
        return translated;
      }
    }
    final message = error.message.trim();
    if (message.isNotEmpty) {
      return error.code.isEmpty
          ? l10n.originalServiceMessage(message)
          : l10n.originalServiceMessageWithCode(error.code, message);
    }
    if (error.messageKey != null)
      return l10n.serviceMessageCodeOnly(error.messageKey!);
    if (error.statusCode != null)
      return l10n.serviceHttpError(error.statusCode!);
  }
  if (error is PlatformException) {
    return localizedPlatformError(l10n, error);
  }
  if (error is UnsupportedError &&
      error.message == 'native_session_unavailable') {
    return l10n.sessionUnsupported;
  }
  return l10n.originalServiceMessage(error.toString());
}

String localizedPlatformError(AppLocalizations l10n, PlatformException error) {
  final details = error.details;
  String? messageKey;
  Map<String, dynamic> args = const <String, dynamic>{};
  dynamic hresult;
  if (details is Map) {
    final rawKey = details['message_key'] ?? details['messageKey'];
    if (rawKey is String && rawKey.trim().isNotEmpty) {
      messageKey = rawKey.trim();
    }
    final rawArgs = details['args'];
    if (rawArgs is Map) args = Map<String, dynamic>.from(rawArgs);
    hresult = details['hresult'] ?? details['HRESULT'];
  }

  final parts = <String>[];
  final translated = messageKey == null
      ? null
      : _knownWorkerMessage(
          l10n,
          WorkerText(messageKey: messageKey, args: args),
        );
  if (translated != null) {
    parts.add(translated);
  } else if (messageKey != null) {
    parts.add(l10n.originalStatusValue(messageKey));
  }
  final originalMessage = error.message?.trim();
  if (originalMessage != null && originalMessage.isNotEmpty) {
    parts.add(l10n.nativeOriginalPlatformMessage(originalMessage));
  }
  parts.add(l10n.nativeErrorCode(error.code));
  if (args.isNotEmpty) {
    parts.add(l10n.nativeOriginalPlatformArgs(jsonEncode(args)));
  }
  if (hresult != null) {
    parts.add(l10n.nativeOriginalHresult(hresult.toString()));
  }
  return parts.join('\n');
}

String jobStateLabel(AppLocalizations l10n, String state) => switch (state) {
  'queued' => l10n.jobStateQueued,
  'running' => l10n.jobStateRunning,
  'needs_manual' => l10n.jobStateNeedsManual,
  'needs_review' => l10n.jobStateNeedsReview,
  'failed' => l10n.jobStateFailed,
  'cancelled' => l10n.jobStateCancelled,
  'verified_media' => l10n.jobStateVerifiedMedia,
  _ => l10n.unknownJobState(state),
};

String jobKindLabel(AppLocalizations l10n, String kind) => switch (kind) {
  'stabilize' => l10n.jobKindStabilize,
  'stabilize_continue' => l10n.jobKindStabilizeContinue,
  'fusion' => l10n.jobKindFusion,
  'preview' => l10n.jobKindPreview,
  'gyroflow_export' => l10n.jobKindGyroflowExport,
  'catalyst_assisted' => l10n.jobKindCatalyst,
  'validate' => l10n.jobKindValidate,
  _ => l10n.jobKindUnknown(kind),
};

String workerStageLabel(AppLocalizations l10n, String? stage) {
  if (stage == null || stage.isEmpty) return l10n.currentStage;
  return switch (stage) {
    'queued' => l10n.jobStateQueued,
    'verified_media' => l10n.jobStateVerifiedMedia,
    'gyroflow_preflight' => l10n.stageCapabilityPreflight,
    'gyroflow_export' => l10n.stageGf,
    'gyroflow_export_verified' => l10n.gyroflowDeclaredChecksPassed,
    'cancellation_requested' => l10n.cancellationRequested,
    'source_acceptance' => l10n.stageSourceAcceptance,
    'capability_preflight' => l10n.stageCapabilityPreflight,
    'ctb' => l10n.stageCtb,
    'gf' => l10n.stageGf,
    'correspondence' => l10n.stageCorrespondence,
    'fresh_measurement' => l10n.stageFreshMeasurement,
    'final_validation' => l10n.stageFinalValidation,
    'starting' => l10n.stageStarting,
    'inspect' => l10n.stageInspect,
    'preview_encode' => l10n.stagePreviewEncode,
    'media_validation' => l10n.stageMediaValidation,
    'cached_trajectory' => l10n.stageCachedTrajectory,
    'fusion' => l10n.stageFusion,
    'registration' => l10n.stageRegistration,
    'quiet_tracking' => l10n.stageQuietTracking,
    'render' => l10n.stageRender,
    'verify' => l10n.stageVerify,
    'catalyst_manual_handoff' => l10n.stageCatalystManual,
    'needs_manual' => l10n.jobStateNeedsManual,
    'needs_review' => l10n.jobStateNeedsReview,
    'cancelled' => l10n.jobStateCancelled,
    'failed' => l10n.jobStateFailed,
    _ => l10n.originalWorkerStage(stage),
  };
}

String workflowStateLabel(AppLocalizations l10n, String? state) =>
    switch (state) {
      null => l10n.unknown,
      'pending' => l10n.workflowPending,
      'passed' => l10n.workflowPassed,
      'ready' => l10n.workflowReady,
      'not_requested' => l10n.workflowNotRequested,
      'blocked' => l10n.blocked,
      _ => jobStateLabel(l10n, state),
    };

String toolStatusLabel(AppLocalizations l10n, String? value) => switch (value) {
  null => l10n.unknown,
  'verified' => l10n.verified,
  'blocked' => l10n.blocked,
  'not_detected' => l10n.notDetected,
  'unverified' => l10n.unverified,
  'needs_review' => l10n.jobStateNeedsReview,
  'verified_media' => l10n.verifiedMedia,
  'cli_blocked' => l10n.cliBlocked,
  'not_audited' => l10n.notAudited,
  'unknown' => l10n.unknown,
  _ => l10n.originalStatusValue(value),
};

String capabilityModeLabel(AppLocalizations l10n, String? mode) =>
    switch (mode) {
      null => l10n.unknown,
      'cli' => l10n.cliMode,
      'assisted' => l10n.catalyst,
      _ => l10n.originalStatusValue(mode),
    };
