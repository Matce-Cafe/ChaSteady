import 'dart:convert';

import 'package:flutter/material.dart';

import 'brand.dart';

enum CapabilityAvailability { detected, missing, unknown }

class ToolCapability {
  const ToolCapability({
    required this.detected,
    this.path,
    this.mode,
    this.priorVerified,
    this.priorVerifiedPath,
    this.cliStatus,
    this.exportVerified,
    this.trimMappingVerified,
    this.validationStatus,
    this.buildId,
    this.profileSafetyRequired,
    this.uiaVerified,
  });

  final bool? detected;
  final String? path;
  final String? mode;
  final bool? priorVerified;
  final String? priorVerifiedPath;
  final String? cliStatus;
  final bool? exportVerified;
  final bool? trimMappingVerified;
  final String? validationStatus;
  final String? buildId;
  final bool? profileSafetyRequired;
  final bool? uiaVerified;

  bool get priorVerificationMatchesConfiguredPath {
    final configured = _normalizedPath(path);
    final verified = _normalizedPath(priorVerifiedPath);
    final pathBoundEvidence = verified != null
        ? configured == verified
        : cliStatus == 'verified';
    final cliAllowsRun = cliStatus == null || cliStatus == 'verified';
    return detected == true &&
        priorVerified == true &&
        configured != null &&
        cliAllowsRun &&
        pathBoundEvidence;
  }

  CapabilityAvailability get availability => switch (detected) {
    true => CapabilityAvailability.detected,
    false => CapabilityAvailability.missing,
    null => CapabilityAvailability.unknown,
  };

  factory ToolCapability.fromJson(dynamic value) {
    if (value is! Map) return const ToolCapability(detected: null);
    final map = Map<String, dynamic>.from(value);
    return ToolCapability(
      detected: map['detected'] is bool ? map['detected'] as bool : null,
      path: _nonEmptyString(map['path']),
      mode: _nonEmptyString(map['mode']),
      priorVerified: map['prior_verified'] is bool
          ? map['prior_verified'] as bool
          : null,
      priorVerifiedPath:
          _nonEmptyString(map['prior_verified_path']) ??
          _nonEmptyString(map['verified_path']),
      cliStatus: _nonEmptyString(map['cli_status']),
      exportVerified: map['export_verified'] is bool
          ? map['export_verified'] as bool
          : null,
      trimMappingVerified: map['trim_mapping_verified'] is bool
          ? map['trim_mapping_verified'] as bool
          : null,
      validationStatus: _nonEmptyString(map['validation_status']),
      buildId: _nonEmptyString(map['build_id']),
      profileSafetyRequired: map['profile_safety_required'] is bool
          ? map['profile_safety_required'] as bool
          : null,
      uiaVerified: map['uia_verified'] is bool
          ? map['uia_verified'] as bool
          : null,
    );
  }
}

class PresetRecord {
  PresetRecord(this.raw);

  final Map<String, dynamic> raw;

  String get displayName =>
      _nonEmptyString(raw['label']) ??
      _nonEmptyString(raw['name']) ??
      _nonEmptyString(raw['id']) ??
      _nonEmptyString(raw['key']) ??
      '';

  String get stableKey =>
      _nonEmptyString(raw['id']) ??
      _nonEmptyString(raw['key']) ??
      _nonEmptyString(raw['name']) ??
      _nonEmptyString(raw['label']) ??
      jsonEncode(raw);

  bool get discoveryRequired => raw['discovery_required'] == true;

  bool get isC7037 {
    final identity = <String?>[
      raw['id'] is String ? raw['id'] as String : null,
      raw['key'] is String ? raw['key'] as String : null,
      raw['name'] is String ? raw['name'] as String : null,
      raw['label'] is String ? raw['label'] as String : null,
    ].whereType<String>().join(' ');
    return identity.toLowerCase().contains('c7037');
  }

  Map<String, dynamic> get request {
    final value = raw['request'];
    return value is Map
        ? Map<String, dynamic>.from(value)
        : const <String, dynamic>{};
  }

  String? get legacyQuietCache =>
      _nonEmptyString(request['legacy_quiet_cache']);
  String? get legacyReferenceCache =>
      _nonEmptyString(request['legacy_reference_cache']);

  bool get hasCompleteCachedV9Request {
    if (discoveryRequired) return false;
    final value = request;
    final requiredPaths = <String>['original', 'ctb', 'reference'];
    final requiredNumbers = <String>[
      'start',
      'end',
      'ctb_origin',
      'reference_origin',
      'quiet_sigma_seconds',
      'reference_fov',
    ];
    return value['mode'] == 'cached_v9' &&
        requiredPaths.every((key) => _nonEmptyString(value[key]) != null) &&
        requiredNumbers.every(
          (key) => value[key] is num && (value[key] as num).toDouble().isFinite,
        ) &&
        value['reference_intervals'] is List &&
        legacyQuietCache != null &&
        legacyReferenceCache != null;
  }

  factory PresetRecord.fromJson(dynamic value) {
    if (value is String) return PresetRecord({'name': value});
    if (value is Map) return PresetRecord(Map<String, dynamic>.from(value));
    return PresetRecord({'name': value.toString()});
  }
}

class Capabilities {
  const Capabilities({
    required this.ffmpeg,
    this.ffprobe = const ToolCapability(detected: null),
    required this.gyroflow,
    required this.catalyst,
    required this.presetCatalog,
    required this.nativePicker,
    this.version,
    this.stabilize = const <String, dynamic>{},
  });

  final ToolCapability ffmpeg;
  final ToolCapability ffprobe;
  final ToolCapability gyroflow;
  final ToolCapability catalyst;
  final List<PresetRecord> presetCatalog;
  final bool? nativePicker;
  final String? version;
  final Map<String, dynamic> stabilize;

  bool get supportsStabilize => stabilize['workflow_version'] == 1;
  bool get supportsStabilizeContinuation =>
      supportsStabilize && stabilize['continuation_supported'] == true;

  factory Capabilities.fromJson(Map<String, dynamic> json) {
    final catalog = json['preset_catalog'];
    return Capabilities(
      ffmpeg: ToolCapability.fromJson(json['ffmpeg']),
      ffprobe: ToolCapability.fromJson(json['ffprobe']),
      gyroflow: ToolCapability.fromJson(json['gyroflow']),
      catalyst: ToolCapability.fromJson(json['catalyst']),
      presetCatalog: catalog is List
          ? catalog.map(PresetRecord.fromJson).toList(growable: false)
          : const <PresetRecord>[],
      nativePicker: json['native_picker'] is bool
          ? json['native_picker'] as bool
          : null,
      version: _nonEmptyString(json['version']),
      stabilize: _stringKeyedMap(json['stabilize']),
    );
  }
}

const toolPathKeys = <String>['ffmpeg', 'ffprobe', 'gyroflow', 'catalyst'];

enum AppLanguageMode { system, zh, en }

class AppPreferences {
  const AppPreferences({
    required this.themeMode,
    required this.seedColor,
    this.languageMode = AppLanguageMode.system,
    this.toolPaths = const <String, String?>{},
    this.toolPathsLoaded = false,
  });

  final ThemeMode themeMode;
  final int seedColor;
  final AppLanguageMode languageMode;
  final Map<String, String?> toolPaths;
  final bool toolPathsLoaded;

  static const defaults = AppPreferences(
    themeMode: ThemeMode.system,
    seedColor: defaultSeedColorArgb,
    languageMode: AppLanguageMode.system,
  );

  bool get hasCompleteToolPaths =>
      toolPathsLoaded && toolPathKeys.every(toolPaths.containsKey);

  factory AppPreferences.fromJson(Map<String, dynamic> json) {
    final mode = switch (json['theme_mode']) {
      'light' => ThemeMode.light,
      'dark' => ThemeMode.dark,
      _ => ThemeMode.system,
    };
    final color = json['seed_color'];
    final languageMode = switch (json['language_mode']) {
      'zh' => AppLanguageMode.zh,
      'en' => AppLanguageMode.en,
      _ => AppLanguageMode.system,
    };
    final rawPaths = json['tool_paths'];
    final paths = <String, String?>{};
    var pathsLoaded =
        rawPaths is Map &&
        toolPathKeys.every((key) => rawPaths.containsKey(key));
    if (rawPaths is Map) {
      for (final key in toolPathKeys) {
        final value = rawPaths[key];
        if (value == null || value is String) {
          paths[key] = value as String?;
        } else {
          pathsLoaded = false;
        }
      }
    }
    return AppPreferences(
      themeMode: mode,
      seedColor: color is int && color >= 0 && color <= 0xFFFFFFFF
          ? color
          : defaultSeedColorArgb,
      languageMode: languageMode,
      toolPaths: Map<String, String?>.unmodifiable(paths),
      toolPathsLoaded: pathsLoaded,
    );
  }

  Map<String, dynamic> toJson() => <String, dynamic>{
    'theme_mode': switch (themeMode) {
      ThemeMode.light => 'light',
      ThemeMode.dark => 'dark',
      ThemeMode.system => 'system',
    },
    'seed_color': seedColor,
    'language_mode': switch (languageMode) {
      AppLanguageMode.system => 'system',
      AppLanguageMode.zh => 'zh',
      AppLanguageMode.en => 'en',
    },
    'tool_paths': <String, String?>{
      for (final key in toolPathKeys) key: toolPaths[key],
    },
  };

  AppPreferences copyWith({
    ThemeMode? themeMode,
    int? seedColor,
    AppLanguageMode? languageMode,
    Map<String, String?>? toolPaths,
    bool? toolPathsLoaded,
  }) => AppPreferences(
    themeMode: themeMode ?? this.themeMode,
    seedColor: seedColor ?? this.seedColor,
    languageMode: languageMode ?? this.languageMode,
    toolPaths: toolPaths ?? this.toolPaths,
    toolPathsLoaded: toolPathsLoaded ?? this.toolPathsLoaded,
  );
}

class WorkerText {
  const WorkerText({
    this.messageKey,
    this.args = const <String, dynamic>{},
    this.original,
  });

  final String? messageKey;
  final Map<String, dynamic> args;
  final String? original;

  factory WorkerText.fromJson(
    dynamic value, {
    dynamic messageKey,
    dynamic args,
  }) {
    if (value is Map) {
      final map = Map<String, dynamic>.from(value);
      return WorkerText(
        messageKey:
            _nonEmptyString(map['message_key']) ??
            _nonEmptyString(map['messageKey']) ??
            _nonEmptyString(messageKey),
        args: _stringKeyedMap(map['args'] ?? map['message_args'] ?? args),
        original:
            _nonEmptyString(map['message']) ??
            _nonEmptyString(map['text']) ??
            _nonEmptyString(map['original']),
      );
    }
    return WorkerText(
      messageKey: _nonEmptyString(messageKey),
      args: _stringKeyedMap(args),
      original: _nonEmptyString(value),
    );
  }
}

class IntervalRange {
  const IntervalRange({required this.start, required this.end});

  final double start;
  final double end;

  Map<String, double> toJson() => <String, double>{'start': start, 'end': end};
}

enum IntervalValidationCode {
  nonNumeric,
  negativeStart,
  endNotAfterStart,
  chronologicalOrder,
  overlap,
  missingSourceWindow,
}

class IntervalValidation {
  const IntervalValidation({this.ranges = const [], this.code, this.row});

  final List<IntervalRange> ranges;
  final IntervalValidationCode? code;
  final int? row;

  /// Stable validation code for logic and tests; UI uses localized messages.
  String? get error => code?.name;

  bool get isValid => code == null;
}

IntervalValidation validateIntervals(Iterable<(String, String)> inputs) {
  final values = inputs.toList(growable: false);
  if (values.isEmpty) return const IntervalValidation();

  final ranges = <IntervalRange>[];
  for (var index = 0; index < values.length; index++) {
    final (startText, endText) = values[index];
    final start = double.tryParse(startText.trim());
    final end = double.tryParse(endText.trim());
    final row = index + 1;
    if (start == null || end == null || !start.isFinite || !end.isFinite) {
      return IntervalValidation(
        code: IntervalValidationCode.nonNumeric,
        row: row,
      );
    }
    if (start < 0) {
      return IntervalValidation(
        code: IntervalValidationCode.negativeStart,
        row: row,
      );
    }
    if (end <= start) {
      return IntervalValidation(
        code: IntervalValidationCode.endNotAfterStart,
        row: row,
      );
    }
    if (ranges.isNotEmpty) {
      final previous = ranges.last;
      if (start < previous.start) {
        return const IntervalValidation(
          code: IntervalValidationCode.chronologicalOrder,
        );
      }
      if (start < previous.end) {
        return IntervalValidation(
          code: IntervalValidationCode.overlap,
          row: row,
        );
      }
    }
    ranges.add(IntervalRange(start: start, end: end));
  }
  return IntervalValidation(ranges: List.unmodifiable(ranges));
}

IntervalValidation validateSourceWindow(String startText, String endText) {
  if (startText.trim().isEmpty || endText.trim().isEmpty) {
    return const IntervalValidation(
      code: IntervalValidationCode.missingSourceWindow,
    );
  }
  return validateIntervals(<(String, String)>[(startText, endText)]);
}

double? parseReferenceFov(String value) {
  final parsed = double.tryParse(value.trim());
  if (parsed == null || !parsed.isFinite || parsed < 1 || parsed > 4)
    return null;
  return parsed;
}

class MediaInfo {
  const MediaInfo({
    required this.path,
    this.name,
    this.width,
    this.height,
    this.fps,
    this.frames,
    this.duration,
    this.videoCodec,
    this.pixelFormat,
    this.audioCodec,
    this.bitDepth,
    this.cfrStatus,
  });

  final String path;
  final String? name;
  final int? width;
  final int? height;
  final double? fps;
  final int? frames;
  final double? duration;
  final String? videoCodec;
  final String? pixelFormat;
  final String? audioCodec;
  final int? bitDepth;
  final String? cfrStatus;

  factory MediaInfo.fromJson(Map<String, dynamic> json) => MediaInfo(
    path: _nonEmptyString(json['path']) ?? '',
    name: _nonEmptyString(json['name']),
    width: json['width'] is num ? (json['width'] as num).toInt() : null,
    height: json['height'] is num ? (json['height'] as num).toInt() : null,
    fps: _number(json['fps']),
    frames: json['frames'] is num ? (json['frames'] as num).toInt() : null,
    duration: _number(json['duration']),
    videoCodec: _nonEmptyString(json['video_codec']),
    pixelFormat: _nonEmptyString(json['pixel_format']),
    audioCodec: _nonEmptyString(json['audio_codec']),
    bitDepth: json['bit_depth'] is num
        ? (json['bit_depth'] as num).toInt()
        : null,
    cfrStatus: _nonEmptyString(json['cfr_status']),
  );
}

class ArtifactRecord {
  const ArtifactRecord({
    required this.id,
    required this.label,
    required this.kind,
    required this.url,
    required this.mime,
    this.path,
    this.mediaMetadata = const <String, dynamic>{},
    this.validationScope,
    this.warnings = const <String>[],
    this.warningTexts = const <WorkerText>[],
  });

  final String id;
  final String label;
  final String kind;
  final String? path;
  final String url;
  final String mime;
  final Map<String, dynamic> mediaMetadata;
  final String? validationScope;
  final List<String> warnings;
  final List<WorkerText> warningTexts;

  List<WorkerText> get workerWarnings => warningTexts.isNotEmpty
      ? warningTexts
      : warnings.map((value) => WorkerText(original: value)).toList();

  bool get isBrowserPreview =>
      kind == 'preview' && mime.toLowerCase().startsWith('video/mp4');

  factory ArtifactRecord.fromJson(Map<String, dynamic> json) {
    final metadata = json['media_metadata'];
    return ArtifactRecord(
      id: _nonEmptyString(json['id']) ?? '',
      label: _nonEmptyString(json['label']) ?? '',
      kind: _nonEmptyString(json['kind']) ?? 'unknown',
      path: _nonEmptyString(json['path']),
      url: _nonEmptyString(json['url']) ?? '',
      mime: _nonEmptyString(json['mime']) ?? 'application/octet-stream',
      mediaMetadata: metadata is Map
          ? Map<String, dynamic>.from(metadata)
          : const <String, dynamic>{},
      validationScope: _nonEmptyString(json['validation_scope']),
      warnings: _stringList(json['warnings']),
      warningTexts: _workerTextList(json['warnings']),
    );
  }
}

class JobSummary {
  const JobSummary({
    required this.id,
    required this.kind,
    required this.state,
    required this.stage,
    required this.progress,
    required this.message,
    required this.artifacts,
    required this.warnings,
    this.createdAt,
    this.updatedAt,
    this.errorCode,
    this.errorMessage,
    this.messageKey,
    this.messageArgs = const <String, dynamic>{},
    this.errorMessageKey,
    this.errorArgs = const <String, dynamic>{},
    this.warningTexts = const <WorkerText>[],
    this.result,
    this.workflow,
  });

  final String id;
  final String kind;
  final String state;
  final String? stage;
  final double? progress;
  final String? message;
  final String? messageKey;
  final Map<String, dynamic> messageArgs;
  final DateTime? createdAt;
  final DateTime? updatedAt;
  final List<ArtifactRecord> artifacts;
  final List<String> warnings;
  final String? errorCode;
  final String? errorMessage;
  final String? errorMessageKey;
  final Map<String, dynamic> errorArgs;
  final List<WorkerText> warningTexts;
  final Map<String, dynamic>? result;
  final Map<String, dynamic>? workflow;

  WorkerText get workerMessage =>
      WorkerText(messageKey: messageKey, args: messageArgs, original: message);

  WorkerText? get workerError => errorMessage == null && errorMessageKey == null
      ? null
      : WorkerText(
          messageKey: errorMessageKey,
          args: errorArgs,
          original: errorMessage,
        );

  List<WorkerText> get workerWarnings => warningTexts.isNotEmpty
      ? warningTexts
      : warnings.map((value) => WorkerText(original: value)).toList();

  bool get canCancel => state == 'queued' || state == 'running';
  bool get isActive => state == 'queued' || state == 'running';

  factory JobSummary.fromJson(Map<String, dynamic> json) {
    final rawProgress = json['progress'];
    double? progress;
    if (rawProgress is num) {
      final candidate = rawProgress.toDouble();
      if (candidate.isFinite && candidate >= 0 && candidate <= 1) {
        progress = candidate;
      }
    }
    final rawArtifacts = json['artifacts'];
    final rawError = json['error'];
    final rawResult = json['result'];
    final messageText = WorkerText.fromJson(
      json['message'],
      messageKey: json['message_key'] ?? json['messageKey'],
      args: json['args'] ?? json['message_args'],
    );
    final errorText = rawError is Map ? WorkerText.fromJson(rawError) : null;
    return JobSummary(
      id: _nonEmptyString(json['id']) ?? '',
      kind: _nonEmptyString(json['kind']) ?? 'unknown',
      state: _nonEmptyString(json['state']) ?? 'unknown',
      stage: _nonEmptyString(json['stage']),
      progress: progress,
      message: messageText.original,
      messageKey: messageText.messageKey,
      messageArgs: messageText.args,
      createdAt: _dateTime(json['created_at']),
      updatedAt: _dateTime(json['updated_at']),
      artifacts: rawArtifacts is List
          ? rawArtifacts
                .whereType<Map>()
                .map(
                  (item) =>
                      ArtifactRecord.fromJson(Map<String, dynamic>.from(item)),
                )
                .where((item) => item.id.isNotEmpty)
                .toList(growable: false)
          : const <ArtifactRecord>[],
      warnings: _stringList(json['warnings']),
      warningTexts: _workerTextList(json['warnings']),
      errorCode: rawError is Map ? _nonEmptyString(rawError['code']) : null,
      errorMessage: errorText?.original,
      errorMessageKey: errorText?.messageKey,
      errorArgs: errorText?.args ?? const <String, dynamic>{},
      result: rawResult is Map ? Map<String, dynamic>.from(rawResult) : null,
      workflow: json['workflow'] is Map
          ? _stringKeyedMap(json['workflow'])
          : null,
    );
  }
}

String? _normalizedPath(String? value) {
  final path = value?.trim();
  if (path == null || path.isEmpty) return null;
  return path
      .replaceAll('\\', '/')
      .replaceFirst(RegExp(r'/+$'), '')
      .toLowerCase();
}

bool localAbsolutePathsEqual(String? first, String? second) {
  final normalizedFirst = _normalizedPath(first);
  final normalizedSecond = _normalizedPath(second);
  return normalizedFirst != null && normalizedFirst == normalizedSecond;
}

String? _nonEmptyString(dynamic value) {
  if (value is! String) return null;
  final trimmed = value.trim();
  return trimmed.isEmpty ? null : trimmed;
}

double? _number(dynamic value) {
  if (value is! num) return null;
  final number = value.toDouble();
  return number.isFinite ? number : null;
}

DateTime? _dateTime(dynamic value) {
  if (value is! String) return null;
  return DateTime.tryParse(value)?.toLocal();
}

Map<String, dynamic> _stringKeyedMap(dynamic value) {
  if (value is! Map) return const <String, dynamic>{};
  return Map<String, dynamic>.unmodifiable(<String, dynamic>{
    for (final entry in value.entries)
      if (entry.key is String) entry.key as String: entry.value,
  });
}

List<WorkerText> _workerTextList(dynamic value) {
  if (value is! List) return const <WorkerText>[];
  return value
      .map((item) => WorkerText.fromJson(item))
      .where((item) => item.original != null || item.messageKey != null)
      .toList(growable: false);
}

List<String> _stringList(dynamic value) {
  if (value is! List) return const <String>[];
  return value
      .map((item) {
        if (item is String) return item.trim();
        if (item is Map && item['message'] is String) {
          return (item['message'] as String).trim();
        }
        return item.toString();
      })
      .where((item) => item.isNotEmpty)
      .toList(growable: false);
}
