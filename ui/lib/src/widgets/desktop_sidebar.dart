import 'package:flutter/material.dart';

import '../brand.dart';
import '../localization.dart';

/// Session-only label preference is owned by AppShell. A temporary compact
/// layout must never overwrite it. Settings and the toggle stay at the bottom.
class DesktopSidebar extends StatelessWidget {
  const DesktopSidebar({
    required this.selectedIndex,
    required this.expanded,
    required this.labelsPreferred,
    required this.onSelected,
    required this.onToggleLabels,
    super.key,
  });

  final int selectedIndex;
  final bool expanded;
  final bool labelsPreferred;
  final ValueChanged<int> onSelected;
  final VoidCallback onToggleLabels;

  @override
  Widget build(BuildContext context) {
    final l10n = context.l10n;
    final colors = Theme.of(context).colorScheme;
    final toggleLabel = labelsPreferred
        ? l10n.sidebarHideLabels
        : l10n.sidebarShowLabels;
    return SizedBox(
      width: expanded ? 220 : 72,
      child: Material(
        color: colors.surfaceContainerLow,
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 12),
          child: Column(
            children: <Widget>[
              SizedBox(
                height: 44,
                child: expanded
                    ? Align(
                        alignment: Alignment.centerLeft,
                        child: Padding(
                          padding: const EdgeInsets.only(left: 12),
                          child: Text(
                            productName,
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                            style: Theme.of(context).textTheme.titleSmall,
                          ),
                        ),
                      )
                    : Icon(Icons.videocam_outlined, color: colors.primary),
              ),
              const SizedBox(height: 12),
              _destination(
                context,
                index: 0,
                label: l10n.navWorkbench,
                icon: Icons.video_library_outlined,
                selectedIcon: Icons.video_library,
              ),
              const SizedBox(height: 6),
              _destination(
                context,
                index: 1,
                label: l10n.navJobs,
                icon: Icons.view_list_outlined,
                selectedIcon: Icons.view_list,
              ),
              const Spacer(),
              _destination(
                context,
                index: 2,
                label: l10n.navSettings,
                icon: Icons.tune_outlined,
                selectedIcon: Icons.tune,
              ),
              const SizedBox(height: 8),
              Divider(color: colors.outlineVariant, height: 16),
              _tile(
                context,
                key: const ValueKey<String>('sidebar-label-toggle'),
                label: toggleLabel,
                icon: labelsPreferred
                    ? Icons.keyboard_double_arrow_left
                    : Icons.keyboard_double_arrow_right,
                toggled: labelsPreferred,
                onTap: onToggleLabels,
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _destination(
    BuildContext context, {
    required int index,
    required String label,
    required IconData icon,
    required IconData selectedIcon,
  }) => _tile(
    context,
    key: ValueKey<String>('sidebar-destination-$index'),
    label: label,
    icon: selectedIndex == index ? selectedIcon : icon,
    selected: selectedIndex == index,
    onTap: () => onSelected(index),
  );

  Widget _tile(
    BuildContext context, {
    required Key key,
    required String label,
    required IconData icon,
    required VoidCallback onTap,
    bool? selected,
    bool? toggled,
  }) {
    final colors = Theme.of(context).colorScheme;
    final active = selected == true;
    return Semantics(
      key: key,
      label: label,
      button: true,
      selected: selected,
      toggled: toggled,
      onTap: onTap,
      child: ExcludeSemantics(
        child: Tooltip(
          message: label,
          child: Material(
            color: active ? colors.secondaryContainer : Colors.transparent,
            borderRadius: BorderRadius.circular(14),
            child: InkWell(
              borderRadius: BorderRadius.circular(14),
              onTap: onTap,
              child: ConstrainedBox(
                constraints: const BoxConstraints(minHeight: 48),
                child: Padding(
                  padding: const EdgeInsets.symmetric(
                    horizontal: 14,
                    vertical: 10,
                  ),
                  child: Row(
                    mainAxisAlignment: expanded
                        ? MainAxisAlignment.start
                        : MainAxisAlignment.center,
                    children: <Widget>[
                      Icon(
                        icon,
                        size: 24,
                        color: active
                            ? colors.onSecondaryContainer
                            : colors.onSurfaceVariant,
                      ),
                      if (expanded) ...<Widget>[
                        const SizedBox(width: 12),
                        Expanded(
                          child: Text(
                            label,
                            maxLines: 2,
                            overflow: TextOverflow.ellipsis,
                            style: Theme.of(context).textTheme.labelLarge
                                ?.copyWith(
                                  color: active
                                      ? colors.onSecondaryContainer
                                      : colors.onSurface,
                                ),
                          ),
                        ),
                      ],
                    ],
                  ),
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}
