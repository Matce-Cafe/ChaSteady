import 'package:flutter/material.dart';

import '../app.dart';
import '../controller.dart';
import '../localization.dart';
import '../models.dart';
import '../path_rules.dart';
import '../platform/media_platform.dart';
import '../widgets/common_widgets.dart';
import '../widgets/interval_editor.dart';
import '../widgets/source_path_field.dart';
import 'jobs_screen.dart';

class WorkbenchScreen extends StatefulWidget {
  const WorkbenchScreen({
    required this.controller,
    required this.platform,
    this.active = true,
    this.dropActive = true,
    this.onOpenJobs,
    super.key,
  });

  final AppController controller;
  final MediaPlatformAdapter platform;
  final bool active;
  // 外部 OLE 源窗口可占前台，拖入资格不能复用预览的前台租约条件。
  final bool dropActive;
  final VoidCallback? onOpenJobs;

  @override
  State<WorkbenchScreen> createState() => _WorkbenchScreenState();
}

class _WorkbenchScreenState extends State<WorkbenchScreen> {
  final TextEditingController _original = TextEditingController();
  final TextEditingController _ctb = TextEditingController();
  final TextEditingController _reference = TextEditingController();
  final TextEditingController _experimentRoot = TextEditingController();
  final TextEditingController _legacyQuiet = TextEditingController();
  final TextEditingController _legacyReference = TextEditingController();
  final TextEditingController _windowStart = TextEditingController();
  final TextEditingController _windowEnd = TextEditingController();
  final TextEditingController _ctbOrigin = TextEditingController(text: '0');
  final TextEditingController _referenceOrigin = TextEditingController(
    text: '0',
  );
  final TextEditingController _quietSigma = TextEditingController(text: '1.3');
  final TextEditingController _referenceFov = TextEditingController(text: '1');
  final List<IntervalInput> _intervals = <IntervalInput>[];

  String _fusionMode = 'fresh';
  PresetRecord? _selectedPreset;
  String? _selectedPresetErrorKey;
  IntervalValidation? _selectedPresetIntervalError;
  MediaInfo? _inspection;
  Object? _inspectionError;
  bool _reviewedIntervals = false;
  bool _attemptedFusion = false;
  bool _submitting = false;
  bool _exporting = false;
  bool _creatingPreview = false;
  bool _validating = false;
  bool _requestingManual = false;
  bool _stabilizing = false;
  bool _researchExpanded = false;
  bool _parametersExpanded = false;
  bool _inspecting = false;
  int _sourceGeneration = 0;
  final _recommendedParameters = <String, TextEditingController>{
    'quiet_sigma_seconds': TextEditingController(text: '1.3'),
    'reference_fov': TextEditingController(text: '1'),
    'alignment_tau_seconds': TextEditingController(text: '0.12'),
    'minimum_weight_transition_seconds': TextEditingController(text: '0.30'),
    'weight_corner_speed': TextEditingController(text: '12.5'),
    'anchor_corner_speed': TextEditingController(text: '5'),
  };

  Map<String, double>? get _parsedParameters {
    const bounds = <String, (double, double, bool)>{
      'quiet_sigma_seconds': (0, 10, false),
      'reference_fov': (1, 4, true),
      'alignment_tau_seconds': (0.01, 2, true),
      'minimum_weight_transition_seconds': (0.04, 5, true),
      'weight_corner_speed': (0, 100, false),
      'anchor_corner_speed': (0, 100, false),
    };
    final parsed = <String, double>{};
    for (final entry in _recommendedParameters.entries) {
      final value = double.tryParse(entry.value.text.trim());
      final (min, max, inclusive) = bounds[entry.key]!;
      if (value == null ||
          !value.isFinite ||
          value > max ||
          (inclusive ? value < min : value <= min))
        return null;
      parsed[entry.key] = value;
    }
    return parsed;
  }

  List<PresetRecord> get _c7037Presets => widget.controller.availablePresets
      .where((preset) => preset.isC7037 && preset.hasCompleteCachedV9Request)
      .toList(growable: false);

  bool get _c7037CatalogNeedsDiscovery => widget.controller.availablePresets
      .any((preset) => preset.isC7037 && !preset.hasCompleteCachedV9Request);

  IntervalValidation get _intervalValidation =>
      validateIntervals(_intervals.map((entry) => entry.value));

  IntervalValidation get _sourceWindowValidation =>
      validateSourceWindow(_windowStart.text, _windowEnd.text);

  bool get _cachedPresetLocked =>
      _fusionMode == 'cached_v9' &&
      _selectedPreset != null &&
      _selectedPresetErrorKey == null;

  bool get _fusionPathsAreLocal =>
      isLocalAbsolutePath(_original.text) &&
      isLocalAbsolutePath(_ctb.text) &&
      isLocalAbsolutePath(_reference.text) &&
      (_fusionMode != 'cached_v9' ||
          (isLocalAbsolutePath(_legacyQuiet.text) &&
              isLocalAbsolutePath(_legacyReference.text)));

  String? _selectedPresetErrorMessage(BuildContext context) {
    final l10n = context.l10n;
    return switch (_selectedPresetErrorKey) {
      null => null,
      'catalogFieldChanged' => l10n.catalogFieldChanged,
      'metadataOnlyCatalog' => l10n.metadataOnlyCatalogError,
      'invalidReferenceInterval' => l10n.invalidReferenceInterval,
      'nonFiniteReferenceInterval' => l10n.nonFiniteReferenceInterval,
      'missingReferenceIntervals' => l10n.missingReferenceIntervals,
      'invalidIntervalList' => intervalValidationMessage(
        l10n,
        _selectedPresetIntervalError ?? const IntervalValidation(),
      ),
      'missingCachedRequestField' => l10n.missingCachedRequestField,
      'catalogNonLocalPath' => l10n.catalogNonLocalPath,
      _ => l10n.genericOperationFailed,
    };
  }

  bool get _gyroflowPathMatchesSavedPreference {
    final capabilityPath = widget.controller.capabilities?.gyroflow.path;
    final savedPath = widget.controller.preferences.toolPaths['gyroflow'];
    return isLocalAbsolutePath(savedPath ?? '') &&
        localAbsolutePathsEqual(capabilityPath, savedPath);
  }

  bool get _hasInvalidSourcePath =>
      <TextEditingController>[_original, _ctb, _reference].any(
        (controller) =>
            controller.text.trim().isNotEmpty &&
            !isLocalAbsolutePath(controller.text),
      );

  @override
  void dispose() {
    ++_sourceGeneration;
    for (final controller in _recommendedParameters.values) {
      controller.dispose();
    }
    _original.dispose();
    _ctb.dispose();
    _reference.dispose();
    _experimentRoot.dispose();
    _legacyQuiet.dispose();
    _legacyReference.dispose();
    _windowStart.dispose();
    _windowEnd.dispose();
    _ctbOrigin.dispose();
    _referenceOrigin.dispose();
    _quietSigma.dispose();
    _referenceFov.dispose();
    for (final entry in _intervals) {
      entry.dispose();
    }
    super.dispose();
  }

  void _showMessage(String message) {
    if (!mounted) return;
    ScaffoldMessenger.of(
      context,
    ).showSnackBar(SnackBar(content: Text(message)));
  }

  void _showError(Object error) {
    if (mounted) _showMessage(localizedError(context.l10n, error));
  }

  void _invalidateSelectedPreset() {
    if (_fusionMode == 'cached_v9' && _selectedPreset != null) {
      _selectedPreset = null;
      _selectedPresetErrorKey = 'catalogFieldChanged';
      _selectedPresetIntervalError = null;
    }
  }

  void _sourceChanged(String _) {
    ++_sourceGeneration;
    setState(() {
      _inspecting = false;
      _invalidateSelectedPreset();
      _reviewedIntervals = false;
      _inspection = null;
      _inspectionError = null;
    });
  }

  void _intervalChanged() {
    setState(() {
      _invalidateSelectedPreset();
      _reviewedIntervals = false;
    });
  }

  void _insertKnownRanges() {
    for (final entry in _intervals) {
      entry.dispose();
    }
    _intervals
      ..clear()
      ..add(IntervalInput(start: '153.0', end: '156.0'))
      ..add(IntervalInput(start: '231.8', end: '235.5'));
    setState(() {
      _invalidateSelectedPreset();
      _reviewedIntervals = false;
      _attemptedFusion = false;
    });
  }

  void _addInterval() {
    setState(() {
      _intervals.add(IntervalInput());
      _invalidateSelectedPreset();
      _reviewedIntervals = false;
    });
  }

  void _removeInterval(int index) {
    if (index < 0 || index >= _intervals.length) return;
    setState(() {
      _intervals.removeAt(index).dispose();
      _invalidateSelectedPreset();
      _reviewedIntervals = false;
    });
  }

  void _chooseFusionMode(String mode) {
    setState(() {
      _fusionMode = mode;
      _reviewedIntervals = false;
    });
  }

  void _selectPreset(PresetRecord? preset) {
    if (preset == null) {
      setState(() {
        _selectedPreset = null;
        _selectedPresetErrorKey = null;
        _selectedPresetIntervalError = null;
        _legacyQuiet.clear();
        _legacyReference.clear();
        _reviewedIntervals = false;
      });
      return;
    }

    final matchingPresets = widget.controller.availablePresets
        .where((item) => item.stableKey == preset.stableKey)
        .toList(growable: false);
    final canonical = matchingPresets.firstWhere(
      (item) => item.hasCompleteCachedV9Request,
      orElse: () => matchingPresets.isEmpty ? preset : matchingPresets.first,
    );
    if (!canonical.hasCompleteCachedV9Request) {
      setState(() {
        _fusionMode = 'cached_v9';
        _selectedPreset = null;
        _selectedPresetErrorKey = 'metadataOnlyCatalog';
        _selectedPresetIntervalError = null;
      });
      return;
    }
    final request = canonical.request;
    String? fieldErrorKey;
    IntervalValidation? fieldValidationError;
    String? textField(String name) {
      final value = request[name];
      return value is String && value.trim().isNotEmpty ? value : null;
    }

    String? numberField(String name) {
      final value = request[name];
      if (value is! num || !value.toDouble().isFinite) return null;
      return value.toString();
    }

    final original = textField('original');
    final ctb = textField('ctb');
    final reference = textField('reference');
    final start = numberField('start');
    final end = numberField('end');
    final ctbOrigin = numberField('ctb_origin');
    final referenceOrigin = numberField('reference_origin');
    final quietSigma = numberField('quiet_sigma_seconds');
    final referenceFov = numberField('reference_fov');
    final rawIntervals = request['reference_intervals'];
    final entries = <IntervalInput>[];
    if (rawIntervals is List) {
      for (final item in rawIntervals) {
        if (item is! Map || item['start'] is! num || item['end'] is! num) {
          fieldErrorKey = 'invalidReferenceInterval';
          break;
        }
        final intervalStart = (item['start'] as num).toDouble();
        final intervalEnd = (item['end'] as num).toDouble();
        if (!intervalStart.isFinite || !intervalEnd.isFinite) {
          fieldErrorKey = 'nonFiniteReferenceInterval';
          break;
        }
        entries.add(
          IntervalInput(
            start: intervalStart.toString(),
            end: intervalEnd.toString(),
          ),
        );
      }
    } else {
      fieldErrorKey = 'missingReferenceIntervals';
    }

    final loadedIntervals = validateIntervals(
      entries.map((entry) => entry.value),
    );
    if (fieldErrorKey == null && !loadedIntervals.isValid) {
      fieldErrorKey = 'invalidIntervalList';
      fieldValidationError = loadedIntervals;
    }
    if (original == null ||
        ctb == null ||
        reference == null ||
        start == null ||
        end == null ||
        ctbOrigin == null ||
        referenceOrigin == null ||
        quietSigma == null ||
        referenceFov == null ||
        canonical.legacyQuietCache == null ||
        canonical.legacyReferenceCache == null ||
        request['mode'] != 'cached_v9') {
      fieldErrorKey ??= 'missingCachedRequestField';
    }
    if (original != null && !isLocalAbsolutePath(original) ||
        ctb != null && !isLocalAbsolutePath(ctb) ||
        reference != null && !isLocalAbsolutePath(reference) ||
        canonical.legacyQuietCache != null &&
            !isLocalAbsolutePath(canonical.legacyQuietCache!) ||
        canonical.legacyReferenceCache != null &&
            !isLocalAbsolutePath(canonical.legacyReferenceCache!)) {
      fieldErrorKey ??= 'catalogNonLocalPath';
    }

    for (final entry in _intervals) {
      entry.dispose();
    }
    _intervals
      ..clear()
      ..addAll(entries);
    setState(() {
      _fusionMode = 'cached_v9';
      _selectedPreset = canonical;
      _selectedPresetErrorKey = fieldErrorKey;
      _selectedPresetIntervalError = fieldValidationError;
      ++_sourceGeneration;
      _inspecting = false;
      _original.text = original ?? '';
      _ctb.text = ctb ?? '';
      _reference.text = reference ?? '';
      _windowStart.text = start ?? '';
      _windowEnd.text = end ?? '';
      _ctbOrigin.text = ctbOrigin ?? '';
      _referenceOrigin.text = referenceOrigin ?? '';
      _quietSigma.text = quietSigma ?? '';
      _referenceFov.text = referenceFov ?? '';
      _legacyQuiet.text = canonical.legacyQuietCache ?? '';
      _legacyReference.text = canonical.legacyReferenceCache ?? '';
      _inspection = null;
      _inspectionError = null;
      _reviewedIntervals = false;
      _attemptedFusion = false;
    });
  }

  Future<void> _inspectOriginal() async {
    if (_inspecting) return;
    final path = _original.text.trim();
    if (path.isEmpty ||
        !isLocalAbsolutePath(path) ||
        !widget.controller.isApiReady) {
      return;
    }
    final generation = ++_sourceGeneration;
    setState(() {
      _inspecting = true;
      _inspection = null;
      _inspectionError = null;
    });
    bool current() =>
        mounted &&
        generation == _sourceGeneration &&
        _original.text.trim() == path;
    try {
      final result = await widget.controller.inspectMedia(path);
      if (current()) setState(() => _inspection = result);
    } catch (error) {
      if (current()) setState(() => _inspectionError = error);
    } finally {
      if (current()) setState(() => _inspecting = false);
    }
  }

  Future<void> _startStabilize() async {
    if (_stabilizing ||
        widget.controller.isCreatingJob ||
        !widget.controller.isApiReady ||
        widget.controller.capabilities?.supportsStabilize != true ||
        !isLocalAbsolutePath(_original.text))
      return;
    final parameters = _parsedParameters;
    if (parameters == null) {
      _showMessage(context.l10n.stabilizeParametersInvalid);
      return;
    }
    setState(() => _stabilizing = true);
    try {
      final job = await widget.controller.createJob(<String, dynamic>{
        'kind': 'stabilize',
        'request': <String, dynamic>{
          'original': _original.text.trim(),
          'profile': 'recommended-v1',
          'full_source': true,
          'parameters': parameters,
        },
      });
      if (!mounted) return;
      _showMessage(
        context.l10n.jobCreatedNotice(
          jobKindLabel(context.l10n, job.kind),
          job.id,
          jobStateLabel(context.l10n, job.state),
        ),
      );
    } catch (error) {
      if (mounted) _showMessage(localizedError(context.l10n, error));
    } finally {
      if (mounted) setState(() => _stabilizing = false);
    }
  }

  Future<void> _discoverPresets() async {
    final root = _experimentRoot.text.trim();
    if (!isLocalAbsolutePath(root)) {
      _showMessage(context.l10n.enterLocalAbsoluteFolder);
      return;
    }
    await widget.controller.discoverPresets(root);
  }

  Future<void> _startFusion() async {
    if (_submitting || widget.controller.isCreatingJob) return;
    setState(() => _attemptedFusion = true);
    final window = _sourceWindowValidation;
    final intervals = _intervalValidation;
    if (!window.isValid || !intervals.isValid || !_reviewedIntervals) return;

    final caps = widget.controller.capabilities;
    if (!_canSubmitFusion(caps)) return;

    late final Map<String, dynamic> payload;
    if (_fusionMode == 'cached_v9') {
      final preset = _selectedPreset;
      if (preset == null || _selectedPresetErrorKey != null) return;
      payload = <String, dynamic>{
        'kind': 'fusion',
        'request': Map<String, dynamic>.from(preset.request),
      };
    } else {
      final ctbOrigin = double.tryParse(_ctbOrigin.text.trim());
      final referenceOrigin = double.tryParse(_referenceOrigin.text.trim());
      final quietSigma = double.tryParse(_quietSigma.text.trim());
      final referenceFov = parseReferenceFov(_referenceFov.text);
      if (ctbOrigin == null ||
          referenceOrigin == null ||
          quietSigma == null ||
          referenceFov == null ||
          !ctbOrigin.isFinite ||
          !referenceOrigin.isFinite ||
          !quietSigma.isFinite ||
          quietSigma <= 0) {
        _showMessage(context.l10n.invalidTimingValues);
        return;
      }
      payload = <String, dynamic>{
        'kind': 'fusion',
        'original': _original.text.trim(),
        'ctb': _ctb.text.trim(),
        'reference': _reference.text.trim(),
        'start': window.ranges.single.start,
        'end': window.ranges.single.end,
        'ctb_origin': ctbOrigin,
        'reference_origin': referenceOrigin,
        'reference_intervals': intervals.ranges
            .map((range) => range.toJson())
            .toList(),
        'quiet_sigma_seconds': quietSigma,
        'reference_fov': referenceFov,
        'mode': 'fresh',
      };
    }

    setState(() => _submitting = true);
    try {
      final job = await widget.controller.createJob(payload);
      if (!mounted) return;
      _showMessage(context.l10n.jobCreatedNotice(job.kind, job.id, job.state));
    } catch (error) {
      _showError(error);
    } finally {
      if (mounted) setState(() => _submitting = false);
    }
  }

  bool _canSubmitFusion(Capabilities? capabilities) {
    if (!widget.controller.isApiReady ||
        _original.text.trim().isEmpty ||
        _ctb.text.trim().isEmpty ||
        _reference.text.trim().isEmpty ||
        !_fusionPathsAreLocal ||
        _submitting) {
      return false;
    }
    if (capabilities?.ffmpeg.detected != true) return false;
    if (_fusionMode == 'fresh') return true;
    return _selectedPreset != null &&
        _selectedPreset!.isC7037 &&
        _selectedPresetErrorKey == null &&
        _legacyQuiet.text.trim().isNotEmpty &&
        _legacyReference.text.trim().isNotEmpty;
  }

  String? _fusionHoldReason(Capabilities? capabilities) {
    final l10n = context.l10n;
    if (!widget.controller.isApiReady) {
      return l10n.sessionRequiredBeforeJob;
    }
    if (_hasInvalidSourcePath) {
      return l10n.localPathsOnly;
    }
    if (_fusionMode == 'cached_v9' &&
        ((_legacyQuiet.text.trim().isNotEmpty &&
                !isLocalAbsolutePath(_legacyQuiet.text)) ||
            (_legacyReference.text.trim().isNotEmpty &&
                !isLocalAbsolutePath(_legacyReference.text)))) {
      return l10n.legacyPathsMustBeAbsolute;
    }
    if (capabilities == null) return l10n.toolStatusNotReturned;
    if (capabilities.ffmpeg.detected != true) {
      return l10n.ffmpegMissingHeld;
    }
    if (_fusionMode == 'cached_v9' && _selectedPreset == null) {
      return _selectedPresetErrorMessage(context) ?? l10n.selectActualPreset;
    }
    if (_fusionMode == 'cached_v9' && _selectedPresetErrorKey != null) {
      return _selectedPresetErrorMessage(context);
    }
    if (_fusionMode == 'cached_v9' &&
        (_legacyQuiet.text.trim().isEmpty ||
            _legacyReference.text.trim().isEmpty)) {
      return l10n.bothLegacyPathsRequired;
    }
    if (!_sourceWindowValidation.isValid) {
      return intervalValidationMessage(l10n, _sourceWindowValidation);
    }
    if (_fusionMode == 'fresh' &&
        parseReferenceFov(_referenceFov.text) == null) {
      return l10n.invalidReferenceFov;
    }
    if (!_intervalValidation.isValid) {
      return intervalValidationMessage(l10n, _intervalValidation);
    }
    if (!_reviewedIntervals) return l10n.reviewManualIntervals;
    return null;
  }

  Future<void> _createPreview() async {
    if (_creatingPreview || widget.controller.isCreatingJob) return;
    final caps = widget.controller.capabilities;
    if (!widget.controller.isApiReady ||
        !isLocalAbsolutePath(_original.text) ||
        caps?.ffmpeg.detected != true) {
      return;
    }
    setState(() => _creatingPreview = true);
    try {
      final job = await widget.controller.createJob(<String, dynamic>{
        'kind': 'preview',
        'source': _original.text.trim(),
        'start': 0,
      });
      if (!mounted) return;
      _showMessage(context.l10n.previewJobCreatedNotice(job.id, job.state));
    } catch (error) {
      _showError(error);
    } finally {
      if (mounted) setState(() => _creatingPreview = false);
    }
  }

  Future<void> _validateOriginal() async {
    if (_validating || widget.controller.isCreatingJob) return;
    if (!widget.controller.isApiReady ||
        !isLocalAbsolutePath(_original.text) ||
        widget.controller.capabilities?.ffprobe.detected != true) {
      return;
    }
    setState(() => _validating = true);
    try {
      final job = await widget.controller.createJob(<String, dynamic>{
        'kind': 'validate',
        'source': _original.text.trim(),
      });
      if (!mounted) return;
      _showMessage(context.l10n.validationJobCreatedNotice(job.id, job.state));
    } catch (error) {
      _showError(error);
    } finally {
      if (mounted) setState(() => _validating = false);
    }
  }

  Future<void> _exportGyroflow() async {
    if (_exporting || widget.controller.isCreatingJob) return;
    final capability = widget.controller.capabilities?.gyroflow;
    if (!widget.controller.isApiReady ||
        !isLocalAbsolutePath(_original.text) ||
        capability?.detected != true ||
        capability?.priorVerificationMatchesConfiguredPath != true ||
        !_gyroflowPathMatchesSavedPreference) {
      return;
    }
    final options = await _showGyroflowExportOptions();
    if (options == null || !mounted) return;

    setState(() => _exporting = true);
    final request = <String, dynamic>{
      'kind': 'gyroflow_export',
      'original': _original.text.trim(),
      'full_source': options.fullSource,
      'output_preset': options.outputPreset,
    };
    if (options.projectTemplate != null) {
      request['project_template'] = options.projectTemplate;
    }
    if (!options.fullSource) {
      request['start'] = options.start;
      request['end'] = options.end;
    }
    try {
      final job = await widget.controller.createJob(request);
      if (!mounted) return;
      _showMessage(context.l10n.gyroflowJobCreatedNotice(job.id, job.state));
    } catch (error) {
      _showError(error);
    } finally {
      if (mounted) setState(() => _exporting = false);
    }
  }

  Future<_GyroflowExportOptions?> _showGyroflowExportOptions() async {
    final projectTemplate = TextEditingController();
    final start = TextEditingController(text: '0');
    final end = TextEditingController(text: '5');
    var fullSource = false;
    var outputPreset = 'reference_1080p';
    try {
      return await showDialog<_GyroflowExportOptions>(
        context: context,
        builder: (dialogContext) => StatefulBuilder(
          builder: (context, setDialogState) {
            final window = validateSourceWindow(start.text, end.text);
            final template = projectTemplate.text.trim();
            final templateValid =
                template.isEmpty || isLocalAbsolutePath(template);
            return AlertDialog(
              shape: ContinuousRectangleBorder(
                borderRadius: BorderRadius.circular(24),
              ),
              title: Text(context.l10n.configureGyroflowExport),
              content: SizedBox(
                width: 500,
                child: SingleChildScrollView(
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    children: <Widget>[
                      TextField(
                        controller: projectTemplate,
                        decoration: InputDecoration(
                          labelText: context.l10n.gyroflowTemplateLabel,
                          helperText: context.l10n.gyroflowTemplateHelper,
                          suffixIcon: IconButton(
                            tooltip: context.l10n.typeProjectTemplatePath,
                            onPressed: () async {
                              final path = await showLocalPathDialog(
                                context,
                                label: context.l10n.projectTemplateLocalPath,
                                initialPath: projectTemplate.text,
                                platform: widget.platform,
                                kind: 'project',
                              );
                              if (path != null) {
                                projectTemplate.text = path;
                                setDialogState(() {});
                              }
                            },
                            icon: const Icon(Icons.edit_outlined),
                          ),
                          border: OutlineInputBorder(
                            borderRadius: BorderRadius.circular(16),
                          ),
                        ),
                        onChanged: (_) => setDialogState(() {}),
                      ),
                      if (!templateValid) ...<Widget>[
                        const SizedBox(height: 6),
                        Text(context.l10n.projectTemplateLocalOnly),
                      ],
                      const SizedBox(height: 14),
                      DropdownButtonFormField<String>(
                        initialValue: outputPreset,
                        decoration: InputDecoration(
                          labelText: context.l10n.outputPreset,
                          helperText: context.l10n.outputPresetHelper,
                          border: OutlineInputBorder(
                            borderRadius: BorderRadius.circular(16),
                          ),
                        ),
                        items: <DropdownMenuItem<String>>[
                          DropdownMenuItem(
                            value: 'reference_1080p',
                            child: Text(context.l10n.reference1080p),
                          ),
                          DropdownMenuItem(
                            value: 'reference_720p',
                            child: Text(context.l10n.reference720p),
                          ),
                        ],
                        onChanged: (value) => setDialogState(
                          () => outputPreset = value ?? 'reference_1080p',
                        ),
                      ),
                      const SizedBox(height: 8),
                      CheckboxListTile(
                        contentPadding: EdgeInsets.zero,
                        controlAffinity: ListTileControlAffinity.leading,
                        value: fullSource,
                        onChanged: (value) =>
                            setDialogState(() => fullSource = value ?? false),
                        title: Text(context.l10n.exportFullSource),
                        subtitle: Text(context.l10n.fullSourceLonger),
                      ),
                      if (!fullSource) ...<Widget>[
                        const SizedBox(height: 8),
                        Row(
                          children: <Widget>[
                            Expanded(
                              child: TextField(
                                controller: start,
                                keyboardType:
                                    const TextInputType.numberWithOptions(
                                      decimal: true,
                                    ),
                                decoration: InputDecoration(
                                  labelText: context.l10n.exportStartSeconds,
                                  border: OutlineInputBorder(
                                    borderRadius: BorderRadius.circular(16),
                                  ),
                                ),
                                onChanged: (_) => setDialogState(() {}),
                              ),
                            ),
                            const SizedBox(width: 10),
                            Expanded(
                              child: TextField(
                                controller: end,
                                keyboardType:
                                    const TextInputType.numberWithOptions(
                                      decimal: true,
                                    ),
                                decoration: InputDecoration(
                                  labelText: context.l10n.exportEndSeconds,
                                  border: OutlineInputBorder(
                                    borderRadius: BorderRadius.circular(16),
                                  ),
                                ),
                                onChanged: (_) => setDialogState(() {}),
                              ),
                            ),
                          ],
                        ),
                        const SizedBox(height: 6),
                        Text(
                          intervalValidationMessage(context.l10n, window) ??
                              context.l10n.defaultReviewSegment,
                          style: window.error == null
                              ? Theme.of(context).textTheme.bodySmall
                              : TextStyle(
                                  color: Theme.of(context).colorScheme.error,
                                ),
                        ),
                      ],
                      const SizedBox(height: 10),
                      NoticeBox(
                        title: context.l10n.renderUnverifiedTitle,
                        message: context.l10n.renderUnverifiedMessage,
                        isWarning: true,
                        icon: Icons.fact_check_outlined,
                      ),
                    ],
                  ),
                ),
              ),
              actions: <Widget>[
                TextButton(
                  onPressed: () => Navigator.of(dialogContext).pop(),
                  child: Text(context.l10n.cancelAction),
                ),
                FilledButton(
                  onPressed: templateValid && (fullSource || window.isValid)
                      ? () {
                          Navigator.of(dialogContext).pop(
                            _GyroflowExportOptions(
                              projectTemplate: template.isEmpty
                                  ? null
                                  : template,
                              fullSource: fullSource,
                              outputPreset: outputPreset,
                              start: window.isValid
                                  ? window.ranges.single.start
                                  : null,
                              end: window.isValid
                                  ? window.ranges.single.end
                                  : null,
                            ),
                          );
                        }
                      : null,
                  child: Text(context.l10n.createExportJob),
                ),
              ],
            );
          },
        ),
      );
    } finally {
      projectTemplate.dispose();
      start.dispose();
      end.dispose();
    }
  }

  Future<void> _requestManualCatalystStage() async {
    if (_requestingManual || widget.controller.isCreatingJob) return;
    final capability = widget.controller.capabilities?.catalyst;
    if (!widget.controller.isApiReady ||
        !isLocalAbsolutePath(_original.text) ||
        capability?.detected != true ||
        capability?.uiaVerified != false) {
      return;
    }
    setState(() => _requestingManual = true);
    try {
      final job = await widget.controller.createJob(<String, dynamic>{
        'kind': 'catalyst_assisted',
        'original': _original.text.trim(),
      });
      if (!mounted) return;
      _showMessage(context.l10n.manualCatalystNotice(job.id, job.state));
    } catch (error) {
      _showError(error);
    } finally {
      if (mounted) setState(() => _requestingManual = false);
    }
  }

  @override
  Widget build(BuildContext context) => LayoutBuilder(
    builder: (context, constraints) {
      // 实际工作区扣除左右 18、间距 20 后，保证表单 600 与任务列 360。
      final twoColumns = constraints.maxWidth >= 1016;
      final taskWidth = ((constraints.maxWidth - 56) * 0.36).clamp(
        360.0,
        440.0,
      );
      return Column(
        children: <Widget>[
          ScreenHeader(
            title: context.l10n.screenWorkbenchTitle,
            subtitle: context.l10n.screenWorkbenchSubtitle,
            trailing: IconButton(
              key: const ValueKey<String>('workbench-open-jobs'),
              tooltip: context.l10n.navJobs,
              onPressed: widget.onOpenJobs,
              icon: const Icon(Icons.view_list_outlined),
            ),
          ),
          Expanded(
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 18),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: <Widget>[
                  Expanded(child: _workspaceList()),
                  if (twoColumns) ...<Widget>[
                    const SizedBox(width: 20),
                    SizedBox(
                      key: const ValueKey<String>('workbench-task-column'),
                      width: taskWidth,
                      child: Column(
                        children: <Widget>[
                          Row(
                            children: <Widget>[
                              Expanded(
                                child: Text(
                                  context.l10n.navJobs,
                                  style: Theme.of(
                                    context,
                                  ).textTheme.titleMedium,
                                ),
                              ),
                              IconButton(
                                tooltip: context.l10n.refreshJobs,
                                onPressed: widget.controller.isApiReady
                                    ? widget.controller.refreshJobs
                                    : null,
                                icon: const Icon(Icons.refresh),
                              ),
                            ],
                          ),
                          Expanded(
                            child: JobsContent(
                              controller: widget.controller,
                              platform: widget.platform,
                              active: widget.active,
                              scrollKey: const PageStorageKey<String>(
                                'workbench-jobs-list',
                              ),
                              padding: const EdgeInsets.only(bottom: 24),
                            ),
                          ),
                        ],
                      ),
                    ),
                  ],
                ],
              ),
            ),
          ),
        ],
      );
    },
  );

  Widget _workspaceList() => ListView(
    key: const ValueKey<String>('workbench-list'),
    padding: const EdgeInsets.only(bottom: 24),
    children: <Widget>[
      ConnectionStatusNotice(controller: widget.controller),
      if (widget.controller.connectionState != AppConnectionState.ready)
        const SizedBox(height: 14),
      _sourceCard(originalOnly: true),
      const SizedBox(height: 14),
      _stabilizeCard(),
      const SizedBox(height: 14),
      ExpansionTile(
        key: const ValueKey<String>('advanced-research'),
        maintainState: true,
        initiallyExpanded: _researchExpanded,
        onExpansionChanged: (value) =>
            setState(() => _researchExpanded = value),
        tilePadding: const EdgeInsets.symmetric(horizontal: 12),
        title: Text(context.l10n.advancedResearchTitle),
        subtitle: Text(context.l10n.advancedResearchSubtitle),
        children: <Widget>[
          NoticeBox(
            title: context.l10n.advancedResearchTitle,
            message: context.l10n.advancedResearchWarning,
            isWarning: true,
          ),
          const SizedBox(height: 14),
          _sourceCard(),
          const SizedBox(height: 14),
          _fusionCard(),
          const SizedBox(height: 14),
          _presetDiscoveryCard(),
          const SizedBox(height: 14),
          _manualIntervalsCard(),
          const SizedBox(height: 14),
          _jobToolsCard(),
          const SizedBox(height: 14),
          CapabilitiesPanel(controller: widget.controller),
        ],
      ),
    ],
  );

  Widget _stabilizeCard() {
    final l10n = context.l10n;
    final supported = widget.controller.capabilities?.supportsStabilize == true;
    final parametersValid = _parsedParameters != null;
    return SectionCard(
      title: l10n.recommendedProfile,
      subtitle: l10n.recommendedProfileSubtitle,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Text(l10n.fullOriginalWorkflow),
          const SizedBox(height: 12),
          NoticeBox(
            title: l10n.automaticWorkflowLimit,
            message: l10n.automaticWorkflowLimitMessage,
            isWarning: true,
            icon: Icons.fact_check_outlined,
          ),
          ExpansionTile(
            key: const ValueKey<String>('stabilize-parameters'),
            maintainState: true,
            initiallyExpanded: _parametersExpanded,
            onExpansionChanged: (value) =>
                setState(() => _parametersExpanded = value),
            title: Text(l10n.stabilizeAdvancedParameters),
            tilePadding: EdgeInsets.zero,
            children: <Widget>[
              for (final entry in _recommendedParameters.entries) ...<Widget>[
                TextField(
                  key: ValueKey<String>('stabilize-parameter-${entry.key}'),
                  controller: entry.value,
                  enabled: !_stabilizing,
                  keyboardType: const TextInputType.numberWithOptions(
                    decimal: true,
                  ),
                  decoration: InputDecoration(
                    labelText: _parameterTitle(entry.key),
                    helperText: _parameterLabel(entry.key),
                    helperMaxLines: 4,
                    border: const OutlineInputBorder(),
                  ),
                  onChanged: (_) => setState(() {}),
                ),
                const SizedBox(height: 12),
              ],
            ],
          ),
          if (!parametersValid)
            Padding(
              padding: const EdgeInsets.only(bottom: 12),
              child: Text(
                l10n.stabilizeParametersInvalid,
                style: TextStyle(color: Theme.of(context).colorScheme.error),
              ),
            ),
          if (!supported && widget.controller.isApiReady)
            Padding(
              padding: const EdgeInsets.only(bottom: 12),
              child: Text(l10n.stabilizeWorkerUnsupported),
            ),
          FilledButton.icon(
            key: const ValueKey<String>('start-stabilize'),
            onPressed:
                supported &&
                    widget.controller.isApiReady &&
                    isLocalAbsolutePath(_original.text) &&
                    parametersValid &&
                    !_stabilizing &&
                    !widget.controller.isCreatingJob
                ? _startStabilize
                : null,
            icon: _stabilizing
                ? const SizedBox.square(
                    dimension: 18,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  )
                : const Icon(Icons.play_arrow),
            label: Text(_stabilizing ? l10n.creatingJob : l10n.startStabilize),
          ),
        ],
      ),
    );
  }

  String _parameterTitle(String key) => switch (key) {
    'quiet_sigma_seconds' => context.l10n.quietSigmaWindow,
    'reference_fov' => context.l10n.referenceFov,
    'alignment_tau_seconds' => context.l10n.alignmentTauName,
    'minimum_weight_transition_seconds' => context.l10n.weightTransitionName,
    'weight_corner_speed' => context.l10n.weightCornerSpeedName,
    'anchor_corner_speed' => context.l10n.anchorCornerSpeedName,
    _ => key,
  };

  String _parameterLabel(String key) => switch (key) {
    'quiet_sigma_seconds' => context.l10n.parameterQuietSigma,
    'reference_fov' => context.l10n.parameterReferenceFov,
    'alignment_tau_seconds' => context.l10n.parameterAlignmentTau,
    'minimum_weight_transition_seconds' => context.l10n.parameterTransition,
    'weight_corner_speed' => context.l10n.parameterWeightSpeed,
    'anchor_corner_speed' => context.l10n.parameterAnchorSpeed,
    _ => key,
  };

  Widget _sourceCard({bool originalOnly = false}) => SectionCard(
    title: originalOnly
        ? context.l10n.importOriginal
        : context.l10n.sourcePaths,
    subtitle: originalOnly
        ? context.l10n.originalImportSubtitle
        : context.l10n.sourcePathsSubtitle,
    child: Column(
      children: <Widget>[
        if (originalOnly)
          SourcePathField(
            key: const ValueKey<String>('original-source-field'),
            label: context.l10n.originalVideo,
            helper: context.l10n.originalVideoHelper,
            kind: 'video',
            pathController: _original,
            appController: widget.controller,
            platform: widget.platform,
            enabled: !_stabilizing,
            dropTargetActive: widget.dropActive && !_stabilizing,
            dropTargetId: 'source',
            onChanged: _sourceChanged,
            onError: _showMessage,
          ),
        if (!originalOnly) ...<Widget>[
          SourcePathField(
            label: context.l10n.ctbInputVideo,
            helper: context.l10n.ctbInputHelper,
            kind: 'video',
            pathController: _ctb,
            appController: widget.controller,
            platform: widget.platform,
            enabled: !_cachedPresetLocked,
            onChanged: _sourceChanged,
            onError: _showMessage,
          ),
          const SizedBox(height: 12),
          SourcePathField(
            label: context.l10n.gyroflowReferenceVideo,
            helper: context.l10n.gyroflowReferenceHelper,
            kind: 'video',
            pathController: _reference,
            appController: widget.controller,
            platform: widget.platform,
            enabled: !_cachedPresetLocked,
            onChanged: _sourceChanged,
            onError: _showMessage,
          ),
        ],
        if (originalOnly
            ? (_original.text.trim().isNotEmpty &&
                  !isLocalAbsolutePath(_original.text))
            : _hasInvalidSourcePath) ...<Widget>[
          const SizedBox(height: 10),
          NoticeBox(
            title: context.l10n.useLocalAbsolutePaths,
            message: context.l10n.invalidSourcePathsMessage,
            isWarning: true,
          ),
        ],
        if (originalOnly) ...<Widget>[
          const SizedBox(height: 10),
          Align(
            alignment: Alignment.centerLeft,
            child: OutlinedButton.icon(
              onPressed:
                  widget.controller.isApiReady &&
                      !_inspecting &&
                      isLocalAbsolutePath(_original.text)
                  ? _inspectOriginal
                  : null,
              icon: const Icon(Icons.search_outlined),
              label: Text(context.l10n.inspectOriginalMetadata),
            ),
          ),
          if (_inspectionError != null) ...<Widget>[
            const SizedBox(height: 10),
            NoticeBox(
              title: context.l10n.inspectionFailed,
              message: localizedError(context.l10n, _inspectionError!),
              isWarning: true,
            ),
          ],
          if (_inspection != null) ...<Widget>[
            const SizedBox(height: 10),
            _MediaInspectionCard(info: _inspection!),
          ],
        ],
      ],
    ),
  );

  Widget _fusionCard() {
    final presets = _c7037Presets;
    final selected = presets.contains(_selectedPreset) ? _selectedPreset : null;
    final holdReason = _fusionHoldReason(widget.controller.capabilities);
    final validation = _intervalValidation;
    final windowValidation = _sourceWindowValidation;
    return SectionCard(
      title: context.l10n.fusionTitle,
      subtitle: context.l10n.fusionSubtitle,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: <Widget>[
              ChoiceChip(
                selected: _fusionMode == 'fresh',
                avatar: const Icon(Icons.play_circle_outline),
                label: Text(context.l10n.freshStrict),
                onSelected: (_) => _chooseFusionMode('fresh'),
              ),
              if (presets.isNotEmpty)
                ChoiceChip(
                  selected: _fusionMode == 'cached_v9',
                  avatar: const Icon(Icons.history_outlined),
                  label: Text(context.l10n.cachedV9),
                  onSelected: (_) => _chooseFusionMode('cached_v9'),
                ),
            ],
          ),
          const SizedBox(height: 12),
          Text(context.l10n.fusionSourceWindow),
          const SizedBox(height: 8),
          Row(
            children: <Widget>[
              Expanded(
                child: _numericField(
                  controller: _windowStart,
                  label: context.l10n.startSeconds,
                  enabled: !_cachedPresetLocked,
                ),
              ),
              const SizedBox(width: 10),
              Expanded(
                child: _numericField(
                  controller: _windowEnd,
                  label: context.l10n.endSeconds,
                  enabled: !_cachedPresetLocked,
                ),
              ),
            ],
          ),
          const SizedBox(height: 6),
          Text(context.l10n.sourceWindowIndependent),
          if (_attemptedFusion && windowValidation.error != null) ...<Widget>[
            const SizedBox(height: 6),
            Text(
              intervalValidationMessage(context.l10n, windowValidation)!,
              style: TextStyle(color: Theme.of(context).colorScheme.error),
            ),
          ],
          const SizedBox(height: 12),
          if (_fusionMode == 'fresh')
            NoticeBox(
              title: context.l10n.strictFreshRun,
              message: context.l10n.strictFreshMessage,
              icon: Icons.rule_outlined,
            )
          else ...<Widget>[
            NoticeBox(
              title: context.l10n.c7037CachedReproduction,
              message: context.l10n.c7037CachedMessage,
              isWarning: true,
              icon: Icons.history_outlined,
            ),
            if (_selectedPresetErrorKey != null) ...<Widget>[
              const SizedBox(height: 10),
              NoticeBox(
                title: context.l10n.invalidCachedPreset,
                message:
                    _selectedPresetErrorMessage(context) ??
                    context.l10n.genericOperationFailed,
                isWarning: true,
              ),
            ],
            const SizedBox(height: 12),
            DropdownButtonFormField<PresetRecord>(
              initialValue: selected,
              decoration: InputDecoration(
                labelText: context.l10n.cachedPresetCatalogLabel,
                border: OutlineInputBorder(
                  borderRadius: BorderRadius.circular(16),
                ),
              ),
              items: presets
                  .map(
                    (preset) => DropdownMenuItem<PresetRecord>(
                      value: preset,
                      child: Text(
                        preset.displayName.isEmpty
                            ? context.l10n.catalogEntry
                            : preset.displayName,
                        overflow: TextOverflow.ellipsis,
                      ),
                    ),
                  )
                  .toList(growable: false),
              onChanged: _selectPreset,
            ),
            const SizedBox(height: 10),
            TextField(
              controller: _legacyQuiet,
              enabled: !_cachedPresetLocked,
              decoration: InputDecoration(
                labelText: context.l10n.legacyQuietCachePath,
                helperText: context.l10n.legacyQuietCacheHelper,
                border: OutlineInputBorder(
                  borderRadius: BorderRadius.circular(16),
                ),
              ),
              onChanged: (_) => setState(_invalidateSelectedPreset),
            ),
            const SizedBox(height: 10),
            TextField(
              controller: _legacyReference,
              enabled: !_cachedPresetLocked,
              decoration: InputDecoration(
                labelText: context.l10n.legacyReferenceCachePath,
                helperText: context.l10n.legacyReferenceCacheHelper,
                border: OutlineInputBorder(
                  borderRadius: BorderRadius.circular(16),
                ),
              ),
              onChanged: (_) => setState(_invalidateSelectedPreset),
            ),
            if ((_legacyQuiet.text.trim().isNotEmpty &&
                    !isLocalAbsolutePath(_legacyQuiet.text)) ||
                (_legacyReference.text.trim().isNotEmpty &&
                    !isLocalAbsolutePath(_legacyReference.text))) ...<Widget>[
              const SizedBox(height: 8),
              NoticeBox(
                title: context.l10n.legacyCacheLocalTitle,
                message: context.l10n.legacyCacheLocalMessage,
                isWarning: true,
              ),
            ],
          ],
          const SizedBox(height: 14),
          Text(context.l10n.timingNormalizationQuiet),
          const SizedBox(height: 8),
          ExpansionTile(
            tilePadding: EdgeInsets.zero,
            childrenPadding: EdgeInsets.zero,
            title: Text(context.l10n.advancedFusionControls),
            subtitle: Text(context.l10n.fusionDefaults),
            children: <Widget>[
              Row(
                children: <Widget>[
                  Expanded(
                    child: _numericField(
                      controller: _ctbOrigin,
                      label: context.l10n.ctbOrigin,
                      enabled: !_cachedPresetLocked,
                    ),
                  ),
                  const SizedBox(width: 10),
                  Expanded(
                    child: _numericField(
                      controller: _referenceOrigin,
                      label: context.l10n.referenceOrigin,
                      enabled: !_cachedPresetLocked,
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 10),
              _numericField(
                controller: _quietSigma,
                label: context.l10n.quietSigmaWindow,
                enabled: !_cachedPresetLocked,
              ),
              const SizedBox(height: 10),
              _numericField(
                controller: _referenceFov,
                label: context.l10n.referenceFov,
                enabled: !_cachedPresetLocked,
              ),
              const SizedBox(height: 8),
              NoticeBox(
                title: context.l10n.referenceFovAnalysisOnly,
                message: context.l10n.referenceFovMessage,
                isWarning: true,
                icon: Icons.crop_free,
              ),
            ],
          ),
          if (_attemptedFusion && validation.error != null) ...<Widget>[
            const SizedBox(height: 8),
            Text(
              intervalValidationMessage(context.l10n, validation)!,
              style: TextStyle(color: Theme.of(context).colorScheme.error),
            ),
          ],
          if (_attemptedFusion && !_reviewedIntervals) ...<Widget>[
            const SizedBox(height: 6),
            Text(
              context.l10n.confirmListedRanges,
              style: TextStyle(color: Theme.of(context).colorScheme.error),
            ),
          ],
          if (holdReason != null &&
              (_attemptedFusion ||
                  !widget.controller.isApiReady ||
                  _original.text.trim().isNotEmpty)) ...<Widget>[
            const SizedBox(height: 10),
            NoticeBox(
              title: context.l10n.fusionHeld,
              message: holdReason,
              isWarning: true,
              icon: Icons.lock_outline,
            ),
          ],
          const SizedBox(height: 14),
          FilledButton.icon(
            onPressed: _canSubmitFusion(widget.controller.capabilities)
                ? _startFusion
                : null,
            icon: _submitting
                ? const SizedBox.square(
                    dimension: 18,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  )
                : const Icon(Icons.play_arrow),
            label: Text(
              _submitting
                  ? context.l10n.creatingJob
                  : context.l10n.createFusionJob,
            ),
          ),
        ],
      ),
    );
  }

  Widget _presetDiscoveryCard() => SectionCard(
    title: context.l10n.presetDiscoveryTitle,
    subtitle: context.l10n.presetDiscoverySubtitle,
    child: Column(
      children: <Widget>[
        SourcePathField(
          label: context.l10n.experimentFolder,
          helper: context.l10n.experimentFolderHelper,
          kind: 'folder',
          pathController: _experimentRoot,
          appController: widget.controller,
          platform: widget.platform,
          onChanged: (_) => setState(() {}),
          onError: _showMessage,
        ),
        const SizedBox(height: 10),
        Align(
          alignment: Alignment.centerLeft,
          child: FilledButton.tonalIcon(
            onPressed:
                widget.controller.isApiReady &&
                    isLocalAbsolutePath(_experimentRoot.text)
                ? _discoverPresets
                : null,
            icon: const Icon(Icons.search_outlined),
            label: Text(context.l10n.discoverPresets),
          ),
        ),
        if (widget.controller.presetDiscoveryError != null) ...<Widget>[
          const SizedBox(height: 10),
          NoticeBox(
            title: context.l10n.presetDiscoveryFailed,
            message: localizedError(
              context.l10n,
              widget.controller.presetDiscoveryError!,
            ),
            isWarning: true,
          ),
        ],
        if (widget.controller.discoveredPresets != null) ...<Widget>[
          const SizedBox(height: 12),
          Align(
            alignment: Alignment.centerLeft,
            child: Text(
              widget.controller.discoveredPresets!.isEmpty
                  ? context.l10n.serviceNoPresets
                  : context.l10n.servicePresetsReturned,
              style: Theme.of(context).textTheme.titleSmall,
            ),
          ),
          for (final preset in widget.controller.discoveredPresets!)
            ListTile(
              contentPadding: EdgeInsets.zero,
              leading: Icon(
                preset.isC7037 ? Icons.bookmark_outline : Icons.folder_outlined,
              ),
              title: Text(
                preset.displayName.isEmpty
                    ? context.l10n.catalogEntry
                    : preset.displayName,
              ),
              subtitle: preset.isC7037
                  ? Text(
                      preset.hasCompleteCachedV9Request
                          ? context.l10n.c7037CachedComplete
                          : context.l10n.metadataOnlyDiscover,
                    )
                  : null,
              onTap: preset.isC7037 && preset.hasCompleteCachedV9Request
                  ? () => _selectPreset(preset)
                  : null,
            ),
        ],
        if (_c7037Presets.isEmpty &&
            widget.controller.discoveredPresets == null) ...<Widget>[
          const SizedBox(height: 8),
          if (_c7037CatalogNeedsDiscovery)
            NoticeBox(
              title: context.l10n.discoverFullC7037First,
              message: context.l10n.metadataCatalogExplanation,
              isWarning: true,
              icon: Icons.search_outlined,
            )
          else
            Text(context.l10n.c7037NeedsCompleteRequest),
        ],
      ],
    ),
  );

  Widget _manualIntervalsCard() {
    final validation = _intervalValidation;
    return SectionCard(
      title: context.l10n.referenceIntervals,
      subtitle: context.l10n.referenceIntervalsSubtitle,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          ManualIntervalEditor(
            entries: _intervals,
            onChanged: _intervalChanged,
            onAdd: _addInterval,
            onRemove: _removeInterval,
            validation: validation,
            showValidation: _attemptedFusion,
            onInsertKnownRanges: _insertKnownRanges,
            enabled: !_cachedPresetLocked,
          ),
          const SizedBox(height: 12),
          CheckboxListTile(
            contentPadding: EdgeInsets.zero,
            controlAffinity: ListTileControlAffinity.leading,
            value: _reviewedIntervals,
            onChanged: (value) =>
                setState(() => _reviewedIntervals = value ?? false),
            title: Text(context.l10n.reviewIntervalsCheckbox),
            subtitle: Text(context.l10n.requiredBeforeFusion),
          ),
          const SizedBox(height: 4),
          NoticeBox(
            title: context.l10n.documentedRangesOptIn,
            message: context.l10n.documentedRangesMessage,
            icon: Icons.info_outline,
          ),
        ],
      ),
    );
  }

  Widget _jobToolsCard() {
    final capabilities = widget.controller.capabilities;
    final ffmpegReady = capabilities?.ffmpeg.detected == true;
    final ffprobeReady = capabilities?.ffprobe.detected == true;
    final gyroflow = capabilities?.gyroflow;
    final catalyst = capabilities?.catalyst;
    final canExport =
        widget.controller.isApiReady &&
        isLocalAbsolutePath(_original.text) &&
        gyroflow?.detected == true &&
        gyroflow?.priorVerificationMatchesConfiguredPath == true &&
        _gyroflowPathMatchesSavedPreference &&
        !_exporting;
    final canManualCatalyst =
        widget.controller.isApiReady &&
        isLocalAbsolutePath(_original.text) &&
        catalyst?.detected == true &&
        catalyst?.uiaVerified == false &&
        !_requestingManual;

    return SectionCard(
      title: context.l10n.otherLocalStages,
      subtitle: context.l10n.otherLocalStagesSubtitle,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: <Widget>[
              FilledButton.tonalIcon(
                onPressed:
                    widget.controller.isApiReady &&
                        isLocalAbsolutePath(_original.text) &&
                        ffmpegReady &&
                        !_creatingPreview &&
                        !widget.controller.isCreatingJob
                    ? _createPreview
                    : null,
                icon: _creatingPreview
                    ? const SizedBox.square(
                        dimension: 16,
                        child: CircularProgressIndicator(strokeWidth: 2),
                      )
                    : const Icon(Icons.movie_outlined),
                label: Text(context.l10n.createPreview),
              ),
              OutlinedButton.icon(
                onPressed:
                    widget.controller.isApiReady &&
                        isLocalAbsolutePath(_original.text) &&
                        ffprobeReady &&
                        !_validating
                    ? _validateOriginal
                    : null,
                icon: _validating
                    ? const SizedBox.square(
                        dimension: 16,
                        child: CircularProgressIndicator(strokeWidth: 2),
                      )
                    : const Icon(Icons.fact_check_outlined),
                label: Text(context.l10n.validateMedia),
              ),
              OutlinedButton.icon(
                onPressed: canExport ? _exportGyroflow : null,
                icon: _exporting
                    ? const SizedBox.square(
                        dimension: 16,
                        child: CircularProgressIndicator(strokeWidth: 2),
                      )
                    : const Icon(Icons.output_outlined),
                label: Text(context.l10n.configureGyroflowExport),
              ),
              if (catalyst?.detected == true && catalyst?.uiaVerified == false)
                OutlinedButton.icon(
                  onPressed: canManualCatalyst
                      ? _requestManualCatalystStage
                      : null,
                  icon: _requestingManual
                      ? const SizedBox.square(
                          dimension: 16,
                          child: CircularProgressIndicator(strokeWidth: 2),
                        )
                      : const Icon(Icons.pan_tool_alt_outlined),
                  label: Text(context.l10n.requestCatalystManual),
                ),
            ],
          ),
          if (!ffmpegReady) ...<Widget>[
            const SizedBox(height: 12),
            NoticeBox(
              title: context.l10n.previewStageUnavailable,
              message: context.l10n.previewUnavailableMessage,
              isWarning: true,
            ),
          ],
          if (!ffprobeReady) ...<Widget>[
            const SizedBox(height: 12),
            NoticeBox(
              title: context.l10n.validationStageUnavailable,
              message: context.l10n.validationUnavailableMessage,
              isWarning: true,
            ),
          ],
          const SizedBox(height: 12),
          NoticeBox(
            title: context.l10n.gyroflowCliSafeguards,
            message: context.l10n.gyroflowSafeguardsMessage,
            isWarning: true,
            icon: Icons.shield_outlined,
          ),
          if (gyroflow?.validationStatus == 'needs_review') ...<Widget>[
            const SizedBox(height: 12),
            NoticeBox(
              title: context.l10n.latestGyroflowNeedsReview,
              message: context.l10n.gyroflowNeedsReviewMessage,
              isWarning: true,
              icon: Icons.fact_check_outlined,
            ),
          ],
          const SizedBox(height: 12),
          NoticeBox(
            title: context.l10n.catalystManualTitle,
            message: context.l10n.catalystManualMessage,
            isWarning: true,
            icon: Icons.pan_tool_alt_outlined,
          ),
          if (catalyst?.detected != true) ...<Widget>[
            const SizedBox(height: 12),
            NoticeBox(
              title: catalyst?.detected == false
                  ? context.l10n.catalystNotDetected
                  : context.l10n.catalystStatusUnknown,
              message: context.l10n.catalystNotStartedMessage,
              isWarning: catalyst?.detected == false,
              icon: Icons.desktop_windows_outlined,
            ),
          ],
          const SizedBox(height: 12),
          Text(context.l10n.gyroClassificationDisabled),
        ],
      ),
    );
  }

  Widget _numericField({
    required TextEditingController controller,
    required String label,
    bool enabled = true,
  }) => TextField(
    controller: controller,
    enabled: enabled,
    keyboardType: const TextInputType.numberWithOptions(
      decimal: true,
      signed: true,
    ),
    decoration: InputDecoration(
      labelText: label,
      border: OutlineInputBorder(borderRadius: BorderRadius.circular(16)),
    ),
    onChanged: (_) => setState(_invalidateSelectedPreset),
  );
}

class _GyroflowExportOptions {
  const _GyroflowExportOptions({
    required this.projectTemplate,
    required this.fullSource,
    required this.outputPreset,
    required this.start,
    required this.end,
  });

  final String? projectTemplate;
  final bool fullSource;
  final String outputPreset;
  final double? start;
  final double? end;
}

class _MediaInspectionCard extends StatelessWidget {
  const _MediaInspectionCard({required this.info});

  final MediaInfo info;

  @override
  Widget build(BuildContext context) {
    final values = <String>[
      if (info.name != null) context.l10n.metadataName(info.name!),
      if (info.width != null && info.height != null)
        context.l10n.dimensions(info.width!, info.height!),
      if (info.fps != null) context.l10n.frameRate(info.fps!),
      if (info.frames != null) context.l10n.frameCount(info.frames!),
      if (info.duration != null) context.l10n.durationSeconds(info.duration!),
      if (info.videoCodec != null) context.l10n.videoCodec(info.videoCodec!),
      if (info.pixelFormat != null) context.l10n.pixelFormat(info.pixelFormat!),
      if (info.audioCodec != null) context.l10n.audioCodec(info.audioCodec!),
      if (info.bitDepth != null) context.l10n.bitDepth(info.bitDepth!),
      if (info.cfrStatus != null) context.l10n.frameTiming(info.cfrStatus!),
    ];
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(14),
      decoration: ShapeDecoration(
        color: Theme.of(context).colorScheme.surfaceContainerHigh,
        shape: ContinuousRectangleBorder(
          borderRadius: BorderRadius.circular(18),
          side: BorderSide(color: Theme.of(context).colorScheme.outlineVariant),
        ),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Text(
            context.l10n.inspectMetadataReturned,
            style: Theme.of(context).textTheme.titleSmall,
          ),
          const SizedBox(height: 8),
          for (final value in values)
            Padding(
              padding: const EdgeInsets.only(bottom: 4),
              child: Text(value),
            ),
          const SizedBox(height: 4),
          Text(context.l10n.dimensionsNotFov),
        ],
      ),
    );
  }
}
