import 'package:flutter/material.dart';

import '../app.dart';
import '../brand.dart';
import '../controller.dart';
import '../localization.dart';
import '../models.dart';
import '../path_rules.dart';
import '../platform/media_platform.dart';
import '../widgets/common_widgets.dart';
import '../widgets/tool_paths_editor.dart';

const _seedColors = <(int, String)>[
  (defaultSeedColorArgb, 'brand'),
  (0xFF607D8B, 'blue'),
  (0xFF8C6958, 'clay'),
  (0xFF766B8A, 'violet'),
];

class SettingsScreen extends StatelessWidget {
  const SettingsScreen({
    required this.controller,
    required this.platform,
    required this.onNavigate,
    required this.onOpenWeb,
    required this.onClose,
    required this.onAbout,
    required this.onLicenses,
    required this.onQualityLimits,
    super.key,
  });

  final AppController controller;
  final MediaPlatformAdapter platform;
  final ValueChanged<int> onNavigate;
  final Future<void> Function() onOpenWeb;
  final Future<bool> Function() onClose;
  final VoidCallback onAbout;
  final VoidCallback onLicenses;
  final Future<void> Function() onQualityLimits;

  @override
  Widget build(BuildContext context) {
    final l10n = context.l10n;
    final draft = controller.draftPreferences;
    final canSave =
        controller.isApiReady &&
        controller.preferencesLoaded &&
        draft.hasCompleteToolPaths &&
        _toolPathsAreValid(draft.toolPaths) &&
        !_samePreferences(controller.preferences, draft);
    return Column(
      children: <Widget>[
        ScreenHeader(
          title: l10n.navSettings,
          subtitle: l10n.screenSettingsSubtitle,
        ),
        Expanded(
          child: ListView(
            key: const ValueKey<String>('settings-list'),
            padding: const EdgeInsets.fromLTRB(20, 0, 20, 24),
            children: <Widget>[
              ConnectionStatusNotice(controller: controller),
              if (controller.connectionState != AppConnectionState.ready)
                const SizedBox(height: 14),
              SectionCard(
                title: l10n.appearance,
                subtitle: l10n.preferencesLocalOnly,
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: <Widget>[
                    Text(
                      l10n.theme,
                      style: Theme.of(context).textTheme.titleSmall,
                    ),
                    const SizedBox(height: 10),
                    SegmentedButton<ThemeMode>(
                      segments: <ButtonSegment<ThemeMode>>[
                        ButtonSegment<ThemeMode>(
                          value: ThemeMode.system,
                          icon: const Icon(Icons.brightness_auto_outlined),
                          label: Text(l10n.themeSystem),
                        ),
                        ButtonSegment<ThemeMode>(
                          value: ThemeMode.light,
                          icon: const Icon(Icons.light_mode_outlined),
                          label: Text(l10n.themeLight),
                        ),
                        ButtonSegment<ThemeMode>(
                          value: ThemeMode.dark,
                          icon: const Icon(Icons.dark_mode_outlined),
                          label: Text(l10n.themeDark),
                        ),
                      ],
                      selected: <ThemeMode>{draft.themeMode},
                      onSelectionChanged: (selected) {
                        if (selected.isNotEmpty) {
                          controller.updatePreferenceDraft(
                            controller.draftPreferences.copyWith(
                              themeMode: selected.first,
                            ),
                          );
                        }
                      },
                    ),
                    const SizedBox(height: 18),
                    Text(
                      l10n.language,
                      style: Theme.of(context).textTheme.titleSmall,
                    ),
                    const SizedBox(height: 10),
                    Semantics(
                      label: l10n.language,
                      child: Wrap(
                        spacing: 8,
                        runSpacing: 8,
                        children: <Widget>[
                          for (final (mode, label)
                              in <(AppLanguageMode, String)>[
                                (AppLanguageMode.system, l10n.languageSystem),
                                (AppLanguageMode.zh, l10n.languageZh),
                                (AppLanguageMode.en, l10n.languageEn),
                              ])
                            ChoiceChip(
                              key: ValueKey<String>(
                                'settings-language-${mode.name}',
                              ),
                              selected: draft.languageMode == mode,
                              label: Text(label),
                              onSelected: (_) =>
                                  controller.saveLanguageMode(mode),
                            ),
                        ],
                      ),
                    ),
                    const SizedBox(height: 8),
                    Text(
                      l10n.languageSavesImmediately,
                      style: Theme.of(context).textTheme.bodySmall,
                    ),
                    const SizedBox(height: 18),
                    Text(
                      l10n.brandSeed,
                      style: Theme.of(context).textTheme.titleSmall,
                    ),
                    const SizedBox(height: 8),
                    Wrap(
                      spacing: 8,
                      runSpacing: 8,
                      children: <Widget>[
                        for (final (color, key) in _seedColors)
                          FilterChip(
                            selected: draft.seedColor == color,
                            avatar: CircleAvatar(
                              backgroundColor: Color(color),
                              radius: 9,
                            ),
                            label: Text(_seedLabel(l10n, key)),
                            onSelected: (_) => controller.updatePreferenceDraft(
                              controller.draftPreferences.copyWith(
                                seedColor: color,
                              ),
                            ),
                          ),
                      ],
                    ),
                    const SizedBox(height: 14),
                    NoticeBox(
                      title: l10n.systemAccentFallback,
                      message: l10n.systemAccentFallbackMessage,
                      icon: Icons.palette_outlined,
                    ),
                    if (controller.preferencesError != null) ...<Widget>[
                      const SizedBox(height: 12),
                      NoticeBox(
                        title: l10n.savedPreferencesUnavailable,
                        message: localizedError(
                          l10n,
                          controller.preferencesError!,
                        ),
                        isWarning: true,
                      ),
                    ],
                    if (controller.preferencesSaveError != null) ...<Widget>[
                      const SizedBox(height: 12),
                      NoticeBox(
                        title: l10n.preferencesNotSaved,
                        message: localizedError(
                          l10n,
                          controller.preferencesSaveError!,
                        ),
                        isWarning: true,
                      ),
                    ],
                    const SizedBox(height: 14),
                    Wrap(
                      spacing: 12,
                      runSpacing: 8,
                      crossAxisAlignment: WrapCrossAlignment.center,
                      children: <Widget>[
                        FilledButton.icon(
                          onPressed: canSave
                              ? controller.savePreferences
                              : null,
                          icon: const Icon(Icons.save_outlined),
                          label: Text(l10n.savePreferences),
                        ),
                        const SizedBox(width: 12),
                        if (controller.preferencesLoaded &&
                            _samePreferences(
                              controller.preferences,
                              controller.draftPreferences,
                            ))
                          Text(l10n.saved),
                        if (!controller.preferencesLoaded &&
                            controller.preferencesError == null)
                          Text(l10n.waitingPreferenceRecord),
                      ],
                    ),
                  ],
                ),
              ),
              const SizedBox(height: 16),
              SectionCard(
                title: l10n.settingsApplication,
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: <Widget>[
                    Text(
                      l10n.settingsNavigation,
                      style: Theme.of(context).textTheme.titleSmall,
                    ),
                    const SizedBox(height: 10),
                    Wrap(
                      spacing: 8,
                      runSpacing: 8,
                      children: <Widget>[
                        for (final (index, label, icon)
                            in <(int, String, IconData)>[
                              (
                                0,
                                l10n.navWorkbench,
                                Icons.video_library_outlined,
                              ),
                              (1, l10n.navJobs, Icons.view_list_outlined),
                              (2, l10n.navSettings, Icons.tune_outlined),
                            ])
                          OutlinedButton.icon(
                            key: ValueKey<String>('settings-page-$index'),
                            onPressed: () => onNavigate(index),
                            icon: Icon(icon),
                            label: Text(label),
                          ),
                      ],
                    ),
                    const SizedBox(height: 18),
                    if (platform.canOpenWeb)
                      ListTile(
                        key: const ValueKey<String>('settings-open-web'),
                        contentPadding: EdgeInsets.zero,
                        leading: const Icon(Icons.open_in_browser_outlined),
                        title: Text(l10n.menuOpenWeb),
                        onTap: onOpenWeb,
                      ),
                    if (platform.managedShutdown)
                      ListTile(
                        key: const ValueKey<String>('settings-exit'),
                        contentPadding: EdgeInsets.zero,
                        leading: const Icon(Icons.power_settings_new),
                        title: Text(l10n.closeConfirmAction),
                        onTap: onClose,
                      ),
                    if (!platform.canOpenWeb && !platform.managedShutdown)
                      Text(l10n.desktopActionsUnavailable),
                    const Divider(height: 24),
                    ListTile(
                      key: const ValueKey<String>('settings-about'),
                      contentPadding: EdgeInsets.zero,
                      leading: const Icon(Icons.info_outline),
                      title: Text(l10n.helpAbout),
                      onTap: onAbout,
                    ),
                    ListTile(
                      key: const ValueKey<String>('settings-licenses'),
                      contentPadding: EdgeInsets.zero,
                      leading: const Icon(Icons.description_outlined),
                      title: Text(l10n.settingsLicenses),
                      onTap: onLicenses,
                    ),
                    ListTile(
                      key: const ValueKey<String>('settings-quality'),
                      contentPadding: EdgeInsets.zero,
                      leading: const Icon(Icons.fact_check_outlined),
                      title: Text(l10n.helpQualityTitle),
                      onTap: onQualityLimits,
                    ),
                  ],
                ),
              ),
              const SizedBox(height: 16),
              SectionCard(
                title: l10n.executablePaths,
                subtitle: l10n.executablePathsSubtitle,
                child: ToolPathsEditor(
                  controller: controller,
                  platform: platform,
                ),
              ),
              const SizedBox(height: 16),
              CapabilitiesPanel(controller: controller),
              const SizedBox(height: 16),
              SectionCard(
                title: l10n.privacyScope,
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: <Widget>[
                    Text(l10n.mediaPathsLocal),
                    const SizedBox(height: 8),
                    Text(l10n.noCloudModels),
                    const SizedBox(height: 8),
                    Text(l10n.browserPreviewOwned),
                  ],
                ),
              ),
            ],
          ),
        ),
      ],
    );
  }
}

String _seedLabel(AppLocalizations l10n, String key) => switch (key) {
  'brand' => l10n.seedGreenGray,
  'blue' => l10n.seedMistBlue,
  'clay' => l10n.seedClay,
  'violet' => l10n.seedSoftViolet,
  _ => key,
};

bool _samePreferences(AppPreferences a, AppPreferences b) =>
    a.themeMode == b.themeMode &&
    a.seedColor == b.seedColor &&
    a.languageMode == b.languageMode &&
    a.hasCompleteToolPaths &&
    b.hasCompleteToolPaths &&
    _sameToolPaths(a.toolPaths, b.toolPaths);

bool _sameToolPaths(Map<String, String?> a, Map<String, String?> b) =>
    toolPathKeys.every((key) => a[key] == b[key]);

bool _toolPathsAreValid(Map<String, String?> paths) =>
    toolPathKeys.every((key) {
      final path = paths[key];
      return path == null || path.trim().isEmpty || isLocalAbsolutePath(path);
    });
