import 'package:flutter/material.dart';

/// Working product identity, intentionally centralized for a later rename.
const String productName = 'ChaSteady';

/// Muted green-gray brand seed used only when the service has no saved seed.
const int defaultSeedColorArgb = 0xFF55766D;

ShapeBorder continuousShape({double radius = 20}) => ContinuousRectangleBorder(
  borderRadius: BorderRadius.all(Radius.circular(radius)),
);
