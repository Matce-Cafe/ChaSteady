import 'dart:async';

import 'package:flutter/material.dart';

import '../controller.dart';
import '../localization.dart';
import '../path_rules.dart';
import '../platform/media_platform.dart';

class SourcePathField extends StatefulWidget {
  const SourcePathField({
    required this.label,
    required this.helper,
    required this.kind,
    required this.pathController,
    required this.appController,
    required this.platform,
    required this.onError,
    this.onChanged,
    this.enabled = true,
    this.dropTargetActive = false,
    this.dropTargetId,
    super.key,
  });

  final String label;
  final String helper;
  final String kind;
  final TextEditingController pathController;
  final AppController appController;
  final MediaPlatformAdapter platform;
  final ValueChanged<String> onError;
  final ValueChanged<String>? onChanged;
  final bool enabled;
  final bool dropTargetActive;
  final String? dropTargetId;

  @override
  State<SourcePathField> createState() => _SourcePathFieldState();
}

class _SourcePathFieldState extends State<SourcePathField>
    with WidgetsBindingObserver {
  final _fieldKey = GlobalKey();
  ScrollPosition? _scrollPosition;
  MediaDropTarget? _lastTarget;
  int _inputGeneration = 0;
  late String _lastInputText;
  int _dropEpoch = 0;
  bool _measuring = false;
  bool _choosing = false;
  bool _dropUnavailable = false;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    FocusManager.instance.addListener(_scheduleGeometry);
    _lastInputText = widget.pathController.text;
    widget.pathController.addListener(_inputEdited);
    widget.platform.nativePickerActive.addListener(_nativePickerChanged);
  }

  void _nativePickerChanged() {
    if (!mounted) return;
    // 其他字段的原生对话框同样会清空 owner 的 OLE 区域；两端均使旧缓存失效。
    _disableDrop();
    setState(() {});
    if (!widget.platform.nativePickerActive.value) _scheduleGeometry();
  }

  void _inputEdited() {
    final text = widget.pathController.text;
    if (text == _lastInputText) return;
    _lastInputText = text;
    ++_inputGeneration;
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    final position = Scrollable.maybeOf(context)?.position;
    if (_scrollPosition != position) {
      _scrollPosition?.removeListener(_scheduleGeometry);
      _scrollPosition = position;
      position?.addListener(_scheduleGeometry);
    }
    _scheduleGeometry();
  }

  @override
  void didUpdateWidget(covariant SourcePathField oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.platform != widget.platform) {
      oldWidget.platform.nativePickerActive.removeListener(
        _nativePickerChanged,
      );
      widget.platform.nativePickerActive.addListener(_nativePickerChanged);
      ++_inputGeneration;
      ++_dropEpoch;
      if (_lastTarget != null) {
        _lastTarget = null;
        unawaited(
          oldWidget.platform.configureMediaDrop(null).catchError((Object _) {}),
        );
      }
    }
    if (oldWidget.pathController != widget.pathController) {
      oldWidget.pathController.removeListener(_inputEdited);
      _lastInputText = widget.pathController.text;
      widget.pathController.addListener(_inputEdited);
      ++_inputGeneration;
    }
    if (!widget.enabled) ++_inputGeneration;
    // 拖入资格独立于文本代次；只读选择范围或普通失焦不会作废选择器结果。
    if (!widget.enabled ||
        (widget.dropTargetId != null && !widget.dropTargetActive)) {
      _disableDrop();
    }
    _scheduleGeometry();
  }

  @override
  void didChangeMetrics() {
    _disableDrop();
    _scheduleGeometry();
  }

  bool get _visibleForDrop {
    final state = WidgetsBinding.instance.lifecycleState;
    return state == null ||
        state == AppLifecycleState.resumed ||
        state == AppLifecycleState.inactive;
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    // 可见但失焦正是外部拖入的正常状态；隐藏、暂停和分离仍立即撤销。
    if (state == AppLifecycleState.resumed ||
        state == AppLifecycleState.inactive) {
      _scheduleGeometry();
    } else {
      _disableDrop();
    }
  }

  void _scheduleGeometry() {
    if (!mounted ||
        _measuring ||
        widget.dropTargetId == null ||
        !widget.platform.supportsNativeMediaDrop)
      return;
    _measuring = true;
    WidgetsBinding.instance.addPostFrameCallback((_) {
      _measuring = false;
      if (mounted) unawaited(_configureDrop());
    });
  }

  void _disableDrop() {
    ++_dropEpoch;
    if (_lastTarget == null) return;
    _lastTarget = null;
    unawaited(
      widget.platform.configureMediaDrop(null).catchError((Object _) {}),
    );
  }

  Future<void> _configureDrop() async {
    if (!widget.enabled ||
        _choosing ||
        widget.platform.nativePickerActive.value ||
        !widget.dropTargetActive ||
        !widget.appController.isApiReady ||
        !_visibleForDrop ||
        ModalRoute.of(context)?.isCurrent == false) {
      _disableDrop();
      return;
    }
    final box = _fieldKey.currentContext?.findRenderObject();
    if (box is! RenderBox || !box.attached || !box.hasSize) {
      _disableDrop();
      return;
    }
    final view = View.of(context);
    final clientSize = view.physicalSize / view.devicePixelRatio;
    var rect = (box.localToGlobal(Offset.zero) & box.size).intersect(
      Offset.zero & clientSize,
    );
    final scrollBox = Scrollable.maybeOf(context)?.context.findRenderObject();
    if (scrollBox is RenderBox && scrollBox.hasSize) {
      rect = rect.intersect(
        scrollBox.localToGlobal(Offset.zero) & scrollBox.size,
      );
    }
    if (rect.isEmpty) {
      _disableDrop();
      return;
    }
    final target = MediaDropTarget(
      targetId: widget.dropTargetId!,
      rect: rect,
      clientWidth: clientSize.width,
    );
    if (!target.isValid) {
      _disableDrop();
      return;
    }
    if (target == _lastTarget) return;
    final epoch = ++_dropEpoch;
    _lastTarget = target;
    try {
      await widget.platform.configureMediaDrop(
        target,
        onDrop: (path) {
          if (mounted &&
              epoch == _dropEpoch &&
              widget.enabled &&
              !_choosing &&
              !widget.platform.nativePickerActive.value &&
              widget.dropTargetActive &&
              widget.appController.isApiReady &&
              _visibleForDrop &&
              ModalRoute.of(context)?.isCurrent != false) {
            _accept(path);
          }
        },
      );
      if (mounted && epoch == _dropEpoch && _dropUnavailable)
        setState(() => _dropUnavailable = false);
    } catch (_) {
      if (mounted && epoch == _dropEpoch) {
        _lastTarget = null;
        if (!_dropUnavailable) setState(() => _dropUnavailable = true);
      }
    }
  }

  /// 手输、选择器和原生拖入共用失效通知；媒体真实性仍由 Worker 验收。
  void _accept(String value, {bool typed = false}) {
    if (!widget.enabled) return;
    ++_inputGeneration;
    if (!typed && !isLocalAbsolutePath(value)) {
      widget.onError(context.l10n.invalidSourcePathsMessage);
      return;
    }
    if (!typed) widget.pathController.text = value.trim();
    widget.onChanged?.call(typed ? value : value.trim());
  }

  Future<void> _choose() async {
    if (!widget.enabled ||
        _choosing ||
        widget.platform.nativePickerActive.value)
      return;
    final generation = _inputGeneration;
    setState(() => _choosing = true);
    _disableDrop();
    try {
      final String? path;
      if (widget.platform.supportsNativePicker) {
        path = await widget.platform.pickLocalPath(widget.kind);
      } else if (widget.appController.capabilities?.nativePicker == true &&
          widget.appController.isApiReady) {
        path = await widget.appController.pickMedia(widget.kind);
      } else {
        path = await showLocalPathDialog(
          context,
          label: widget.label,
          initialPath: widget.pathController.text,
        );
      }
      if (mounted &&
          widget.enabled &&
          generation == _inputGeneration &&
          path != null)
        _accept(path);
    } catch (error) {
      if (mounted && generation == _inputGeneration)
        widget.onError(localizedError(context.l10n, error));
    } finally {
      if (mounted) {
        setState(() => _choosing = false);
        _scheduleGeometry();
      }
    }
  }

  @override
  void dispose() {
    ++_inputGeneration;
    _disableDrop();
    widget.pathController.removeListener(_inputEdited);
    widget.platform.nativePickerActive.removeListener(_nativePickerChanged);
    _scrollPosition?.removeListener(_scheduleGeometry);
    FocusManager.instance.removeListener(_scheduleGeometry);
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final picker =
        widget.platform.supportsNativePicker ||
        widget.appController.capabilities?.nativePicker == true;
    return NotificationListener<SizeChangedLayoutNotification>(
      onNotification: (_) {
        _scheduleGeometry();
        return false;
      },
      child: SizeChangedLayoutNotifier(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: <Widget>[
            TextField(
              key: _fieldKey,
              controller: widget.pathController,
              enabled: widget.enabled,
              textInputAction: TextInputAction.next,
              decoration: InputDecoration(
                labelText: widget.label,
                helperText: widget.helper,
                helperMaxLines: 4,
                prefixIcon: const Icon(Icons.folder_open_outlined),
                suffixIcon: IconButton(
                  tooltip: picker
                      ? context.l10n.pickerChooseLocal(
                          _localizedKind(context, widget.kind),
                        )
                      : context.l10n.pickerEnterLocal,
                  onPressed:
                      widget.enabled &&
                          !_choosing &&
                          !widget.platform.nativePickerActive.value
                      ? _choose
                      : null,
                  icon: Icon(
                    picker ? Icons.folder_open_outlined : Icons.edit_outlined,
                  ),
                ),
                border: OutlineInputBorder(
                  borderRadius: BorderRadius.circular(16),
                ),
              ),
              onChanged: (value) => _accept(value, typed: true),
            ),
            if (widget.dropTargetId != null)
              Padding(
                padding: const EdgeInsets.only(top: 8),
                child: Text(
                  widget.platform.supportsNativeMediaDrop
                      ? (_dropUnavailable
                            ? context.l10n.nativeDropUnavailable
                            : context.l10n.dropSingleOriginalHint)
                      : context.l10n.browserLocalPathNotice,
                  style: Theme.of(context).textTheme.bodySmall,
                ),
              ),
          ],
        ),
      ),
    );
  }
}

String _localizedKind(BuildContext context, String kind) => switch (kind) {
  'video' => context.l10n.originalVideo,
  'project' => context.l10n.gyroflowTemplateLabel,
  'folder' => context.l10n.experimentFolder,
  'executable' => context.l10n.toolExecutableFallback,
  _ => kind,
};

Future<String?> showLocalPathDialog(
  BuildContext context, {
  required String label,
  String initialPath = '',
  MediaPlatformAdapter? platform,
  String kind = 'project',
}) async {
  if (platform?.supportsNativePicker == true) {
    return platform!.pickLocalPath(kind);
  }
  final pathController = TextEditingController(text: initialPath);
  try {
    return await showDialog<String>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        shape: ContinuousRectangleBorder(
          borderRadius: BorderRadius.circular(24),
        ),
        title: Text(context.l10n.pathDialogTitle(label)),
        content: SizedBox(
          width: 480,
          child: TextField(
            controller: pathController,
            autofocus: true,
            keyboardType: TextInputType.text,
            textInputAction: TextInputAction.done,
            onSubmitted: (value) =>
                Navigator.of(dialogContext).pop(value.trim()),
            decoration: InputDecoration(
              labelText: context.l10n.absoluteLocalPath,
              hintText: r'N:\folder\media.mp4',
              helperText: context.l10n.pathStaysLocal,
              border: OutlineInputBorder(
                borderRadius: BorderRadius.circular(16),
              ),
            ),
          ),
        ),
        actions: <Widget>[
          TextButton(
            onPressed: () => Navigator.of(dialogContext).pop(),
            child: Text(context.l10n.cancelAction),
          ),
          FilledButton(
            onPressed: () =>
                Navigator.of(dialogContext).pop(pathController.text.trim()),
            child: Text(context.l10n.usePath),
          ),
        ],
      ),
    );
  } finally {
    pathController.dispose();
  }
}
