import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import 'api/api_service.dart';
import 'brand.dart';
import 'controller.dart';
import 'localization.dart';
import 'models.dart';
import 'platform/media_platform.dart';
import 'screens/jobs_screen.dart';
import 'screens/settings_screen.dart';
import 'screens/workbench_screen.dart';
import 'theme/app_theme.dart';
import 'widgets/common_widgets.dart';

class ChaSteadyApp extends StatefulWidget {
  const ChaSteadyApp({
    required this.api,
    required this.platform,
    required this.sessionNonce,
    super.key,
  });

  final ApiService api;
  final MediaPlatformAdapter platform;
  final String? sessionNonce;

  @override
  State<ChaSteadyApp> createState() => _ChaSteadyAppState();
}

class _ChaSteadyAppState extends State<ChaSteadyApp> {
  late final AppController _controller;

  @override
  void initState() {
    super.initState();
    _controller = AppController(
      api: widget.api,
      platform: widget.platform,
      sessionNonce: widget.sessionNonce,
    );
    _controller.initialize();
  }

  @override
  void dispose() {
    _controller.dispose();
    unawaited(widget.platform.dispose());
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => AnimatedBuilder(
    animation: _controller,
    builder: (context, _) {
      final seed = _controller.draftPreferences.seedColor;
      return MaterialApp(
        onGenerateTitle: (context) => context.l10n.appTitle,
        debugShowCheckedModeBanner: false,
        theme: buildAppTheme(seedColor: seed, brightness: Brightness.light),
        darkTheme: buildAppTheme(seedColor: seed, brightness: Brightness.dark),
        themeMode: _controller.draftPreferences.themeMode,
        locale: preferredLocale(_controller.draftPreferences.languageMode),
        localeResolutionCallback: (locale, supportedLocales) =>
            resolveSupportedLocale(locale),
        localizationsDelegates: AppLocalizations.localizationsDelegates,
        supportedLocales: AppLocalizations.supportedLocales,
        home: AppShell(controller: _controller, platform: widget.platform),
      );
    },
  );
}

class StartupFailureApp extends StatelessWidget {
  const StartupFailureApp({required this.error, super.key});

  final Object error;

  @override
  Widget build(BuildContext context) => MaterialApp(
    onGenerateTitle: (context) => context.l10n.appTitle,
    debugShowCheckedModeBanner: false,
    theme: buildAppTheme(
      seedColor: defaultSeedColorArgb,
      brightness: Brightness.light,
    ),
    darkTheme: buildAppTheme(
      seedColor: defaultSeedColorArgb,
      brightness: Brightness.dark,
    ),
    localeResolutionCallback: (locale, supportedLocales) =>
        resolveSupportedLocale(locale),
    localizationsDelegates: AppLocalizations.localizationsDelegates,
    supportedLocales: AppLocalizations.supportedLocales,
    home: Builder(
      builder: (context) {
        final l10n = context.l10n;
        return Scaffold(
          body: SafeArea(
            child: Center(
              child: ConstrainedBox(
                constraints: const BoxConstraints(maxWidth: 720),
                child: Padding(
                  padding: const EdgeInsets.all(24),
                  child: SectionCard(
                    title: l10n.startupFailedTitle,
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: <Widget>[
                        Text(l10n.startupFailedBody),
                        const SizedBox(height: 12),
                        Text(l10n.startupFailureDetails(error.toString())),
                      ],
                    ),
                  ),
                ),
              ),
            ),
          ),
        );
      },
    ),
  );
}

class AppShell extends StatefulWidget {
  const AppShell({required this.controller, required this.platform, super.key});

  final AppController controller;
  final MediaPlatformAdapter platform;

  @override
  State<AppShell> createState() => _AppShellState();
}

class _AppShellState extends State<AppShell> {
  int _selectedIndex = 0;
  bool _closing = false;

  @override
  void initState() {
    super.initState();
    widget.platform.setRequestCloseHandler(_requestClose);
    widget.platform.setShutdownWarningHandler(_showShutdownWarning);
  }

  @override
  void dispose() {
    widget.platform.setRequestCloseHandler(() async => false);
    widget.platform.setShutdownWarningHandler(() async {});
    super.dispose();
  }

  void _select(int index) {
    if (_closing || index < 0 || index > 2) return;
    setState(() => _selectedIndex = index);
  }

  Future<void> _openWeb() async {
    if (_closing) return;
    try {
      await widget.platform.openWeb();
    } catch (error) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(localizedError(context.l10n, error))),
      );
    }
  }

  Future<void> _showShutdownWarning() async {
    if (!mounted) return;
    final l10n = context.l10n;
    await showDialog<void>(
      context: context,
      barrierDismissible: false,
      builder: (dialogContext) => AlertDialog(
        title: Text(l10n.forcedShutdownTitle),
        content: SingleChildScrollView(child: Text(l10n.forcedShutdownMessage)),
        actions: <Widget>[
          FilledButton(
            onPressed: () => Navigator.of(dialogContext).pop(),
            child: Text(l10n.acknowledgeForcedShutdown),
          ),
        ],
      ),
    );
  }

  Future<void> _chooseLanguage(AppLanguageMode mode) async {
    await widget.controller.saveLanguageMode(mode);
  }

  void _showAbout() {
    final l10n = context.l10n;
    showAboutDialog(
      context: context,
      applicationName: l10n.appTitle,
      applicationIcon: Icon(
        Icons.videocam_outlined,
        color: Theme.of(context).colorScheme.primary,
      ),
      children: <Widget>[Text(l10n.helpAboutBody)],
    );
  }

  Future<void> _showQualityLimits() async {
    final l10n = context.l10n;
    await showDialog<void>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: Text(l10n.helpQualityTitle),
        content: SingleChildScrollView(child: Text(l10n.helpQualityBody)),
        actions: <Widget>[
          TextButton(
            onPressed: () => Navigator.of(dialogContext).pop(),
            child: Text(l10n.cancelAction),
          ),
        ],
      ),
    );
  }

  Future<bool> _requestClose() async {
    if (!mounted || _closing) return false;
    final l10n = context.l10n;
    final activeJobs =
        widget.controller.jobs?.where((job) => job.isActive).length ?? 0;
    final accepted = await showDialog<bool>(
      context: context,
      barrierDismissible: false,
      builder: (dialogContext) => AlertDialog(
        title: Text(l10n.closeConfirmTitle),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: <Widget>[
            if (activeJobs > 0) ...<Widget>[
              Text(l10n.closeActiveJobs(activeJobs)),
              const SizedBox(height: 10),
            ],
            if (widget.platform.supportsLocalServer) Text(l10n.closeWebWarning),
          ],
        ),
        actions: <Widget>[
          TextButton(
            onPressed: () => Navigator.of(dialogContext).pop(false),
            child: Text(l10n.cancelAction),
          ),
          FilledButton(
            onPressed: () => Navigator.of(dialogContext).pop(true),
            child: Text(l10n.closeConfirmAction),
          ),
        ],
      ),
    );
    if (accepted != true || !mounted) return false;
    setState(() => _closing = true);
    final messenger = ScaffoldMessenger.of(context);
    messenger.showSnackBar(
      SnackBar(
        duration: const Duration(days: 1),
        dismissDirection: DismissDirection.none,
        content: Row(
          children: <Widget>[
            const SizedBox.square(
              dimension: 18,
              child: CircularProgressIndicator(strokeWidth: 2),
            ),
            const SizedBox(width: 12),
            Expanded(child: Text(context.l10n.stoppingProcessing)),
          ],
        ),
      ),
    );
    try {
      await widget.platform.requestShutdown();
      return true;
    } catch (error) {
      if (mounted) {
        messenger.hideCurrentSnackBar();
        setState(() => _closing = false);
        messenger.showSnackBar(
          SnackBar(content: Text(localizedError(context.l10n, error))),
        );
      }
      return false;
    }
  }

  Widget _menuBar(BuildContext context) {
    final l10n = context.l10n;
    return MenuBar(
      children: <Widget>[
        SubmenuButton(
          menuChildren: <Widget>[
            if (widget.platform.canOpenWeb)
              MenuItemButton(
                onPressed: _closing ? null : _openWeb,
                leadingIcon: const Icon(Icons.open_in_browser_outlined),
                child: Text(l10n.menuOpenWeb),
              ),
            if (widget.platform.supportsNativePicker)
              MenuItemButton(
                onPressed: _closing ? null : () => unawaited(_requestClose()),
                leadingIcon: const Icon(Icons.close),
                child: Text(l10n.closeConfirmAction),
              ),
            if (!widget.platform.canOpenWeb &&
                !widget.platform.supportsNativePicker)
              MenuItemButton(
                onPressed: null,
                child: Text(l10n.desktopActionsUnavailable),
              ),
          ],
          child: Text(l10n.menuFile),
        ),
        SubmenuButton(
          menuChildren: <Widget>[
            MenuItemButton(
              onPressed: () => _select(0),
              child: Text(l10n.navWorkbench),
            ),
            MenuItemButton(
              onPressed: () => _select(1),
              child: Text(l10n.navJobs),
            ),
            MenuItemButton(
              onPressed: () => _select(2),
              child: Text(l10n.navSettings),
            ),
            SubmenuButton(
              menuChildren: <Widget>[
                MenuItemButton(
                  onPressed: () => _chooseLanguage(AppLanguageMode.system),
                  child: Text(l10n.languageSystem),
                ),
                MenuItemButton(
                  onPressed: () => _chooseLanguage(AppLanguageMode.zh),
                  child: Text(l10n.languageZh),
                ),
                MenuItemButton(
                  onPressed: () => _chooseLanguage(AppLanguageMode.en),
                  child: Text(l10n.languageEn),
                ),
              ],
              child: Text(l10n.menuLanguage),
            ),
          ],
          child: Text(l10n.menuView),
        ),
        SubmenuButton(
          menuChildren: <Widget>[
            MenuItemButton(onPressed: _showAbout, child: Text(l10n.helpAbout)),
            MenuItemButton(
              onPressed: _showQualityLimits,
              child: Text(l10n.helpQualityTitle),
            ),
          ],
          child: Text(l10n.menuHelp),
        ),
      ],
    );
  }

  @override
  Widget build(BuildContext context) => LayoutBuilder(
    builder: (context, constraints) {
      final compact = constraints.maxWidth < 800;
      final extendedRail = constraints.maxWidth >= 1100;
      final pages = <Widget>[
        WorkbenchScreen(
          controller: widget.controller,
          platform: widget.platform,
        ),
        JobsScreen(controller: widget.controller, platform: widget.platform),
        SettingsScreen(
          controller: widget.controller,
          platform: widget.platform,
        ),
      ];
      return CallbackShortcuts(
        bindings: <ShortcutActivator, VoidCallback>{
          const SingleActivator(LogicalKeyboardKey.digit1, control: true): () =>
              _select(0),
          const SingleActivator(LogicalKeyboardKey.digit2, control: true): () =>
              _select(1),
          const SingleActivator(LogicalKeyboardKey.digit3, control: true): () =>
              _select(2),
        },
        child: FocusTraversalGroup(
          child: PopScope<Object?>(
            canPop: !widget.platform.supportsNativePicker,
            onPopInvokedWithResult: (didPop, result) {
              if (!didPop && widget.platform.supportsNativePicker) {
                unawaited(_requestClose());
              }
            },
            child: AbsorbPointer(
              absorbing: _closing,
              child: Scaffold(
                body: Column(
                  children: <Widget>[
                    _menuBar(context),
                    Expanded(
                      child: SafeArea(
                        top: false,
                        child: Row(
                          children: <Widget>[
                            if (!compact)
                              NavigationRail(
                                selectedIndex: _selectedIndex,
                                extended: extendedRail,
                                minWidth: 80,
                                minExtendedWidth: 220,
                                onDestinationSelected: _select,
                                destinations: <NavigationRailDestination>[
                                  NavigationRailDestination(
                                    icon: const Icon(
                                      Icons.video_library_outlined,
                                    ),
                                    selectedIcon: const Icon(
                                      Icons.video_library,
                                    ),
                                    label: Text(context.l10n.navWorkbench),
                                  ),
                                  NavigationRailDestination(
                                    icon: const Icon(Icons.view_list_outlined),
                                    selectedIcon: const Icon(Icons.view_list),
                                    label: Text(context.l10n.navJobs),
                                  ),
                                  NavigationRailDestination(
                                    icon: const Icon(Icons.tune_outlined),
                                    selectedIcon: const Icon(Icons.tune),
                                    label: Text(context.l10n.navSettings),
                                  ),
                                ],
                              ),
                            if (!compact)
                              VerticalDivider(
                                width: 1,
                                color: Theme.of(
                                  context,
                                ).colorScheme.outlineVariant,
                              ),
                            Expanded(
                              child: IndexedStack(
                                index: _selectedIndex,
                                children: pages,
                              ),
                            ),
                          ],
                        ),
                      ),
                    ),
                  ],
                ),
                bottomNavigationBar: compact
                    ? NavigationBar(
                        selectedIndex: _selectedIndex,
                        onDestinationSelected: _select,
                        destinations: <NavigationDestination>[
                          NavigationDestination(
                            icon: const Icon(Icons.video_library_outlined),
                            selectedIcon: const Icon(Icons.video_library),
                            label: context.l10n.navWorkbench,
                          ),
                          NavigationDestination(
                            icon: const Icon(Icons.view_list_outlined),
                            selectedIcon: const Icon(Icons.view_list),
                            label: context.l10n.navJobs,
                          ),
                          NavigationDestination(
                            icon: const Icon(Icons.tune_outlined),
                            selectedIcon: const Icon(Icons.tune),
                            label: context.l10n.navSettings,
                          ),
                        ],
                      )
                    : null,
              ),
            ),
          ),
        ),
      );
    },
  );
}

class ConnectionStatusNotice extends StatelessWidget {
  const ConnectionStatusNotice({required this.controller, super.key});

  final AppController controller;

  @override
  Widget build(BuildContext context) {
    if (controller.connectionState == AppConnectionState.ready) {
      return const SizedBox.shrink();
    }
    final l10n = context.l10n;
    final starting = controller.connectionState == AppConnectionState.starting;
    final canRetry = controller.connectionState == AppConnectionState.error;
    final title = starting ? l10n.connectingService : l10n.serviceUnavailable;
    String message;
    switch (controller.connectionState) {
      case AppConnectionState.starting:
        message = l10n.establishingSession;
      case AppConnectionState.unsupported:
        message = l10n.sessionUnsupported;
      case AppConnectionState.needsSession:
        message = l10n.openFromLauncher;
      case AppConnectionState.error:
        message = controller.connectionError == null
            ? l10n.genericOperationFailed
            : localizedError(l10n, controller.connectionError!);
      case AppConnectionState.ready:
        return const SizedBox.shrink();
    }
    return SectionCard(
      title: title,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          if (starting)
            Row(
              children: <Widget>[
                const SizedBox.square(
                  dimension: 18,
                  child: CircularProgressIndicator(strokeWidth: 2),
                ),
                const SizedBox(width: 12),
                Expanded(child: Text(message)),
              ],
            )
          else
            NoticeBox(
              title: l10n.noSessionActive,
              message: message,
              isWarning: true,
              icon: Icons.link_off_outlined,
            ),
          if (canRetry) ...<Widget>[
            const SizedBox(height: 12),
            OutlinedButton.icon(
              onPressed: controller.retry,
              icon: const Icon(Icons.refresh),
              label: Text(l10n.retrySession),
            ),
          ],
        ],
      ),
    );
  }
}

class ScreenHeader extends StatelessWidget {
  const ScreenHeader({
    required this.title,
    required this.subtitle,
    this.trailing,
    super.key,
  });

  final String title;
  final String subtitle;
  final Widget? trailing;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    return Padding(
      padding: const EdgeInsets.fromLTRB(20, 18, 20, 14),
      child: Row(
        children: <Widget>[
          Container(
            width: 46,
            height: 46,
            decoration: ShapeDecoration(
              color: colors.primaryContainer,
              shape: continuousShape(radius: 16),
            ),
            child: Icon(
              Icons.videocam_outlined,
              color: colors.onPrimaryContainer,
            ),
          ),
          const SizedBox(width: 13),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: <Widget>[
                Text(
                  productName,
                  style: Theme.of(context).textTheme.labelLarge,
                ),
                Text(title, style: Theme.of(context).textTheme.titleLarge),
                Text(
                  subtitle,
                  style: Theme.of(context).textTheme.bodySmall?.copyWith(
                    color: colors.onSurfaceVariant,
                  ),
                ),
              ],
            ),
          ),
          if (trailing != null) trailing!,
        ],
      ),
    );
  }
}
