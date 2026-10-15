import 'dart:convert';

import 'package:http/http.dart' as http;

import '../brand.dart';
import '../models.dart';
import 'api_service.dart';

class HttpApiService implements ApiService {
  HttpApiService({required Uri? baseUri, http.Client? client})
    : _baseUri = baseUri,
      _client = client ?? http.Client();

  final Uri? _baseUri;
  final http.Client _client;
  String? _nonce;

  @override
  Uri? get origin => _baseUri;

  @override
  Future<void> establishSession(String nonce) async {
    await _request(
      'POST',
      '/api/session',
      body: const <String, dynamic>{},
      authorizationNonce: nonce,
    );
    _nonce = nonce;
  }

  @override
  Future<Capabilities> getCapabilities() async => Capabilities.fromJson(
    _requiredMap(await _request('GET', '/api/capabilities')),
  );

  @override
  Future<AppPreferences> getPreferences() async => AppPreferences.fromJson(
    _requiredMap(await _request('GET', '/api/preferences')),
  );

  @override
  Future<AppPreferences> putPreferences(AppPreferences preferences) =>
      patchPreferences(preferences.toJson());

  @override
  Future<AppPreferences> patchPreferences(Map<String, dynamic> patch) async =>
      AppPreferences.fromJson(
        _requiredMap(
          await _request('PUT', '/api/preferences', body: patch),
        ),
      );

  @override
  Future<List<JobSummary>> getJobs() async {
    final body = _requiredMap(await _request('GET', '/api/jobs'));
    final rawJobs = body['jobs'];
    if (rawJobs is! List) {
      throw const ApiException(
        code: 'invalid_response',
        message: 'The local service returned an invalid jobs list.',
        messageKey: 'ui.error.invalidJobsList',
      );
    }
    return rawJobs
        .whereType<Map>()
        .map((item) => JobSummary.fromJson(Map<String, dynamic>.from(item)))
        .where((job) => job.id.isNotEmpty)
        .toList(growable: false);
  }

  @override
  Future<JobSummary> getJob(String id) async {
    final body = _requiredMap(
      await _request('GET', '/api/jobs/${_safeId(id)}'),
    );
    return JobSummary.fromJson(_jobMap(body));
  }

  @override
  Future<JobSummary> createJob(
    String kind,
    Map<String, dynamic> request,
  ) async {
    final body = _requiredMap(
      await _request(
        'POST',
        '/api/jobs',
        body: <String, dynamic>{'kind': kind, 'request': request},
      ),
    );
    return JobSummary.fromJson(_jobMap(body));
  }

  @override
  Future<JobSummary> cancelJob(String id) async {
    final body = _requiredMap(
      await _request('POST', '/api/jobs/${_safeId(id)}/cancel', body: const {}),
    );
    return JobSummary.fromJson(_jobMap(body));
  }

  @override
  Future<MediaInfo> inspectMedia(String path) async => MediaInfo.fromJson(
    _requiredMap(
      await _request(
        'POST',
        '/api/media/inspect',
        body: <String, dynamic>{'path': path},
      ),
    ),
  );

  @override
  Future<String?> pickMedia(String kind) async {
    final body = _requiredMap(
      await _request(
        'POST',
        '/api/media/pick',
        body: <String, dynamic>{'kind': kind},
      ),
    );
    final path = body['path'];
    return path is String && path.trim().isNotEmpty ? path.trim() : null;
  }

  @override
  Future<List<PresetRecord>> discoverPresets(String experimentRoot) async {
    final body = _requiredMap(
      await _request(
        'POST',
        '/api/presets/discover',
        body: <String, dynamic>{'experiment_root': experimentRoot},
      ),
    );
    final rawPresets = body['presets'];
    if (rawPresets is! List) {
      throw const ApiException(
        code: 'invalid_response',
        message: 'The local service returned an invalid preset catalog.',
        messageKey: 'ui.error.invalidPresetCatalog',
      );
    }
    return rawPresets.map(PresetRecord.fromJson).toList(growable: false);
  }

  @override
  Future<void> openArtifact(String id) async {
    await _request(
      'POST',
      '/api/artifacts/${_safeId(id)}/open',
      body: const <String, dynamic>{},
    );
  }

  Future<dynamic> _request(
    String method,
    String path, {
    Map<String, dynamic>? body,
    String? authorizationNonce,
  }) async {
    final baseUri = _baseUri;
    if (baseUri == null) {
      throw const ApiException(
        code: 'unsupported_platform',
        message: 'The local API adapter is not available on this platform.',
        messageKey: 'ui.error.unsupportedPlatform',
      );
    }
    final nonce = authorizationNonce ?? _nonce;
    if (nonce == null || nonce.isEmpty) {
      throw const ApiException(
        code: 'session_required',
        message: 'Open $productName from its local launcher session link.',
        messageKey: 'ui.error.sessionRequired',
      );
    }

    final uri = baseUri.resolve(path);
    final headers = <String, String>{
      'Authorization': 'Bearer $nonce',
      'Accept': 'application/json',
    };
    if (body != null) headers['Content-Type'] = 'application/json';

    late http.Response response;
    try {
      final request = http.Request(method, uri)..headers.addAll(headers);
      if (body != null) request.body = jsonEncode(body);
      final streamed = await _client.send(request);
      response = await http.Response.fromStream(streamed);
    } on http.ClientException {
      throw const ApiException(
        code: 'connection_error',
        message: 'Could not reach the local $productName service.',
        messageKey: 'ui.error.connectionFailed',
        args: const <String, dynamic>{'appName': productName},
      );
    }

    dynamic decoded;
    if (response.bodyBytes.isNotEmpty) {
      try {
        decoded = jsonDecode(utf8.decode(response.bodyBytes));
      } on FormatException {
        if (response.statusCode >= 200 && response.statusCode < 300) {
          throw const ApiException(
            code: 'invalid_response',
            message: 'The local service returned an unreadable response.',
            messageKey: 'ui.error.invalidResponse',
          );
        }
      }
    }
    if (response.statusCode < 200 || response.statusCode >= 300) {
      final error = decoded is Map ? decoded['error'] : null;
      throw ApiException(
        code: error is Map && error['code'] is String
            ? error['code'] as String
            : 'http_${response.statusCode}',
        message: error is Map && error['message'] is String
            ? error['message'] as String
            : 'The local service returned HTTP ${response.statusCode}.',
        statusCode: response.statusCode,
        details: error is Map ? error['details'] : null,
        messageKey: error is Map && error['message_key'] is String
            ? (error['message_key'] as String).trim()
            : 'ui.error.httpStatus',
        args: error is Map && error['args'] is Map
            ? Map<String, dynamic>.from(error['args'] as Map)
            : error is Map && error['message_key'] is String
            ? const <String, dynamic>{}
            : <String, dynamic>{'statusCode': response.statusCode},
      );
    }
    return decoded;
  }

  String _safeId(String id) {
    if (!RegExp(r'^[A-Za-z0-9_-]+$').hasMatch(id)) {
      throw const ApiException(
        code: 'invalid_id',
        message: 'The service returned an invalid local resource identifier.',
        messageKey: 'ui.error.invalidResourceId',
      );
    }
    return Uri.encodeComponent(id);
  }

  Map<String, dynamic> _requiredMap(dynamic value) {
    if (value is Map) return Map<String, dynamic>.from(value);
    throw const ApiException(
      code: 'invalid_response',
      message: 'The local service returned an invalid response.',
      messageKey: 'ui.error.invalidResponse',
    );
  }

  Map<String, dynamic> _jobMap(Map<String, dynamic> response) {
    final rawJob = response['job'];
    if (rawJob is Map) return Map<String, dynamic>.from(rawJob);
    throw const ApiException(
      code: 'invalid_response',
      message: 'The local service did not return a job record.',
      messageKey: 'ui.error.jobRecordMissing',
    );
  }
}
