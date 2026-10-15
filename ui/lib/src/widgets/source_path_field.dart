import 'package:flutter/material.dart';

import '../controller.dart';
import '../localization.dart';
import '../platform/media_platform.dart';

class SourcePathField extends StatelessWidget {
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

  Future<void> _choose(BuildContext context) async {
    if (!enabled) return;
    if (platform.supportsNativePicker) {
      try {
        final path = await platform.pickLocalPath(kind);
        if (path != null) {
          pathController.text = path;
          onChanged?.call(path);
        }
      } catch (error) {
        onError(localizedError(context.l10n, error));
      }
      return;
    }
    if (appController.capabilities?.nativePicker == true &&
        appController.isApiReady) {
      try {
        final path = await appController.pickMedia(kind);
        if (path != null) {
          pathController.text = path;
          onChanged?.call(path);
        }
      } catch (error) {
        onError(localizedError(context.l10n, error));
      }
      return;
    }

    final path = await showLocalPathDialog(
      context,
      label: label,
      initialPath: pathController.text,
    );
    if (path != null) {
      pathController.text = path;
      onChanged?.call(path);
    }
  }

  @override
  Widget build(BuildContext context) => TextField(
    controller: pathController,
    enabled: enabled,
    textInputAction: TextInputAction.next,
    decoration: InputDecoration(
      labelText: label,
      helperText: helper,
      prefixIcon: const Icon(Icons.folder_open_outlined),
      suffixIcon: IconButton(
        tooltip: platform.supportsNativePicker ||
                appController.capabilities?.nativePicker == true
            ? context.l10n.pickerChooseLocal(_localizedKind(context, kind))
            : context.l10n.pickerEnterLocal,
        onPressed: enabled ? () => _choose(context) : null,
        icon: Icon(
          platform.supportsNativePicker ||
                  appController.capabilities?.nativePicker == true
              ? Icons.folder_open_outlined
              : Icons.edit_outlined,
        ),
      ),
      border: OutlineInputBorder(borderRadius: BorderRadius.circular(16)),
    ),
    onChanged: onChanged,
  );
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
