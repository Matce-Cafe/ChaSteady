import 'package:flutter/foundation.dart';
import 'package:flutter/widgets.dart';

import '../localization.dart';
import 'desktop_window.dart';

export 'desktop_window.dart';

abstract interface class MediaPlatformAdapter {
  /// Performs asynchronous platform bootstrap before API origin/session access.
  Future<void> initialize();

  bool get supportsLocalServer;
  Uri? get apiOrigin;

  /// Reads the one-time launcher fragment and removes it from the address bar.
  String? consumeSessionNonce();

  bool get supportsNativePicker;

  /// 任意共享原生选择器的明确边界；拖入宿主据此撤销旧几何并在结束后重配。
  ValueListenable<bool> get nativePickerActive;
  Future<String?> pickLocalPath(String kind);

  bool get canOpenWeb;
  Future<void> openWeb();

  /// True only for an adapter that owns a native desktop window, not Web on a
  /// desktop OS. Layout must not infer this from file-picker availability.
  bool get isNativeDesktop;

  /// Owned-worker shutdown remains available even if custom chrome fails.
  bool get managedShutdown;

  ValueListenable<DesktopWindowState> get desktopWindowState;

  /// Null restores the stock frame; non-null enables measured custom chrome.
  Future<DesktopWindowState> configureWindowChrome(
    DesktopWindowGeometry? geometry,
  );
  Future<void> minimizeWindow();
  Future<void> toggleMaximizeWindow();
  Future<void> startWindowDrag();
  Future<void> setAlwaysOnTop(bool value);

  /// Called for native WM_CLOSE, the caption close button and Settings > Exit.
  void setRequestCloseHandler(Future<bool> Function() handler);
  void setShutdownWarningHandler(Future<void> Function() handler);

  /// Stops the owned local supervisor after the user confirms closing.
  Future<void> requestShutdown();

  /// Releases platform event/player resources without changing user state.
  Future<void> dispose();

  Widget buildVideoPreview(Uri contentUri);

  /// 只配置当前可见原片导入区；空值立即撤销订阅和原生几何。
  bool get supportsNativeMediaDrop;
  Future<void> configureMediaDrop(
    MediaDropTarget? target, {
    ValueChanged<String>? onDrop,
  });
}

const ValueListenable<bool> noNativePickerActivity = _NoNativePickerActivity();

class _NoNativePickerActivity implements ValueListenable<bool> {
  const _NoNativePickerActivity();
  @override
  bool get value => false;
  @override
  void addListener(VoidCallback listener) {}
  @override
  void removeListener(VoidCallback listener) {}
}

class MediaDropTarget {
  const MediaDropTarget({
    required this.targetId,
    required this.rect,
    required this.clientWidth,
  });
  final String targetId;
  final Rect rect;
  final double clientWidth;

  bool get isValid =>
      RegExp(r'^[A-Za-z0-9_-]{1,64}$').hasMatch(targetId) &&
      <double>[
        rect.left,
        rect.top,
        rect.right,
        rect.bottom,
        clientWidth,
      ].every((value) => value.isFinite) &&
      clientWidth > 0 &&
      rect.left >= 0 &&
      rect.top >= 0 &&
      !rect.isEmpty &&
      rect.right <= clientWidth;

  @override
  bool operator ==(Object other) =>
      other is MediaDropTarget &&
      other.targetId == targetId &&
      other.rect == rect &&
      other.clientWidth == clientWidth;
  @override
  int get hashCode => Object.hash(targetId, rect, clientWidth);
}

class UnsupportedVideoPreview extends StatelessWidget {
  const UnsupportedVideoPreview({super.key});

  @override
  Widget build(BuildContext context) => Center(
    child: Text(
      context.l10n.unsupportedBrowserPlayback,
      textAlign: TextAlign.center,
    ),
  );
}
