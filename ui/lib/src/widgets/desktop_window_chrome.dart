import 'dart:async';

import 'package:flutter/material.dart';

import '../localization.dart';
import '../platform/media_platform.dart';

/// Original, lightweight caption. Win32 owns mouse caption/max-button hit tests;
/// Dart actions remain available to keyboard and accessibility users.
class DesktopWindowChrome extends StatefulWidget {
  const DesktopWindowChrome({
    required this.platform,
    required this.onClose,
    required this.child,
    this.busy = false,
    super.key,
  });

  final MediaPlatformAdapter platform;
  final Future<bool> Function() onClose;
  final Widget child;
  final bool busy;

  @override
  State<DesktopWindowChrome> createState() => _DesktopWindowChromeState();
}

class _DesktopWindowChromeState extends State<DesktopWindowChrome>
    with WidgetsBindingObserver {
  static const _captionHeight = 40.0;
  final _captionKey = GlobalKey();
  final _pinKey = GlobalKey();
  final _maximizeKey = GlobalKey();
  bool _measurementScheduled = false;
  bool _updatingGeometry = false;
  bool _failed = false;
  bool _configured = false;
  DesktopWindowGeometry? _pendingGeometry;
  DesktopWindowGeometry? _lastGeometry;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
  }

  @override
  void didChangeMetrics() => _scheduleMeasurement();

  void _scheduleMeasurement() {
    if (_measurementScheduled || _failed || !mounted) return;
    _measurementScheduled = true;
    WidgetsBinding.instance.addPostFrameCallback((_) {
      _measurementScheduled = false;
      if (!mounted || _failed) return;
      final caption = _captionKey.currentContext?.findRenderObject();
      final pin = _pinKey.currentContext?.findRenderObject();
      final maximize = _maximizeKey.currentContext?.findRenderObject();
      if (caption is! RenderBox ||
          pin is! RenderBox ||
          maximize is! RenderBox ||
          !caption.hasSize ||
          !pin.hasSize ||
          !maximize.hasSize) {
        return;
      }
      final geometry = DesktopWindowGeometry(
        titleBarHeight: caption
            .localToGlobal(Offset(0, caption.size.height))
            .dy,
        controlsLeft: pin.localToGlobal(Offset.zero).dx,
        clientWidth: MediaQuery.sizeOf(context).width,
        maximizeButton: maximize.localToGlobal(Offset.zero) & maximize.size,
      );
      if (!geometry.isValid ||
          (geometry == _lastGeometry && !_updatingGeometry)) {
        return;
      }
      _pendingGeometry = geometry;
      if (!_updatingGeometry) unawaited(_updateGeometry());
    });
  }

  Future<void> _updateGeometry() async {
    _updatingGeometry = true;
    try {
      while (mounted && !_failed && _pendingGeometry != null) {
        final geometry = _pendingGeometry!;
        _pendingGeometry = null;
        if (geometry == _lastGeometry) continue;
        _configured = true;
        final state = await widget.platform.configureWindowChrome(geometry);
        if (!mounted) return;
        if (!state.supported || !state.customFrameEnabled) {
          throw StateError('Native custom frame was not enabled');
        }
        _lastGeometry = geometry;
      }
    } catch (_) {
      // Stock chrome is the safe fallback. Do not retry on every build or let a
      // window-control failure interfere with managed worker shutdown.
      if (mounted) setState(() => _failed = true);
      await _restoreStockFrame();
    } finally {
      _updatingGeometry = false;
    }
  }

  Future<void> _restoreStockFrame() async {
    try {
      await widget.platform.configureWindowChrome(null);
    } catch (_) {
      // Best effort only; normal native close/managed shutdown remains intact.
    }
  }

  Future<void> _command(Future<void> Function() action) async {
    try {
      await action();
    } catch (error) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(localizedError(context.l10n, error))),
      );
    }
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    if (_configured) unawaited(_restoreStockFrame());
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    // An adapter, not Theme.platform, decides whether this is a real window.
    if (!widget.platform.isNativeDesktop) return widget.child;
    return ValueListenableBuilder<DesktopWindowState>(
      valueListenable: widget.platform.desktopWindowState,
      builder: (context, state, _) {
        final available = state.supported && !_failed;
        final visible = available && state.customFrameEnabled;
        return LayoutBuilder(
          builder: (context, constraints) {
            if (available) _scheduleMeasurement();
            return Stack(
              fit: StackFit.expand,
              children: <Widget>[
                Padding(
                  padding: EdgeInsets.only(top: visible ? _captionHeight : 0),
                  child: widget.child,
                ),
                if (available)
                  Positioned(
                    left: 0,
                    right: 0,
                    top: 0,
                    height: _captionHeight,
                    // Keep a full-size measurable probe until native accepts
                    // geometry, without showing a second title bar meanwhile.
                    child: IgnorePointer(
                      ignoring: !visible,
                      child: ExcludeSemantics(
                        excluding: !visible,
                        child: Opacity(
                          opacity: visible ? 1 : 0,
                          child: ExcludeFocus(
                            excluding: !visible,
                            child: _caption(context, state),
                          ),
                        ),
                      ),
                    ),
                  ),
              ],
            );
          },
        );
      },
    );
  }

  Widget _caption(BuildContext context, DesktopWindowState state) {
    final l10n = context.l10n;
    final colors = Theme.of(context).colorScheme;
    return Material(
      key: _captionKey,
      color: colors.surfaceContainerLow,
      child: Row(
        children: <Widget>[
          Expanded(
            child: Semantics(
              label: l10n.windowDrag,
              child: ExcludeSemantics(
                child: Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 14),
                  child: Row(
                    children: <Widget>[
                      Icon(
                        Icons.videocam_outlined,
                        size: 18,
                        color: colors.primary,
                      ),
                      const SizedBox(width: 9),
                      Expanded(
                        child: Text(
                          l10n.appTitle,
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: Theme.of(context).textTheme.labelLarge,
                        ),
                      ),
                    ],
                  ),
                ),
              ),
            ),
          ),
          _CaptionButton(
            key: _pinKey,
            label: state.alwaysOnTop ? l10n.windowUnpin : l10n.windowPin,
            icon: state.alwaysOnTop ? Icons.push_pin : Icons.push_pin_outlined,
            toggled: state.alwaysOnTop,
            onPressed: widget.busy
                ? null
                : () => unawaited(
                    _command(
                      () => widget.platform.setAlwaysOnTop(!state.alwaysOnTop),
                    ),
                  ),
          ),
          _CaptionButton(
            label: l10n.windowMinimize,
            icon: Icons.remove,
            onPressed: widget.busy
                ? null
                : () => unawaited(_command(widget.platform.minimizeWindow)),
          ),
          _CaptionButton(
            key: _maximizeKey,
            label: state.maximized ? l10n.windowRestore : l10n.windowMaximize,
            icon: state.maximized ? Icons.filter_none : Icons.crop_square,
            nativeHovered: state.maximizeButtonHovered,
            nativePressed: state.maximizeButtonPressed,
            onPressed: widget.busy
                ? null
                : () =>
                      unawaited(_command(widget.platform.toggleMaximizeWindow)),
          ),
          _CaptionButton(
            label: l10n.windowClose,
            icon: Icons.close,
            close: true,
            onPressed: widget.busy || !widget.platform.managedShutdown
                ? null
                : () => unawaited(widget.onClose()),
          ),
        ],
      ),
    );
  }
}

class _CaptionButton extends StatelessWidget {
  const _CaptionButton({
    required this.label,
    required this.icon,
    required this.onPressed,
    this.toggled,
    this.nativeHovered = false,
    this.nativePressed = false,
    this.close = false,
    super.key,
  });

  final String label;
  final IconData icon;
  final VoidCallback? onPressed;
  final bool? toggled;
  final bool nativeHovered;
  final bool nativePressed;
  final bool close;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    return Semantics(
      label: label,
      button: true,
      enabled: onPressed != null,
      toggled: toggled,
      onTap: onPressed,
      child: ExcludeSemantics(
        child: SizedBox(
          width: 46,
          height: 40,
          child: ColoredBox(
            color: nativePressed
                ? colors.onSurface.withValues(alpha: 0.16)
                : nativeHovered
                ? colors.onSurface.withValues(alpha: 0.08)
                : Colors.transparent,
            child: IconButton(
              tooltip: label,
              onPressed: onPressed,
              icon: Icon(icon, size: 18),
              style: ButtonStyle(
                padding: const WidgetStatePropertyAll(EdgeInsets.zero),
                shape: const WidgetStatePropertyAll(RoundedRectangleBorder()),
                overlayColor: close
                    ? WidgetStateProperty.resolveWith(
                        (states) =>
                            states.contains(WidgetState.hovered) ||
                                states.contains(WidgetState.pressed)
                            ? colors.errorContainer
                            : null,
                      )
                    : null,
              ),
            ),
          ),
        ),
      ),
    );
  }
}
