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
}
