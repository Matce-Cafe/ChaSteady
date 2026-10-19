// 仅供测试的模拟 API 和平台；不能作为真实拖入、播放或生产流程证据。
import 'package:cha_stabilizer_ui/src/api/api_service.dart';
import 'package:cha_stabilizer_ui/src/models.dart';
import 'package:cha_stabilizer_ui/src/platform/media_platform.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';

class TestPlatformAdapter implements MediaPlatformAdapter {
  TestPlatformAdapter({
    this.nativePicker = false,
    this.webAvailable = false,
    this.nativeDrop = false,
    bool nativeDesktop = false,
    this.managedShutdown = false,
    DesktopWindowState windowState = const DesktopWindowState(),
  }) : isNativeDesktop = nativeDesktop,
       _windowState = ValueNotifier(windowState);

  final bool nativePicker;
  final bool nativeDrop;
  String? pickerPath;
  Future<String?>? pickerGate;
  bool simulateNativePickerClearsDrop = false;
  final _nativePickerActive = ValueNotifier(false);
  @override
  ValueListenable<bool> get nativePickerActive => _nativePickerActive;
  final dropTargets = <MediaDropTarget?>[];
  ValueChanged<String>? dropHandler;
  Object? dropError;
  int activePreviews = 0;
  int maxActivePreviews = 0;
  final previewUris = <Uri>[];

  @override
  bool get supportsNativeMediaDrop => nativeDrop;
  @override
  Future<void> configureMediaDrop(
    MediaDropTarget? target, {
    ValueChanged<String>? onDrop,
  }) async {
    dropTargets.add(target);
    dropHandler = target == null ? null : onDrop;
    if (target != null && dropError != null) throw dropError!;
  }

  void simulateDrop(String path) => dropHandler?.call(path);
  final bool webAvailable;
  @override
  final bool isNativeDesktop;
  @override
  final bool managedShutdown;
  final ValueNotifier<DesktopWindowState> _windowState;
  @override
  ValueListenable<DesktopWindowState> get desktopWindowState => _windowState;
  final configureCalls = <DesktopWindowGeometry?>[];
  final windowCommands = <String>[];
  final alwaysOnTopValues = <bool>[];
  Future<void>? configureGate;
  Object? configureError;
  Object? windowCommandError;
  bool rejectCustomFrame = false;
  Future<bool> Function()? closeRequestHandler;
  bool shutdownRequested = false;
  bool simulateShutdownWarning = false;
  Future<void>? shutdownGate;
  Object? shutdownError;
  int shutdownCount = 0;
  int openWebCount = 0;
  bool _disposed = false;

  void emitWindowState(DesktopWindowState state) {
    if (!_disposed) _windowState.value = state;
  }

  @override
  Future<DesktopWindowState> configureWindowChrome(
    DesktopWindowGeometry? geometry,
  ) async {
    configureCalls.add(geometry);
    if (geometry != null) {
      await configureGate;
      if (configureError != null) throw configureError!;
    }
    final previous = _windowState.value;
    final state = DesktopWindowState(
      supported: previous.supported,
      customFrameEnabled: geometry != null && !rejectCustomFrame,
      maximized: previous.maximized,
      alwaysOnTop: previous.alwaysOnTop,
      maximizeButtonHovered: previous.maximizeButtonHovered,
      maximizeButtonPressed: previous.maximizeButtonPressed,
    );
    emitWindowState(state);
    return state;
  }

  Future<void> _windowCommand(String name) async {
    windowCommands.add(name);
    if (windowCommandError != null) throw windowCommandError!;
  }

  @override
  Future<void> minimizeWindow() => _windowCommand('minimizeWindow');
  @override
  Future<void> toggleMaximizeWindow() => _windowCommand('toggleMaximizeWindow');
  @override
  Future<void> startWindowDrag() => _windowCommand('startWindowDrag');
  @override
  Future<void> setAlwaysOnTop(bool value) {
    alwaysOnTopValues.add(value);
    return _windowCommand('setAlwaysOnTop');
  }

  @override
  Future<void> initialize() async {}

  @override
  Uri? get apiOrigin => Uri.parse('http://127.0.0.1:8765');

  @override
  bool get supportsLocalServer => true;

  @override
  String? consumeSessionNonce() => 'test-only-session';

  @override
  bool get supportsNativePicker => nativePicker;

  @override
  Future<String?> pickLocalPath(String kind) async {
    if (_nativePickerActive.value)
      throw StateError('native_picker_unavailable');
    _nativePickerActive.value = true;
    try {
      if (simulateNativePickerClearsDrop) {
        // 模拟原生 owner WM_ENABLE(FALSE) 清空配置，不另发焦点或几何变化。
        dropTargets.add(null);
        dropHandler = null;
      }
      return pickerGate == null ? pickerPath : await pickerGate;
    } finally {
      if (!_disposed) _nativePickerActive.value = false;
    }
  }

  @override
  bool get canOpenWeb => webAvailable;

  @override
  Future<void> openWeb() async {
    openWebCount++;
  }

  @override
  void setRequestCloseHandler(Future<bool> Function() handler) {
    closeRequestHandler = handler;
  }

  @override
  void setShutdownWarningHandler(Future<void> Function() handler) {
    shutdownWarningHandler = handler;
  }

  Future<void> Function()? shutdownWarningHandler;

  @override
  Future<void> requestShutdown() async {
    shutdownCount++;
    if (simulateShutdownWarning) await shutdownWarningHandler?.call();
    await shutdownGate;
    if (shutdownError != null) throw shutdownError!;
    shutdownRequested = true;
  }

  @override
  Future<void> dispose() async {
    if (_disposed) return;
    _disposed = true;
    _windowState.dispose();
    _nativePickerActive.dispose();
  }

  @override
  Widget buildVideoPreview(Uri contentUri) => _TestVideoPreview(
    key: ValueKey(contentUri),
    platform: this,
    uri: contentUri,
  );
}

class _TestVideoPreview extends StatefulWidget {
  const _TestVideoPreview({
    required this.platform,
    required this.uri,
    super.key,
  });
  final TestPlatformAdapter platform;
  final Uri uri;
  @override
  State<_TestVideoPreview> createState() => _TestVideoPreviewState();
}

class _TestVideoPreviewState extends State<_TestVideoPreview> {
  bool _leased = false;
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) return;
      _leased = true;
      final platform = widget.platform;
      platform.activePreviews++;
      if (platform.activePreviews > platform.maxActivePreviews)
        platform.maxActivePreviews = platform.activePreviews;
      platform.previewUris.add(widget.uri);
    });
  }

  @override
  void dispose() {
    if (_leased) widget.platform.activePreviews--;
    super.dispose();
  }

  @override
  Widget build(BuildContext context) =>
      const ColoredBox(color: Color(0xFF202020));
}

class TestApiService implements ApiService {
  TestApiService({
    Capabilities? capabilities,
    List<JobSummary>? jobs,
    AppPreferences? preferences,
    List<PresetRecord>? presets,
  }) : capabilities = capabilities ?? _unknownCapabilities(),
       jobs = List<JobSummary>.of(jobs ?? const <JobSummary>[]),
       preferences = preferences ?? _testPreferences(),
       presets = presets ?? const <PresetRecord>[];

  final Capabilities capabilities;
  final List<JobSummary> jobs;
  final List<PresetRecord> presets;
  AppPreferences preferences;
  final submittedRequests = <(String, Map<String, dynamic>)>[];
  final preferencePatches = <Map<String, dynamic>>[];
  int _nextId = 1;
  int listCalls = 0;
  int detailCalls = 0;
  int createCalls = 0;
  int cancelCalls = 0;
  Future<List<JobSummary>> Function()? listHandler;
  Future<JobSummary> Function(String)? detailHandler;
  Future<JobSummary> Function(String, Map<String, dynamic>)? createHandler;
  Future<JobSummary> Function(String)? cancelHandler;
  Future<MediaInfo> Function(String)? inspectHandler;
  Future<String?> Function(String)? pickHandler;
  final openedArtifacts = <String>[];

  @override
  Uri? get origin => Uri.parse('http://127.0.0.1:8765');

  @override
  Future<void> establishSession(String nonce) async {
    if (nonce != 'test-only-session') {
      throw const ApiException(
        code: 'test_session',
        message: 'Test session rejected.',
      );
    }
  }

  @override
  Future<Capabilities> getCapabilities() async => capabilities;

  @override
  Future<AppPreferences> getPreferences() async => preferences;

  @override
  Future<AppPreferences> putPreferences(AppPreferences value) async {
    preferences = value;
    return value;
  }

  @override
  Future<AppPreferences> patchPreferences(Map<String, dynamic> patch) async {
    preferencePatches.add(Map<String, dynamic>.from(patch));
    final merged = Map<String, dynamic>.from(preferences.toJson());
    for (final entry in patch.entries) {
      if (entry.key == 'tool_paths' && entry.value is Map) {
        final existing = Map<String, dynamic>.from(
          merged['tool_paths'] as Map? ?? const <String, dynamic>{},
        );
        existing.addAll(Map<String, dynamic>.from(entry.value as Map));
        merged['tool_paths'] = existing;
      } else {
        merged[entry.key] = entry.value;
      }
    }
    preferences = AppPreferences.fromJson(merged);
    return preferences;
  }

  @override
  Future<List<JobSummary>> getJobs() async {
    listCalls++;
    return listHandler == null
        ? List<JobSummary>.of(jobs)
        : await listHandler!();
  }

  @override
  Future<JobSummary> getJob(String id) async {
    detailCalls++;
    return detailHandler == null
        ? jobs.firstWhere((job) => job.id == id)
        : await detailHandler!(id);
  }

  @override
  Future<JobSummary> createJob(
    String kind,
    Map<String, dynamic> request,
  ) async {
    createCalls++;
    submittedRequests.add((kind, Map<String, dynamic>.from(request)));
    if (createHandler != null) return createHandler!(kind, request);
    final job = JobSummary.fromJson(<String, dynamic>{
      'id': 'test-job-${_nextId++}',
      'kind': kind,
      'state': 'queued',
      'stage': 'queued',
      'progress': null,
      'message': 'Test-only job created by the fake API.',
      'artifacts': <dynamic>[],
      'warnings': <dynamic>[],
    });
    jobs.insert(0, job);
    return job;
  }

  @override
  Future<JobSummary> cancelJob(String id) async {
    cancelCalls++;
    if (cancelHandler != null) return cancelHandler!(id);
    final old = jobs.firstWhere((job) => job.id == id);
    final cancelled = JobSummary(
      id: old.id,
      kind: old.kind,
      state: 'cancelled',
      stage: old.stage,
      progress: old.progress,
      message: 'Test-only cancellation.',
      createdAt: old.createdAt,
      updatedAt: old.updatedAt,
      artifacts: old.artifacts,
      warnings: old.warnings,
    );
    jobs[jobs.indexWhere((job) => job.id == id)] = cancelled;
    return cancelled;
  }

  @override
  Future<MediaInfo> inspectMedia(String path) async => inspectHandler != null
      ? await inspectHandler!(path)
      : MediaInfo(
          path: path,
          name: 'test-only media',
          width: 1920,
          height: 1080,
          fps: 30,
          frames: 300,
          duration: 10,
          videoCodec: 'h264',
          audioCodec: 'aac',
        );

  @override
  Future<String?> pickMedia(String kind) async =>
      pickHandler == null ? null : await pickHandler!(kind);

  @override
  Future<List<PresetRecord>> discoverPresets(String experimentRoot) async =>
      presets;

  @override
  Future<void> openArtifact(String id) async {
    openedArtifacts.add(id);
  }
}

AppPreferences _testPreferences() => const AppPreferences(
  themeMode: ThemeMode.system,
  seedColor: 4283215696,
  toolPaths: <String, String?>{
    'ffmpeg': r'C:\\APPS\\ffmpeg\\bin\\ffmpeg.exe',
    'ffprobe': r'C:\\APPS\\ffmpeg\\bin\\ffprobe.exe',
    'gyroflow': null,
    'catalyst': null,
  },
  toolPathsLoaded: true,
);

Capabilities _unknownCapabilities() => const Capabilities(
  ffmpeg: ToolCapability(detected: null),
  gyroflow: ToolCapability(detected: null),
  catalyst: ToolCapability(detected: null),
  presetCatalog: <PresetRecord>[],
  nativePicker: false,
);
