import 'package:flutter/widgets.dart';

import '../localization.dart';

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

  /// Called for a native WM_CLOSE request and by the File > Close command.
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
