// ignore: unused_import
import 'package:intl/intl.dart' as intl;
import 'app_localizations.dart';

// ignore_for_file: type=lint

/// The translations for English (`en`).
class AppLocalizationsEn extends AppLocalizations {
  AppLocalizationsEn([String locale = 'en']) : super(locale);

  @override
  String workerComponentVersion(Object version) {
    return 'Worker component: $version';
  }

  @override
  String get importOriginal => 'Import original video';

  @override
  String get gyroflowDeclaredChecksPassed =>
      'GF export passed its declared checks; inspect the reported scope.';

  @override
  String get cancellationRequested =>
      'Cancellation requested; waiting for owned work to stop.';

  @override
  String get ctbExecutorUnavailable =>
      'No validated lawful unattended CTB exporter is available. Manual intervention is required; no automatic export has been completed.';

  @override
  String get fullContentCorrespondenceUnverified =>
      'Full-source frame-by-frame content correspondence is not verified. The job remains needs_review and retains diagnostics.';

  @override
  String get originalImportSubtitle =>
      'Read-only local source. The workflow manages its own intermediate outputs.';

  @override
  String get recommendedProfile => 'Recommended · recommended-v1';

  @override
  String get recommendedProfileSubtitle =>
      'A versioned starting point, not a universal quality guarantee.';

  @override
  String get fullOriginalWorkflow =>
      'Process the complete original video with source acceptance, capability checks, CTB, GF, fresh measurement, rigid fusion and final verification.';

  @override
  String get automaticWorkflowLimit => 'Automation is still being verified';

  @override
  String get automaticWorkflowLimitMessage =>
      'No validated unattended CTB exporter is available yet. Starting a job records the real blocker as needs_manual; manual continuation is not automatic stabilization. Measurement failures remain needs_review.';

  @override
  String get stabilizeAdvancedParameters => 'Advanced parameters';

  @override
  String get stabilizeParametersInvalid =>
      'Enter finite values within the displayed ranges. Quality gates cannot be disabled.';

  @override
  String get stabilizeWorkerUnsupported =>
      'This Worker does not report stabilize-v1 support. The advanced research paths remain available.';

  @override
  String get startStabilize => 'Start stabilization';

  @override
  String get advancedResearchTitle =>
      'Advanced research · explicit inputs and history';

  @override
  String get advancedResearchSubtitle =>
      'Three-source fusion, historical presets and standalone stages.';

  @override
  String get advancedResearchWarning =>
      'These are separate research operations, not the single-original automatic workflow. The original video above is shared; CTB/reference inputs, manual ranges and historical cache reproduction keep their original meaning.';

  @override
  String get alignmentTauName => 'Alignment tau';

  @override
  String get weightTransitionName => 'Minimum weight transition';

  @override
  String get weightCornerSpeedName => 'Weight corner speed';

  @override
  String get anchorCornerSpeedName => 'Anchor corner speed';

  @override
  String get parameterQuietSigma => 'Quiet sigma (s) · 0 < value ≤ 10';

  @override
  String get parameterReferenceFov => 'Reference analysis FOV · 1–4×';

  @override
  String get parameterAlignmentTau => 'Alignment tau (s) · 0.01–2';

  @override
  String get parameterTransition => 'Minimum weight transition (s) · 0.04–5';

  @override
  String get parameterWeightSpeed =>
      'Weight corner speed (1280-wide analysis px/s) · 0 < value ≤ 100';

  @override
  String get parameterAnchorSpeed =>
      'Anchor corner speed (1280-wide analysis px/s) · 0 < value ≤ 100';

  @override
  String get dropSingleOriginalHint =>
      'Drop one local media file here to import its path. The Worker still validates the file and streams.';

  @override
  String get nativeDropUnavailable =>
      'Native drop is currently unavailable. Use the local picker or type an absolute path.';

  @override
  String get browserLocalPathNotice =>
      'Browsers cannot expose an Explorer drop as an absolute local path. Use the local-service picker when available, or type the path. No fakepath or media upload is used.';

  @override
  String get jobCreatePending =>
      'A job creation is still pending. Wait for it to finish before starting another.';

  @override
  String get jobKindStabilize => 'Original-video stabilization';

  @override
  String get jobKindStabilizeContinue => 'Manual-CTB continuation';

  @override
  String get manualContinueTitle => 'Continue with manual CTB';

  @override
  String get manualCtbPath => 'Manual CTB video';

  @override
  String get manualCtbOrigin => 'CTB source origin (s, ≥ 0)';

  @override
  String get declareManualCtb =>
      'I declare that this CTB file was exported manually from the same original.';

  @override
  String get createContinuationJob => 'Create linked continuation';

  @override
  String get manualContinuationProvenance =>
      'Manual CTB import creates a new linked job and revalidates it. The parent remains blocked; this does not count as unattended CTB export.';

  @override
  String workflowProfile(Object profile) {
    return 'Workflow profile: $profile';
  }

  @override
  String workflowAttempt(Object attempt) {
    return 'Workflow attempt: $attempt';
  }

  @override
  String workflowParent(Object id) {
    return 'Parent job: $id';
  }

  @override
  String workflowStageStatus(Object stage, Object state) {
    return '$stage: $state';
  }

  @override
  String workflowPreviewStatus(Object state) {
    return 'Output preview: $state';
  }

  @override
  String get openWorkflowPreviewJob => 'Open preview job';

  @override
  String get workflowPending => 'Not started';

  @override
  String get workflowReady => 'Ready for preview';

  @override
  String get workflowPassed => 'Passed declared checks';

  @override
  String get workflowNotRequested => 'Not requested';

  @override
  String get stageSourceAcceptance => 'Source acceptance';

  @override
  String get stageCapabilityPreflight => 'Capability preflight';

  @override
  String get stageCtb => 'CTB export';

  @override
  String get stageGf => 'GF export';

  @override
  String get stageCorrespondence => 'Time and content correspondence';

  @override
  String get stageFreshMeasurement => 'Fresh measurement';

  @override
  String get stageFinalValidation => 'Final verification';

  @override
  String get appTitle => 'ChaSteady';

  @override
  String get navWorkbench => 'Workbench';

  @override
  String get navJobs => 'Jobs';

  @override
  String get navSettings => 'Settings';

  @override
  String get sidebarShowLabels => 'Show navigation labels';

  @override
  String get sidebarHideLabels => 'Hide navigation labels';

  @override
  String get settingsApplication => 'Application';

  @override
  String get settingsNavigation => 'Pages · Ctrl+1 / Ctrl+2 / Ctrl+3';

  @override
  String get settingsLicenses => 'Open-source licenses';

  @override
  String get languageSavesImmediately =>
      'Language changes save separately from tool paths.';

  @override
  String get windowDrag => 'Drag window';

  @override
  String get windowPin => 'Keep window on top';

  @override
  String get windowUnpin => 'Stop keeping window on top';

  @override
  String get windowMinimize => 'Minimize';

  @override
  String get windowMaximize => 'Maximize';

  @override
  String get windowRestore => 'Restore';

  @override
  String get windowClose => 'Close';

  @override
  String get menuFile => 'File';

  @override
  String get menuView => 'View';

  @override
  String get menuHelp => 'Help';

  @override
  String get menuOpenWeb => 'Open Web session';

  @override
  String get menuLanguage => 'Language';

  @override
  String get languageSystem => 'System default';

  @override
  String get languageZh => '简体中文';

  @override
  String get languageEn => 'English';

  @override
  String get helpAbout => 'About ChaSteady';

  @override
  String get helpAboutTitle => 'About ChaSteady';

  @override
  String get helpAboutBody =>
      'ChaSteady is a local-first video stabilization workbench. Footage stays on this computer and jobs are reported by the local worker.';

  @override
  String get helpQualityTitle => 'Quality and verification limits';

  @override
  String get helpQualityBody =>
      'CTB output remains manual and is not a quality or full-field-of-view certificate. Gyroflow exports that do not pass frame, PTS, and content checks remain needs_review. Media verification does not certify a perceptual winner, original FOV, or crop-free output.';

  @override
  String get closeConfirmTitle => 'Close ChaSteady?';

  @override
  String closeActiveJobs(int count) {
    String _temp0 = intl.Intl.pluralLogic(
      count,
      locale: localeName,
      other: 'There are $count active jobs',
      one: 'There is 1 active job',
    );
    return '$_temp0. Closing will ask the local supervisor to stop and wait for its owned work.';
  }

  @override
  String get closeWebWarning =>
      'The Web session will disconnect when the local service shuts down.';

  @override
  String get closeConfirmAction => 'Stop work and close';

  @override
  String get cancelAction => 'Cancel';

  @override
  String get startupFailedTitle => 'ChaSteady could not start';

  @override
  String get startupFailedBody =>
      'The local desktop platform did not finish initializing.';

  @override
  String startupFailureDetails(Object details) {
    return 'Platform-reported details: $details';
  }

  @override
  String get connectingService => 'Connecting to the local service';

  @override
  String get serviceUnavailable => 'Local service unavailable';

  @override
  String get establishingSession => 'Establishing the launcher session.';

  @override
  String get noSessionActive => 'No local session is active';

  @override
  String get sessionNotAccepted =>
      'The local service did not accept this session.';

  @override
  String get retrySession => 'Retry session';

  @override
  String get sessionUnsupported =>
      'The native local-server session adapter is not configured. Open the Web UI from a ChaSteady launcher session.';

  @override
  String get openFromLauncher =>
      'Open this page from the ChaSteady launcher session link. This UI cannot create a session by itself.';

  @override
  String get genericOperationFailed =>
      'The local operation did not complete. Check the service and try again.';

  @override
  String originalServiceMessage(Object message) {
    return 'Original service message: $message';
  }

  @override
  String originalServiceMessageWithCode(Object code, Object message) {
    return 'Original service message ($code): $message';
  }

  @override
  String serviceMessageCodeOnly(Object code) {
    return 'Service message code: $code';
  }

  @override
  String originalWorkerMessage(Object message) {
    return 'Original worker message: $message';
  }

  @override
  String originalWorkerWarning(Object message) {
    return 'Original worker warning: $message';
  }

  @override
  String originalArtifactWarning(Object message) {
    return 'Original artifact warning: $message';
  }

  @override
  String unknownWorkerCode(Object code) {
    return 'Worker message code: $code';
  }

  @override
  String originalWorkerStage(Object stage) {
    return 'Original worker stage: $stage';
  }

  @override
  String originalStatusValue(Object value) {
    return 'Original status value: $value';
  }

  @override
  String get screenWorkbenchTitle => 'Stabilization workspace';

  @override
  String get screenWorkbenchSubtitle =>
      'Import an original, start a job, inspect real stages and outputs.';

  @override
  String get refreshLocalJobs => 'Refresh local jobs';

  @override
  String get localMediaWorkspace => 'Local media workspace';

  @override
  String localMediaWorkspaceMessage(Object appName) {
    return '$appName references absolute local paths. Footage is not uploaded, and the browser never opens an original source as a preview.';
  }

  @override
  String get sourcePaths => 'Source paths';

  @override
  String get sourcePathsSubtitle =>
      'Original video / CTB video / Gyroflow reference video.';

  @override
  String get originalVideo => 'Original video';

  @override
  String get originalVideoHelper =>
      'Read-only local source. A typed absolute path is always supported.';

  @override
  String get ctbInputVideo => 'CTB input video';

  @override
  String get ctbInputHelper =>
      'The CTB input rectangle is not a full-input FOV certificate.';

  @override
  String get gyroflowReferenceVideo => 'Gyroflow reference video';

  @override
  String get gyroflowReferenceHelper =>
      'Fusion reads this as local video media. A .gyroflow project is not a reference video; export templates are configured separately.';

  @override
  String get useLocalAbsolutePaths => 'Use local absolute paths';

  @override
  String get invalidSourcePathsMessage =>
      'Relative paths and URLs are not sent to the worker. Use a drive path such as N:\\folder\\file.mp4 or a local absolute POSIX path.';

  @override
  String get inspectOriginalMetadata => 'Inspect original metadata';

  @override
  String get inspectionFailed => 'Inspection failed';

  @override
  String get fusionTitle => 'CTB fusion';

  @override
  String get fusionSubtitle =>
      'Fresh measurement is strict; cache reuse is an explicit C7037 reproduction.';

  @override
  String get freshStrict => 'Fresh strict';

  @override
  String get cachedV9 => 'Cached v9';

  @override
  String get fusionSourceWindow => 'Fusion source window';

  @override
  String get startSeconds => 'Start (s)';

  @override
  String get endSeconds => 'End (s)';

  @override
  String get sourceWindowIndependent =>
      'This source-processing window is independent of the optional reference-interval list below.';

  @override
  String get strictFreshRun => 'Strict fresh run';

  @override
  String get strictFreshMessage =>
      'No legacy trajectory cache is reused. Missing active pose/correspondence blocks the run. The selected local GF reference may be used without a local Gyroflow executable; automatic gyro classification remains disabled.';

  @override
  String get c7037CachedReproduction => 'C7037 cached reproduction';

  @override
  String get c7037CachedMessage =>
      'This is an explicit approved-cache reproduction, not a fresh measurement. Legacy gap warnings must remain visible in the worker result.';

  @override
  String get invalidCachedPreset => 'Cached preset request invalid';

  @override
  String get cachedPresetCatalogLabel =>
      'C7037 preset from the actual service catalog';

  @override
  String get legacyQuietCachePath => 'Legacy quiet cache path';

  @override
  String get legacyQuietCacheHelper =>
      'Only the selected preset path or an explicit local path is used.';

  @override
  String get legacyReferenceCachePath => 'Legacy reference cache path';

  @override
  String get legacyReferenceCacheHelper =>
      'No cache file is inferred when this field is empty.';

  @override
  String get legacyCacheLocalTitle => 'Legacy cache paths must be local';

  @override
  String get legacyCacheLocalMessage =>
      'Use absolute local paths for both selected C7037 caches. URLs and relative paths are rejected.';

  @override
  String get timingNormalizationQuiet =>
      'Timing, normalization, and quiet-window settings';

  @override
  String get advancedFusionControls => 'Advanced fusion controls';

  @override
  String get fusionDefaults =>
      'Defaults: origins 0 s, quiet sigma 1.3 s, reference FOV 1.0.';

  @override
  String get ctbOrigin => 'CTB origin (s)';

  @override
  String get referenceOrigin => 'Reference origin (s)';

  @override
  String get quietSigmaWindow => 'Quiet sigma window (s)';

  @override
  String get referenceFov => 'Reference FOV (1–4)';

  @override
  String get referenceFovAnalysisOnly => 'Reference FOV is analysis-only';

  @override
  String get referenceFovMessage =>
      'It normalizes the fusion reference and does not change render zoom or guarantee no crop. The default 1.0 preserves the C7037 legacy behavior.';

  @override
  String get confirmListedRanges =>
      'Confirm the listed ranges against the selected footage.';

  @override
  String get fusionHeld => 'Fusion is held';

  @override
  String get creatingJob => 'Creating job…';

  @override
  String get createFusionJob => 'Create fusion job';

  @override
  String get presetDiscoveryTitle => 'Experiment preset discovery';

  @override
  String get presetDiscoverySubtitle =>
      'Scoped catalog lookup only; no whole-disk recursion.';

  @override
  String get experimentFolder => 'Experiment folder';

  @override
  String get experimentFolderHelper =>
      'Point to the real experiment folder to read its catalog.';

  @override
  String get discoverPresets => 'Discover presets';

  @override
  String get presetDiscoveryFailed => 'Preset discovery failed';

  @override
  String get serviceNoPresets =>
      'The service returned no presets for this folder.';

  @override
  String get servicePresetsReturned => 'Presets returned by the service';

  @override
  String get c7037CachedComplete =>
      'C7037 cached reproduction · complete request';

  @override
  String get metadataOnlyDiscover =>
      'Metadata only · discover the full approved request before selection';

  @override
  String get discoverFullC7037First => 'Discover the full C7037 request first';

  @override
  String get metadataCatalogExplanation =>
      'The capabilities catalog contains metadata only. Set the explicit experiment folder above and select Discover presets; the cached preset stays unavailable until the service returns its approved request, including reference_intervals.';

  @override
  String get c7037NeedsCompleteRequest =>
      'C7037 becomes selectable only after the local service returns a complete approved request.';

  @override
  String get referenceIntervals => 'Reference intervals';

  @override
  String get referenceIntervalsSubtitle =>
      'Optional start/end list — no timeline chart, auto-time selector, or gyro classifier.';

  @override
  String get intervalsManualOnly =>
      'Enter only reviewed time ranges. No motion chart or automatic range detection is used.';

  @override
  String get noReferenceIntervals =>
      'No reference intervals selected. An empty list is valid for a CTB-only preset such as Fixed 212–228.';

  @override
  String get addRange => 'Add range';

  @override
  String get insertLabRanges => 'Insert documented lab ranges';

  @override
  String get reviewIntervalsCheckbox =>
      'I reviewed the reference-interval list, including an empty list, against this request.';

  @override
  String get requiredBeforeFusion => 'Required before creating a fusion job.';

  @override
  String get documentedRangesOptIn => 'Documented lab ranges are opt-in';

  @override
  String get documentedRangesMessage =>
      'The insert action adds 153–156 s and 231.8–235.5 s. The separate CTB-only interval 212–228 s is not automatically added to fusion.';

  @override
  String get otherLocalStages => 'Other local stages';

  @override
  String get otherLocalStagesSubtitle =>
      'Actions create real API jobs; the worker owns tool execution and result state.';

  @override
  String get createPreview => 'Create H.264/AAC preview';

  @override
  String get validateMedia => 'Validate media';

  @override
  String get configureGyroflowExport => 'Configure Gyroflow export';

  @override
  String get requestCatalystManual => 'Request Catalyst manual steps';

  @override
  String get previewStageUnavailable => 'Preview stage unavailable';

  @override
  String get previewUnavailableMessage =>
      'FFmpeg is missing or its status is unknown. No preview is claimed until the worker creates a real H.264/AAC artifact.';

  @override
  String get validationStageUnavailable => 'Validation stage unavailable';

  @override
  String get validationUnavailableMessage =>
      'FFprobe is missing or its status is unknown. Validation jobs are held until the configured probe is detected.';

  @override
  String get gyroflowCliSafeguards => 'Gyroflow CLI safeguards';

  @override
  String get gyroflowSafeguardsMessage =>
      'Export is enabled only when the saved executable path matches the service-reported path and the audited CLI/profile guard is verified. The 1080p output preset and a bounded 0–5 second segment are defaults; full source and 720p are explicit choices. Every new render still needs frame, PTS, and content-alignment review.';

  @override
  String get latestGyroflowNeedsReview => 'Latest Gyroflow output needs review';

  @override
  String get gyroflowNeedsReviewMessage =>
      'The service reports needs_review and does not claim verified export or trim mapping. A CLI exit code of 0 is not a successful output-validation result.';

  @override
  String get catalystManualTitle =>
      'Catalyst assisted export · needs manual steps';

  @override
  String get catalystManualMessage =>
      'This UI never starts Catalyst automation. The owned-window probe did not expose controls and changed a Sony profile log; this stage remains manual.';

  @override
  String get catalystNotDetected => 'Catalyst not detected';

  @override
  String get catalystStatusUnknown => 'Catalyst status unknown';

  @override
  String get catalystNotStartedMessage =>
      'No Catalyst stage is started from this UI. An installed executable alone never means the UI stage is verified.';

  @override
  String get gyroClassificationDisabled =>
      'Automatic gyro classification is disabled. Source codec support is not assumed; use a real preview artifact for browser playback.';

  @override
  String get inspectMetadataReturned => 'Metadata returned by the worker';

  @override
  String dimensions(Object width, Object height) {
    return 'Dimensions: $width × $height';
  }

  @override
  String frameRate(Object fps) {
    return 'Frame rate: $fps fps';
  }

  @override
  String frameCount(Object frames) {
    return 'Frames: $frames';
  }

  @override
  String durationSeconds(Object duration) {
    return 'Duration: $duration s';
  }

  @override
  String metadataName(Object name) {
    return 'Name: $name';
  }

  @override
  String videoCodec(Object value) {
    return 'Video codec: $value';
  }

  @override
  String audioCodec(Object value) {
    return 'Audio codec: $value';
  }

  @override
  String pixelFormat(Object value) {
    return 'Pixel format: $value';
  }

  @override
  String bitDepth(Object value) {
    return 'Bit depth: $value';
  }

  @override
  String frameTiming(Object value) {
    return 'Frame timing: $value';
  }

  @override
  String get dimensionsNotFov =>
      'Dimensions do not certify the full-input field of view.';

  @override
  String get gyroflowDialogTitle => 'Configure Gyroflow export';

  @override
  String get gyroflowTemplateLabel => 'Gyroflow project template (optional)';

  @override
  String get gyroflowTemplateHelper =>
      'This is explicit; the fusion reference is never inferred as an export template.';

  @override
  String get typeProjectTemplatePath => 'Type local project template path';

  @override
  String get projectTemplateLocalPath => 'Gyroflow project template';

  @override
  String get projectTemplateLocalOnly =>
      'Project template must be a local absolute path.';

  @override
  String get outputPreset => 'Output preset';

  @override
  String get outputPresetHelper =>
      'Choose an approved reference_1080p or reference_720p worker preset; arbitrary size, codec, and commands are not accepted.';

  @override
  String get reference1080p => 'Reference 1080p';

  @override
  String get reference720p => 'Reference 720p';

  @override
  String get exportFullSource => 'Export full source';

  @override
  String get fullSourceLonger =>
      'Optional and off by default; a full-source render may take much longer.';

  @override
  String get exportStartSeconds => 'Export start (s)';

  @override
  String get exportEndSeconds => 'Export end (s)';

  @override
  String get defaultReviewSegment =>
      'Default review segment: 0–5 seconds. Adjust to match the source.';

  @override
  String get renderUnverifiedTitle => 'Render output remains unverified';

  @override
  String get renderUnverifiedMessage =>
      'A successful process exit does not verify frame count, PTS alignment, or content alignment.';

  @override
  String get createExportJob => 'Create export job';

  @override
  String manualCatalystNotice(Object id, Object state) {
    return 'Catalyst stage $id · $state. No automatic action was started by the UI.';
  }

  @override
  String jobCreatedNotice(Object kind, Object id, Object state) {
    return 'Created $kind job $id · $state. The worker has not reported a result yet.';
  }

  @override
  String previewJobCreatedNotice(Object id, Object state) {
    return 'Created preview job $id · $state.';
  }

  @override
  String validationJobCreatedNotice(Object id, Object state) {
    return 'Created validation job $id · $state.';
  }

  @override
  String gyroflowJobCreatedNotice(Object id, Object state) {
    return 'Created Gyroflow export $id · $state. Frame/PTS/content verification is still required.';
  }

  @override
  String get sourceWindowInvalid =>
      'Enter both fusion source-window start and end values.';

  @override
  String intervalNonNumeric(int row) {
    return 'Interval $row needs numeric start and end values.';
  }

  @override
  String intervalNegativeStart(int row) {
    return 'Interval $row cannot start before 0 seconds.';
  }

  @override
  String intervalEndNotAfterStart(int row) {
    return 'Interval $row end must be after its start.';
  }

  @override
  String get intervalChronologicalOrder =>
      'Intervals must be listed in chronological order.';

  @override
  String intervalOverlap(int row) {
    return 'Interval $row overlaps the interval before it.';
  }

  @override
  String get invalidTimingValues =>
      'Timing values must be finite, quiet sigma must be positive, and reference FOV must be from 1 to 4.';

  @override
  String get invalidReferenceFov =>
      'Reference FOV normalization must be a number from 1 to 4.';

  @override
  String get sessionRequiredBeforeJob =>
      'A valid launcher session is required before creating jobs.';

  @override
  String get localPathsOnly =>
      'Use local absolute paths only; URLs and relative paths are rejected.';

  @override
  String get legacyPathsMustBeAbsolute =>
      'Legacy cache paths must be local absolute paths.';

  @override
  String get toolStatusNotReturned =>
      'Tool capability status has not been returned by the service.';

  @override
  String get ffmpegMissingHeld =>
      'FFmpeg is missing or its status is unknown. Fusion output is held.';

  @override
  String get selectActualPreset =>
      'Select an actual C7037 preset returned by the service.';

  @override
  String get bothLegacyPathsRequired =>
      'The selected preset request must include both legacy cache paths.';

  @override
  String get reviewManualIntervals =>
      'Review the manual intervals against these sources.';

  @override
  String get catalogFieldChanged =>
      'A catalog request field changed. Select the approved preset again before cached_v9 can run.';

  @override
  String get metadataOnlyCatalogError =>
      'This catalog item contains metadata only. Enter its explicit experiment folder and use Discover presets to load the full approved request before selection.';

  @override
  String get invalidReferenceInterval =>
      'The catalog preset contains an invalid reference interval.';

  @override
  String get nonFiniteReferenceInterval =>
      'The catalog preset contains a non-finite reference interval.';

  @override
  String get missingReferenceIntervals =>
      'The catalog preset has no reference_intervals array.';

  @override
  String get missingCachedRequestField =>
      'The catalog entry is missing a required cached_v9 request field.';

  @override
  String get catalogNonLocalPath =>
      'The catalog request contains a non-local path.';

  @override
  String get enterLocalAbsoluteFolder =>
      'Enter a local absolute experiment folder path.';

  @override
  String get jobRequestKindRequired => 'A supported job kind is required.';

  @override
  String get jobFieldsNested => 'Job fields must be nested under request.';

  @override
  String get jobRequestObject => 'Job request must be an object.';

  @override
  String get invalidArtifactOpen =>
      'This artifact cannot be opened as a local preview.';

  @override
  String get toolAvailability => 'Tool availability';

  @override
  String get capabilitiesUnavailable => 'Capabilities unavailable';

  @override
  String get toolStatusUnknown => 'Status unknown';

  @override
  String get capabilitiesNotProvided =>
      'The local service has not provided capability data for this session.';

  @override
  String get waitingToolStatus => 'Waiting for local tool status.';

  @override
  String get toolAvailabilityProvenance => 'Tool availability & provenance';

  @override
  String workerVersion(Object version) {
    return 'Worker $version';
  }

  @override
  String get ffmpeg => 'FFmpeg';

  @override
  String get ffprobe => 'FFprobe';

  @override
  String get gyroflow => 'Gyroflow';

  @override
  String get catalyst => 'Catalyst';

  @override
  String get gyroflowBuild => 'Gyroflow build';

  @override
  String get cliStatus => 'CLI status';

  @override
  String get priorCliInvocation => 'Prior CLI invocation';

  @override
  String get savedPathProfileGuard => 'Saved-path profile guard';

  @override
  String get latestExportValidation => 'Latest export validation';

  @override
  String get latestMediaExportVerified => 'Latest media export verified';

  @override
  String get latestTrimMappingVerified => 'Latest trim mapping verified';

  @override
  String get profileSafety => 'Profile safety';

  @override
  String get exportHeldProfileSafety => 'Export held for profile safety';

  @override
  String get profileSafetyMismatchMessage =>
      'The service-reported executable and saved tool_paths.gyroflow do not both match a verified CLI/profile guard. Save the audited executable path and refresh its capability status before exporting. ChaSteady keeps export held.';

  @override
  String get boundedExportNeedsReview => 'Latest bounded export needs review';

  @override
  String get boundedExportNeedsReviewMessage =>
      'The service reports needs_review. A successful CLI exit or prior invocation does not verify this output; media export and trim mapping remain separate checks.';

  @override
  String get exportNeedsVerification =>
      'A real export still needs verification';

  @override
  String get exportVerificationMessage =>
      'The prior CLI/profile check is a launch guard only. Each new rendered export needs frame, PTS, and content-alignment review before it can be trusted.';

  @override
  String get catalystManualRequired =>
      'Catalyst assisted export · manual required';

  @override
  String get catalystManualRequiredMessage =>
      'This UI does not expose an automatic Catalyst button. The current owned-window probe did not expose controls and changed a Sony profile log; the stage remains manual regardless of installation detection.';

  @override
  String get someStagesUnavailable => 'Some stages may be unavailable';

  @override
  String get missingToolsTruthful =>
      'Missing or unknown executables are shown as such. Jobs are not marked complete when a tool is absent.';

  @override
  String get detected => 'Detected';

  @override
  String get notDetected => 'Not detected';

  @override
  String get statusUnknown => 'Status unknown';

  @override
  String toolCapabilitySemantics(Object status) {
    return '$status tool capability';
  }

  @override
  String configuredPath(Object path) {
    return 'Configured path: $path';
  }

  @override
  String modeValue(Object mode) {
    return 'Mode: $mode';
  }

  @override
  String gyroflowBuildValue(Object value) {
    return 'Gyroflow build: $value';
  }

  @override
  String get verified => 'Verified';

  @override
  String get notVerified => 'Not verified';

  @override
  String get unknown => 'Unknown';

  @override
  String get reportedTrue => 'Reported true';

  @override
  String get reportedFalse => 'Reported false';

  @override
  String get blocked => 'Blocked';

  @override
  String get unverified => 'Unverified';

  @override
  String get verifiedMedia => 'Verified media';

  @override
  String get cliBlocked => 'CLI blocked';

  @override
  String get notAudited => 'Not audited';

  @override
  String get required => 'Required';

  @override
  String get notRequired => 'Not required';

  @override
  String get savedPathMismatch => 'Saved path mismatch';

  @override
  String get cliProfileGuardUnavailable => 'CLI/profile guard unavailable';

  @override
  String get verifiedForSavedPath => 'Verified for saved path';

  @override
  String originalStatusLabel(Object value) {
    return 'Original status: $value';
  }

  @override
  String get screenSettingsSubtitle =>
      'Local appearance and reported runtime status.';

  @override
  String get appearance => 'Appearance';

  @override
  String get preferencesLocalOnly =>
      'Preferences are stored by the local service. No account or cloud sync is used.';

  @override
  String get theme => 'Theme';

  @override
  String get themeSystem => 'System';

  @override
  String get themeLight => 'Light';

  @override
  String get themeDark => 'Dark';

  @override
  String get language => 'Language';

  @override
  String get brandSeed => 'Brand seed';

  @override
  String get seedGreenGray => 'ChaSteady green-gray';

  @override
  String get seedMistBlue => 'Mist blue';

  @override
  String get seedClay => 'Clay';

  @override
  String get seedSoftViolet => 'Soft violet';

  @override
  String get systemAccentFallback => 'System accent fallback';

  @override
  String get systemAccentFallbackMessage =>
      'A verified Windows accent color is not provided by the local service. The saved ChaSteady seed is used instead.';

  @override
  String get savedPreferencesUnavailable => 'Saved preferences unavailable';

  @override
  String get preferencesNotSaved => 'Preferences were not saved';

  @override
  String get savePreferences => 'Save preferences';

  @override
  String get saved => 'Saved';

  @override
  String get waitingPreferenceRecord =>
      'Waiting for the local preference record';

  @override
  String get executablePaths => 'Executable paths';

  @override
  String get executablePathsSubtitle =>
      'Configure the known local FFmpeg, FFprobe, Gyroflow, and Catalyst tools.';

  @override
  String get privacyScope => 'Privacy & scope';

  @override
  String get mediaPathsLocal =>
      'Media paths are local absolute paths; footage is not uploaded.';

  @override
  String get noCloudModels =>
      'No cloud models, analytics, or remote font assets are used.';

  @override
  String get browserPreviewOwned =>
      'The browser preview is limited to owned H.264/AAC proxy artifacts.';

  @override
  String get ffmpegExecutable => 'FFmpeg executable';

  @override
  String get ffprobeExecutable => 'FFprobe executable';

  @override
  String get gyroflowCliExecutable => 'Gyroflow CLI executable';

  @override
  String get catalystExecutable => 'Catalyst executable';

  @override
  String get toolPathsPersistedMessage =>
      'These app-owned paths are persisted through the local service and apply to future jobs. They are not per-job command overrides.';

  @override
  String get absolutePathClearHelper =>
      'Absolute local path; leave blank only to clear this setting.';

  @override
  String typeToolPath(Object tool) {
    return 'Type local $tool path';
  }

  @override
  String clearToolPath(Object tool) {
    return 'Clear $tool path';
  }

  @override
  String get toolPathRecordUnavailable => 'Tool path record unavailable';

  @override
  String get toolPathRecordUnavailableMessage =>
      'The service did not return all four known executable paths. Saving is disabled so an unknown path cannot be cleared accidentally.';

  @override
  String get absoluteExecutablePaths => 'Use absolute local executable paths';

  @override
  String get invalidToolPathMessage =>
      'Relative paths and URLs cannot be saved as tool paths.';

  @override
  String get unsavedToolPaths => 'Unsaved tool paths';

  @override
  String get unsavedToolPathsMessage =>
      'Save preferences to persist these ChaSteady tool paths.';

  @override
  String get toolExecutableFallback => 'tool executable';

  @override
  String get screenJobsSubtitle =>
      'Only jobs returned by the local worker appear here.';

  @override
  String get refreshJobs => 'Refresh jobs';

  @override
  String get queueLoadFailed => 'Could not load the queue';

  @override
  String get waitingQueueData => 'Waiting for queue data';

  @override
  String get serviceNoJobList => 'The service has not returned a job list yet.';

  @override
  String get queueUnavailable => 'Queue unavailable';

  @override
  String get queueUnknownNotEmpty =>
      'No local session is active, so the job list is unknown—not empty.';

  @override
  String get noJobsYet => 'No jobs yet';

  @override
  String get emptyQueueDescription =>
      'The local service returned an empty queue. Create a job from the Workbench when its sources and required tools are ready.';

  @override
  String get latestJobDetailsUnavailable => 'Latest job details unavailable';

  @override
  String get screenJobsError => 'Could not load job details';

  @override
  String get jobActivity => 'Job activity';

  @override
  String get waitingLocalQueue => 'Waiting for the local queue';

  @override
  String realJobsCount(int count) {
    String _temp0 = intl.Intl.pluralLogic(
      count,
      locale: localeName,
      other: '$count real jobs from the service',
      one: '1 real job from the service',
    );
    return '$_temp0';
  }

  @override
  String get resizeJobActivityPanel => 'Resize job activity panel';

  @override
  String get resizeJobSheet => 'Resize job sheet';

  @override
  String get queueCouldNotRefresh => 'Queue could not be refreshed';

  @override
  String get loadingLocalJobs => 'Loading local jobs';

  @override
  String get queueEmpty => 'Queue is empty';

  @override
  String get noJobsReturned =>
      'No jobs have been returned by the local service. A job appears here only after the service creates one.';

  @override
  String get jobDetails => 'Job details';

  @override
  String get jobError => 'Job error';

  @override
  String get manualActionRequired => 'Manual action required';

  @override
  String get manualActionMessage =>
      'No UI automation success is assumed. Follow only the explicit next steps returned by the local worker.';

  @override
  String get reviewBeforeContinue => 'Review before continuing';

  @override
  String get reviewPerceptualFovMessage =>
      'The worker has not certified a perceptual winner or original-field-of-view result.';

  @override
  String get evidenceScopeLimited => 'Evidence scope is limited';

  @override
  String get verifiedMediaScopeMessage =>
      'This status confirms media/geometry evidence only. It is not a perceptual winner or an original FOV certificate.';

  @override
  String get interpretationLimits => 'Interpretation limits';

  @override
  String get fusionScopeMessage =>
      'Source FOV is unverified; CTB describes the input rectangle only. No crop or quality claim is inferred from this screen.';

  @override
  String get exportVerificationRequired => 'Export verification still required';

  @override
  String get exportVerificationDetails =>
      'A successful process exit does not validate frame count, PTS alignment, or content alignment. Source FOV remains unverified.';

  @override
  String get ownedOutputs => 'Owned outputs';

  @override
  String workerWarningsCount(int count) {
    return 'Worker warnings · $count';
  }

  @override
  String get workerResultDetails => 'Worker result details';

  @override
  String reportedScope(Object scope) {
    return 'Reported scope: $scope. This states what was checked only; it is not a perceptual/content or original-FOV certification.';
  }

  @override
  String reportedReferenceFov(Object value) {
    return 'Reported reference FOV metadata: $value (analysis only)';
  }

  @override
  String get fovNotCropGuarantee => 'FOV metadata is not a crop guarantee';

  @override
  String get fovNoCropDetails =>
      'Reference normalization does not change render zoom and does not certify that the output is crop-free.';

  @override
  String get artifactValidationScope => 'Artifact validation scope';

  @override
  String get artifactPreview =>
      'Local H.264/AAC preview. The browser requests this owned artifact with byte ranges; the original is not streamed.';

  @override
  String get previewCodecUnknown =>
      'Preview codec metadata is not confirmed. No browser-decoder support is assumed; create or inspect a real H.264/AAC preview.';

  @override
  String artifactWarningsCount(int count) {
    return 'Artifact warnings · $count';
  }

  @override
  String get openLocalOutput => 'Open local output';

  @override
  String get unsupportedBrowserPlayback =>
      'Local browser playback is not available on this platform. Create a real preview artifact and use the web workbench.';

  @override
  String get localPreviewSemantics => 'Local H.264/AAC preview';

  @override
  String get jobStateQueued => 'Queued';

  @override
  String get jobStateRunning => 'Running';

  @override
  String get jobStateNeedsManual => 'Needs manual step';

  @override
  String get jobStateNeedsReview => 'Needs review';

  @override
  String get jobStateFailed => 'Failed';

  @override
  String get jobStateCancelled => 'Cancelled';

  @override
  String get jobStateVerifiedMedia => 'Verified media evidence only';

  @override
  String unknownJobState(Object state) {
    return 'Status: $state';
  }

  @override
  String get progressNotReported => 'Progress not reported';

  @override
  String get currentStage => 'Current stage';

  @override
  String stageProgressUnknown(Object stage) {
    return '$stage progress unknown';
  }

  @override
  String stageProgressPercent(Object stage, int percent) {
    return '$stage progress $percent percent';
  }

  @override
  String get indeterminateProgress => 'Indeterminate';

  @override
  String get noWorkerPercentage =>
      'The worker has not reported a percentage for this stage.';

  @override
  String stageValue(Object stage) {
    return 'Stage: $stage';
  }

  @override
  String warningCount(int count) {
    String _temp0 = intl.Intl.pluralLogic(
      count,
      locale: localeName,
      other: '$count warnings from the worker',
      one: '1 warning from the worker',
    );
    return '$_temp0';
  }

  @override
  String get cancelJob => 'Cancel job';

  @override
  String get jobKindFusion => 'CTB fusion';

  @override
  String get jobKindPreview => 'Browser preview';

  @override
  String get jobKindGyroflowExport => 'Gyroflow export';

  @override
  String get jobKindCatalyst => 'Catalyst assisted stage';

  @override
  String get jobKindValidate => 'Media validation';

  @override
  String jobKindUnknown(Object kind) {
    return 'Original job kind: $kind';
  }

  @override
  String get toolStatusDetected => 'Detected';

  @override
  String get toolStatusMissing => 'Not detected';

  @override
  String pickerChooseLocal(Object kind) {
    return 'Choose local $kind';
  }

  @override
  String get pickerEnterLocal => 'Enter local path';

  @override
  String pathDialogTitle(Object label) {
    return 'Enter local $label path';
  }

  @override
  String get absoluteLocalPath => 'Absolute local path';

  @override
  String get pathStaysLocal =>
      'The file stays on this computer. Browser file upload is not used.';

  @override
  String get usePath => 'Use path';

  @override
  String get cancel => 'Cancel';

  @override
  String get workerStarting => 'Starting the local worker.';

  @override
  String get workerCancelledBeforeStart =>
      'Cancelled before processing started.';

  @override
  String get workerCancellationRequested =>
      'Cancellation requested; owned work was stopped.';

  @override
  String get workerInspectSource => 'Inspecting the selected source media.';

  @override
  String get workerInspectFusionInputs =>
      'Inspecting inputs and selected source-frame timestamps.';

  @override
  String get workerCachedTrajectory =>
      'Reading the approved C7037 historical trajectory; this is not a new measurement.';

  @override
  String get workerComputeFusion =>
      'Computing the two-anchor global rigid trajectory without blending Gyroflow pixels.';

  @override
  String workerRegistrationProgress(int current, int total) {
    return 'Registering frame $current of $total.';
  }

  @override
  String workerRenderProgress(int current, int total) {
    return 'Rendering frame $current of $total.';
  }

  @override
  String get workerVerifyOutput =>
      'Fully decoding and verifying video and corresponding source audio.';

  @override
  String get workerPreviewInspect =>
      'Inspecting source media to prepare a local browser preview.';

  @override
  String get workerPreviewEncode =>
      'Encoding an H.264/AAC preview; the encoder did not provide verified numeric progress.';

  @override
  String get workerValidateMedia =>
      'Fully decoding audio and video, then checking actual frame count and requested frame rate.';

  @override
  String get workerCatalystManual =>
      'Catalyst automation is not verified; manual steps are required.';

  @override
  String jobErrorCode(Object code) {
    return 'Error code: $code';
  }

  @override
  String serviceHttpError(int statusCode) {
    return 'The local service returned HTTP $statusCode.';
  }

  @override
  String get mode => 'Mode';

  @override
  String get uiAutomationVerification => 'UI automation verification';

  @override
  String get stageStarting => 'Starting';

  @override
  String get stageInspect => 'Inspecting media';

  @override
  String get stagePreviewEncode => 'Encoding preview';

  @override
  String get stageMediaValidation => 'Media validation';

  @override
  String get stageCachedTrajectory => 'Loading approved cached trajectory';

  @override
  String get stageFusion => 'Fusion';

  @override
  String get stageRegistration => 'Frame registration';

  @override
  String get stageQuietTracking => 'Quiet-window tracking';

  @override
  String get stageRender => 'Rendering';

  @override
  String get stageVerify => 'Verifying output';

  @override
  String get stageCatalystManual => 'Catalyst manual handoff';

  @override
  String get workerQueued => 'Waiting in the local worker queue.';

  @override
  String get workerNeedsManual =>
      'The worker requires a manual step; no automatic action was performed.';

  @override
  String get workerNeedsReview =>
      'The worker requires review before this result can be trusted.';

  @override
  String get workerFailed => 'The worker could not complete this task.';

  @override
  String get workerCancelled => 'The worker cancelled this task.';

  @override
  String get workerVerifiedMedia =>
      'Media evidence was verified; this does not certify perceptual quality or original FOV.';

  @override
  String workerQuietTrackingProgress(int current, int total) {
    return 'Tracking quiet frame $current of $total.';
  }

  @override
  String get workerErrorNeedsReview =>
      'This result requires manual review and is not certified.';

  @override
  String get workerErrorNeedsManual =>
      'This task requires manual steps; the UI did not automate them.';

  @override
  String get workerErrorCancelled => 'The task was cancelled.';

  @override
  String get workerErrorInterrupted =>
      'The owned worker was interrupted before completion.';

  @override
  String get workerErrorMissingCapability =>
      'A required local tool capability is unavailable.';

  @override
  String get workerErrorProcessingFailed =>
      'The local worker could not process this request.';

  @override
  String get playerLoading => 'Loading preview';

  @override
  String get playerPlay => 'Play';

  @override
  String get playerPause => 'Pause';

  @override
  String get playerSeek => 'Seek';

  @override
  String get playerVolume => 'Volume';

  @override
  String get playerMute => 'Mute';

  @override
  String get playerUnmute => 'Unmute';

  @override
  String playerError(Object code) {
    return 'Player error: $code';
  }

  @override
  String get playerFinished => 'Playback finished';

  @override
  String get nativeLeaseUnavailable =>
      'The local media preview lease is unavailable.';

  @override
  String get nativeActionUnsupported =>
      'This native platform action is not supported.';

  @override
  String get nativeProtocolUnsupported =>
      'The native platform protocol version is not supported.';

  @override
  String get nativeProtocolError =>
      'The native platform request could not be completed.';

  @override
  String intervalStartLabel(int row) {
    return 'Start $row (seconds)';
  }

  @override
  String intervalEndLabel(int row) {
    return 'End $row (seconds)';
  }

  @override
  String intervalExample(Object value) {
    return 'e.g. $value';
  }

  @override
  String removeInterval(int row) {
    return 'Remove interval $row';
  }

  @override
  String get cliMode => 'CLI';

  @override
  String originalArtifactLabel(Object label) {
    return 'Worker-provided artifact label: $label';
  }

  @override
  String artifactFormat(Object kind, Object mime) {
    return 'Worker-reported artifact type: $kind · media type: $mime';
  }

  @override
  String artifactKindUnknown(Object kind) {
    return 'Original artifact type: $kind';
  }

  @override
  String get desktopActionsUnavailable =>
      'Native desktop actions are unavailable on this platform.';

  @override
  String get invalidJobsList =>
      'The local service returned an invalid jobs list.';

  @override
  String get invalidPresetCatalog =>
      'The local service returned an invalid preset catalog.';

  @override
  String get invalidServiceResponse =>
      'The local service returned an invalid response.';

  @override
  String get invalidLocalResourceId =>
      'The service returned an invalid local resource identifier.';

  @override
  String get missingJobRecord =>
      'The local service did not return a job record.';

  @override
  String localConnectionFailed(Object appName) {
    return 'Could not reach the local $appName service.';
  }

  @override
  String get invalidApiJobKind => 'A supported job kind is required.';

  @override
  String get apiJobFieldsNested => 'Job fields must be nested under request.';

  @override
  String get apiJobRequestInvalid => 'Job request must be an object.';

  @override
  String get invalidArtifactPreview =>
      'This artifact cannot be opened as a local preview.';

  @override
  String get catalogEntry => 'Unnamed catalog entry';

  @override
  String get unnamedArtifact => 'Unnamed artifact';

  @override
  String get nativeProtocolInvalidRequest =>
      'The native protocol request is invalid.';

  @override
  String get nativeWorkerStopping => 'The local worker is stopping.';

  @override
  String get nativeWorkerStopped => 'The local worker has stopped.';

  @override
  String get nativeWorkerStartup => 'The local worker could not start.';

  @override
  String get nativeWorkerBundle => 'The packaged worker bundle is unavailable.';

  @override
  String get nativeWorkerDataRoot =>
      'The local worker data directory is unavailable.';

  @override
  String get nativeWorkerAlreadyRunning =>
      'A ChaSteady worker is already running.';

  @override
  String get nativeWorkerDiagnostics =>
      'The local worker diagnostics stream is unavailable.';

  @override
  String get nativeWorkerPipe => 'The local worker communication pipe failed.';

  @override
  String get nativeWorkerJob => 'The native worker rejected the job request.';

  @override
  String get nativeWorkerReady => 'The local worker did not become ready.';

  @override
  String get nativeWorkerNotReady => 'The local worker is not ready.';

  @override
  String get nativeWorkerRequestLimit =>
      'The native worker request exceeded its allowed size.';

  @override
  String get nativeWorkerProtocol =>
      'The native worker protocol request is invalid.';

  @override
  String get nativeWorkerExited => 'The local worker exited unexpectedly.';

  @override
  String get nativeWorkerTimeout =>
      'The local worker did not respond before the timeout.';

  @override
  String get nativePickerInvalidKind =>
      'This local file picker type is not supported.';

  @override
  String get nativePickerFailed => 'The local file picker could not complete.';

  @override
  String get nativeMediaInvalidArtifact => 'This preview artifact is invalid.';

  @override
  String get nativeMediaInvalidLease =>
      'A valid local media lease could not be obtained.';

  @override
  String get nativeMediaUnavailable => 'Native media playback is unavailable.';

  @override
  String get nativeMediaInvalidPlayer =>
      'The native media player could not be created.';

  @override
  String get nativeMediaInvalidPosition =>
      'The requested seek position is invalid.';

  @override
  String get nativeMediaInvalidVolume =>
      'The requested volume value is invalid.';

  @override
  String get nativeMediaInvalidMuted => 'The requested mute state is invalid.';

  @override
  String get nativeMediaPlayerNotFound =>
      'The native media player was not found.';

  @override
  String get nativeMediaDisposeFailed =>
      'The native media player could not be released cleanly.';

  @override
  String get nativeMediaPlayerAction =>
      'The requested native media player action failed.';

  @override
  String get nativeWebInvalidSession => 'The local Web session is invalid.';

  @override
  String get nativeWebOpenFailed => 'The Web session could not be opened.';

  @override
  String nativeErrorCode(Object code) {
    return 'Platform error code: $code';
  }

  @override
  String nativeOriginalPlatformMessage(Object message) {
    return 'Original platform message: $message';
  }

  @override
  String nativeOriginalHresult(Object value) {
    return 'Original HRESULT: $value';
  }

  @override
  String nativeOriginalPlatformArgs(Object args) {
    return 'Original platform arguments: $args';
  }

  @override
  String get stoppingProcessing =>
      'Stopping processing. Waiting for the local worker to finish owned tasks and close safely…';

  @override
  String get forcedShutdownTitle => 'The worker required forced shutdown';

  @override
  String get forcedShutdownMessage =>
      'The local worker did not stop gracefully in time. ChaSteady closed only its owned worker process tree; active work may have been interrupted and the result is not certified.';

  @override
  String get acknowledgeForcedShutdown => 'Continue closing';
}
