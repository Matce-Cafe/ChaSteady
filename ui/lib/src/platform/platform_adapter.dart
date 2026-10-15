import 'media_platform.dart';
import 'platform_adapter_stub.dart'
    if (dart.library.html) 'platform_adapter_web.dart'
    if (dart.library.io) 'platform_adapter_windows.dart'
    as platform;

MediaPlatformAdapter createPlatformAdapter() =>
    platform.createPlatformAdapter();
