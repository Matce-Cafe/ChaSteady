import 'package:flutter/material.dart';

import '../controller.dart';
import '../localization.dart';
import '../models.dart';
import '../path_rules.dart';
import '../platform/media_platform.dart';
import 'common_widgets.dart';
import 'source_path_field.dart';

class ToolPathsEditor extends StatefulWidget {
  const ToolPathsEditor({
    required this.controller,
    required this.platform,
    super.key,
  });

  final AppController controller;
  final MediaPlatformAdapter platform;

  @override
  State<ToolPathsEditor> createState() => _ToolPathsEditorState();
}

class _ToolPathsEditorState extends State<ToolPathsEditor> {
  late final Map<String, TextEditingController> _fields =
      <String, TextEditingController>{
        for (final key in toolPathKeys) key: TextEditingController(),
      };
  bool _initializedFromService = false;
  bool _dirty = false;
  bool _wasSaved = false;
  final Set<String> _locallyEditedKeys = <String>{};

  @override
  void initState() {
    super.initState();
    final preferences = widget.controller.draftPreferences;
    if (preferences.hasCompleteToolPaths) {
      _syncFields(preferences.toolPaths);
      _initializedFromService = true;
      _wasSaved = _isSaved;
    }
  }

  @override
  void didUpdateWidget(covariant ToolPathsEditor oldWidget) {
    super.didUpdateWidget(oldWidget);
    final preferences = widget.controller.draftPreferences;
    if (preferences.hasCompleteToolPaths && !_initializedFromService) {
      _syncFields(preferences.toolPaths);
      _initializedFromService = true;
    } else if (_dirty && _isSaved && !_wasSaved) {
      _syncFields(preferences.toolPaths);
      _dirty = false;
    } else if (preferences.hasCompleteToolPaths) {
      for (final key in toolPathKeys) {
        if (!_locallyEditedKeys.contains(key)) {
          _fields[key]!.text = preferences.toolPaths[key] ?? '';
        }
      }
    }
    _wasSaved = _isSaved;
  }

  bool get _isSaved =>
      widget.controller.preferencesLoaded &&
      _sameToolPaths(
        widget.controller.preferences.toolPaths,
        widget.controller.draftPreferences.toolPaths,
      );

  bool get _editable =>
      widget.controller.isApiReady &&
      widget.controller.preferencesLoaded &&
      widget.controller.draftPreferences.hasCompleteToolPaths;

  void _syncFields(Map<String, String?> paths) {
    for (final key in toolPathKeys) {
      _fields[key]!.text = paths[key] ?? '';
    }
    _locallyEditedKeys.clear();
  }

  String _toolLabel(BuildContext context, String key) {
    final l10n = context.l10n;
    return switch (key) {
      'ffmpeg' => l10n.ffmpegExecutable,
      'ffprobe' => l10n.ffprobeExecutable,
      'gyroflow' => l10n.gyroflowCliExecutable,
      'catalyst' => l10n.catalystExecutable,
      _ => l10n.toolExecutableFallback,
    };
  }

  void _updatePath(String key, String value) {
    _dirty = true;
    _wasSaved = false;
    _locallyEditedKeys.add(key);
    final paths = Map<String, String?>.of(
      widget.controller.draftPreferences.toolPaths,
    );
    final trimmed = value.trim();
    paths[key] = trimmed.isEmpty ? null : trimmed;
    widget.controller.updatePreferenceDraft(
      widget.controller.draftPreferences.copyWith(
        toolPaths: Map<String, String?>.unmodifiable(paths),
        toolPathsLoaded: true,
      ),
    );
  }

  Future<void> _enterPath(String key) async {
    final path = await showLocalPathDialog(
      context,
      label: _toolLabel(context, key),
      initialPath: _fields[key]!.text,
      platform: widget.platform,
      kind: 'executable',
    );
    if (path == null) return;
    _fields[key]!.text = path;
    _updatePath(key, path);
  }

  bool _pathValuesValid(Map<String, String?> paths) =>
      toolPathKeys.every((key) {
        final path = paths[key];
        return path == null || path.trim().isEmpty || isLocalAbsolutePath(path);
      });

  @override
  void dispose() {
    for (final field in _fields.values) {
      field.dispose();
    }
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final l10n = context.l10n;
    final paths = widget.controller.draftPreferences.toolPaths;
    final complete = widget.controller.draftPreferences.hasCompleteToolPaths;
    final valid = complete && _pathValuesValid(paths);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: <Widget>[
        Text(l10n.toolPathsPersistedMessage),
        const SizedBox(height: 12),
        for (final key in toolPathKeys) ...<Widget>[
          TextField(
            controller: _fields[key],
            enabled: _editable,
            textInputAction: TextInputAction.next,
            decoration: InputDecoration(
              labelText: _toolLabel(context, key),
              helperText: l10n.absolutePathClearHelper,
              prefixIcon: const Icon(Icons.settings_outlined),
              suffixIcon: Row(
                mainAxisSize: MainAxisSize.min,
                children: <Widget>[
                  IconButton(
                    tooltip: l10n.typeToolPath(_toolLabel(context, key)),
                    onPressed: _editable ? () => _enterPath(key) : null,
                    icon: const Icon(Icons.edit_outlined),
                  ),
                  IconButton(
                    tooltip: l10n.clearToolPath(_toolLabel(context, key)),
                    onPressed: _editable && _fields[key]!.text.isNotEmpty
                        ? () {
                            _fields[key]!.clear();
                            _updatePath(key, '');
                          }
                        : null,
                    icon: const Icon(Icons.clear),
                  ),
                ],
              ),
              border: OutlineInputBorder(
                borderRadius: BorderRadius.circular(16),
              ),
            ),
            onChanged: (value) => _updatePath(key, value),
          ),
          if (key != toolPathKeys.last) const SizedBox(height: 12),
        ],
        if (!complete) ...<Widget>[
          const SizedBox(height: 12),
          NoticeBox(
            title: l10n.toolPathRecordUnavailable,
            message: l10n.toolPathRecordUnavailableMessage,
            isWarning: true,
          ),
        ] else if (!valid) ...<Widget>[
          const SizedBox(height: 12),
          NoticeBox(
            title: l10n.absoluteExecutablePaths,
            message: l10n.invalidToolPathMessage,
            isWarning: true,
          ),
        ] else if (!_isSaved) ...<Widget>[
          const SizedBox(height: 12),
          NoticeBox(
            title: l10n.unsavedToolPaths,
            message: l10n.unsavedToolPathsMessage,
            icon: Icons.save_outlined,
          ),
        ],
      ],
    );
  }
}

bool _sameToolPaths(Map<String, String?> a, Map<String, String?> b) =>
    toolPathKeys.every((key) => a[key] == b[key]);
