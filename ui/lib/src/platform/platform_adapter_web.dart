// ignore: deprecated_member_use
import 'dart:html' as html;
import 'dart:ui_web' as ui_web;

import 'package:flutter/foundation.dart';
import 'package:flutter/widgets.dart';

import '../localization.dart';
import 'media_platform.dart';

MediaPlatformAdapter createPlatformAdapter() => _WebPlatformAdapter();

class _WebPlatformAdapter implements MediaPlatformAdapter {
  @override
  Future<void> initialize() async {}

  @override
  bool get supportsNativePicker => false;

  @override
  Future<String?> pickLocalPath(String kind) async => null;

  @override
  bool get canOpenWeb => false;

  @override
  Future<void> openWeb() async {}

  @override
  void setRequestCloseHandler(Future<bool> Function() handler) {}

  @override
  void setShutdownWarningHandler(Future<void> Function() handler) {}

  @override
  bool get isNativeDesktop => false;

  @override
  bool get managedShutdown => false;

  @override
  ValueListenable<DesktopWindowState> get desktopWindowState =>
      unsupportedDesktopWindow;

  @override
  Future<DesktopWindowState> configureWindowChrome(
    DesktopWindowGeometry? geometry,
  ) async => const DesktopWindowState();

  @override
  Future<void> minimizeWindow() async {}

  @override
  Future<void> toggleMaximizeWindow() async {}

  @override
  Future<void> startWindowDrag() async {}

  @override
  Future<void> setAlwaysOnTop(bool value) async {}

  @override
  Future<void> requestShutdown() async {}

  @override
  Future<void> dispose() async {}

  @override
  Uri? get apiOrigin {
    final parsed = Uri.tryParse(html.window.location.origin);
    if (parsed == null ||
        !parsed.hasAuthority ||
        parsed.host.isEmpty ||
        (parsed.scheme != 'http' && parsed.scheme != 'https')) {
      return null;
    }
    return parsed;
  }

  @override
  bool get supportsLocalServer => apiOrigin != null;

  @override
  String? consumeSessionNonce() {
    String? nonce;
    try {
      final fragment = Uri.base.fragment;
      if (fragment.isNotEmpty) {
        nonce = Uri.splitQueryString(fragment)['session'];
      }
    } on FormatException {
      nonce = null;
    } finally {
      final pathAndQuery =
          '${html.window.location.pathname}${html.window.location.search}';
      html.window.history.replaceState(null, '', pathAndQuery);
    }
    final trimmed = nonce?.trim();
    return trimmed == null || trimmed.isEmpty ? null : trimmed;
  }

  @override
  Widget buildVideoPreview(Uri contentUri) =>
      _LocalVideoElement(uri: contentUri);
}

class _LocalVideoElement extends StatefulWidget {
  const _LocalVideoElement({required this.uri});

  final Uri uri;

  @override
  State<_LocalVideoElement> createState() => _LocalVideoElementState();
}

class _LocalVideoElementState extends State<_LocalVideoElement> {
  static int _nextViewId = 0;

  late final String _viewType;
  late final html.VideoElement _video;

  @override
  void initState() {
    super.initState();
    _viewType = 'cha-steady-local-video-${_nextViewId++}';
    _video = html.VideoElement()
      ..controls = true
      ..autoplay = false
      ..muted = true
      ..preload = 'metadata'
      ..src = widget.uri.toString()
      ..setAttribute('playsinline', '');
    _video.style
      ..width = '100%'
      ..height = '100%'
      ..backgroundColor = '#111614'
      ..objectFit = 'contain';
    ui_web.platformViewRegistry.registerViewFactory(
      _viewType,
      (int viewId) => _video,
    );
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    _video.setAttribute('aria-label', context.l10n.localPreviewSemantics);
  }

  @override
  void didUpdateWidget(covariant _LocalVideoElement oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.uri != widget.uri) {
      _video.pause();
      _video.src = widget.uri.toString();
      _video.load();
    }
  }

  @override
  void dispose() {
    _video.pause();
    _video.removeAttribute('src');
    _video.load();
    _video.remove();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => HtmlElementView(viewType: _viewType);
}
