import 'dart:async';
import 'dart:io';

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../localization.dart';
import 'media_platform.dart';
import 'platform_adapter_stub.dart' as fallback;

MediaPlatformAdapter createPlatformAdapter() => Platform.isWindows
    ? _WindowsPlatformAdapter()
    : fallback.createPlatformAdapter();

class _WindowsPlatformAdapter implements MediaPlatformAdapter {
  static const _channel = MethodChannel('chasteady/native');
  final _states = <String, ValueNotifier<Map<String, dynamic>>>{};
  final _windowState = ValueNotifier(const DesktopWindowState());
  bool _bootstrapReady = false;
  bool _disposed = false;
  Uri? _origin;
  String? _bearer;
  bool _shuttingDown = false;
  Future<void>? _shutdownFuture;
  Future<bool> Function()? _requestClose;
  Future<void> Function()? _shutdownWarning;

  @override
  Future<void> initialize() async {
    _channel.setMethodCallHandler(_onNativeCall);
    final response = await _channel.invokeMapMethod<String, dynamic>(
      'bootstrap',
    );
    final originValue = response?['origin'];
    final origin = originValue is String ? Uri.tryParse(originValue) : null;
    final bearer = response?['bearer'];
    if (origin == null ||
        origin.scheme != 'http' ||
        origin.host != '127.0.0.1' ||
        !origin.hasPort ||
        origin.port <= 0 ||
        origin.port > 65535 ||
        origin.hasFragment ||
        origin.hasQuery ||
        origin.userInfo.isNotEmpty ||
        (origin.path.isNotEmpty && origin.path != '/') ||
        bearer is! String ||
        bearer.length < 32) {
      throw PlatformException(code: 'invalid_native_bootstrap');
    }
    _origin = origin;
    _bearer = bearer;
    _bootstrapReady = true;
    // Window controls are optional. A missing/failed capability query must not
    // turn a valid worker session into StartupFailureApp or disable normal exit.
    try {
      _publishWindowState(await _readWindowState('getWindowState'));
    } catch (_) {
      _publishWindowState(const DesktopWindowState());
    }
  }

  Future<DesktopWindowState> _readWindowState(
    String method, [
    Map<String, Object>? arguments,
  ]) async {
    final result = await _channel.invokeMapMethod<Object?, Object?>(
      method,
      arguments,
    );
    if (result == null) throw PlatformException(code: 'invalid_window_state');
    return DesktopWindowState.fromMap(result);
  }

  void _publishWindowState(DesktopWindowState state) {
    if (!_disposed) _windowState.value = state;
  }

  Future<dynamic> _onNativeCall(MethodCall call) async {
    if (call.method == 'windowStateChanged') {
      if (call.arguments is Map) {
        try {
          _publishWindowState(
            DesktopWindowState.fromMap(
              Map<Object?, Object?>.from(call.arguments as Map),
            ),
          );
        } on FormatException {
          // Ignore malformed window notifications, never treat them as media.
        }
      }
      return null;
    }
    if (call.method == 'requestClose') {
      final handler = _requestClose;
      if (handler != null) return handler();
      // No job UI has been created during bootstrap. Still shut down the owned
      // supervisor so a failed startup does not leave an uncloseable window.
      await requestShutdown();
      return true;
    }
    if (call.method == 'shutdownWarning') {
      await _shutdownWarning?.call();
      return null;
    }
    if (call.method == 'mediaEvent' && call.arguments is Map) {
      final state = Map<String, dynamic>.from(call.arguments as Map);
      final player = state['player_id'];
      if (player is String && _states.containsKey(player)) {
        _states[player]!.value = state;
      }
    }
    return null;
  }

  @override
  bool get supportsLocalServer => _origin != null && !_shuttingDown;
  @override
  Uri? get apiOrigin => _origin;
  @override
  String? consumeSessionNonce() {
    final value = _bearer;
    _bearer = null;
    return value;
  }

  @override
  bool get supportsNativePicker => supportsLocalServer;
  @override
  bool get canOpenWeb => supportsLocalServer;
  @override
  bool get isNativeDesktop => true;
  @override
  bool get managedShutdown => _bootstrapReady && !_shuttingDown;
  @override
  ValueListenable<DesktopWindowState> get desktopWindowState => _windowState;

  @override
  Future<DesktopWindowState> configureWindowChrome(
    DesktopWindowGeometry? geometry,
  ) async {
    if (!_bootstrapReady ||
        _disposed ||
        (geometry != null && !geometry.isValid)) {
      throw PlatformException(code: 'invalid_window_chrome');
    }
    final state = await _readWindowState(
      'configureWindowChrome',
      geometry?.toChannelArguments() ?? <String, Object>{'enabled': false},
    );
    _publishWindowState(state);
    return state;
  }

  Future<void> _windowCommand(
    String method, [
    Map<String, Object>? args,
  ]) async {
    if (!_windowState.value.supported || _shuttingDown || _disposed) {
      throw PlatformException(code: 'window_controls_unavailable');
    }
    await _channel.invokeMethod<void>(method, args);
  }

  @override
  Future<void> minimizeWindow() => _windowCommand('minimizeWindow');
  @override
  Future<void> toggleMaximizeWindow() => _windowCommand('toggleMaximizeWindow');
  @override
  Future<void> startWindowDrag() => _windowCommand('startWindowDrag');
  @override
  Future<void> setAlwaysOnTop(bool value) =>
      _windowCommand('setAlwaysOnTop', <String, Object>{'value': value});

  @override
  Future<String?> pickLocalPath(String kind) async {
    if (!const {'video', 'project', 'folder', 'executable'}.contains(kind)) {
      throw PlatformException(code: 'invalid_picker_kind');
    }
    return _channel.invokeMethod<String>('pickFile', {'kind': kind});
  }

  @override
  Future<void> openWeb() => _channel.invokeMethod<void>('openWeb');
  @override
  void setRequestCloseHandler(Future<bool> Function() handler) =>
      _requestClose = handler;
  @override
  void setShutdownWarningHandler(Future<void> Function() handler) =>
      _shutdownWarning = handler;
  @override
  Future<void> requestShutdown() => _shutdownFuture ??= _performShutdown();

  Future<void> _performShutdown() async {
    try {
      await _channel.invokeMethod<void>('requestShutdown');
      _shuttingDown = true;
    } catch (_) {
      _shutdownFuture = null;
      rethrow;
    }
  }

  @override
  Future<void> dispose() async {
    if (_disposed) return;
    _disposed = true;
    _requestClose = null;
    _shutdownWarning = null;
    for (final player in _states.keys.toList()) {
      await _release(player);
    }
    _channel.setMethodCallHandler(null);
    _windowState.dispose();
  }

  @override
  Widget buildVideoPreview(Uri contentUri) {
    final match = RegExp(
      r'^/api/artifacts/([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/content$',
    ).firstMatch(contentUri.path);
    if (_origin == null ||
        contentUri.scheme != 'http' ||
        contentUri.userInfo.isNotEmpty ||
        contentUri.origin != _origin!.origin ||
        contentUri.hasQuery ||
        contentUri.hasFragment ||
        match == null) {
      throw PlatformException(code: 'invalid_native_artifact');
    }
    return _NativeVideoPreview(adapter: this, artifactId: match.group(1)!);
  }

  Future<Map<String, dynamic>> _create(String artifactId) async {
    final result = await _channel.invokeMapMethod<String, dynamic>(
      'createPreview',
      {'artifact_id': artifactId},
    );
    if (result == null ||
        result['player_id'] is! String ||
        result['texture_id'] is! int ||
        (result['texture_id'] as int) < 0) {
      throw PlatformException(code: 'invalid_native_player');
    }
    final player = result['player_id'] as String;
    final initial = result['state'] is Map
        ? Map<String, dynamic>.from(result['state'] as Map)
        : <String, dynamic>{};
    _states[player] = ValueNotifier(initial);
    return result;
  }

  Future<void> _command(
    String method,
    String player, [
    Map<String, dynamic>? arguments,
  ]) =>
      _channel.invokeMethod<void>(method, {'player_id': player, ...?arguments});

  Future<void> _refresh(String player) async {
    final notifier = _states[player];
    if (notifier == null || _shuttingDown) return;
    final result = await _channel.invokeMapMethod<String, dynamic>(
      'playerState',
      {'player_id': player},
    );
    if (result != null && _states[player] == notifier) notifier.value = result;
  }

  Future<void> _release(String player) async {
    final notifier = _states.remove(player);
    if (notifier == null) return;
    notifier.dispose();
    if (!_shuttingDown) {
      try {
        await _channel.invokeMethod<void>('disposePreview', {
          'player_id': player,
        });
      } on PlatformException {
        // The owned supervisor may already be terminating; its teardown closes
        // all players and leases. Do not launch a new worker for disposal.
      }
    }
  }
}

class _NativeVideoPreview extends StatefulWidget {
  const _NativeVideoPreview({required this.adapter, required this.artifactId});
  final _WindowsPlatformAdapter adapter;
  final String artifactId;
  @override
  State<_NativeVideoPreview> createState() => _NativeVideoPreviewState();
}

class _NativeVideoPreviewState extends State<_NativeVideoPreview> {
  String? _player;
  int? _texture;
  double _aspect = 16 / 9;
  PlatformException? _error;
  Timer? _timer;
  bool _polling = false;
  int _generation = 0;

  @override
  void initState() {
    super.initState();
    unawaited(_initialize());
  }

  @override
  void didUpdateWidget(covariant _NativeVideoPreview oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.artifactId == widget.artifactId) return;
    _timer?.cancel();
    final previous = _player;
    _player = null;
    _texture = null;
    _error = null;
    _aspect = 16 / 9;
    if (previous != null) unawaited(oldWidget.adapter._release(previous));
    unawaited(_initialize());
  }

  Future<void> _initialize() async {
    final generation = ++_generation;
    try {
      final result = await widget.adapter._create(widget.artifactId);
      final player = result['player_id'] as String;
      if (!mounted || generation != _generation) {
        await widget.adapter._release(player);
        return;
      }
      final width = result['width'];
      final height = result['height'];
      setState(() {
        _player = player;
        _texture = result['texture_id'] as int;
        if (width is num && height is num && width > 0 && height > 0) {
          _aspect = width / height;
        }
      });
      _timer = Timer.periodic(
        const Duration(milliseconds: 250),
        (_) => _poll(),
      );
      await _poll();
    } on PlatformException catch (error) {
      if (mounted && generation == _generation) setState(() => _error = error);
    }
  }

  Future<void> _poll() async {
    final player = _player;
    if (_polling || player == null || !mounted) return;
    _polling = true;
    final generation = _generation;
    try {
      await widget.adapter._refresh(player);
    } on PlatformException catch (error) {
      if (mounted && generation == _generation) setState(() => _error = error);
    } finally {
      _polling = false;
    }
  }

  Future<void> _control(String method, [Map<String, dynamic>? args]) async {
    final player = _player;
    if (player == null) return;
    final generation = _generation;
    try {
      await widget.adapter._command(method, player, args);
      if (generation == _generation) await _poll();
    } on PlatformException catch (error) {
      if (mounted && generation == _generation) setState(() => _error = error);
    }
  }

  @override
  void dispose() {
    ++_generation;
    _timer?.cancel();
    final player = _player;
    if (player != null) unawaited(widget.adapter._release(player));
    super.dispose();
  }

  String _time(double seconds) {
    final whole = seconds.isFinite ? seconds.floor().clamp(0, 999999) : 0;
    return '${(whole ~/ 60).toString().padLeft(2, '0')}:${(whole % 60).toString().padLeft(2, '0')}';
  }

  @override
  Widget build(BuildContext context) {
    final strings = AppLocalizations.of(context);
    final notifier = _player == null ? null : widget.adapter._states[_player];
    if (notifier == null) {
      return Center(
        child: _error == null
            ? Text(strings.playerLoading)
            : Text(
                strings.playerError(localizedPlatformError(strings, _error!)),
              ),
      );
    }
    return ValueListenableBuilder<Map<String, dynamic>>(
      valueListenable: notifier,
      builder: (context, state, _) {
        double number(String key, double fallback) {
          final value = state[key];
          return value is num && value.isFinite ? value.toDouble() : fallback;
        }

        final duration = number(
          'duration_seconds',
          0,
        ).clamp(0.0, 999999.0).toDouble();
        final position = number(
          'position_seconds',
          0,
        ).clamp(0.0, duration).toDouble();
        final volume = number('volume', 1).clamp(0.0, 1.0).toDouble();
        final ready = state['ready'] == true;
        final canPlay = ready || state['can_play'] == true;
        final playing = state['playing'] == true;
        final muted = state['muted'] != false;
        final nativeError = state['error_code'];
        final error = _error != null
            ? localizedPlatformError(strings, _error!)
            : (nativeError is String && nativeError.isNotEmpty
                  ? localizedPlatformError(
                      strings,
                      PlatformException(code: nativeError),
                    )
                  : null);
        return Column(
          children: [
            Expanded(
              child: ColoredBox(
                color: Colors.black,
                child: Stack(
                  alignment: Alignment.center,
                  children: [
                    if (_texture != null)
                      Center(
                        child: AspectRatio(
                          aspectRatio: _aspect,
                          child: Texture(textureId: _texture!),
                        ),
                      ),
                    if (error != null)
                      Padding(
                        padding: const EdgeInsets.all(12),
                        child: Text(
                          strings.playerError(error),
                          style: const TextStyle(color: Colors.white),
                        ),
                      )
                    else if (!ready)
                      Text(
                        strings.playerLoading,
                        style: const TextStyle(color: Colors.white),
                      ),
                  ],
                ),
              ),
            ),
            LayoutBuilder(
              builder: (context, constraints) {
                final compact = constraints.maxWidth < 500;
                final playback = <Widget>[
                  IconButton(
                    tooltip: playing ? strings.playerPause : strings.playerPlay,
                    onPressed: canPlay && error == null
                        ? () => _control(playing ? 'pause' : 'play')
                        : null,
                    icon: Icon(playing ? Icons.pause : Icons.play_arrow),
                  ),
                  Expanded(
                    child: Semantics(
                      label: strings.playerSeek,
                      child: Slider(
                        value: position,
                        max: duration > 0 ? duration : 1,
                        onChanged: ready && duration > 0 && error == null
                            ? (value) =>
                                  _control('seek', {'position_seconds': value})
                            : null,
                      ),
                    ),
                  ),
                  Text('${_time(position)} / ${_time(duration)}'),
                ];
                final mute = IconButton(
                  tooltip: muted ? strings.playerUnmute : strings.playerMute,
                  onPressed: error == null
                      ? () => _control('muted', {'muted': !muted})
                      : null,
                  icon: Icon(muted ? Icons.volume_off : Icons.volume_up),
                );
                final volumeControl = Semantics(
                  label: strings.playerVolume,
                  child: Slider(
                    value: volume,
                    onChanged: error == null
                        ? (value) => _control('volume', {'volume': value})
                        : null,
                  ),
                );
                if (compact) {
                  return Column(
                    children: [
                      Row(children: playback),
                      Row(
                        children: [
                          mute,
                          Expanded(child: volumeControl),
                        ],
                      ),
                    ],
                  );
                }
                return Row(
                  children: [
                    ...playback,
                    mute,
                    SizedBox(width: 90, child: volumeControl),
                  ],
                );
              },
            ),
          ],
        );
      },
    );
  }
}
