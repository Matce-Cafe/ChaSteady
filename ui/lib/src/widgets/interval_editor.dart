import 'package:flutter/material.dart';

import '../localization.dart';
import '../models.dart';

class IntervalInput {
  IntervalInput({String start = '', String end = ''})
    : startController = TextEditingController(text: start),
      endController = TextEditingController(text: end);

  final TextEditingController startController;
  final TextEditingController endController;

  (String, String) get value =>
      (startController.text.trim(), endController.text.trim());

  void dispose() {
    startController.dispose();
    endController.dispose();
  }
}

class ManualIntervalEditor extends StatelessWidget {
  const ManualIntervalEditor({
    required this.entries,
    required this.onChanged,
    required this.onAdd,
    required this.onRemove,
    required this.validation,
    required this.showValidation,
    required this.onInsertKnownRanges,
    this.enabled = true,
    super.key,
  });

  final List<IntervalInput> entries;
  final VoidCallback onChanged;
  final VoidCallback onAdd;
  final ValueChanged<int> onRemove;
  final IntervalValidation validation;
  final bool showValidation;
  final VoidCallback onInsertKnownRanges;
  final bool enabled;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    final validationMessage = intervalValidationMessage(
      context.l10n,
      validation,
    );
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: <Widget>[
        Text(context.l10n.intervalsManualOnly),
        const SizedBox(height: 12),
        if (entries.isEmpty) Text(context.l10n.noReferenceIntervals),
        for (var index = 0; index < entries.length; index++) ...<Widget>[
          _IntervalRow(
            index: index,
            entry: entries[index],
            onChanged: onChanged,
            onRemove: () => onRemove(index),
            enabled: enabled,
          ),
          if (index != entries.length - 1) const SizedBox(height: 10),
        ],
        if (showValidation && validationMessage != null) ...<Widget>[
          const SizedBox(height: 10),
          Semantics(
            liveRegion: true,
            child: Text(
              validationMessage,
              style: TextStyle(color: colors.error),
            ),
          ),
        ],
        const SizedBox(height: 12),
        Wrap(
          spacing: 8,
          runSpacing: 8,
          children: <Widget>[
            OutlinedButton.icon(
              onPressed: enabled ? onAdd : null,
              icon: const Icon(Icons.add),
              label: Text(context.l10n.addRange),
            ),
            TextButton.icon(
              onPressed: enabled ? onInsertKnownRanges : null,
              icon: const Icon(Icons.bookmark_outline),
              label: Text(context.l10n.insertLabRanges),
            ),
          ],
        ),
      ],
    );
  }
}

class _IntervalRow extends StatelessWidget {
  const _IntervalRow({
    required this.index,
    required this.entry,
    required this.onChanged,
    required this.onRemove,
    required this.enabled,
  });

  final int index;
  final IntervalInput entry;
  final VoidCallback onChanged;
  final VoidCallback onRemove;
  final bool enabled;

  @override
  Widget build(BuildContext context) {
    final l10n = context.l10n;
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: <Widget>[
        Expanded(
          child: TextField(
            controller: entry.startController,
            enabled: enabled,
            keyboardType: const TextInputType.numberWithOptions(decimal: true),
            textInputAction: TextInputAction.next,
            decoration: InputDecoration(
              labelText: l10n.intervalStartLabel(index + 1),
              hintText: l10n.intervalExample('153.0'),
              border: OutlineInputBorder(
                borderRadius: BorderRadius.circular(16),
              ),
            ),
            onChanged: (_) => onChanged(),
          ),
        ),
        const SizedBox(width: 10),
        Expanded(
          child: TextField(
            controller: entry.endController,
            enabled: enabled,
            keyboardType: const TextInputType.numberWithOptions(decimal: true),
            textInputAction: TextInputAction.next,
            decoration: InputDecoration(
              labelText: l10n.intervalEndLabel(index + 1),
              hintText: l10n.intervalExample('156.0'),
              border: OutlineInputBorder(
                borderRadius: BorderRadius.circular(16),
              ),
            ),
            onChanged: (_) => onChanged(),
          ),
        ),
        const SizedBox(width: 4),
        IconButton(
          tooltip: l10n.removeInterval(index + 1),
          onPressed: onRemove,
          icon: const Icon(Icons.close),
        ),
      ],
    );
  }
}
