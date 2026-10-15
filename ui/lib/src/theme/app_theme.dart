import 'package:flutter/material.dart';

ThemeData buildAppTheme({
  required int seedColor,
  required Brightness brightness,
}) {
  final scheme = ColorScheme.fromSeed(
    seedColor: Color(seedColor),
    brightness: brightness,
  );
  return ThemeData(
    useMaterial3: true,
    colorScheme: scheme,
    fontFamilyFallback: const <String>['NotoSansSC'],
    scaffoldBackgroundColor: scheme.surface,
  );
}
