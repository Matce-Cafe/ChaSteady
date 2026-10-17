import 'package:flutter/animation.dart';
import 'package:flutter/foundation.dart';

/// Authoritative window state from the native owner of the Flutter client.
/// This capability is independent of the local worker and managed shutdown.
@immutable
class DesktopWindowState {
  const DesktopWindowState({
    this.supported = false,
    this.customFrameEnabled = false,
    this.maximized = false,
    this.alwaysOnTop = false,
    this.maximizeButtonHovered = false,
    this.maximizeButtonPressed = false,
  });

  factory DesktopWindowState.fromMap(Map<Object?, Object?> values) {
    bool flag(String name) {
      final value = values[name];
      if (value is! bool) throw FormatException('Invalid window state: $name');
      return value;
    }

    return DesktopWindowState(
      supported: flag('supported'),
      customFrameEnabled: flag('customFrameEnabled'),
      maximized: flag('maximized'),
      alwaysOnTop: flag('alwaysOnTop'),
      maximizeButtonHovered: flag('maximizeButtonHovered'),
      maximizeButtonPressed: flag('maximizeButtonPressed'),
    );
  }

  final bool supported;
  final bool customFrameEnabled;
  final bool maximized;
  final bool alwaysOnTop;
  final bool maximizeButtonHovered;
  final bool maximizeButtonPressed;

  @override
  bool operator ==(Object other) =>
      other is DesktopWindowState &&
      supported == other.supported &&
      customFrameEnabled == other.customFrameEnabled &&
      maximized == other.maximized &&
      alwaysOnTop == other.alwaysOnTop &&
      maximizeButtonHovered == other.maximizeButtonHovered &&
      maximizeButtonPressed == other.maximizeButtonPressed;

  @override
  int get hashCode => Object.hash(
    supported,
    customFrameEnabled,
    maximized,
    alwaysOnTop,
    maximizeButtonHovered,
    maximizeButtonPressed,
  );
}

/// Logical pixels relative to the Flutter client, measured after layout.
@immutable
class DesktopWindowGeometry {
  const DesktopWindowGeometry({
    required this.titleBarHeight,
    required this.controlsLeft,
    required this.clientWidth,
    required this.maximizeButton,
  });

  final double titleBarHeight;
  final double controlsLeft;
  final double clientWidth;
  final Rect maximizeButton;

  bool get isValid =>
      <double>[
        titleBarHeight,
        controlsLeft,
        clientWidth,
        maximizeButton.left,
        maximizeButton.top,
        maximizeButton.width,
        maximizeButton.height,
      ].every((value) => value.isFinite) &&
      titleBarHeight > 0 &&
      controlsLeft >= 0 &&
      controlsLeft < clientWidth &&
      maximizeButton.width > 0 &&
      maximizeButton.height > 0 &&
      maximizeButton.left >= controlsLeft &&
      maximizeButton.right <= clientWidth &&
      maximizeButton.top >= 0 &&
      maximizeButton.bottom <= titleBarHeight;

  Map<String, Object> toChannelArguments() => <String, Object>{
    'enabled': true,
    'titleBarHeight': titleBarHeight,
    'controlsLeft': controlsLeft,
    'clientWidth': clientWidth,
    'maximizeButton': <String, double>{
      'left': maximizeButton.left,
      'top': maximizeButton.top,
      'width': maximizeButton.width,
      'height': maximizeButton.height,
    },
  };

  @override
  bool operator ==(Object other) =>
      other is DesktopWindowGeometry &&
      titleBarHeight == other.titleBarHeight &&
      controlsLeft == other.controlsLeft &&
      clientWidth == other.clientWidth &&
      maximizeButton == other.maximizeButton;

  @override
  int get hashCode =>
      Object.hash(titleBarHeight, controlsLeft, clientWidth, maximizeButton);
}

/// Shared by adapters that never own an operating-system window (including Web
/// on Windows). It cannot accidentally acquire desktop controls from the theme.
const unsupportedDesktopWindow = AlwaysStoppedAnimation<DesktopWindowState>(
  DesktopWindowState(),
);
