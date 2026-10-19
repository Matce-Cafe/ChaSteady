import 'package:flutter/material.dart';

/// 集中维护产品名称，便于统一界面身份。
const String productName = 'ChaSteady';

/// 由构建入口从 pubspec 注入；开发运行不得伪装成发布版本。
const String productVersion = String.fromEnvironment(
  'CHASTEADY_PRODUCT_VERSION',
  defaultValue: 'development',
);
const String productBuildNumber = String.fromEnvironment(
  'CHASTEADY_BUILD_NUMBER',
);
String get productVersionLabel => productBuildNumber.isEmpty
    ? productVersion
    : '$productVersion+$productBuildNumber';

/// 服务未保存主题色时使用低饱和绿灰色。
const int defaultSeedColorArgb = 0xFF55766D;

ShapeBorder continuousShape({double radius = 20}) => ContinuousRectangleBorder(
  borderRadius: BorderRadius.all(Radius.circular(radius)),
);
