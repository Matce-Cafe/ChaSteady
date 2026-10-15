import 'package:cha_stabilizer_ui/src/theme/app_theme.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('light and dark themes provide the bundled CJK font fallback', () {
    for (final brightness in <Brightness>[Brightness.light, Brightness.dark]) {
      final theme = buildAppTheme(
        seedColor: 0xFF55766D,
        brightness: brightness,
      );
      expect(
        theme.textTheme.bodyMedium?.fontFamilyFallback,
        contains('NotoSansSC'),
      );
      expect(
        theme.textTheme.bodySmall?.fontFamilyFallback,
        contains('NotoSansSC'),
      );
    }
  });
}
