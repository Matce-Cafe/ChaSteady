import 'package:flutter/foundation.dart';
import 'package:flutter/widgets.dart';

import 'media_platform.dart';

MediaPlatformAdapter createPlatformAdapter() => const _StubPlatformAdapter();

class _StubPlatformAdapter implements MediaPlatformAdapter {
  const _StubPlatformAdapter();

  @override
  Future<void> initialize() async {}

  @override
  bool get supportsNativePicker => false;

  @override
  ValueListenable<bool> get nativePickerActive => noNativePickerActivity;

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
  Uri? get apiOrigin => null;

  @override
  bool get supportsLocalServer => false;

  @override
  String? consumeSessionNonce() => null;

  @override
  Widget buildVideoPreview(Uri contentUri) => const UnsupportedVideoPreview();

  @override
  bool get supportsNativeMediaDrop => false;
  @override
  Future<void> configureMediaDrop(
    MediaDropTarget? target, {
    ValueChanged<String>? onDrop,
  }) async {}
}
