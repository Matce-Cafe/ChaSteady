import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart' show ThemeMode;

import 'api/api_service.dart';
import 'models.dart';
import 'platform/media_platform.dart';

class AppController extends ChangeNotifier {
  AppController({
    required this.api,
    required this.platform,
    required this.sessionNonce,
  });

  final ApiService api;
  final MediaPlatformAdapter platform;
  final String? sessionNonce;

  AppConnectionState connectionState = AppConnectionState.starting;
  Object? connectionError;
  Capabilities? capabilities;
  Object? capabilitiesError;
  AppPreferences preferences = AppPreferences.defaults;
  AppPreferences draftPreferences = AppPreferences.defaults;
  bool preferencesLoaded = false;
  Object? preferencesError;
  Object? preferencesSaveError;
  List<JobSummary>? jobs;
  Object? jobsError;
  String? selectedJobId;
  Object? selectedJobError;
  List<PresetRecord>? discoveredPresets;
  Object? presetDiscoveryError;

  Timer? _pollTimer;
  Timer? _preferencesTimer;
  bool _refreshingJobs = false;
  bool _refreshingPreferences = false;
  bool _disposed = false;

  bool get isApiReady => connectionState == AppConnectionState.ready;

  JobSummary? get selectedJob {
    final currentJobs = jobs;
    if (currentJobs == null || selectedJobId == null) return null;
    for (final job in currentJobs) {
      if (job.id == selectedJobId) return job;
    }
    return null;
  }

  List<PresetRecord> get availablePresets {
    final all = <PresetRecord>[];
    final keys = <String>{};
    // Discovery responses carry the full approved request. Prefer them over
    // metadata-only capability catalog entries with the same stable identity.
    for (final preset in <PresetRecord>[
      ...?discoveredPresets,
      ...?capabilities?.presetCatalog,
    ]) {
      if (keys.add(preset.stableKey)) all.add(preset);
    }
    return all;
  }

  Future<void> initialize() async {
    if (!platform.supportsLocalServer) {
      connectionState = AppConnectionState.unsupported;
      connectionError = UnsupportedError('native_session_unavailable');
      _notify();
      return;
    }
    final nonce = sessionNonce;
    if (nonce == null || nonce.isEmpty) {
      connectionState = AppConnectionState.needsSession;
      connectionError = null;
      _notify();
      return;
    }

    connectionState = AppConnectionState.starting;
    connectionError = null;
    _notify();
    try {
      await api.establishSession(nonce);
    } catch (error) {
      connectionState = AppConnectionState.error;
      connectionError = error;
      _notify();
      return;
    }

    connectionState = AppConnectionState.ready;
    connectionError = null;
    _notify();
    await Future.wait<void>(<Future<void>>[
      _loadCapabilities(),
      _loadPreferences(),
      refreshJobs(),
    ]);
    _preferencesTimer ??= Timer.periodic(
      const Duration(seconds: 5),
      (_) => refreshPreferences(),
    );
    _updatePolling();
  }

  Future<void> retry() => initialize();

  Future<void> _loadCapabilities() async {
    try {
      capabilities = await api.getCapabilities();
      capabilitiesError = null;
    } catch (error) {
      capabilitiesError = error;
    }
    _notify();
  }

  Future<void> _loadPreferences() async {
    try {
      _mergeServerPreferences(await api.getPreferences());
      preferencesLoaded = true;
      preferencesError = null;
    } catch (error) {
      preferencesError = error;
    }
    _notify();
  }

  Future<void> refreshPreferences() async {
    if (!isApiReady || !preferencesLoaded || _refreshingPreferences) return;
    _refreshingPreferences = true;
    try {
      _mergeServerPreferences(await api.getPreferences());
      preferencesError = null;
    } catch (error) {
      preferencesError = error;
    } finally {
      _refreshingPreferences = false;
      _notify();
    }
  }

  void _mergeServerPreferences(AppPreferences incoming) {
    final previous = preferences;
    final draft = draftPreferences;
    final paths = <String, String?>{...incoming.toolPaths};
    for (final key in toolPathKeys) {
      if (draft.toolPaths[key] != previous.toolPaths[key]) {
        paths[key] = draft.toolPaths[key];
      }
    }
    preferences = incoming;
    draftPreferences = incoming.copyWith(
      themeMode: draft.themeMode != previous.themeMode
          ? draft.themeMode
          : incoming.themeMode,
      seedColor: draft.seedColor != previous.seedColor
          ? draft.seedColor
          : incoming.seedColor,
      languageMode: draft.languageMode != previous.languageMode
          ? draft.languageMode
          : incoming.languageMode,
      toolPaths: Map<String, String?>.unmodifiable(paths),
      toolPathsLoaded: incoming.toolPathsLoaded,
    );
  }

  Future<void> refreshJobs() async {
    if (!isApiReady || _refreshingJobs) return;
    _refreshingJobs = true;
    try {
      final received = await api.getJobs();
      jobs = received;
      jobsError = null;
      if (selectedJobId != null &&
          !received.any((job) => job.id == selectedJobId)) {
        selectedJobId = null;
      }
    } catch (error) {
      jobsError = error;
    } finally {
      _refreshingJobs = false;
      _notify();
      _updatePolling();
    }
  }

  Future<void> selectJob(String id) async {
    selectedJobId = id;
    selectedJobError = null;
    _notify();
    if (!isApiReady) return;
    try {
      final detail = await api.getJob(id);
      _upsertJob(detail);
      selectedJobError = null;
    } catch (error) {
      selectedJobError = error;
    }
    _notify();
  }

  Future<JobSummary> createJob(Map<String, dynamic> payload) async {
    final kind = payload['kind'];
    if (kind is! String || kind.trim().isEmpty) {
      throw const ApiException(
        code: 'invalid_job',
        message: 'A supported job kind is required.',
        messageKey: 'ui.error.jobKindRequired',
      );
    }
    final rawRequest = payload['request'];
    late final Map<String, dynamic> request;
    if (rawRequest is Map) {
      if (payload.keys.any((key) => key != 'kind' && key != 'request')) {
        throw const ApiException(
          code: 'invalid_job',
          message: 'Job fields must be nested under request.',
          messageKey: 'ui.error.jobFieldsNested',
        );
      }
      request = Map<String, dynamic>.from(rawRequest);
    } else {
      request = Map<String, dynamic>.from(payload)..remove('kind');
      if (payload.containsKey('request')) {
        throw const ApiException(
          code: 'invalid_job',
          message: 'Job request must be an object.',
          messageKey: 'ui.error.jobRequestInvalid',
        );
      }
    }
    final job = await api.createJob(kind, request);
    _upsertJob(job);
    selectedJobId = job.id;
    selectedJobError = null;
    _notify();
    _updatePolling();
    return job;
  }

  Future<void> cancelJob(String id) async {
    final job = await api.cancelJob(id);
    _upsertJob(job);
    selectedJobError = null;
    _notify();
    _updatePolling();
  }

  Future<MediaInfo> inspectMedia(String path) => api.inspectMedia(path);

  Future<String?> pickMedia(String kind) => api.pickMedia(kind);

  Future<void> discoverPresets(String experimentRoot) async {
    discoveredPresets = null;
    presetDiscoveryError = null;
    _notify();
    try {
      discoveredPresets = await api.discoverPresets(experimentRoot);
    } catch (error) {
      presetDiscoveryError = error;
    }
    _notify();
  }

  void updatePreferenceDraft(AppPreferences value) {
    draftPreferences = value;
    preferencesSaveError = null;
    _notify();
  }

  Future<void> saveLanguageMode(AppLanguageMode mode) async {
    updatePreferenceDraft(draftPreferences.copyWith(languageMode: mode));
    if (!isApiReady || !preferencesLoaded) return;
    try {
      final language = switch (mode) {
        AppLanguageMode.system => 'system',
        AppLanguageMode.zh => 'zh',
        AppLanguageMode.en => 'en',
      };
      _mergeServerPreferences(
        await api.patchPreferences(<String, dynamic>{'language_mode': language}),
      );
      preferencesSaveError = null;
    } catch (error) {
      preferencesSaveError = error;
    }
    _notify();
  }

  Map<String, dynamic> _preferencePatch() {
    final patch = <String, dynamic>{};
    if (draftPreferences.themeMode != preferences.themeMode) {
      patch['theme_mode'] = switch (draftPreferences.themeMode) {
        ThemeMode.light => 'light',
        ThemeMode.dark => 'dark',
        ThemeMode.system => 'system',
      };
    }
    if (draftPreferences.seedColor != preferences.seedColor) {
      patch['seed_color'] = draftPreferences.seedColor;
    }
    if (draftPreferences.languageMode != preferences.languageMode) {
      patch['language_mode'] = switch (draftPreferences.languageMode) {
        AppLanguageMode.system => 'system',
        AppLanguageMode.zh => 'zh',
        AppLanguageMode.en => 'en',
      };
    }
    final changedPaths = <String, String?>{};
    for (final key in toolPathKeys) {
      if (draftPreferences.toolPaths[key] != preferences.toolPaths[key]) {
        changedPaths[key] = draftPreferences.toolPaths[key];
      }
    }
    if (changedPaths.isNotEmpty) patch['tool_paths'] = changedPaths;
    return patch;
  }

  Future<void> savePreferences() async {
    final patch = _preferencePatch();
    if (patch.isEmpty) return;
    final sentDraft = draftPreferences;
    preferencesSaveError = null;
    _notify();
    try {
      final saved = await api.patchPreferences(patch);
      final currentDraft = draftPreferences;
      final paths = <String, String?>{...saved.toolPaths};
      for (final key in toolPathKeys) {
        if (currentDraft.toolPaths[key] != sentDraft.toolPaths[key]) {
          paths[key] = currentDraft.toolPaths[key];
        }
      }
      preferences = saved;
      draftPreferences = saved.copyWith(
        themeMode: currentDraft.themeMode != sentDraft.themeMode
            ? currentDraft.themeMode
            : saved.themeMode,
        seedColor: currentDraft.seedColor != sentDraft.seedColor
            ? currentDraft.seedColor
            : saved.seedColor,
        languageMode: currentDraft.languageMode != sentDraft.languageMode
            ? currentDraft.languageMode
            : saved.languageMode,
        toolPaths: Map<String, String?>.unmodifiable(paths),
        toolPathsLoaded: saved.toolPathsLoaded,
      );
      preferencesLoaded = true;
      if (patch.containsKey('tool_paths')) await _loadCapabilities();
    } catch (error) {
      preferencesSaveError = error;
    }
    _notify();
  }

  Uri artifactContentUri(ArtifactRecord artifact) {
    final base = api.origin;
    if (base == null || !RegExp(r'^[A-Za-z0-9_-]+$').hasMatch(artifact.id)) {
      throw const ApiException(
        code: 'invalid_artifact',
        message: 'This artifact cannot be opened as a local preview.',
        messageKey: 'ui.error.invalidArtifact',
      );
    }
    return base.resolve(
      '/api/artifacts/${Uri.encodeComponent(artifact.id)}/content',
    );
  }

  Future<void> openArtifact(ArtifactRecord artifact) =>
      api.openArtifact(artifact.id);

  void _upsertJob(JobSummary job) {
    final current = jobs ?? <JobSummary>[];
    final index = current.indexWhere((item) => item.id == job.id);
    if (index < 0) {
      jobs = <JobSummary>[job, ...current];
    } else {
      final updated = List<JobSummary>.of(current);
      updated[index] = job;
      jobs = updated;
    }
    jobsError = null;
  }

  void _updatePolling() {
    if (_disposed) return;
    final hasActive = jobs?.any((job) => job.isActive) ?? false;
    if (hasActive && _pollTimer == null && isApiReady) {
      _pollTimer = Timer.periodic(
        const Duration(seconds: 3),
        (_) => refreshJobs(),
      );
    } else if (!hasActive) {
      _pollTimer?.cancel();
      _pollTimer = null;
    }
  }

  void _notify() {
    if (!_disposed) notifyListeners();
  }

  @override
  void dispose() {
    _disposed = true;
    _pollTimer?.cancel();
    _preferencesTimer?.cancel();
    super.dispose();
  }
}

enum AppConnectionState { starting, ready, unsupported, needsSession, error }

