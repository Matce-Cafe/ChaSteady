import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import 'api/api_service.dart';
import 'brand.dart';
import 'controller.dart';
import 'localization.dart';
import 'platform/media_platform.dart';
import 'screens/jobs_screen.dart';
import 'screens/settings_screen.dart';
import 'screens/workbench_screen.dart';
import 'theme/app_theme.dart';
import 'widgets/common_widgets.dart';
import 'widgets/desktop_sidebar.dart';
import 'widgets/desktop_window_chrome.dart';

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
  late final AppLifecycleListener _lifecycle;
  final _shellKey = GlobalKey<_AppShellState>();
  final _closing = ValueNotifier(false);

  Future<bool> _requestClose() =>
      _shellKey.currentState?._requestClose() ?? Future<bool>.value(false);

  void _selectPage(int index) {
    final shell = _shellKey.currentState;
    // Caption focus belongs outside the Navigator. Keep main-shell shortcuts
    // global without navigating behind a dialog or a pushed page.
    if (shell != null && ModalRoute.of(shell.context)?.isCurrent == true) {
      shell._select(index);
    }
  }

  @override
  void initState() {
    super.initState();
    _controller = AppController(
      api: widget.api,
      platform: widget.platform,
      sessionNonce: widget.sessionNonce,
    );
    _lifecycle = AppLifecycleListener(
      onStateChange: (state) =>
          _controller.setForeground(state == AppLifecycleState.resumed),
    );
    _controller.initialize();
  }

  @override
  void dispose() {
    _lifecycle.dispose();
    _controller.dispose();
    _closing.dispose();
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
        builder: (context, navigator) => CallbackShortcuts(
          bindings: <ShortcutActivator, VoidCallback>{
            const SingleActivator(
              LogicalKeyboardKey.digit1,
              control: true,
            ): () =>
                _selectPage(0),
            const SingleActivator(
              LogicalKeyboardKey.digit2,
              control: true,
            ): () =>
                _selectPage(1),
            const SingleActivator(
              LogicalKeyboardKey.digit3,
              control: true,
            ): () =>
                _selectPage(2),
          },
          child: ValueListenableBuilder<bool>(
            valueListenable: _closing,
            child: navigator,
            // Caption tooltips are outside the Navigator's overlay, so provide
            // one stable outer overlay without recreating chrome per route.
            builder: (context, closing, child) => Overlay.wrap(
              child: DesktopWindowChrome(
                platform: widget.platform,
                onClose: _requestClose,
                busy: closing,
                child: child ?? const SizedBox.shrink(),
              ),
            ),
          ),
        ),
        home: AppShell(
          key: _shellKey,
          controller: _controller,
          platform: widget.platform,
          onClosingChanged: (closing) => _closing.value = closing,
        ),
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
  const AppShell({
    required this.controller,
    required this.platform,
    this.onClosingChanged,
    super.key,
  });

  final AppController controller;
  final MediaPlatformAdapter platform;
  final ValueChanged<bool>? onClosingChanged;

  @override
  State<AppShell> createState() => _AppShellState();
}

class _AppShellState extends State<AppShell> {
  int _selectedIndex = 0;
  bool _sidebarLabelsPreferred = true;
  bool _closing = false;
  Future<bool>? _closeFuture;

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

  void _setClosing(bool value) {
    if (_closing == value) return;
    setState(() => _closing = value);
    widget.onClosingChanged?.call(value);
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

  void _showAbout() {
    final l10n = context.l10n;
    showAboutDialog(
      context: context,
      applicationName: l10n.appTitle,
      applicationVersion: productVersionLabel,
      applicationIcon: Icon(
        Icons.videocam_outlined,
        color: Theme.of(context).colorScheme.primary,
      ),
      children: <Widget>[
        Text(l10n.helpAboutBody),
        const SizedBox(height: 12),
        Text(
          l10n.workerComponentVersion(
            widget.controller.capabilities?.version ?? l10n.unknown,
          ),
        ),
      ],
    );
  }

  void _showLicenses() {
    showLicensePage(context: context, applicationName: context.l10n.appTitle);
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

  Future<bool> _requestClose() {
    final pending = _closeFuture;
    if (pending != null) return pending;
    if (!mounted || !widget.platform.managedShutdown) {
      return Future<bool>.value(false);
    }
    final future = _confirmAndShutdown().catchError((Object error) {
      if (mounted) {
        _setClosing(false);
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text(localizedError(context.l10n, error))),
        );
      }
      return false;
    });
    _closeFuture = future;
    unawaited(
      future.then((closed) {
        if (!closed && identical(_closeFuture, future)) _closeFuture = null;
      }),
    );
    return future;
  }

  Future<bool> _confirmAndShutdown() async {
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
    _setClosing(true);
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
        _setClosing(false);
        messenger.showSnackBar(
          SnackBar(content: Text(localizedError(context.l10n, error))),
        );
      }
      return false;
    }
  }

  @override
  Widget build(BuildContext context) => LayoutBuilder(
    builder: (context, constraints) {
      final bottomNavigation = constraints.maxWidth < 800;
      final expandedSidebar = _sidebarLabelsPreferred;
      final pages = <Widget>[
        WorkbenchScreen(
          controller: widget.controller,
          platform: widget.platform,
          active:
              _selectedIndex == 0 &&
              !_closing &&
              widget.controller.isForeground,
          dropActive: _selectedIndex == 0 && !_closing,
          onOpenJobs: () => _select(1),
        ),
        JobsScreen(
          controller: widget.controller,
          platform: widget.platform,
          active:
              _selectedIndex == 1 &&
              !_closing &&
              widget.controller.isForeground,
        ),
        SettingsScreen(
          controller: widget.controller,
          platform: widget.platform,
          onNavigate: _select,
          onOpenWeb: _openWeb,
          onClose: _requestClose,
          onAbout: _showAbout,
          onLicenses: _showLicenses,
          onQualityLimits: _showQualityLimits,
        ),
      ];
      return Focus(
        autofocus: true,
        child: FocusTraversalGroup(
          child: PopScope<Object?>(
            canPop: !widget.platform.managedShutdown,
            onPopInvokedWithResult: (didPop, result) {
              if (!didPop && widget.platform.managedShutdown) {
                unawaited(_requestClose());
              }
            },
            child: AbsorbPointer(
              absorbing: _closing,
              child: Scaffold(
                body: SafeArea(
                  child: Row(
                    children: <Widget>[
                      if (!bottomNavigation) ...<Widget>[
                        DesktopSidebar(
                          selectedIndex: _selectedIndex,
                          expanded: expandedSidebar,
                          labelsPreferred: _sidebarLabelsPreferred,
                          onSelected: _select,
                          onToggleLabels: () => setState(() {
                            _sidebarLabelsPreferred = !_sidebarLabelsPreferred;
                          }),
                        ),
                        VerticalDivider(
                          width: 1,
                          color: Theme.of(context).colorScheme.outlineVariant,
                        ),
                      ],
                      Expanded(
                        key: const ValueKey<String>('app-pages'),
                        child: IndexedStack(
                          index: _selectedIndex,
                          children: pages,
                        ),
                      ),
                    ],
                  ),
                ),
                bottomNavigationBar: bottomNavigation
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
