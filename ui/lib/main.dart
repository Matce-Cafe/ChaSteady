import 'package:flutter/widgets.dart';

import 'src/api/http_api_service.dart';
import 'src/app.dart';
import 'src/platform/platform_adapter.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  final platform = createPlatformAdapter();
  try {
    await platform.initialize();
    final sessionNonce = platform.consumeSessionNonce();
    runApp(
      ChaSteadyApp(
        api: HttpApiService(baseUri: platform.apiOrigin),
        platform: platform,
        sessionNonce: sessionNonce,
      ),
    );
  } catch (error) {
    try {
      await platform.dispose();
    } catch (_) {
      // Startup failure UI remains available even if cleanup also fails.
    }
    runApp(StartupFailureApp(error: error));
  }
}
