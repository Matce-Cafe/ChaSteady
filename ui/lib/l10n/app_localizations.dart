import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter/widgets.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:intl/intl.dart' as intl;

import 'app_localizations_en.dart';
import 'app_localizations_zh.dart';

// ignore_for_file: type=lint

/// Callers can lookup localized strings with an instance of AppLocalizations
/// returned by `AppLocalizations.of(context)`.
///
/// Applications need to include `AppLocalizations.delegate()` in their app's
/// `localizationDelegates` list, and the locales they support in the app's
/// `supportedLocales` list. For example:
///
/// ```dart
/// import 'l10n/app_localizations.dart';
///
/// return MaterialApp(
///   localizationsDelegates: AppLocalizations.localizationsDelegates,
///   supportedLocales: AppLocalizations.supportedLocales,
///   home: MyApplicationHome(),
/// );
/// ```
///
/// ## Update pubspec.yaml
///
/// Please make sure to update your pubspec.yaml to include the following
/// packages:
///
/// ```yaml
/// dependencies:
///   # Internationalization support.
///   flutter_localizations:
///     sdk: flutter
///   intl: any # Use the pinned version from flutter_localizations
///
///   # Rest of dependencies
/// ```
///
/// ## iOS Applications
///
/// iOS applications define key application metadata, including supported
/// locales, in an Info.plist file that is built into the application bundle.
/// To configure the locales supported by your app, you’ll need to edit this
/// file.
///
/// First, open your project’s ios/Runner.xcworkspace Xcode workspace file.
/// Then, in the Project Navigator, open the Info.plist file under the Runner
/// project’s Runner folder.
///
/// Next, select the Information Property List item, select Add Item from the
/// Editor menu, then select Localizations from the pop-up menu.
///
/// Select and expand the newly-created Localizations item then, for each
/// locale your application supports, add a new item and select the locale
/// you wish to add from the pop-up menu in the Value field. This list should
/// be consistent with the languages listed in the AppLocalizations.supportedLocales
/// property.
abstract class AppLocalizations {
  AppLocalizations(String locale)
    : localeName = intl.Intl.canonicalizedLocale(locale.toString());

  final String localeName;

  static AppLocalizations of(BuildContext context) {
    return Localizations.of<AppLocalizations>(context, AppLocalizations)!;
  }

  static const LocalizationsDelegate<AppLocalizations> delegate =
      _AppLocalizationsDelegate();

  /// A list of this localizations delegate along with the default localizations
  /// delegates.
  ///
  /// Returns a list of localizations delegates containing this delegate along with
  /// GlobalMaterialLocalizations.delegate, GlobalCupertinoLocalizations.delegate,
  /// and GlobalWidgetsLocalizations.delegate.
  ///
  /// Additional delegates can be added by appending to this list in
  /// MaterialApp. This list does not have to be used at all if a custom list
  /// of delegates is preferred or required.
  static const List<LocalizationsDelegate<dynamic>> localizationsDelegates =
      <LocalizationsDelegate<dynamic>>[
        delegate,
        GlobalMaterialLocalizations.delegate,
        GlobalCupertinoLocalizations.delegate,
        GlobalWidgetsLocalizations.delegate,
      ];

  /// A list of this localizations delegate's supported locales.
  static const List<Locale> supportedLocales = <Locale>[
    Locale('en'),
    Locale('zh'),
  ];

  /// No description provided for @appTitle.
  ///
  /// In en, this message translates to:
  /// **'ChaSteady'**
  String get appTitle;

  /// No description provided for @navWorkbench.
  ///
  /// In en, this message translates to:
  /// **'Workbench'**
  String get navWorkbench;

  /// No description provided for @navJobs.
  ///
  /// In en, this message translates to:
  /// **'Jobs'**
  String get navJobs;

  /// No description provided for @navSettings.
  ///
  /// In en, this message translates to:
  /// **'Settings'**
  String get navSettings;

  /// No description provided for @menuFile.
  ///
  /// In en, this message translates to:
  /// **'File'**
  String get menuFile;

  /// No description provided for @menuView.
  ///
  /// In en, this message translates to:
  /// **'View'**
  String get menuView;

  /// No description provided for @menuHelp.
  ///
  /// In en, this message translates to:
  /// **'Help'**
  String get menuHelp;

  /// No description provided for @menuOpenWeb.
  ///
  /// In en, this message translates to:
  /// **'Open Web session'**
  String get menuOpenWeb;

  /// No description provided for @menuLanguage.
  ///
  /// In en, this message translates to:
  /// **'Language'**
  String get menuLanguage;

  /// No description provided for @languageSystem.
  ///
  /// In en, this message translates to:
  /// **'System default'**
  String get languageSystem;

  /// No description provided for @languageZh.
  ///
  /// In en, this message translates to:
  /// **'简体中文'**
  String get languageZh;

  /// No description provided for @languageEn.
  ///
  /// In en, this message translates to:
  /// **'English'**
  String get languageEn;

  /// No description provided for @helpAbout.
  ///
  /// In en, this message translates to:
  /// **'About ChaSteady'**
  String get helpAbout;

  /// No description provided for @helpAboutTitle.
  ///
  /// In en, this message translates to:
  /// **'About ChaSteady'**
  String get helpAboutTitle;

  /// No description provided for @helpAboutBody.
  ///
  /// In en, this message translates to:
  /// **'ChaSteady is a local-first video stabilization workbench. Footage stays on this computer and jobs are reported by the local worker.'**
  String get helpAboutBody;

  /// No description provided for @helpQualityTitle.
  ///
  /// In en, this message translates to:
  /// **'Quality and verification limits'**
  String get helpQualityTitle;

  /// No description provided for @helpQualityBody.
  ///
  /// In en, this message translates to:
  /// **'CTB output remains manual and is not a quality or full-field-of-view certificate. Gyroflow exports that do not pass frame, PTS, and content checks remain needs_review. Media verification does not certify a perceptual winner, original FOV, or crop-free output.'**
  String get helpQualityBody;

  /// No description provided for @closeConfirmTitle.
  ///
  /// In en, this message translates to:
  /// **'Close ChaSteady?'**
  String get closeConfirmTitle;

  /// No description provided for @closeActiveJobs.
  ///
  /// In en, this message translates to:
  /// **'{count, plural, =1{There is 1 active job} other{There are {count} active jobs}}. Closing will ask the local supervisor to stop and wait for its owned work.'**
  String closeActiveJobs(int count);

  /// No description provided for @closeWebWarning.
  ///
  /// In en, this message translates to:
  /// **'The Web session will disconnect when the local service shuts down.'**
  String get closeWebWarning;

  /// No description provided for @closeConfirmAction.
  ///
  /// In en, this message translates to:
  /// **'Stop work and close'**
  String get closeConfirmAction;

  /// No description provided for @cancelAction.
  ///
  /// In en, this message translates to:
  /// **'Cancel'**
  String get cancelAction;

  /// No description provided for @startupFailedTitle.
  ///
  /// In en, this message translates to:
  /// **'ChaSteady could not start'**
  String get startupFailedTitle;

  /// No description provided for @startupFailedBody.
  ///
  /// In en, this message translates to:
  /// **'The local desktop platform did not finish initializing.'**
  String get startupFailedBody;

  /// No description provided for @startupFailureDetails.
  ///
  /// In en, this message translates to:
  /// **'Platform-reported details: {details}'**
  String startupFailureDetails(Object details);

  /// No description provided for @connectingService.
  ///
  /// In en, this message translates to:
  /// **'Connecting to the local service'**
  String get connectingService;

  /// No description provided for @serviceUnavailable.
  ///
  /// In en, this message translates to:
  /// **'Local service unavailable'**
  String get serviceUnavailable;

  /// No description provided for @establishingSession.
  ///
  /// In en, this message translates to:
  /// **'Establishing the launcher session.'**
  String get establishingSession;

  /// No description provided for @noSessionActive.
  ///
  /// In en, this message translates to:
  /// **'No local session is active'**
  String get noSessionActive;

  /// No description provided for @sessionNotAccepted.
  ///
  /// In en, this message translates to:
  /// **'The local service did not accept this session.'**
  String get sessionNotAccepted;

  /// No description provided for @retrySession.
  ///
  /// In en, this message translates to:
  /// **'Retry session'**
  String get retrySession;

  /// No description provided for @sessionUnsupported.
  ///
  /// In en, this message translates to:
  /// **'The native local-server session adapter is not configured. Open the Web UI from a ChaSteady launcher session.'**
  String get sessionUnsupported;

  /// No description provided for @openFromLauncher.
  ///
  /// In en, this message translates to:
  /// **'Open this page from the ChaSteady launcher session link. This UI cannot create a session by itself.'**
  String get openFromLauncher;

  /// No description provided for @genericOperationFailed.
  ///
  /// In en, this message translates to:
  /// **'The local operation did not complete. Check the service and try again.'**
  String get genericOperationFailed;

  /// No description provided for @originalServiceMessage.
  ///
  /// In en, this message translates to:
  /// **'Original service message: {message}'**
  String originalServiceMessage(Object message);

  /// No description provided for @originalServiceMessageWithCode.
  ///
  /// In en, this message translates to:
  /// **'Original service message ({code}): {message}'**
  String originalServiceMessageWithCode(Object code, Object message);

  /// No description provided for @serviceMessageCodeOnly.
  ///
  /// In en, this message translates to:
  /// **'Service message code: {code}'**
  String serviceMessageCodeOnly(Object code);

  /// No description provided for @originalWorkerMessage.
  ///
  /// In en, this message translates to:
  /// **'Original worker message: {message}'**
  String originalWorkerMessage(Object message);

  /// No description provided for @originalWorkerWarning.
  ///
  /// In en, this message translates to:
  /// **'Original worker warning: {message}'**
  String originalWorkerWarning(Object message);

  /// No description provided for @originalArtifactWarning.
  ///
  /// In en, this message translates to:
  /// **'Original artifact warning: {message}'**
  String originalArtifactWarning(Object message);

  /// No description provided for @unknownWorkerCode.
  ///
  /// In en, this message translates to:
  /// **'Worker message code: {code}'**
  String unknownWorkerCode(Object code);

  /// No description provided for @originalWorkerStage.
  ///
  /// In en, this message translates to:
  /// **'Original worker stage: {stage}'**
  String originalWorkerStage(Object stage);

  /// No description provided for @originalStatusValue.
  ///
  /// In en, this message translates to:
  /// **'Original status value: {value}'**
  String originalStatusValue(Object value);

  /// No description provided for @screenWorkbenchTitle.
  ///
  /// In en, this message translates to:
  /// **'Stabilization workspace'**
  String get screenWorkbenchTitle;

  /// No description provided for @screenWorkbenchSubtitle.
  ///
  /// In en, this message translates to:
  /// **'Three local sources, explicit intervals, real worker jobs.'**
  String get screenWorkbenchSubtitle;

  /// No description provided for @refreshLocalJobs.
  ///
  /// In en, this message translates to:
  /// **'Refresh local jobs'**
  String get refreshLocalJobs;

  /// No description provided for @localMediaWorkspace.
  ///
  /// In en, this message translates to:
  /// **'Local media workspace'**
  String get localMediaWorkspace;

  /// No description provided for @localMediaWorkspaceMessage.
  ///
  /// In en, this message translates to:
  /// **'{appName} references absolute local paths. Footage is not uploaded, and the browser never opens an original source as a preview.'**
  String localMediaWorkspaceMessage(Object appName);

  /// No description provided for @sourcePaths.
  ///
  /// In en, this message translates to:
  /// **'Source paths'**
  String get sourcePaths;

  /// No description provided for @sourcePathsSubtitle.
  ///
  /// In en, this message translates to:
  /// **'Original video / CTB video / Gyroflow reference video.'**
  String get sourcePathsSubtitle;

  /// No description provided for @originalVideo.
  ///
  /// In en, this message translates to:
  /// **'Original video'**
  String get originalVideo;

  /// No description provided for @originalVideoHelper.
  ///
  /// In en, this message translates to:
  /// **'Read-only local source. A typed absolute path is always supported.'**
  String get originalVideoHelper;

  /// No description provided for @ctbInputVideo.
  ///
  /// In en, this message translates to:
  /// **'CTB input video'**
  String get ctbInputVideo;

  /// No description provided for @ctbInputHelper.
  ///
  /// In en, this message translates to:
  /// **'The CTB input rectangle is not a full-input FOV certificate.'**
  String get ctbInputHelper;

  /// No description provided for @gyroflowReferenceVideo.
  ///
  /// In en, this message translates to:
  /// **'Gyroflow reference video'**
  String get gyroflowReferenceVideo;

  /// No description provided for @gyroflowReferenceHelper.
  ///
  /// In en, this message translates to:
  /// **'Fusion reads this as local video media. A .gyroflow project is not a reference video; export templates are configured separately.'**
  String get gyroflowReferenceHelper;

  /// No description provided for @useLocalAbsolutePaths.
  ///
  /// In en, this message translates to:
  /// **'Use local absolute paths'**
  String get useLocalAbsolutePaths;

  /// No description provided for @invalidSourcePathsMessage.
  ///
  /// In en, this message translates to:
  /// **'Relative paths and URLs are not sent to the worker. Use a drive path such as N:\\folder\\file.mp4 or a local absolute POSIX path.'**
  String get invalidSourcePathsMessage;

  /// No description provided for @inspectOriginalMetadata.
  ///
  /// In en, this message translates to:
  /// **'Inspect original metadata'**
  String get inspectOriginalMetadata;

  /// No description provided for @inspectionFailed.
  ///
  /// In en, this message translates to:
  /// **'Inspection failed'**
  String get inspectionFailed;

  /// No description provided for @fusionTitle.
  ///
  /// In en, this message translates to:
  /// **'CTB fusion'**
  String get fusionTitle;

  /// No description provided for @fusionSubtitle.
  ///
  /// In en, this message translates to:
  /// **'Fresh measurement is strict; cache reuse is an explicit C7037 reproduction.'**
  String get fusionSubtitle;

  /// No description provided for @freshStrict.
  ///
  /// In en, this message translates to:
  /// **'Fresh strict'**
  String get freshStrict;

  /// No description provided for @cachedV9.
  ///
  /// In en, this message translates to:
  /// **'Cached v9'**
  String get cachedV9;

  /// No description provided for @fusionSourceWindow.
  ///
  /// In en, this message translates to:
  /// **'Fusion source window'**
  String get fusionSourceWindow;

  /// No description provided for @startSeconds.
  ///
  /// In en, this message translates to:
  /// **'Start (s)'**
  String get startSeconds;

  /// No description provided for @endSeconds.
  ///
  /// In en, this message translates to:
  /// **'End (s)'**
  String get endSeconds;

  /// No description provided for @sourceWindowIndependent.
  ///
  /// In en, this message translates to:
  /// **'This source-processing window is independent of the optional reference-interval list below.'**
  String get sourceWindowIndependent;

  /// No description provided for @strictFreshRun.
  ///
  /// In en, this message translates to:
  /// **'Strict fresh run'**
  String get strictFreshRun;

  /// No description provided for @strictFreshMessage.
  ///
  /// In en, this message translates to:
  /// **'No legacy trajectory cache is reused. Missing active pose/correspondence blocks the run. The selected local GF reference may be used without a local Gyroflow executable; automatic gyro classification remains disabled.'**
  String get strictFreshMessage;

  /// No description provided for @c7037CachedReproduction.
  ///
  /// In en, this message translates to:
  /// **'C7037 cached reproduction'**
  String get c7037CachedReproduction;

  /// No description provided for @c7037CachedMessage.
  ///
  /// In en, this message translates to:
  /// **'This is an explicit approved-cache reproduction, not a fresh measurement. Legacy gap warnings must remain visible in the worker result.'**
  String get c7037CachedMessage;

  /// No description provided for @invalidCachedPreset.
  ///
  /// In en, this message translates to:
  /// **'Cached preset request invalid'**
  String get invalidCachedPreset;

  /// No description provided for @cachedPresetCatalogLabel.
  ///
  /// In en, this message translates to:
  /// **'C7037 preset from the actual service catalog'**
  String get cachedPresetCatalogLabel;

  /// No description provided for @legacyQuietCachePath.
  ///
  /// In en, this message translates to:
  /// **'Legacy quiet cache path'**
  String get legacyQuietCachePath;

  /// No description provided for @legacyQuietCacheHelper.
  ///
  /// In en, this message translates to:
  /// **'Only the selected preset path or an explicit local path is used.'**
  String get legacyQuietCacheHelper;

  /// No description provided for @legacyReferenceCachePath.
  ///
  /// In en, this message translates to:
  /// **'Legacy reference cache path'**
  String get legacyReferenceCachePath;

  /// No description provided for @legacyReferenceCacheHelper.
  ///
  /// In en, this message translates to:
  /// **'No cache file is inferred when this field is empty.'**
  String get legacyReferenceCacheHelper;

  /// No description provided for @legacyCacheLocalTitle.
  ///
  /// In en, this message translates to:
  /// **'Legacy cache paths must be local'**
  String get legacyCacheLocalTitle;

  /// No description provided for @legacyCacheLocalMessage.
  ///
  /// In en, this message translates to:
  /// **'Use absolute local paths for both selected C7037 caches. URLs and relative paths are rejected.'**
  String get legacyCacheLocalMessage;

  /// No description provided for @timingNormalizationQuiet.
  ///
  /// In en, this message translates to:
  /// **'Timing, normalization, and quiet-window settings'**
  String get timingNormalizationQuiet;

  /// No description provided for @advancedFusionControls.
  ///
  /// In en, this message translates to:
  /// **'Advanced fusion controls'**
  String get advancedFusionControls;

  /// No description provided for @fusionDefaults.
  ///
  /// In en, this message translates to:
  /// **'Defaults: origins 0 s, quiet sigma 1.3 s, reference FOV 1.0.'**
  String get fusionDefaults;

  /// No description provided for @ctbOrigin.
  ///
  /// In en, this message translates to:
  /// **'CTB origin (s)'**
  String get ctbOrigin;

  /// No description provided for @referenceOrigin.
  ///
  /// In en, this message translates to:
  /// **'Reference origin (s)'**
  String get referenceOrigin;

  /// No description provided for @quietSigmaWindow.
  ///
  /// In en, this message translates to:
  /// **'Quiet sigma window (s)'**
  String get quietSigmaWindow;

  /// No description provided for @referenceFov.
  ///
  /// In en, this message translates to:
  /// **'Reference FOV (1–4)'**
  String get referenceFov;

  /// No description provided for @referenceFovAnalysisOnly.
  ///
  /// In en, this message translates to:
  /// **'Reference FOV is analysis-only'**
  String get referenceFovAnalysisOnly;

  /// No description provided for @referenceFovMessage.
  ///
  /// In en, this message translates to:
  /// **'It normalizes the fusion reference and does not change render zoom or guarantee no crop. The default 1.0 preserves the C7037 legacy behavior.'**
  String get referenceFovMessage;

  /// No description provided for @confirmListedRanges.
  ///
  /// In en, this message translates to:
  /// **'Confirm the listed ranges against the selected footage.'**
  String get confirmListedRanges;

  /// No description provided for @fusionHeld.
  ///
  /// In en, this message translates to:
  /// **'Fusion is held'**
  String get fusionHeld;

  /// No description provided for @creatingJob.
  ///
  /// In en, this message translates to:
  /// **'Creating job…'**
  String get creatingJob;

  /// No description provided for @createFusionJob.
  ///
  /// In en, this message translates to:
  /// **'Create fusion job'**
  String get createFusionJob;

  /// No description provided for @presetDiscoveryTitle.
  ///
  /// In en, this message translates to:
  /// **'Experiment preset discovery'**
  String get presetDiscoveryTitle;

  /// No description provided for @presetDiscoverySubtitle.
  ///
  /// In en, this message translates to:
  /// **'Scoped catalog lookup only; no whole-disk recursion.'**
  String get presetDiscoverySubtitle;

  /// No description provided for @experimentFolder.
  ///
  /// In en, this message translates to:
  /// **'Experiment folder'**
  String get experimentFolder;

  /// No description provided for @experimentFolderHelper.
  ///
  /// In en, this message translates to:
  /// **'Point to the real experiment folder to read its catalog.'**
  String get experimentFolderHelper;

  /// No description provided for @discoverPresets.
  ///
  /// In en, this message translates to:
  /// **'Discover presets'**
  String get discoverPresets;

  /// No description provided for @presetDiscoveryFailed.
  ///
  /// In en, this message translates to:
  /// **'Preset discovery failed'**
  String get presetDiscoveryFailed;

  /// No description provided for @serviceNoPresets.
  ///
  /// In en, this message translates to:
  /// **'The service returned no presets for this folder.'**
  String get serviceNoPresets;

  /// No description provided for @servicePresetsReturned.
  ///
  /// In en, this message translates to:
  /// **'Presets returned by the service'**
  String get servicePresetsReturned;

  /// No description provided for @c7037CachedComplete.
  ///
  /// In en, this message translates to:
  /// **'C7037 cached reproduction · complete request'**
  String get c7037CachedComplete;

  /// No description provided for @metadataOnlyDiscover.
  ///
  /// In en, this message translates to:
  /// **'Metadata only · discover the full approved request before selection'**
  String get metadataOnlyDiscover;

  /// No description provided for @discoverFullC7037First.
  ///
  /// In en, this message translates to:
  /// **'Discover the full C7037 request first'**
  String get discoverFullC7037First;

  /// No description provided for @metadataCatalogExplanation.
  ///
  /// In en, this message translates to:
  /// **'The capabilities catalog contains metadata only. Set the explicit experiment folder above and select Discover presets; the cached preset stays unavailable until the service returns its approved request, including reference_intervals.'**
  String get metadataCatalogExplanation;

  /// No description provided for @c7037NeedsCompleteRequest.
  ///
  /// In en, this message translates to:
  /// **'C7037 becomes selectable only after the local service returns a complete approved request.'**
  String get c7037NeedsCompleteRequest;

  /// No description provided for @referenceIntervals.
  ///
  /// In en, this message translates to:
  /// **'Reference intervals'**
  String get referenceIntervals;

  /// No description provided for @referenceIntervalsSubtitle.
  ///
  /// In en, this message translates to:
  /// **'Optional start/end list — no timeline chart, auto-time selector, or gyro classifier.'**
  String get referenceIntervalsSubtitle;

  /// No description provided for @intervalsManualOnly.
  ///
  /// In en, this message translates to:
  /// **'Enter only reviewed time ranges. No motion chart or automatic range detection is used.'**
  String get intervalsManualOnly;

  /// No description provided for @noReferenceIntervals.
  ///
  /// In en, this message translates to:
  /// **'No reference intervals selected. An empty list is valid for a CTB-only preset such as Fixed 212–228.'**
  String get noReferenceIntervals;

  /// No description provided for @addRange.
  ///
  /// In en, this message translates to:
  /// **'Add range'**
  String get addRange;

  /// No description provided for @insertLabRanges.
  ///
  /// In en, this message translates to:
  /// **'Insert documented lab ranges'**
  String get insertLabRanges;

  /// No description provided for @reviewIntervalsCheckbox.
  ///
  /// In en, this message translates to:
  /// **'I reviewed the reference-interval list, including an empty list, against this request.'**
  String get reviewIntervalsCheckbox;

  /// No description provided for @requiredBeforeFusion.
  ///
  /// In en, this message translates to:
  /// **'Required before creating a fusion job.'**
  String get requiredBeforeFusion;

  /// No description provided for @documentedRangesOptIn.
  ///
  /// In en, this message translates to:
  /// **'Documented lab ranges are opt-in'**
  String get documentedRangesOptIn;

  /// No description provided for @documentedRangesMessage.
  ///
  /// In en, this message translates to:
  /// **'The insert action adds 153–156 s and 231.8–235.5 s. The separate CTB-only interval 212–228 s is not automatically added to fusion.'**
  String get documentedRangesMessage;

  /// No description provided for @otherLocalStages.
  ///
  /// In en, this message translates to:
  /// **'Other local stages'**
  String get otherLocalStages;

  /// No description provided for @otherLocalStagesSubtitle.
  ///
  /// In en, this message translates to:
  /// **'Actions create real API jobs; the worker owns tool execution and result state.'**
  String get otherLocalStagesSubtitle;

  /// No description provided for @createPreview.
  ///
  /// In en, this message translates to:
  /// **'Create H.264/AAC preview'**
  String get createPreview;

  /// No description provided for @validateMedia.
  ///
  /// In en, this message translates to:
  /// **'Validate media'**
  String get validateMedia;

  /// No description provided for @configureGyroflowExport.
  ///
  /// In en, this message translates to:
  /// **'Configure Gyroflow export'**
  String get configureGyroflowExport;

  /// No description provided for @requestCatalystManual.
  ///
  /// In en, this message translates to:
  /// **'Request Catalyst manual steps'**
  String get requestCatalystManual;

  /// No description provided for @previewStageUnavailable.
  ///
  /// In en, this message translates to:
  /// **'Preview stage unavailable'**
  String get previewStageUnavailable;

  /// No description provided for @previewUnavailableMessage.
  ///
  /// In en, this message translates to:
  /// **'FFmpeg is missing or its status is unknown. No preview is claimed until the worker creates a real H.264/AAC artifact.'**
  String get previewUnavailableMessage;

  /// No description provided for @validationStageUnavailable.
  ///
  /// In en, this message translates to:
  /// **'Validation stage unavailable'**
  String get validationStageUnavailable;

  /// No description provided for @validationUnavailableMessage.
  ///
  /// In en, this message translates to:
  /// **'FFprobe is missing or its status is unknown. Validation jobs are held until the configured probe is detected.'**
  String get validationUnavailableMessage;

  /// No description provided for @gyroflowCliSafeguards.
  ///
  /// In en, this message translates to:
  /// **'Gyroflow CLI safeguards'**
  String get gyroflowCliSafeguards;

  /// No description provided for @gyroflowSafeguardsMessage.
  ///
  /// In en, this message translates to:
  /// **'Export is enabled only when the saved executable path matches the service-reported path and the audited CLI/profile guard is verified. The 1080p output preset and a bounded 0–5 second segment are defaults; full source and 720p are explicit choices. Every new render still needs frame, PTS, and content-alignment review.'**
  String get gyroflowSafeguardsMessage;

  /// No description provided for @latestGyroflowNeedsReview.
  ///
  /// In en, this message translates to:
  /// **'Latest Gyroflow output needs review'**
  String get latestGyroflowNeedsReview;

  /// No description provided for @gyroflowNeedsReviewMessage.
  ///
  /// In en, this message translates to:
  /// **'The service reports needs_review and does not claim verified export or trim mapping. A CLI exit code of 0 is not a successful output-validation result.'**
  String get gyroflowNeedsReviewMessage;

  /// No description provided for @catalystManualTitle.
  ///
  /// In en, this message translates to:
  /// **'Catalyst assisted export · needs manual steps'**
  String get catalystManualTitle;

  /// No description provided for @catalystManualMessage.
  ///
  /// In en, this message translates to:
  /// **'This UI never starts Catalyst automation. The owned-window probe did not expose controls and changed a Sony profile log; this stage remains manual.'**
  String get catalystManualMessage;

  /// No description provided for @catalystNotDetected.
  ///
  /// In en, this message translates to:
  /// **'Catalyst not detected'**
  String get catalystNotDetected;

  /// No description provided for @catalystStatusUnknown.
  ///
  /// In en, this message translates to:
  /// **'Catalyst status unknown'**
  String get catalystStatusUnknown;

  /// No description provided for @catalystNotStartedMessage.
  ///
  /// In en, this message translates to:
  /// **'No Catalyst stage is started from this UI. An installed executable alone never means the UI stage is verified.'**
  String get catalystNotStartedMessage;

  /// No description provided for @gyroClassificationDisabled.
  ///
  /// In en, this message translates to:
  /// **'Automatic gyro classification is disabled. Source codec support is not assumed; use a real preview artifact for browser playback.'**
  String get gyroClassificationDisabled;

  /// No description provided for @inspectMetadataReturned.
  ///
  /// In en, this message translates to:
  /// **'Metadata returned by the worker'**
  String get inspectMetadataReturned;

  /// No description provided for @dimensions.
  ///
  /// In en, this message translates to:
  /// **'Dimensions: {width} × {height}'**
  String dimensions(Object width, Object height);

  /// No description provided for @frameRate.
  ///
  /// In en, this message translates to:
  /// **'Frame rate: {fps} fps'**
  String frameRate(Object fps);

  /// No description provided for @frameCount.
  ///
  /// In en, this message translates to:
  /// **'Frames: {frames}'**
  String frameCount(Object frames);

  /// No description provided for @durationSeconds.
  ///
  /// In en, this message translates to:
  /// **'Duration: {duration} s'**
  String durationSeconds(Object duration);

  /// No description provided for @metadataName.
  ///
  /// In en, this message translates to:
  /// **'Name: {name}'**
  String metadataName(Object name);

  /// No description provided for @videoCodec.
  ///
  /// In en, this message translates to:
  /// **'Video codec: {value}'**
  String videoCodec(Object value);

  /// No description provided for @audioCodec.
  ///
  /// In en, this message translates to:
  /// **'Audio codec: {value}'**
  String audioCodec(Object value);

  /// No description provided for @pixelFormat.
  ///
  /// In en, this message translates to:
  /// **'Pixel format: {value}'**
  String pixelFormat(Object value);

  /// No description provided for @bitDepth.
  ///
  /// In en, this message translates to:
  /// **'Bit depth: {value}'**
  String bitDepth(Object value);

  /// No description provided for @frameTiming.
  ///
  /// In en, this message translates to:
  /// **'Frame timing: {value}'**
  String frameTiming(Object value);

  /// No description provided for @dimensionsNotFov.
  ///
  /// In en, this message translates to:
  /// **'Dimensions do not certify the full-input field of view.'**
  String get dimensionsNotFov;

  /// No description provided for @gyroflowDialogTitle.
  ///
  /// In en, this message translates to:
  /// **'Configure Gyroflow export'**
  String get gyroflowDialogTitle;

  /// No description provided for @gyroflowTemplateLabel.
  ///
  /// In en, this message translates to:
  /// **'Gyroflow project template (optional)'**
  String get gyroflowTemplateLabel;

  /// No description provided for @gyroflowTemplateHelper.
  ///
  /// In en, this message translates to:
  /// **'This is explicit; the fusion reference is never inferred as an export template.'**
  String get gyroflowTemplateHelper;

  /// No description provided for @typeProjectTemplatePath.
  ///
  /// In en, this message translates to:
  /// **'Type local project template path'**
  String get typeProjectTemplatePath;

  /// No description provided for @projectTemplateLocalPath.
  ///
  /// In en, this message translates to:
  /// **'Gyroflow project template'**
  String get projectTemplateLocalPath;

  /// No description provided for @projectTemplateLocalOnly.
  ///
  /// In en, this message translates to:
  /// **'Project template must be a local absolute path.'**
  String get projectTemplateLocalOnly;

  /// No description provided for @outputPreset.
  ///
  /// In en, this message translates to:
  /// **'Output preset'**
  String get outputPreset;

  /// No description provided for @outputPresetHelper.
  ///
  /// In en, this message translates to:
  /// **'Choose an approved reference_1080p or reference_720p worker preset; arbitrary size, codec, and commands are not accepted.'**
  String get outputPresetHelper;

  /// No description provided for @reference1080p.
  ///
  /// In en, this message translates to:
  /// **'Reference 1080p'**
  String get reference1080p;

  /// No description provided for @reference720p.
  ///
  /// In en, this message translates to:
  /// **'Reference 720p'**
  String get reference720p;

  /// No description provided for @exportFullSource.
  ///
  /// In en, this message translates to:
  /// **'Export full source'**
  String get exportFullSource;

  /// No description provided for @fullSourceLonger.
  ///
  /// In en, this message translates to:
  /// **'Optional and off by default; a full-source render may take much longer.'**
  String get fullSourceLonger;

  /// No description provided for @exportStartSeconds.
  ///
  /// In en, this message translates to:
  /// **'Export start (s)'**
  String get exportStartSeconds;

  /// No description provided for @exportEndSeconds.
  ///
  /// In en, this message translates to:
  /// **'Export end (s)'**
  String get exportEndSeconds;

  /// No description provided for @defaultReviewSegment.
  ///
  /// In en, this message translates to:
  /// **'Default review segment: 0–5 seconds. Adjust to match the source.'**
  String get defaultReviewSegment;

  /// No description provided for @renderUnverifiedTitle.
  ///
  /// In en, this message translates to:
  /// **'Render output remains unverified'**
  String get renderUnverifiedTitle;

  /// No description provided for @renderUnverifiedMessage.
  ///
  /// In en, this message translates to:
  /// **'A successful process exit does not verify frame count, PTS alignment, or content alignment.'**
  String get renderUnverifiedMessage;

  /// No description provided for @createExportJob.
  ///
  /// In en, this message translates to:
  /// **'Create export job'**
  String get createExportJob;

  /// No description provided for @manualCatalystNotice.
  ///
  /// In en, this message translates to:
  /// **'Catalyst stage {id} · {state}. No automatic action was started by the UI.'**
  String manualCatalystNotice(Object id, Object state);

  /// No description provided for @jobCreatedNotice.
  ///
  /// In en, this message translates to:
  /// **'Created {kind} job {id} · {state}. The worker has not reported a result yet.'**
  String jobCreatedNotice(Object kind, Object id, Object state);

  /// No description provided for @previewJobCreatedNotice.
  ///
  /// In en, this message translates to:
  /// **'Created preview job {id} · {state}.'**
  String previewJobCreatedNotice(Object id, Object state);

  /// No description provided for @validationJobCreatedNotice.
  ///
  /// In en, this message translates to:
  /// **'Created validation job {id} · {state}.'**
  String validationJobCreatedNotice(Object id, Object state);

  /// No description provided for @gyroflowJobCreatedNotice.
  ///
  /// In en, this message translates to:
  /// **'Created Gyroflow export {id} · {state}. Frame/PTS/content verification is still required.'**
  String gyroflowJobCreatedNotice(Object id, Object state);

  /// No description provided for @sourceWindowInvalid.
  ///
  /// In en, this message translates to:
  /// **'Enter both fusion source-window start and end values.'**
  String get sourceWindowInvalid;

  /// No description provided for @intervalNonNumeric.
  ///
  /// In en, this message translates to:
  /// **'Interval {row} needs numeric start and end values.'**
  String intervalNonNumeric(int row);

  /// No description provided for @intervalNegativeStart.
  ///
  /// In en, this message translates to:
  /// **'Interval {row} cannot start before 0 seconds.'**
  String intervalNegativeStart(int row);

  /// No description provided for @intervalEndNotAfterStart.
  ///
  /// In en, this message translates to:
  /// **'Interval {row} end must be after its start.'**
  String intervalEndNotAfterStart(int row);

  /// No description provided for @intervalChronologicalOrder.
  ///
  /// In en, this message translates to:
  /// **'Intervals must be listed in chronological order.'**
  String get intervalChronologicalOrder;

  /// No description provided for @intervalOverlap.
  ///
  /// In en, this message translates to:
  /// **'Interval {row} overlaps the interval before it.'**
  String intervalOverlap(int row);

  /// No description provided for @invalidTimingValues.
  ///
  /// In en, this message translates to:
  /// **'Timing values must be finite, quiet sigma must be positive, and reference FOV must be from 1 to 4.'**
  String get invalidTimingValues;

  /// No description provided for @invalidReferenceFov.
  ///
  /// In en, this message translates to:
  /// **'Reference FOV normalization must be a number from 1 to 4.'**
  String get invalidReferenceFov;

  /// No description provided for @sessionRequiredBeforeJob.
  ///
  /// In en, this message translates to:
  /// **'A valid launcher session is required before creating jobs.'**
  String get sessionRequiredBeforeJob;

  /// No description provided for @localPathsOnly.
  ///
  /// In en, this message translates to:
  /// **'Use local absolute paths only; URLs and relative paths are rejected.'**
  String get localPathsOnly;

  /// No description provided for @legacyPathsMustBeAbsolute.
  ///
  /// In en, this message translates to:
  /// **'Legacy cache paths must be local absolute paths.'**
  String get legacyPathsMustBeAbsolute;

  /// No description provided for @toolStatusNotReturned.
  ///
  /// In en, this message translates to:
  /// **'Tool capability status has not been returned by the service.'**
  String get toolStatusNotReturned;

  /// No description provided for @ffmpegMissingHeld.
  ///
  /// In en, this message translates to:
  /// **'FFmpeg is missing or its status is unknown. Fusion output is held.'**
  String get ffmpegMissingHeld;

  /// No description provided for @selectActualPreset.
  ///
  /// In en, this message translates to:
  /// **'Select an actual C7037 preset returned by the service.'**
  String get selectActualPreset;

  /// No description provided for @bothLegacyPathsRequired.
  ///
  /// In en, this message translates to:
  /// **'The selected preset request must include both legacy cache paths.'**
  String get bothLegacyPathsRequired;

  /// No description provided for @reviewManualIntervals.
  ///
  /// In en, this message translates to:
  /// **'Review the manual intervals against these sources.'**
  String get reviewManualIntervals;

  /// No description provided for @catalogFieldChanged.
  ///
  /// In en, this message translates to:
  /// **'A catalog request field changed. Select the approved preset again before cached_v9 can run.'**
  String get catalogFieldChanged;

  /// No description provided for @metadataOnlyCatalogError.
  ///
  /// In en, this message translates to:
  /// **'This catalog item contains metadata only. Enter its explicit experiment folder and use Discover presets to load the full approved request before selection.'**
  String get metadataOnlyCatalogError;

  /// No description provided for @invalidReferenceInterval.
  ///
  /// In en, this message translates to:
  /// **'The catalog preset contains an invalid reference interval.'**
  String get invalidReferenceInterval;

  /// No description provided for @nonFiniteReferenceInterval.
  ///
  /// In en, this message translates to:
  /// **'The catalog preset contains a non-finite reference interval.'**
  String get nonFiniteReferenceInterval;

  /// No description provided for @missingReferenceIntervals.
  ///
  /// In en, this message translates to:
  /// **'The catalog preset has no reference_intervals array.'**
  String get missingReferenceIntervals;

  /// No description provided for @missingCachedRequestField.
  ///
  /// In en, this message translates to:
  /// **'The catalog entry is missing a required cached_v9 request field.'**
  String get missingCachedRequestField;

  /// No description provided for @catalogNonLocalPath.
  ///
  /// In en, this message translates to:
  /// **'The catalog request contains a non-local path.'**
  String get catalogNonLocalPath;

  /// No description provided for @enterLocalAbsoluteFolder.
  ///
  /// In en, this message translates to:
  /// **'Enter a local absolute experiment folder path.'**
  String get enterLocalAbsoluteFolder;

  /// No description provided for @jobRequestKindRequired.
  ///
  /// In en, this message translates to:
  /// **'A supported job kind is required.'**
  String get jobRequestKindRequired;

  /// No description provided for @jobFieldsNested.
  ///
  /// In en, this message translates to:
  /// **'Job fields must be nested under request.'**
  String get jobFieldsNested;

  /// No description provided for @jobRequestObject.
  ///
  /// In en, this message translates to:
  /// **'Job request must be an object.'**
  String get jobRequestObject;

  /// No description provided for @invalidArtifactOpen.
  ///
  /// In en, this message translates to:
  /// **'This artifact cannot be opened as a local preview.'**
  String get invalidArtifactOpen;

  /// No description provided for @toolAvailability.
  ///
  /// In en, this message translates to:
  /// **'Tool availability'**
  String get toolAvailability;

  /// No description provided for @capabilitiesUnavailable.
  ///
  /// In en, this message translates to:
  /// **'Capabilities unavailable'**
  String get capabilitiesUnavailable;

  /// No description provided for @toolStatusUnknown.
  ///
  /// In en, this message translates to:
  /// **'Status unknown'**
  String get toolStatusUnknown;

  /// No description provided for @capabilitiesNotProvided.
  ///
  /// In en, this message translates to:
  /// **'The local service has not provided capability data for this session.'**
  String get capabilitiesNotProvided;

  /// No description provided for @waitingToolStatus.
  ///
  /// In en, this message translates to:
  /// **'Waiting for local tool status.'**
  String get waitingToolStatus;

  /// No description provided for @toolAvailabilityProvenance.
  ///
  /// In en, this message translates to:
  /// **'Tool availability & provenance'**
  String get toolAvailabilityProvenance;

  /// No description provided for @workerVersion.
  ///
  /// In en, this message translates to:
  /// **'Worker {version}'**
  String workerVersion(Object version);

  /// No description provided for @ffmpeg.
  ///
  /// In en, this message translates to:
  /// **'FFmpeg'**
  String get ffmpeg;

  /// No description provided for @ffprobe.
  ///
  /// In en, this message translates to:
  /// **'FFprobe'**
  String get ffprobe;

  /// No description provided for @gyroflow.
  ///
  /// In en, this message translates to:
  /// **'Gyroflow'**
  String get gyroflow;

  /// No description provided for @catalyst.
  ///
  /// In en, this message translates to:
  /// **'Catalyst'**
  String get catalyst;

  /// No description provided for @gyroflowBuild.
  ///
  /// In en, this message translates to:
  /// **'Gyroflow build'**
  String get gyroflowBuild;

  /// No description provided for @cliStatus.
  ///
  /// In en, this message translates to:
  /// **'CLI status'**
  String get cliStatus;

  /// No description provided for @priorCliInvocation.
  ///
  /// In en, this message translates to:
  /// **'Prior CLI invocation'**
  String get priorCliInvocation;

  /// No description provided for @savedPathProfileGuard.
  ///
  /// In en, this message translates to:
  /// **'Saved-path profile guard'**
  String get savedPathProfileGuard;

  /// No description provided for @latestExportValidation.
  ///
  /// In en, this message translates to:
  /// **'Latest export validation'**
  String get latestExportValidation;

  /// No description provided for @latestMediaExportVerified.
  ///
  /// In en, this message translates to:
  /// **'Latest media export verified'**
  String get latestMediaExportVerified;

  /// No description provided for @latestTrimMappingVerified.
  ///
  /// In en, this message translates to:
  /// **'Latest trim mapping verified'**
  String get latestTrimMappingVerified;

  /// No description provided for @profileSafety.
  ///
  /// In en, this message translates to:
  /// **'Profile safety'**
  String get profileSafety;

  /// No description provided for @exportHeldProfileSafety.
  ///
  /// In en, this message translates to:
  /// **'Export held for profile safety'**
  String get exportHeldProfileSafety;

  /// No description provided for @profileSafetyMismatchMessage.
  ///
  /// In en, this message translates to:
  /// **'The service-reported executable and saved tool_paths.gyroflow do not both match a verified CLI/profile guard. Save the audited executable path and refresh its capability status before exporting. ChaSteady keeps export held.'**
  String get profileSafetyMismatchMessage;

  /// No description provided for @boundedExportNeedsReview.
  ///
  /// In en, this message translates to:
  /// **'Latest bounded export needs review'**
  String get boundedExportNeedsReview;

  /// No description provided for @boundedExportNeedsReviewMessage.
  ///
  /// In en, this message translates to:
  /// **'The service reports needs_review. A successful CLI exit or prior invocation does not verify this output; media export and trim mapping remain separate checks.'**
  String get boundedExportNeedsReviewMessage;

  /// No description provided for @exportNeedsVerification.
  ///
  /// In en, this message translates to:
  /// **'A real export still needs verification'**
  String get exportNeedsVerification;

  /// No description provided for @exportVerificationMessage.
  ///
  /// In en, this message translates to:
  /// **'The prior CLI/profile check is a launch guard only. Each new rendered export needs frame, PTS, and content-alignment review before it can be trusted.'**
  String get exportVerificationMessage;

  /// No description provided for @catalystManualRequired.
  ///
  /// In en, this message translates to:
  /// **'Catalyst assisted export · manual required'**
  String get catalystManualRequired;

  /// No description provided for @catalystManualRequiredMessage.
  ///
  /// In en, this message translates to:
  /// **'This UI does not expose an automatic Catalyst button. The current owned-window probe did not expose controls and changed a Sony profile log; the stage remains manual regardless of installation detection.'**
  String get catalystManualRequiredMessage;

  /// No description provided for @someStagesUnavailable.
  ///
  /// In en, this message translates to:
  /// **'Some stages may be unavailable'**
  String get someStagesUnavailable;

  /// No description provided for @missingToolsTruthful.
  ///
  /// In en, this message translates to:
  /// **'Missing or unknown executables are shown as such. Jobs are not marked complete when a tool is absent.'**
  String get missingToolsTruthful;

  /// No description provided for @detected.
  ///
  /// In en, this message translates to:
  /// **'Detected'**
  String get detected;

  /// No description provided for @notDetected.
  ///
  /// In en, this message translates to:
  /// **'Not detected'**
  String get notDetected;

  /// No description provided for @statusUnknown.
  ///
  /// In en, this message translates to:
  /// **'Status unknown'**
  String get statusUnknown;

  /// No description provided for @toolCapabilitySemantics.
  ///
  /// In en, this message translates to:
  /// **'{status} tool capability'**
  String toolCapabilitySemantics(Object status);

  /// No description provided for @configuredPath.
  ///
  /// In en, this message translates to:
  /// **'Configured path: {path}'**
  String configuredPath(Object path);

  /// No description provided for @modeValue.
  ///
  /// In en, this message translates to:
  /// **'Mode: {mode}'**
  String modeValue(Object mode);

  /// No description provided for @gyroflowBuildValue.
  ///
  /// In en, this message translates to:
  /// **'Gyroflow build: {value}'**
  String gyroflowBuildValue(Object value);

  /// No description provided for @verified.
  ///
  /// In en, this message translates to:
  /// **'Verified'**
  String get verified;

  /// No description provided for @notVerified.
  ///
  /// In en, this message translates to:
  /// **'Not verified'**
  String get notVerified;

  /// No description provided for @unknown.
  ///
  /// In en, this message translates to:
  /// **'Unknown'**
  String get unknown;

  /// No description provided for @reportedTrue.
  ///
  /// In en, this message translates to:
  /// **'Reported true'**
  String get reportedTrue;

  /// No description provided for @reportedFalse.
  ///
  /// In en, this message translates to:
  /// **'Reported false'**
  String get reportedFalse;

  /// No description provided for @blocked.
  ///
  /// In en, this message translates to:
  /// **'Blocked'**
  String get blocked;

  /// No description provided for @unverified.
  ///
  /// In en, this message translates to:
  /// **'Unverified'**
  String get unverified;

  /// No description provided for @verifiedMedia.
  ///
  /// In en, this message translates to:
  /// **'Verified media'**
  String get verifiedMedia;

  /// No description provided for @cliBlocked.
  ///
  /// In en, this message translates to:
  /// **'CLI blocked'**
  String get cliBlocked;

  /// No description provided for @notAudited.
  ///
  /// In en, this message translates to:
  /// **'Not audited'**
  String get notAudited;

  /// No description provided for @required.
  ///
  /// In en, this message translates to:
  /// **'Required'**
  String get required;

  /// No description provided for @notRequired.
  ///
  /// In en, this message translates to:
  /// **'Not required'**
  String get notRequired;

  /// No description provided for @savedPathMismatch.
  ///
  /// In en, this message translates to:
  /// **'Saved path mismatch'**
  String get savedPathMismatch;

  /// No description provided for @cliProfileGuardUnavailable.
  ///
  /// In en, this message translates to:
  /// **'CLI/profile guard unavailable'**
  String get cliProfileGuardUnavailable;

  /// No description provided for @verifiedForSavedPath.
  ///
  /// In en, this message translates to:
  /// **'Verified for saved path'**
  String get verifiedForSavedPath;

  /// No description provided for @originalStatusLabel.
  ///
  /// In en, this message translates to:
  /// **'Original status: {value}'**
  String originalStatusLabel(Object value);

  /// No description provided for @screenSettingsSubtitle.
  ///
  /// In en, this message translates to:
  /// **'Local appearance and reported runtime status.'**
  String get screenSettingsSubtitle;

  /// No description provided for @appearance.
  ///
  /// In en, this message translates to:
  /// **'Appearance'**
  String get appearance;

  /// No description provided for @preferencesLocalOnly.
  ///
  /// In en, this message translates to:
  /// **'Preferences are stored by the local service. No account or cloud sync is used.'**
  String get preferencesLocalOnly;

  /// No description provided for @theme.
  ///
  /// In en, this message translates to:
  /// **'Theme'**
  String get theme;

  /// No description provided for @themeSystem.
  ///
  /// In en, this message translates to:
  /// **'System'**
  String get themeSystem;

  /// No description provided for @themeLight.
  ///
  /// In en, this message translates to:
  /// **'Light'**
  String get themeLight;

  /// No description provided for @themeDark.
  ///
  /// In en, this message translates to:
  /// **'Dark'**
  String get themeDark;

  /// No description provided for @language.
  ///
  /// In en, this message translates to:
  /// **'Language'**
  String get language;

  /// No description provided for @brandSeed.
  ///
  /// In en, this message translates to:
  /// **'Brand seed'**
  String get brandSeed;

  /// No description provided for @seedGreenGray.
  ///
  /// In en, this message translates to:
  /// **'ChaSteady green-gray'**
  String get seedGreenGray;

  /// No description provided for @seedMistBlue.
  ///
  /// In en, this message translates to:
  /// **'Mist blue'**
  String get seedMistBlue;

  /// No description provided for @seedClay.
  ///
  /// In en, this message translates to:
  /// **'Clay'**
  String get seedClay;

  /// No description provided for @seedSoftViolet.
  ///
  /// In en, this message translates to:
  /// **'Soft violet'**
  String get seedSoftViolet;

  /// No description provided for @systemAccentFallback.
  ///
  /// In en, this message translates to:
  /// **'System accent fallback'**
  String get systemAccentFallback;

  /// No description provided for @systemAccentFallbackMessage.
  ///
  /// In en, this message translates to:
  /// **'A verified Windows accent color is not provided by the local service. The saved ChaSteady seed is used instead.'**
  String get systemAccentFallbackMessage;

  /// No description provided for @savedPreferencesUnavailable.
  ///
  /// In en, this message translates to:
  /// **'Saved preferences unavailable'**
  String get savedPreferencesUnavailable;

  /// No description provided for @preferencesNotSaved.
  ///
  /// In en, this message translates to:
  /// **'Preferences were not saved'**
  String get preferencesNotSaved;

  /// No description provided for @savePreferences.
  ///
  /// In en, this message translates to:
  /// **'Save preferences'**
  String get savePreferences;

  /// No description provided for @saved.
  ///
  /// In en, this message translates to:
  /// **'Saved'**
  String get saved;

  /// No description provided for @waitingPreferenceRecord.
  ///
  /// In en, this message translates to:
  /// **'Waiting for the local preference record'**
  String get waitingPreferenceRecord;

  /// No description provided for @executablePaths.
  ///
  /// In en, this message translates to:
  /// **'Executable paths'**
  String get executablePaths;

  /// No description provided for @executablePathsSubtitle.
  ///
  /// In en, this message translates to:
  /// **'Configure the known local FFmpeg, FFprobe, Gyroflow, and Catalyst tools.'**
  String get executablePathsSubtitle;

  /// No description provided for @privacyScope.
  ///
  /// In en, this message translates to:
  /// **'Privacy & scope'**
  String get privacyScope;

  /// No description provided for @mediaPathsLocal.
  ///
  /// In en, this message translates to:
  /// **'Media paths are local absolute paths; footage is not uploaded.'**
  String get mediaPathsLocal;

  /// No description provided for @noCloudModels.
  ///
  /// In en, this message translates to:
  /// **'No cloud models, analytics, or remote font assets are used.'**
  String get noCloudModels;

  /// No description provided for @browserPreviewOwned.
  ///
  /// In en, this message translates to:
  /// **'The browser preview is limited to owned H.264/AAC proxy artifacts.'**
  String get browserPreviewOwned;

  /// No description provided for @ffmpegExecutable.
  ///
  /// In en, this message translates to:
  /// **'FFmpeg executable'**
  String get ffmpegExecutable;

  /// No description provided for @ffprobeExecutable.
  ///
  /// In en, this message translates to:
  /// **'FFprobe executable'**
  String get ffprobeExecutable;

  /// No description provided for @gyroflowCliExecutable.
  ///
  /// In en, this message translates to:
  /// **'Gyroflow CLI executable'**
  String get gyroflowCliExecutable;

  /// No description provided for @catalystExecutable.
  ///
  /// In en, this message translates to:
  /// **'Catalyst executable'**
  String get catalystExecutable;

  /// No description provided for @toolPathsPersistedMessage.
  ///
  /// In en, this message translates to:
  /// **'These app-owned paths are persisted through the local service and apply to future jobs. They are not per-job command overrides.'**
  String get toolPathsPersistedMessage;

  /// No description provided for @absolutePathClearHelper.
  ///
  /// In en, this message translates to:
  /// **'Absolute local path; leave blank only to clear this setting.'**
  String get absolutePathClearHelper;

  /// No description provided for @typeToolPath.
  ///
  /// In en, this message translates to:
  /// **'Type local {tool} path'**
  String typeToolPath(Object tool);

  /// No description provided for @clearToolPath.
  ///
  /// In en, this message translates to:
  /// **'Clear {tool} path'**
  String clearToolPath(Object tool);

  /// No description provided for @toolPathRecordUnavailable.
  ///
  /// In en, this message translates to:
  /// **'Tool path record unavailable'**
  String get toolPathRecordUnavailable;

  /// No description provided for @toolPathRecordUnavailableMessage.
  ///
  /// In en, this message translates to:
  /// **'The service did not return all four known executable paths. Saving is disabled so an unknown path cannot be cleared accidentally.'**
  String get toolPathRecordUnavailableMessage;

  /// No description provided for @absoluteExecutablePaths.
  ///
  /// In en, this message translates to:
  /// **'Use absolute local executable paths'**
  String get absoluteExecutablePaths;

  /// No description provided for @invalidToolPathMessage.
  ///
  /// In en, this message translates to:
  /// **'Relative paths and URLs cannot be saved as tool paths.'**
  String get invalidToolPathMessage;

  /// No description provided for @unsavedToolPaths.
  ///
  /// In en, this message translates to:
  /// **'Unsaved tool paths'**
  String get unsavedToolPaths;

  /// No description provided for @unsavedToolPathsMessage.
  ///
  /// In en, this message translates to:
  /// **'Save preferences to persist these ChaSteady tool paths.'**
  String get unsavedToolPathsMessage;

  /// No description provided for @toolExecutableFallback.
  ///
  /// In en, this message translates to:
  /// **'tool executable'**
  String get toolExecutableFallback;

  /// No description provided for @screenJobsSubtitle.
  ///
  /// In en, this message translates to:
  /// **'Only jobs returned by the local worker appear here.'**
  String get screenJobsSubtitle;

  /// No description provided for @refreshJobs.
  ///
  /// In en, this message translates to:
  /// **'Refresh jobs'**
  String get refreshJobs;

  /// No description provided for @queueLoadFailed.
  ///
  /// In en, this message translates to:
  /// **'Could not load the queue'**
  String get queueLoadFailed;

  /// No description provided for @waitingQueueData.
  ///
  /// In en, this message translates to:
  /// **'Waiting for queue data'**
  String get waitingQueueData;

  /// No description provided for @serviceNoJobList.
  ///
  /// In en, this message translates to:
  /// **'The service has not returned a job list yet.'**
  String get serviceNoJobList;

  /// No description provided for @queueUnavailable.
  ///
  /// In en, this message translates to:
  /// **'Queue unavailable'**
  String get queueUnavailable;

  /// No description provided for @queueUnknownNotEmpty.
  ///
  /// In en, this message translates to:
  /// **'No local session is active, so the job list is unknown—not empty.'**
  String get queueUnknownNotEmpty;

  /// No description provided for @noJobsYet.
  ///
  /// In en, this message translates to:
  /// **'No jobs yet'**
  String get noJobsYet;

  /// No description provided for @emptyQueueDescription.
  ///
  /// In en, this message translates to:
  /// **'The local service returned an empty queue. Create a job from the Workbench when its sources and required tools are ready.'**
  String get emptyQueueDescription;

  /// No description provided for @latestJobDetailsUnavailable.
  ///
  /// In en, this message translates to:
  /// **'Latest job details unavailable'**
  String get latestJobDetailsUnavailable;

  /// No description provided for @screenJobsError.
  ///
  /// In en, this message translates to:
  /// **'Could not load job details'**
  String get screenJobsError;

  /// No description provided for @jobActivity.
  ///
  /// In en, this message translates to:
  /// **'Job activity'**
  String get jobActivity;

  /// No description provided for @waitingLocalQueue.
  ///
  /// In en, this message translates to:
  /// **'Waiting for the local queue'**
  String get waitingLocalQueue;

  /// No description provided for @realJobsCount.
  ///
  /// In en, this message translates to:
  /// **'{count, plural, =1{1 real job from the service} other{{count} real jobs from the service}}'**
  String realJobsCount(int count);

  /// No description provided for @resizeJobActivityPanel.
  ///
  /// In en, this message translates to:
  /// **'Resize job activity panel'**
  String get resizeJobActivityPanel;

  /// No description provided for @resizeJobSheet.
  ///
  /// In en, this message translates to:
  /// **'Resize job sheet'**
  String get resizeJobSheet;

  /// No description provided for @queueCouldNotRefresh.
  ///
  /// In en, this message translates to:
  /// **'Queue could not be refreshed'**
  String get queueCouldNotRefresh;

  /// No description provided for @loadingLocalJobs.
  ///
  /// In en, this message translates to:
  /// **'Loading local jobs'**
  String get loadingLocalJobs;

  /// No description provided for @queueEmpty.
  ///
  /// In en, this message translates to:
  /// **'Queue is empty'**
  String get queueEmpty;

  /// No description provided for @noJobsReturned.
  ///
  /// In en, this message translates to:
  /// **'No jobs have been returned by the local service. A job appears here only after the service creates one.'**
  String get noJobsReturned;

  /// No description provided for @jobDetails.
  ///
  /// In en, this message translates to:
  /// **'Job details'**
  String get jobDetails;

  /// No description provided for @jobError.
  ///
  /// In en, this message translates to:
  /// **'Job error'**
  String get jobError;

  /// No description provided for @manualActionRequired.
  ///
  /// In en, this message translates to:
  /// **'Manual action required'**
  String get manualActionRequired;

  /// No description provided for @manualActionMessage.
  ///
  /// In en, this message translates to:
  /// **'No UI automation success is assumed. Follow only the explicit next steps returned by the local worker.'**
  String get manualActionMessage;

  /// No description provided for @reviewBeforeContinue.
  ///
  /// In en, this message translates to:
  /// **'Review before continuing'**
  String get reviewBeforeContinue;

  /// No description provided for @reviewPerceptualFovMessage.
  ///
  /// In en, this message translates to:
  /// **'The worker has not certified a perceptual winner or original-field-of-view result.'**
  String get reviewPerceptualFovMessage;

  /// No description provided for @evidenceScopeLimited.
  ///
  /// In en, this message translates to:
  /// **'Evidence scope is limited'**
  String get evidenceScopeLimited;

  /// No description provided for @verifiedMediaScopeMessage.
  ///
  /// In en, this message translates to:
  /// **'This status confirms media/geometry evidence only. It is not a perceptual winner or an original FOV certificate.'**
  String get verifiedMediaScopeMessage;

  /// No description provided for @interpretationLimits.
  ///
  /// In en, this message translates to:
  /// **'Interpretation limits'**
  String get interpretationLimits;

  /// No description provided for @fusionScopeMessage.
  ///
  /// In en, this message translates to:
  /// **'Source FOV is unverified; CTB describes the input rectangle only. No crop or quality claim is inferred from this screen.'**
  String get fusionScopeMessage;

  /// No description provided for @exportVerificationRequired.
  ///
  /// In en, this message translates to:
  /// **'Export verification still required'**
  String get exportVerificationRequired;

  /// No description provided for @exportVerificationDetails.
  ///
  /// In en, this message translates to:
  /// **'A successful process exit does not validate frame count, PTS alignment, or content alignment. Source FOV remains unverified.'**
  String get exportVerificationDetails;

  /// No description provided for @ownedOutputs.
  ///
  /// In en, this message translates to:
  /// **'Owned outputs'**
  String get ownedOutputs;

  /// No description provided for @workerWarningsCount.
  ///
  /// In en, this message translates to:
  /// **'Worker warnings · {count}'**
  String workerWarningsCount(int count);

  /// No description provided for @workerResultDetails.
  ///
  /// In en, this message translates to:
  /// **'Worker result details'**
  String get workerResultDetails;

  /// No description provided for @reportedScope.
  ///
  /// In en, this message translates to:
  /// **'Reported scope: {scope}. This states what was checked only; it is not a perceptual/content or original-FOV certification.'**
  String reportedScope(Object scope);

  /// No description provided for @reportedReferenceFov.
  ///
  /// In en, this message translates to:
  /// **'Reported reference FOV metadata: {value} (analysis only)'**
  String reportedReferenceFov(Object value);

  /// No description provided for @fovNotCropGuarantee.
  ///
  /// In en, this message translates to:
  /// **'FOV metadata is not a crop guarantee'**
  String get fovNotCropGuarantee;

  /// No description provided for @fovNoCropDetails.
  ///
  /// In en, this message translates to:
  /// **'Reference normalization does not change render zoom and does not certify that the output is crop-free.'**
  String get fovNoCropDetails;

  /// No description provided for @artifactValidationScope.
  ///
  /// In en, this message translates to:
  /// **'Artifact validation scope'**
  String get artifactValidationScope;

  /// No description provided for @artifactPreview.
  ///
  /// In en, this message translates to:
  /// **'Local H.264/AAC preview. The browser requests this owned artifact with byte ranges; the original is not streamed.'**
  String get artifactPreview;

  /// No description provided for @previewCodecUnknown.
  ///
  /// In en, this message translates to:
  /// **'Preview codec metadata is not confirmed. No browser-decoder support is assumed; create or inspect a real H.264/AAC preview.'**
  String get previewCodecUnknown;

  /// No description provided for @artifactWarningsCount.
  ///
  /// In en, this message translates to:
  /// **'Artifact warnings · {count}'**
  String artifactWarningsCount(int count);

  /// No description provided for @openLocalOutput.
  ///
  /// In en, this message translates to:
  /// **'Open local output'**
  String get openLocalOutput;

  /// No description provided for @unsupportedBrowserPlayback.
  ///
  /// In en, this message translates to:
  /// **'Local browser playback is not available on this platform. Create a real preview artifact and use the web workbench.'**
  String get unsupportedBrowserPlayback;

  /// No description provided for @localPreviewSemantics.
  ///
  /// In en, this message translates to:
  /// **'Local H.264/AAC preview'**
  String get localPreviewSemantics;

  /// No description provided for @jobStateQueued.
  ///
  /// In en, this message translates to:
  /// **'Queued'**
  String get jobStateQueued;

  /// No description provided for @jobStateRunning.
  ///
  /// In en, this message translates to:
  /// **'Running'**
  String get jobStateRunning;

  /// No description provided for @jobStateNeedsManual.
  ///
  /// In en, this message translates to:
  /// **'Needs manual step'**
  String get jobStateNeedsManual;

  /// No description provided for @jobStateNeedsReview.
  ///
  /// In en, this message translates to:
  /// **'Needs review'**
  String get jobStateNeedsReview;

  /// No description provided for @jobStateFailed.
  ///
  /// In en, this message translates to:
  /// **'Failed'**
  String get jobStateFailed;

  /// No description provided for @jobStateCancelled.
  ///
  /// In en, this message translates to:
  /// **'Cancelled'**
  String get jobStateCancelled;

  /// No description provided for @jobStateVerifiedMedia.
  ///
  /// In en, this message translates to:
  /// **'Verified media evidence only'**
  String get jobStateVerifiedMedia;

  /// No description provided for @unknownJobState.
  ///
  /// In en, this message translates to:
  /// **'Status: {state}'**
  String unknownJobState(Object state);

  /// No description provided for @progressNotReported.
  ///
  /// In en, this message translates to:
  /// **'Progress not reported'**
  String get progressNotReported;

  /// No description provided for @currentStage.
  ///
  /// In en, this message translates to:
  /// **'Current stage'**
  String get currentStage;

  /// No description provided for @stageProgressUnknown.
  ///
  /// In en, this message translates to:
  /// **'{stage} progress unknown'**
  String stageProgressUnknown(Object stage);

  /// No description provided for @stageProgressPercent.
  ///
  /// In en, this message translates to:
  /// **'{stage} progress {percent} percent'**
  String stageProgressPercent(Object stage, int percent);

  /// No description provided for @indeterminateProgress.
  ///
  /// In en, this message translates to:
  /// **'Indeterminate'**
  String get indeterminateProgress;

  /// No description provided for @noWorkerPercentage.
  ///
  /// In en, this message translates to:
  /// **'The worker has not reported a percentage for this stage.'**
  String get noWorkerPercentage;

  /// No description provided for @stageValue.
  ///
  /// In en, this message translates to:
  /// **'Stage: {stage}'**
  String stageValue(Object stage);

  /// No description provided for @warningCount.
  ///
  /// In en, this message translates to:
  /// **'{count, plural, =1{1 warning from the worker} other{{count} warnings from the worker}}'**
  String warningCount(int count);

  /// No description provided for @cancelJob.
  ///
  /// In en, this message translates to:
  /// **'Cancel job'**
  String get cancelJob;

  /// No description provided for @jobKindFusion.
  ///
  /// In en, this message translates to:
  /// **'CTB fusion'**
  String get jobKindFusion;

  /// No description provided for @jobKindPreview.
  ///
  /// In en, this message translates to:
  /// **'Browser preview'**
  String get jobKindPreview;

  /// No description provided for @jobKindGyroflowExport.
  ///
  /// In en, this message translates to:
  /// **'Gyroflow export'**
  String get jobKindGyroflowExport;

  /// No description provided for @jobKindCatalyst.
  ///
  /// In en, this message translates to:
  /// **'Catalyst assisted stage'**
  String get jobKindCatalyst;

  /// No description provided for @jobKindValidate.
  ///
  /// In en, this message translates to:
  /// **'Media validation'**
  String get jobKindValidate;

  /// No description provided for @jobKindUnknown.
  ///
  /// In en, this message translates to:
  /// **'Original job kind: {kind}'**
  String jobKindUnknown(Object kind);

  /// No description provided for @toolStatusDetected.
  ///
  /// In en, this message translates to:
  /// **'Detected'**
  String get toolStatusDetected;

  /// No description provided for @toolStatusMissing.
  ///
  /// In en, this message translates to:
  /// **'Not detected'**
  String get toolStatusMissing;

  /// No description provided for @pickerChooseLocal.
  ///
  /// In en, this message translates to:
  /// **'Choose local {kind}'**
  String pickerChooseLocal(Object kind);

  /// No description provided for @pickerEnterLocal.
  ///
  /// In en, this message translates to:
  /// **'Enter local path'**
  String get pickerEnterLocal;

  /// No description provided for @pathDialogTitle.
  ///
  /// In en, this message translates to:
  /// **'Enter local {label} path'**
  String pathDialogTitle(Object label);

  /// No description provided for @absoluteLocalPath.
  ///
  /// In en, this message translates to:
  /// **'Absolute local path'**
  String get absoluteLocalPath;

  /// No description provided for @pathStaysLocal.
  ///
  /// In en, this message translates to:
  /// **'The file stays on this computer. Browser file upload is not used.'**
  String get pathStaysLocal;

  /// No description provided for @usePath.
  ///
  /// In en, this message translates to:
  /// **'Use path'**
  String get usePath;

  /// No description provided for @cancel.
  ///
  /// In en, this message translates to:
  /// **'Cancel'**
  String get cancel;

  /// No description provided for @workerStarting.
  ///
  /// In en, this message translates to:
  /// **'Starting the local worker.'**
  String get workerStarting;

  /// No description provided for @workerCancelledBeforeStart.
  ///
  /// In en, this message translates to:
  /// **'Cancelled before processing started.'**
  String get workerCancelledBeforeStart;

  /// No description provided for @workerCancellationRequested.
  ///
  /// In en, this message translates to:
  /// **'Cancellation requested; owned work was stopped.'**
  String get workerCancellationRequested;

  /// No description provided for @workerInspectSource.
  ///
  /// In en, this message translates to:
  /// **'Inspecting the selected source media.'**
  String get workerInspectSource;

  /// No description provided for @workerInspectFusionInputs.
  ///
  /// In en, this message translates to:
  /// **'Inspecting inputs and selected source-frame timestamps.'**
  String get workerInspectFusionInputs;

  /// No description provided for @workerCachedTrajectory.
  ///
  /// In en, this message translates to:
  /// **'Reading the approved C7037 historical trajectory; this is not a new measurement.'**
  String get workerCachedTrajectory;

  /// No description provided for @workerComputeFusion.
  ///
  /// In en, this message translates to:
  /// **'Computing the two-anchor global rigid trajectory without blending Gyroflow pixels.'**
  String get workerComputeFusion;

  /// No description provided for @workerRegistrationProgress.
  ///
  /// In en, this message translates to:
  /// **'Registering frame {current} of {total}.'**
  String workerRegistrationProgress(int current, int total);

  /// No description provided for @workerRenderProgress.
  ///
  /// In en, this message translates to:
  /// **'Rendering frame {current} of {total}.'**
  String workerRenderProgress(int current, int total);

  /// No description provided for @workerVerifyOutput.
  ///
  /// In en, this message translates to:
  /// **'Fully decoding and verifying video and corresponding source audio.'**
  String get workerVerifyOutput;

  /// No description provided for @workerPreviewInspect.
  ///
  /// In en, this message translates to:
  /// **'Inspecting source media to prepare a local browser preview.'**
  String get workerPreviewInspect;

  /// No description provided for @workerPreviewEncode.
  ///
  /// In en, this message translates to:
  /// **'Encoding an H.264/AAC preview; the encoder did not provide verified numeric progress.'**
  String get workerPreviewEncode;

  /// No description provided for @workerValidateMedia.
  ///
  /// In en, this message translates to:
  /// **'Fully decoding audio and video, then checking actual frame count and requested frame rate.'**
  String get workerValidateMedia;

  /// No description provided for @workerCatalystManual.
  ///
  /// In en, this message translates to:
  /// **'Catalyst automation is not verified; manual steps are required.'**
  String get workerCatalystManual;

  /// No description provided for @jobErrorCode.
  ///
  /// In en, this message translates to:
  /// **'Error code: {code}'**
  String jobErrorCode(Object code);

  /// No description provided for @serviceHttpError.
  ///
  /// In en, this message translates to:
  /// **'The local service returned HTTP {statusCode}.'**
  String serviceHttpError(int statusCode);

  /// No description provided for @mode.
  ///
  /// In en, this message translates to:
  /// **'Mode'**
  String get mode;

  /// No description provided for @uiAutomationVerification.
  ///
  /// In en, this message translates to:
  /// **'UI automation verification'**
  String get uiAutomationVerification;

  /// No description provided for @stageStarting.
  ///
  /// In en, this message translates to:
  /// **'Starting'**
  String get stageStarting;

  /// No description provided for @stageInspect.
  ///
  /// In en, this message translates to:
  /// **'Inspecting media'**
  String get stageInspect;

  /// No description provided for @stagePreviewEncode.
  ///
  /// In en, this message translates to:
  /// **'Encoding preview'**
  String get stagePreviewEncode;

  /// No description provided for @stageMediaValidation.
  ///
  /// In en, this message translates to:
  /// **'Media validation'**
  String get stageMediaValidation;

  /// No description provided for @stageCachedTrajectory.
  ///
  /// In en, this message translates to:
  /// **'Loading approved cached trajectory'**
  String get stageCachedTrajectory;

  /// No description provided for @stageFusion.
  ///
  /// In en, this message translates to:
  /// **'Fusion'**
  String get stageFusion;

  /// No description provided for @stageRegistration.
  ///
  /// In en, this message translates to:
  /// **'Frame registration'**
  String get stageRegistration;

  /// No description provided for @stageQuietTracking.
  ///
  /// In en, this message translates to:
  /// **'Quiet-window tracking'**
  String get stageQuietTracking;

  /// No description provided for @stageRender.
  ///
  /// In en, this message translates to:
  /// **'Rendering'**
  String get stageRender;

  /// No description provided for @stageVerify.
  ///
  /// In en, this message translates to:
  /// **'Verifying output'**
  String get stageVerify;

  /// No description provided for @stageCatalystManual.
  ///
  /// In en, this message translates to:
  /// **'Catalyst manual handoff'**
  String get stageCatalystManual;

  /// No description provided for @workerQueued.
  ///
  /// In en, this message translates to:
  /// **'Waiting in the local worker queue.'**
  String get workerQueued;

  /// No description provided for @workerNeedsManual.
  ///
  /// In en, this message translates to:
  /// **'The worker requires a manual step; no automatic action was performed.'**
  String get workerNeedsManual;

  /// No description provided for @workerNeedsReview.
  ///
  /// In en, this message translates to:
  /// **'The worker requires review before this result can be trusted.'**
  String get workerNeedsReview;

  /// No description provided for @workerFailed.
  ///
  /// In en, this message translates to:
  /// **'The worker could not complete this task.'**
  String get workerFailed;

  /// No description provided for @workerCancelled.
  ///
  /// In en, this message translates to:
  /// **'The worker cancelled this task.'**
  String get workerCancelled;

  /// No description provided for @workerVerifiedMedia.
  ///
  /// In en, this message translates to:
  /// **'Media evidence was verified; this does not certify perceptual quality or original FOV.'**
  String get workerVerifiedMedia;

  /// No description provided for @workerQuietTrackingProgress.
  ///
  /// In en, this message translates to:
  /// **'Tracking quiet frame {current} of {total}.'**
  String workerQuietTrackingProgress(int current, int total);

  /// No description provided for @workerErrorNeedsReview.
  ///
  /// In en, this message translates to:
  /// **'This result requires manual review and is not certified.'**
  String get workerErrorNeedsReview;

  /// No description provided for @workerErrorNeedsManual.
  ///
  /// In en, this message translates to:
  /// **'This task requires manual steps; the UI did not automate them.'**
  String get workerErrorNeedsManual;

  /// No description provided for @workerErrorCancelled.
  ///
  /// In en, this message translates to:
  /// **'The task was cancelled.'**
  String get workerErrorCancelled;

  /// No description provided for @workerErrorInterrupted.
  ///
  /// In en, this message translates to:
  /// **'The owned worker was interrupted before completion.'**
  String get workerErrorInterrupted;

  /// No description provided for @workerErrorMissingCapability.
  ///
  /// In en, this message translates to:
  /// **'A required local tool capability is unavailable.'**
  String get workerErrorMissingCapability;

  /// No description provided for @workerErrorProcessingFailed.
  ///
  /// In en, this message translates to:
  /// **'The local worker could not process this request.'**
  String get workerErrorProcessingFailed;

  /// No description provided for @playerLoading.
  ///
  /// In en, this message translates to:
  /// **'Loading preview'**
  String get playerLoading;

  /// No description provided for @playerPlay.
  ///
  /// In en, this message translates to:
  /// **'Play'**
  String get playerPlay;

  /// No description provided for @playerPause.
  ///
  /// In en, this message translates to:
  /// **'Pause'**
  String get playerPause;

  /// No description provided for @playerSeek.
  ///
  /// In en, this message translates to:
  /// **'Seek'**
  String get playerSeek;

  /// No description provided for @playerVolume.
  ///
  /// In en, this message translates to:
  /// **'Volume'**
  String get playerVolume;

  /// No description provided for @playerMute.
  ///
  /// In en, this message translates to:
  /// **'Mute'**
  String get playerMute;

  /// No description provided for @playerUnmute.
  ///
  /// In en, this message translates to:
  /// **'Unmute'**
  String get playerUnmute;

  /// No description provided for @playerError.
  ///
  /// In en, this message translates to:
  /// **'Player error: {code}'**
  String playerError(Object code);

  /// No description provided for @playerFinished.
  ///
  /// In en, this message translates to:
  /// **'Playback finished'**
  String get playerFinished;

  /// No description provided for @nativeLeaseUnavailable.
  ///
  /// In en, this message translates to:
  /// **'The local media preview lease is unavailable.'**
  String get nativeLeaseUnavailable;

  /// No description provided for @nativeActionUnsupported.
  ///
  /// In en, this message translates to:
  /// **'This native platform action is not supported.'**
  String get nativeActionUnsupported;

  /// No description provided for @nativeProtocolUnsupported.
  ///
  /// In en, this message translates to:
  /// **'The native platform protocol version is not supported.'**
  String get nativeProtocolUnsupported;

  /// No description provided for @nativeProtocolError.
  ///
  /// In en, this message translates to:
  /// **'The native platform request could not be completed.'**
  String get nativeProtocolError;

  /// No description provided for @intervalStartLabel.
  ///
  /// In en, this message translates to:
  /// **'Start {row} (seconds)'**
  String intervalStartLabel(int row);

  /// No description provided for @intervalEndLabel.
  ///
  /// In en, this message translates to:
  /// **'End {row} (seconds)'**
  String intervalEndLabel(int row);

  /// No description provided for @intervalExample.
  ///
  /// In en, this message translates to:
  /// **'e.g. {value}'**
  String intervalExample(Object value);

  /// No description provided for @removeInterval.
  ///
  /// In en, this message translates to:
  /// **'Remove interval {row}'**
  String removeInterval(int row);

  /// No description provided for @cliMode.
  ///
  /// In en, this message translates to:
  /// **'CLI'**
  String get cliMode;

  /// No description provided for @originalArtifactLabel.
  ///
  /// In en, this message translates to:
  /// **'Worker-provided artifact label: {label}'**
  String originalArtifactLabel(Object label);

  /// No description provided for @artifactFormat.
  ///
  /// In en, this message translates to:
  /// **'Worker-reported artifact type: {kind} · media type: {mime}'**
  String artifactFormat(Object kind, Object mime);

  /// No description provided for @artifactKindUnknown.
  ///
  /// In en, this message translates to:
  /// **'Original artifact type: {kind}'**
  String artifactKindUnknown(Object kind);

  /// No description provided for @desktopActionsUnavailable.
  ///
  /// In en, this message translates to:
  /// **'Native desktop actions are unavailable on this platform.'**
  String get desktopActionsUnavailable;

  /// No description provided for @invalidJobsList.
  ///
  /// In en, this message translates to:
  /// **'The local service returned an invalid jobs list.'**
  String get invalidJobsList;

  /// No description provided for @invalidPresetCatalog.
  ///
  /// In en, this message translates to:
  /// **'The local service returned an invalid preset catalog.'**
  String get invalidPresetCatalog;

  /// No description provided for @invalidServiceResponse.
  ///
  /// In en, this message translates to:
  /// **'The local service returned an invalid response.'**
  String get invalidServiceResponse;

  /// No description provided for @invalidLocalResourceId.
  ///
  /// In en, this message translates to:
  /// **'The service returned an invalid local resource identifier.'**
  String get invalidLocalResourceId;

  /// No description provided for @missingJobRecord.
  ///
  /// In en, this message translates to:
  /// **'The local service did not return a job record.'**
  String get missingJobRecord;

  /// No description provided for @localConnectionFailed.
  ///
  /// In en, this message translates to:
  /// **'Could not reach the local {appName} service.'**
  String localConnectionFailed(Object appName);

  /// No description provided for @invalidApiJobKind.
  ///
  /// In en, this message translates to:
  /// **'A supported job kind is required.'**
  String get invalidApiJobKind;

  /// No description provided for @apiJobFieldsNested.
  ///
  /// In en, this message translates to:
  /// **'Job fields must be nested under request.'**
  String get apiJobFieldsNested;

  /// No description provided for @apiJobRequestInvalid.
  ///
  /// In en, this message translates to:
  /// **'Job request must be an object.'**
  String get apiJobRequestInvalid;

  /// No description provided for @invalidArtifactPreview.
  ///
  /// In en, this message translates to:
  /// **'This artifact cannot be opened as a local preview.'**
  String get invalidArtifactPreview;

  /// No description provided for @catalogEntry.
  ///
  /// In en, this message translates to:
  /// **'Unnamed catalog entry'**
  String get catalogEntry;

  /// No description provided for @unnamedArtifact.
  ///
  /// In en, this message translates to:
  /// **'Unnamed artifact'**
  String get unnamedArtifact;

  /// No description provided for @nativeProtocolInvalidRequest.
  ///
  /// In en, this message translates to:
  /// **'The native protocol request is invalid.'**
  String get nativeProtocolInvalidRequest;

  /// No description provided for @nativeWorkerStopping.
  ///
  /// In en, this message translates to:
  /// **'The local worker is stopping.'**
  String get nativeWorkerStopping;

  /// No description provided for @nativeWorkerStopped.
  ///
  /// In en, this message translates to:
  /// **'The local worker has stopped.'**
  String get nativeWorkerStopped;

  /// No description provided for @nativeWorkerStartup.
  ///
  /// In en, this message translates to:
  /// **'The local worker could not start.'**
  String get nativeWorkerStartup;

  /// No description provided for @nativeWorkerBundle.
  ///
  /// In en, this message translates to:
  /// **'The packaged worker bundle is unavailable.'**
  String get nativeWorkerBundle;

  /// No description provided for @nativeWorkerDataRoot.
  ///
  /// In en, this message translates to:
  /// **'The local worker data directory is unavailable.'**
  String get nativeWorkerDataRoot;

  /// No description provided for @nativeWorkerAlreadyRunning.
  ///
  /// In en, this message translates to:
  /// **'A ChaSteady worker is already running.'**
  String get nativeWorkerAlreadyRunning;

  /// No description provided for @nativeWorkerDiagnostics.
  ///
  /// In en, this message translates to:
  /// **'The local worker diagnostics stream is unavailable.'**
  String get nativeWorkerDiagnostics;

  /// No description provided for @nativeWorkerPipe.
  ///
  /// In en, this message translates to:
  /// **'The local worker communication pipe failed.'**
  String get nativeWorkerPipe;

  /// No description provided for @nativeWorkerJob.
  ///
  /// In en, this message translates to:
  /// **'The native worker rejected the job request.'**
  String get nativeWorkerJob;

  /// No description provided for @nativeWorkerReady.
  ///
  /// In en, this message translates to:
  /// **'The local worker did not become ready.'**
  String get nativeWorkerReady;

  /// No description provided for @nativeWorkerNotReady.
  ///
  /// In en, this message translates to:
  /// **'The local worker is not ready.'**
  String get nativeWorkerNotReady;

  /// No description provided for @nativeWorkerRequestLimit.
  ///
  /// In en, this message translates to:
  /// **'The native worker request exceeded its allowed size.'**
  String get nativeWorkerRequestLimit;

  /// No description provided for @nativeWorkerProtocol.
  ///
  /// In en, this message translates to:
  /// **'The native worker protocol request is invalid.'**
  String get nativeWorkerProtocol;

  /// No description provided for @nativeWorkerExited.
  ///
  /// In en, this message translates to:
  /// **'The local worker exited unexpectedly.'**
  String get nativeWorkerExited;

  /// No description provided for @nativeWorkerTimeout.
  ///
  /// In en, this message translates to:
  /// **'The local worker did not respond before the timeout.'**
  String get nativeWorkerTimeout;

  /// No description provided for @nativePickerInvalidKind.
  ///
  /// In en, this message translates to:
  /// **'This local file picker type is not supported.'**
  String get nativePickerInvalidKind;

  /// No description provided for @nativePickerFailed.
  ///
  /// In en, this message translates to:
  /// **'The local file picker could not complete.'**
  String get nativePickerFailed;

  /// No description provided for @nativeMediaInvalidArtifact.
  ///
  /// In en, this message translates to:
  /// **'This preview artifact is invalid.'**
  String get nativeMediaInvalidArtifact;

  /// No description provided for @nativeMediaInvalidLease.
  ///
  /// In en, this message translates to:
  /// **'A valid local media lease could not be obtained.'**
  String get nativeMediaInvalidLease;

  /// No description provided for @nativeMediaUnavailable.
  ///
  /// In en, this message translates to:
  /// **'Native media playback is unavailable.'**
  String get nativeMediaUnavailable;

  /// No description provided for @nativeMediaInvalidPlayer.
  ///
  /// In en, this message translates to:
  /// **'The native media player could not be created.'**
  String get nativeMediaInvalidPlayer;

  /// No description provided for @nativeMediaInvalidPosition.
  ///
  /// In en, this message translates to:
  /// **'The requested seek position is invalid.'**
  String get nativeMediaInvalidPosition;

  /// No description provided for @nativeMediaInvalidVolume.
  ///
  /// In en, this message translates to:
  /// **'The requested volume value is invalid.'**
  String get nativeMediaInvalidVolume;

  /// No description provided for @nativeMediaInvalidMuted.
  ///
  /// In en, this message translates to:
  /// **'The requested mute state is invalid.'**
  String get nativeMediaInvalidMuted;

  /// No description provided for @nativeMediaPlayerNotFound.
  ///
  /// In en, this message translates to:
  /// **'The native media player was not found.'**
  String get nativeMediaPlayerNotFound;

  /// No description provided for @nativeMediaDisposeFailed.
  ///
  /// In en, this message translates to:
  /// **'The native media player could not be released cleanly.'**
  String get nativeMediaDisposeFailed;

  /// No description provided for @nativeMediaPlayerAction.
  ///
  /// In en, this message translates to:
  /// **'The requested native media player action failed.'**
  String get nativeMediaPlayerAction;

  /// No description provided for @nativeWebInvalidSession.
  ///
  /// In en, this message translates to:
  /// **'The local Web session is invalid.'**
  String get nativeWebInvalidSession;

  /// No description provided for @nativeWebOpenFailed.
  ///
  /// In en, this message translates to:
  /// **'The Web session could not be opened.'**
  String get nativeWebOpenFailed;

  /// No description provided for @nativeErrorCode.
  ///
  /// In en, this message translates to:
  /// **'Platform error code: {code}'**
  String nativeErrorCode(Object code);

  /// No description provided for @nativeOriginalPlatformMessage.
  ///
  /// In en, this message translates to:
  /// **'Original platform message: {message}'**
  String nativeOriginalPlatformMessage(Object message);

  /// No description provided for @nativeOriginalHresult.
  ///
  /// In en, this message translates to:
  /// **'Original HRESULT: {value}'**
  String nativeOriginalHresult(Object value);

  /// No description provided for @nativeOriginalPlatformArgs.
  ///
  /// In en, this message translates to:
  /// **'Original platform arguments: {args}'**
  String nativeOriginalPlatformArgs(Object args);

  /// No description provided for @stoppingProcessing.
  ///
  /// In en, this message translates to:
  /// **'Stopping processing. Waiting for the local worker to finish owned tasks and close safely…'**
  String get stoppingProcessing;

  /// No description provided for @forcedShutdownTitle.
  ///
  /// In en, this message translates to:
  /// **'The worker required forced shutdown'**
  String get forcedShutdownTitle;

  /// No description provided for @forcedShutdownMessage.
  ///
  /// In en, this message translates to:
  /// **'The local worker did not stop gracefully in time. ChaSteady closed only its owned worker process tree; active work may have been interrupted and the result is not certified.'**
  String get forcedShutdownMessage;

  /// No description provided for @acknowledgeForcedShutdown.
  ///
  /// In en, this message translates to:
  /// **'Continue closing'**
  String get acknowledgeForcedShutdown;
}

class _AppLocalizationsDelegate
    extends LocalizationsDelegate<AppLocalizations> {
  const _AppLocalizationsDelegate();

  @override
  Future<AppLocalizations> load(Locale locale) {
    return SynchronousFuture<AppLocalizations>(lookupAppLocalizations(locale));
  }

  @override
  bool isSupported(Locale locale) =>
      <String>['en', 'zh'].contains(locale.languageCode);

  @override
  bool shouldReload(_AppLocalizationsDelegate old) => false;
}

AppLocalizations lookupAppLocalizations(Locale locale) {
  // Lookup logic when only language code is specified.
  switch (locale.languageCode) {
    case 'en':
      return AppLocalizationsEn();
    case 'zh':
      return AppLocalizationsZh();
  }

  throw FlutterError(
    'AppLocalizations.delegate failed to load unsupported locale "$locale". This is likely '
    'an issue with the localizations generation tool. Please file an issue '
    'on GitHub with a reproducible sample app and the gen-l10n configuration '
    'that was used.',
  );
}
