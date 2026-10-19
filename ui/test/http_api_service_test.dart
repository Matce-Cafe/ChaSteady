import 'dart:convert';

import 'package:cha_stabilizer_ui/src/api/http_api_service.dart';
import 'package:cha_stabilizer_ui/src/controller.dart';
import 'package:cha_stabilizer_ui/src/models.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

import 'test_fakes.dart';

void main() {
  group('HttpApiService HTTP contract', () {
    test(
      'session and job creation use the strict nested request envelope',
      () async {
        final observed = <http.Request>[];
        final client = MockClient((request) async {
          observed.add(request);
          _expectBearer(request);
          if (request.url.path == '/api/session') {
            expect(request.method, 'POST');
            expect(jsonDecode(request.body), <String, dynamic>{});
            return _jsonResponse(<String, dynamic>{'session_ready': true});
          }
          if (request.url.path == '/api/capabilities') {
            expect(request.method, 'GET');
            return _jsonResponse(<String, dynamic>{
              'ffmpeg': <String, dynamic>{
                'detected': true,
                'path': r'C:\\ffmpeg.exe',
              },
              'ffprobe': <String, dynamic>{
                'detected': true,
                'path': r'C:\\ffprobe.exe',
              },
              'gyroflow': <String, dynamic>{
                'detected': false,
                'prior_verified': false,
              },
              'catalyst': <String, dynamic>{
                'detected': false,
                'uia_verified': false,
              },
              'preset_catalog': <dynamic>[],
              'native_picker': false,
            });
          }
          if (request.url.path == '/api/preferences') {
            expect(request.method, 'GET');
            return _jsonResponse(<String, dynamic>{
              'theme_mode': 'system',
              'seed_color': 4283215696,
              'tool_paths': <String, dynamic>{
                'ffmpeg': r'C:\\ffmpeg.exe',
                'ffprobe': r'C:\\ffprobe.exe',
                'gyroflow': null,
                'catalyst': null,
              },
            });
          }
          if (request.url.path == '/api/jobs' && request.method == 'GET') {
            return _jsonResponse(<String, dynamic>{'jobs': <dynamic>[]});
          }
          if (request.url.path == '/api/jobs') {
            expect(request.method, 'POST');
            final envelope = jsonDecode(request.body) as Map<String, dynamic>;
            final kind = envelope['kind'] as String;
            final requestBody = envelope['request'] as Map<String, dynamic>;
            final expectedRequest = switch (kind) {
              'fusion' => <String, dynamic>{
                'original': r'N:\lab\original.mp4',
                'ctb': r'N:\lab\ctb.mp4',
                'reference': r'N:\lab\reference.mp4',
                'start': 212.0,
                'end': 228.0,
                'ctb_origin': 0.0,
                'reference_origin': 0.0,
                'reference_intervals': <dynamic>[],
                'reference_fov': 1.0,
                'quiet_sigma_seconds': 1.3,
                'mode': 'fresh',
              },
              'preview' => <String, dynamic>{
                'source': r'N:\lab\original.mp4',
                'start': 0,
              },
              'validate' => <String, dynamic>{'source': r'N:\lab\original.mp4'},
              'gyroflow_export' =>
                requestBody['full_source'] == true
                    ? <String, dynamic>{
                        'original': r'N:\lab\original.mp4',
                        'full_source': true,
                        'output_preset': 'reference_720p',
                      }
                    : <String, dynamic>{
                        'original': r'N:\lab\original.mp4',
                        'project_template': r'N:\lab\project.gyroflow',
                        'full_source': false,
                        'output_preset': 'reference_1080p',
                        'start': 0.0,
                        'end': 5.0,
                      },
              'catalyst_assisted' => <String, dynamic>{
                'original': r'N:\lab\original.mp4',
              },
              _ => throw StateError('Unexpected job kind: $kind'),
            };
            expect(envelope, <String, dynamic>{
              'kind': kind,
              'request': expectedRequest,
            });
            return _jsonResponse(<String, dynamic>{
              'job': <String, dynamic>{
                'id': 'a17e0f59-9740-409e-a872-55c80fb4d2b8',
                'kind': kind,
                'state': 'queued',
                'stage': 'queued',
                'progress': null,
                'message': 'Accepted by the local worker.',
                'artifacts': <dynamic>[],
                'warnings': <dynamic>[],
              },
            }, statusCode: 202);
          }
          return _jsonResponse(<String, dynamic>{
            'error': 'unexpected route',
          }, statusCode: 404);
        });
        final api = HttpApiService(
          baseUri: Uri.parse('http://127.0.0.1:8765'),
          client: client,
        );
        final controller = AppController(
          api: api,
          platform: TestPlatformAdapter(),
          sessionNonce: 'mock-session-nonce',
        );

        await controller.initialize();
        final jobs = <JobSummary>[];
        for (final payload in <Map<String, dynamic>>[
          <String, dynamic>{
            'kind': 'fusion',
            'original': r'N:\lab\original.mp4',
            'ctb': r'N:\lab\ctb.mp4',
            'reference': r'N:\lab\reference.mp4',
            'start': 212.0,
            'end': 228.0,
            'ctb_origin': 0.0,
            'reference_origin': 0.0,
            'reference_intervals': <dynamic>[],
            'reference_fov': 1.0,
            'quiet_sigma_seconds': 1.3,
            'mode': 'fresh',
          },
          <String, dynamic>{
            'kind': 'preview',
            'source': r'N:\lab\original.mp4',
            'start': 0,
          },
          <String, dynamic>{
            'kind': 'validate',
            'source': r'N:\lab\original.mp4',
          },
          <String, dynamic>{
            'kind': 'gyroflow_export',
            'original': r'N:\lab\original.mp4',
            'project_template': r'N:\lab\project.gyroflow',
            'full_source': false,
            'output_preset': 'reference_1080p',
            'start': 0.0,
            'end': 5.0,
          },
          <String, dynamic>{
            'kind': 'gyroflow_export',
            'original': r'N:\lab\original.mp4',
            'full_source': true,
            'output_preset': 'reference_720p',
          },
          <String, dynamic>{
            'kind': 'catalyst_assisted',
            'original': r'N:\lab\original.mp4',
          },
        ]) {
          jobs.add(await controller.createJob(payload));
        }

        expect(observed.map((request) => request.url.path), <String>[
          '/api/session',
          '/api/capabilities',
          '/api/preferences',
          '/api/jobs',
          '/api/jobs',
          '/api/jobs',
          '/api/jobs',
          '/api/jobs',
          '/api/jobs',
          '/api/jobs',
        ]);
        expect(jobs.map((job) => job.kind), <String>[
          'fusion',
          'preview',
          'validate',
          'gyroflow_export',
          'gyroflow_export',
          'catalyst_assisted',
        ]);
        expect(jobs.every((job) => job.state == 'queued'), isTrue);
        controller.dispose();
        client.close();
      },
    );

    test(
      'metadata-only catalog discovers and submits the full C7037 request',
      () async {
        final observed = <http.Request>[];
        final presetRequest = <String, dynamic>{
          'original': r'C:\Media\SampleProject\C7037.MP4',
          'ctb':
              r'C:\Media\SampleProject\Catalyst Browse\C7037-Catalyst-Browse.mp4',
          'reference': r'C:\Media\SampleProject\Gyroflow\C7037_Gyroflow.mp4',
          'start': 212.0,
          'end': 228.0,
          'ctb_origin': 0,
          'reference_origin': 0,
          'reference_intervals': <dynamic>[],
          'reference_fov': 1.0,
          'quiet_sigma_seconds': 1.3,
          'mode': 'cached_v9',
          'legacy_quiet_cache': r'N:\approved\quiet.npz',
          'legacy_reference_cache': r'N:\approved\reference.npz',
        };
        final preferencesJson = <String, dynamic>{
          'theme_mode': 'system',
          'seed_color': 4283215696,
          'tool_paths': <String, dynamic>{
            'ffmpeg': r'C:\APPS\ffmpeg\bin\ffmpeg.exe',
            'ffprobe': r'C:\APPS\ffmpeg\bin\ffprobe.exe',
            'gyroflow': null,
            'catalyst': null,
          },
        };
        final catalogPreset = <String, dynamic>{
          'id': 'c7037-fixed-212-228',
          'label': 'C7037 Fixed 212–228',
          'kind': 'fusion',
          'mode': 'cached_v9',
          'discovery_required': true,
          'warnings': <String>['Explicit cached reproduction only.'],
        };
        final discoveredPreset = <String, dynamic>{
          'id': 'c7037-fixed-212-228',
          'label': 'C7037 Fixed 212–228',
          'kind': 'fusion',
          'mode': 'cached_v9',
          'warnings': <String>['Explicit cached reproduction only.'],
          'request': presetRequest,
        };
        final client = MockClient((request) async {
          observed.add(request);
          _expectBearer(request);
          switch ('${request.method} ${request.url.path}') {
            case 'POST /api/session':
              return _jsonResponse(<String, dynamic>{'session_ready': true});
            case 'GET /api/capabilities':
              return _jsonResponse(<String, dynamic>{
                'version': 'test-worker',
                'ffmpeg': <String, dynamic>{
                  'detected': true,
                  'path': r'C:\APPS\ffmpeg\bin\ffmpeg.exe',
                },
                'ffprobe': <String, dynamic>{
                  'detected': true,
                  'path': r'C:\APPS\ffmpeg\bin\ffprobe.exe',
                },
                'gyroflow': <String, dynamic>{
                  'detected': true,
                  'path': r'C:\Tools\Gyroflow\gyroflow.exe',
                  'mode': 'cli',
                  'build_id': 'official_nightly_gh2811',
                  'cli_status': 'verified',
                  'prior_verified': true,
                  'export_verified': false,
                  'trim_mapping_verified': false,
                  'validation_status': 'needs_review',
                  'profile_safety_required': true,
                },
                'catalyst': <String, dynamic>{
                  'detected': false,
                  'mode': 'assisted',
                  'uia_verified': false,
                },
                'preset_catalog': <dynamic>[catalogPreset],
                'native_picker': false,
              });
            case 'GET /api/preferences':
              return _jsonResponse(preferencesJson);
            case 'PUT /api/preferences':
              expect(jsonDecode(request.body), <String, dynamic>{
                'theme_mode': 'dark',
                'seed_color': 4283215696,
                'language_mode': 'system',
                'tool_paths': <String, dynamic>{
                  'ffmpeg': r'C:\APPS\ffmpeg\bin\ffmpeg.exe',
                  'ffprobe': r'C:\APPS\ffmpeg\bin\ffprobe.exe',
                  'gyroflow': r'C:\Tools\Gyroflow\gyroflow.exe',
                  'catalyst': null,
                },
              });
              return _jsonResponse(
                jsonDecode(request.body) as Map<String, dynamic>,
              );
            case 'POST /api/presets/discover':
              expect(jsonDecode(request.body), <String, dynamic>{
                'experiment_root':
                    r'C:\Media\SampleProject\Frontier_Stabilization_20261012_150110',
              });
              return _jsonResponse(<String, dynamic>{
                'presets': <dynamic>[discoveredPreset],
              });
            case 'POST /api/jobs':
              expect(jsonDecode(request.body), <String, dynamic>{
                'kind': 'fusion',
                'request': presetRequest,
              });
              return _jsonResponse(<String, dynamic>{
                'job': <String, dynamic>{
                  'id': 'cached-c7037-job',
                  'kind': 'fusion',
                  'state': 'queued',
                  'stage': 'queued',
                  'progress': null,
                  'message': 'Cached preset accepted by the local worker.',
                  'artifacts': <dynamic>[],
                  'warnings': <dynamic>[],
                },
              }, statusCode: 202);
          }
          return _jsonResponse(<String, dynamic>{
            'error': 'unexpected route',
          }, statusCode: 404);
        });
        final api = HttpApiService(
          baseUri: Uri.parse('http://127.0.0.1:8765'),
          client: client,
        );
        await api.establishSession('mock-session-nonce');

        final capabilities = await api.getCapabilities();
        expect(capabilities.ffprobe.detected, isTrue);
        expect(capabilities.ffprobe.path, r'C:\APPS\ffmpeg\bin\ffprobe.exe');
        expect(capabilities.gyroflow.cliStatus, 'verified');
        expect(
          capabilities.gyroflow.priorVerificationMatchesConfiguredPath,
          isTrue,
        );
        expect(capabilities.gyroflow.exportVerified, isFalse);
        expect(capabilities.gyroflow.trimMappingVerified, isFalse);
        expect(capabilities.gyroflow.validationStatus, 'needs_review');
        expect(capabilities.presetCatalog.single.discoveryRequired, isTrue);
        expect(capabilities.presetCatalog.single.request, isEmpty);
        expect(
          capabilities.presetCatalog.single.hasCompleteCachedV9Request,
          isFalse,
        );
        expect(capabilities.presetCatalog.single.legacyQuietCache, isNull);

        final preferences = await api.getPreferences();
        expect(preferences.hasCompleteToolPaths, isTrue);
        expect(
          preferences.toolPaths['ffmpeg'],
          r'C:\APPS\ffmpeg\bin\ffmpeg.exe',
        );
        final updated = preferences.copyWith(
          themeMode: ThemeMode.dark,
          toolPaths: <String, String?>{
            ...preferences.toolPaths,
            'gyroflow': r'C:\Tools\Gyroflow\gyroflow.exe',
          },
        );
        final saved = await api.putPreferences(updated);
        expect(saved.toolPaths['ffprobe'], r'C:\APPS\ffmpeg\bin\ffprobe.exe');
        expect(saved.toolPaths['gyroflow'], r'C:\Tools\Gyroflow\gyroflow.exe');

        final discovered = await api.discoverPresets(
          r'C:\Media\SampleProject\Frontier_Stabilization_20261012_150110',
        );
        expect(discovered.single.discoveryRequired, isFalse);
        expect(discovered.single.hasCompleteCachedV9Request, isTrue);
        expect(discovered.single.request['start'], 212.0);
        expect(discovered.single.request['reference_intervals'], isEmpty);

        final controller =
            AppController(
                api: api,
                platform: TestPlatformAdapter(),
                sessionNonce: 'mock-session-nonce',
              )
              ..capabilities = capabilities
              ..discoveredPresets = discovered;
        expect(controller.availablePresets, hasLength(1));
        expect(
          controller.availablePresets.single.hasCompleteCachedV9Request,
          isTrue,
        );
        final cachedJob = await controller.createJob(<String, dynamic>{
          'kind': 'fusion',
          'request': controller.availablePresets.single.request,
        });
        expect(cachedJob.id, 'cached-c7037-job');
        controller.dispose();
        expect(observed.map((request) => request.url.path), <String>[
          '/api/session',
          '/api/capabilities',
          '/api/preferences',
          '/api/preferences',
          '/api/presets/discover',
          '/api/jobs',
        ]);
        client.close();
      },
    );

    test('preference language patch sends only the changed field', () async {
      final observed = <http.Request>[];
      final client = MockClient((request) async {
        observed.add(request);
        _expectBearer(request);
        if (request.url.path == '/api/session') {
          return _jsonResponse(<String, dynamic>{'session_ready': true});
        }
        expect(request.url.path, '/api/preferences');
        expect(request.method, 'PUT');
        expect(jsonDecode(request.body), <String, dynamic>{
          'language_mode': 'zh',
        });
        return _jsonResponse(<String, dynamic>{
          'theme_mode': 'dark',
          'seed_color': 4283215696,
          'language_mode': 'zh',
          'tool_paths': <String, dynamic>{
            'ffmpeg': r'C:\\APPS\\ffmpeg\\bin\\ffmpeg.exe',
            'ffprobe': r'C:\\APPS\\ffmpeg\\bin\\ffprobe.exe',
            'gyroflow': r'C:\\Tools\\Gyroflow\\gyroflow.exe',
            'catalyst': null,
          },
        });
      });
      final api = HttpApiService(
        baseUri: Uri.parse('http://127.0.0.1:8765'),
        client: client,
      );
      await api.establishSession('mock-session-nonce');
      final saved = await api.patchPreferences(<String, dynamic>{
        'language_mode': 'zh',
      });

      expect(saved.languageMode, AppLanguageMode.zh);
      expect(saved.themeMode, ThemeMode.dark);
      expect(saved.toolPaths['ffmpeg'], contains('ffmpeg.exe'));
      expect(saved.toolPaths['gyroflow'], contains('gyroflow.exe'));
      expect(observed.map((request) => request.url.path), <String>[
        '/api/session',
        '/api/preferences',
      ]);
      client.close();
    });
  });
}

void _expectBearer(http.Request request) {
  final authorization = request.headers.entries
      .firstWhere((entry) => entry.key.toLowerCase() == 'authorization')
      .value;
  expect(authorization, 'Bearer mock-session-nonce');
}

http.Response _jsonResponse(Object? body, {int statusCode = 200}) =>
    http.Response(
      jsonEncode(body),
      statusCode,
      headers: <String, String>{'content-type': 'application/json'},
    );
