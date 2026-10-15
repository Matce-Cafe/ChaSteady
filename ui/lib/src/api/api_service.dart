import '../models.dart';

class ApiException implements Exception {
  const ApiException({
    required this.code,
    required this.message,
    this.statusCode,
    this.details,
    this.messageKey,
    this.args = const <String, dynamic>{},
  });

  final String code;
  final String message;
  final int? statusCode;
  final dynamic details;
  final String? messageKey;
  final Map<String, dynamic> args;

  @override
  String toString() => message;
}

abstract interface class ApiService {
  Uri? get origin;

  Future<void> establishSession(String nonce);
  Future<Capabilities> getCapabilities();
  Future<AppPreferences> getPreferences();
  Future<AppPreferences> putPreferences(AppPreferences preferences);
  Future<AppPreferences> patchPreferences(Map<String, dynamic> patch);
  Future<List<JobSummary>> getJobs();
  Future<JobSummary> getJob(String id);
  Future<JobSummary> createJob(String kind, Map<String, dynamic> request);
  Future<JobSummary> cancelJob(String id);
  Future<MediaInfo> inspectMedia(String path);
  Future<String?> pickMedia(String kind);
  Future<List<PresetRecord>> discoverPresets(String experimentRoot);
  Future<void> openArtifact(String id);
}
