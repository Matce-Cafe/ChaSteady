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
