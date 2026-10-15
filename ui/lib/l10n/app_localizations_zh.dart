// ignore: unused_import
import 'package:intl/intl.dart' as intl;
import 'app_localizations.dart';

// ignore_for_file: type=lint

/// The translations for Chinese (`zh`).
class AppLocalizationsZh extends AppLocalizations {
  AppLocalizationsZh([String locale = 'zh']) : super(locale);

  @override
  String get appTitle => 'ChaSteady';

  @override
  String get navWorkbench => '工作台';

  @override
  String get navJobs => '任务';

  @override
  String get navSettings => '设置';

  @override
  String get menuFile => '文件';

  @override
  String get menuView => '视图';

  @override
  String get menuHelp => '帮助';

  @override
  String get menuOpenWeb => '打开 Web 会话';

  @override
  String get menuLanguage => '语言';

  @override
  String get languageSystem => '跟随系统';

  @override
  String get languageZh => '简体中文';

  @override
  String get languageEn => 'English';

  @override
  String get helpAbout => '关于 ChaSteady';

  @override
  String get helpAboutTitle => '关于 ChaSteady';

  @override
  String get helpAboutBody =>
      'ChaSteady 是一款本地优先的视频稳定工作台。素材保留在此电脑上，任务状态由本地工作进程报告。';

  @override
  String get helpQualityTitle => '质量与验证限制';

  @override
  String get helpQualityBody =>
      'CTB 输出仍需人工处理，不能作为质量或完整视场证明。未通过帧数、PTS 和内容检查的 Gyroflow 导出会保持 needs_review。媒体验证不证明感知效果胜出、原始视场完整或输出无裁切。';

  @override
  String get closeConfirmTitle => '关闭 ChaSteady？';

  @override
  String closeActiveJobs(int count) {
    String _temp0 = intl.Intl.pluralLogic(
      count,
      locale: localeName,
      other: '$count 个活动任务',
      one: '1 个活动任务',
    );
    return '当前有$_temp0。关闭时会请求本地监督进程停止并等待其拥有的工作结束。';
  }

  @override
  String get closeWebWarning => '本地服务关闭后，Web 会话也会断开。';

  @override
  String get closeConfirmAction => '停止工作并关闭';

  @override
  String get cancelAction => '取消';

  @override
  String get startupFailedTitle => 'ChaSteady 无法启动';

  @override
  String get startupFailedBody => '本地桌面平台未能完成初始化。';

  @override
  String startupFailureDetails(Object details) {
    return '平台报告的详细信息：$details';
  }

  @override
  String get connectingService => '正在连接本地服务';

  @override
  String get serviceUnavailable => '本地服务不可用';

  @override
  String get establishingSession => '正在建立启动器会话。';

  @override
  String get noSessionActive => '当前没有活动的本地会话';

  @override
  String get sessionNotAccepted => '本地服务未接受此会话。';

  @override
  String get retrySession => '重试会话';

  @override
  String get sessionUnsupported =>
      '尚未配置原生本地服务会话适配器。请从 ChaSteady 启动器会话打开 Web 界面。';

  @override
  String get openFromLauncher => '请通过 ChaSteady 启动器会话链接打开此页面。本界面无法自行创建会话。';

  @override
  String get genericOperationFailed => '本地操作未完成。请检查服务后重试。';

  @override
  String originalServiceMessage(Object message) {
    return '服务原始消息：$message';
  }

  @override
  String originalServiceMessageWithCode(Object code, Object message) {
    return '服务原始消息（$code）：$message';
  }

  @override
  String serviceMessageCodeOnly(Object code) {
    return '服务消息代码：$code';
  }

  @override
  String originalWorkerMessage(Object message) {
    return '工作进程原始消息：$message';
  }

  @override
  String originalWorkerWarning(Object message) {
    return '工作进程原始警告：$message';
  }

  @override
  String originalArtifactWarning(Object message) {
    return '产物原始警告：$message';
  }

  @override
  String unknownWorkerCode(Object code) {
    return '工作进程消息代码：$code';
  }

  @override
  String originalWorkerStage(Object stage) {
    return '工作进程原始阶段：$stage';
  }

  @override
  String originalStatusValue(Object value) {
    return '原始状态值：$value';
  }

  @override
  String get screenWorkbenchTitle => '稳定工作区';

  @override
  String get screenWorkbenchSubtitle => '三个本地来源、明确的时间区间和真实工作进程任务。';

  @override
  String get refreshLocalJobs => '刷新本地任务';

  @override
  String get localMediaWorkspace => '本地媒体工作区';

  @override
  String localMediaWorkspaceMessage(Object appName) {
    return '$appName 使用本地绝对路径引用素材。素材不会上传，浏览器也不会将原始来源作为预览打开。';
  }

  @override
  String get sourcePaths => '来源路径';

  @override
  String get sourcePathsSubtitle => '原始视频 / CTB 视频 / Gyroflow 参考视频。';

  @override
  String get originalVideo => '原始视频';

  @override
  String get originalVideoHelper => '只读本地来源；始终支持手动输入绝对路径。';

  @override
  String get ctbInputVideo => 'CTB 输入视频';

  @override
  String get ctbInputHelper => 'CTB 输入矩形不代表完整输入视场已得到证明。';

  @override
  String get gyroflowReferenceVideo => 'Gyroflow 参考视频';

  @override
  String get gyroflowReferenceHelper =>
      '融合会将此项作为本地视频媒体读取。.gyroflow 工程不是参考视频；导出模板需单独设置。';

  @override
  String get useLocalAbsolutePaths => '请使用本地绝对路径';

  @override
  String get invalidSourcePathsMessage =>
      '相对路径和 URL 不会发送给工作进程。请使用 N:\\folder\\file.mp4 这样的盘符路径，或本地 POSIX 绝对路径。';

  @override
  String get inspectOriginalMetadata => '检查原始媒体元数据';

  @override
  String get inspectionFailed => '检查失败';

  @override
  String get fusionTitle => 'CTB 融合';

  @override
  String get fusionSubtitle => '严格执行新测量；复用缓存是明确的 C7037 复现操作。';

  @override
  String get freshStrict => '严格新测量';

  @override
  String get cachedV9 => '缓存 v9';

  @override
  String get fusionSourceWindow => '融合来源时间范围';

  @override
  String get startSeconds => '开始时间（秒）';

  @override
  String get endSeconds => '结束时间（秒）';

  @override
  String get sourceWindowIndependent => '此来源处理时间范围独立于下方可选的参考区间列表。';

  @override
  String get strictFreshRun => '严格新测量';

  @override
  String get strictFreshMessage =>
      '不会复用旧轨迹缓存。缺少活动姿态或对应关系时会阻止运行。可在没有本地 Gyroflow 可执行文件时使用选定的本地 GF 参考；自动陀螺仪分类仍处于禁用状态。';

  @override
  String get c7037CachedReproduction => 'C7037 缓存复现';

  @override
  String get c7037CachedMessage => '这是明确使用已批准缓存的复现，不是新测量。工作进程结果中必须保留历史数据缺口警告。';

  @override
  String get invalidCachedPreset => '缓存预设请求无效';

  @override
  String get cachedPresetCatalogLabel => '来自实际服务目录的 C7037 预设';

  @override
  String get legacyQuietCachePath => '旧版静稳缓存路径';

  @override
  String get legacyQuietCacheHelper => '仅使用所选预设路径或明确输入的本地路径。';

  @override
  String get legacyReferenceCachePath => '旧版参考缓存路径';

  @override
  String get legacyReferenceCacheHelper => '此字段为空时不会推断任何缓存文件。';

  @override
  String get legacyCacheLocalTitle => '旧版缓存路径必须位于本地';

  @override
  String get legacyCacheLocalMessage =>
      '所选的两个 C7037 缓存都必须使用本地绝对路径。不接受 URL 或相对路径。';

  @override
  String get timingNormalizationQuiet => '时间、归一化与静稳窗口设置';

  @override
  String get advancedFusionControls => '高级融合控制项';

  @override
  String get fusionDefaults => '默认值：来源偏移 0 秒、静稳 sigma 1.3 秒、参考视场 1.0。';

  @override
  String get ctbOrigin => 'CTB 偏移（秒）';

  @override
  String get referenceOrigin => '参考偏移（秒）';

  @override
  String get quietSigmaWindow => '静稳 sigma 窗口（秒）';

  @override
  String get referenceFov => '参考视场（1–4）';

  @override
  String get referenceFovAnalysisOnly => '参考视场仅用于分析';

  @override
  String get referenceFovMessage =>
      '该值用于归一化融合参考，不会改变渲染缩放，也不保证无裁切。默认值 1.0 保留 C7037 旧版行为。';

  @override
  String get confirmListedRanges => '请对照所选素材确认列出的时间区间。';

  @override
  String get fusionHeld => '融合任务已阻止';

  @override
  String get creatingJob => '正在创建任务…';

  @override
  String get createFusionJob => '创建融合任务';

  @override
  String get presetDiscoveryTitle => '实验预设发现';

  @override
  String get presetDiscoverySubtitle => '仅查询限定目录，不递归扫描整块磁盘。';

  @override
  String get experimentFolder => '实验文件夹';

  @override
  String get experimentFolderHelper => '选择实际实验文件夹以读取其中的目录。';

  @override
  String get discoverPresets => '发现预设';

  @override
  String get presetDiscoveryFailed => '预设发现失败';

  @override
  String get serviceNoPresets => '服务未在此文件夹中返回预设。';

  @override
  String get servicePresetsReturned => '服务返回的预设';

  @override
  String get c7037CachedComplete => 'C7037 缓存复现 · 完整请求';

  @override
  String get metadataOnlyDiscover => '仅含元数据 · 选择前请发现完整的已批准请求';

  @override
  String get discoverFullC7037First => '请先发现完整的 C7037 请求';

  @override
  String get metadataCatalogExplanation =>
      '能力目录只包含元数据。请在上方明确指定实验文件夹并选择“发现预设”；只有服务返回包含 reference_intervals 的已批准完整请求后，缓存预设才可用。';

  @override
  String get c7037NeedsCompleteRequest => '只有本地服务返回完整的已批准请求后，C7037 才可选择。';

  @override
  String get referenceIntervals => '参考区间';

  @override
  String get referenceIntervalsSubtitle => '可选开始/结束区间列表；不提供时间轴、自动选时或陀螺仪分类。';

  @override
  String get intervalsManualOnly => '仅输入经过审核的时间范围。不使用运动图表或自动范围检测。';

  @override
  String get noReferenceIntervals =>
      '未选择参考区间。对于 Fixed 212–228 这类仅 CTB 的预设，空列表是有效的。';

  @override
  String get addRange => '添加区间';

  @override
  String get insertLabRanges => '插入实验室记录的区间';

  @override
  String get reviewIntervalsCheckbox => '我已根据此请求检查参考区间列表（包括空列表）。';

  @override
  String get requiredBeforeFusion => '创建融合任务前必须确认。';

  @override
  String get documentedRangesOptIn => '记录的实验区间为可选项';

  @override
  String get documentedRangesMessage =>
      '插入操作会添加 153–156 秒和 231.8–235.5 秒。独立的仅 CTB 区间 212–228 秒不会自动添加到融合任务中。';

  @override
  String get otherLocalStages => '其他本地阶段';

  @override
  String get otherLocalStagesSubtitle => '操作会创建真实 API 任务；工具执行和结果状态由工作进程负责。';

  @override
  String get createPreview => '创建 H.264/AAC 预览';

  @override
  String get validateMedia => '验证媒体';

  @override
  String get configureGyroflowExport => '配置 Gyroflow 导出';

  @override
  String get requestCatalystManual => '请求 Catalyst 人工步骤';

  @override
  String get previewStageUnavailable => '预览阶段不可用';

  @override
  String get previewUnavailableMessage =>
      '未检测到 FFmpeg 或其状态未知。工作进程创建真实 H.264/AAC 产物前，不会声称预览可用。';

  @override
  String get validationStageUnavailable => '验证阶段不可用';

  @override
  String get validationUnavailableMessage =>
      '未检测到 FFprobe 或其状态未知。检测到已配置的探测工具前，验证任务将被阻止。';

  @override
  String get gyroflowCliSafeguards => 'Gyroflow 命令行保护措施';

  @override
  String get gyroflowSafeguardsMessage =>
      '只有保存的可执行文件路径与服务报告路径一致，且经过审计的 CLI/配置文件保护检查已验证，才会启用导出。默认使用 1080p 预设和 0–5 秒有界片段；完整来源和 720p 需要显式选择。每次新渲染仍需检查帧数、PTS 和内容对齐。';

  @override
  String get latestGyroflowNeedsReview => '最新 Gyroflow 输出需要审核';

  @override
  String get gyroflowNeedsReviewMessage =>
      '服务报告 needs_review，未声称导出或裁切映射已验证。CLI 退出代码为 0 不代表输出验证成功。';

  @override
  String get catalystManualTitle => 'Catalyst 辅助导出 · 需要人工步骤';

  @override
  String get catalystManualMessage =>
      '此界面不会启动 Catalyst 自动化。所属窗口探测未发现可用控件，且曾更改 Sony 配置文件日志；此阶段仍需人工处理。';

  @override
  String get catalystNotDetected => '未检测到 Catalyst';

  @override
  String get catalystStatusUnknown => 'Catalyst 状态未知';

  @override
  String get catalystNotStartedMessage =>
      '此界面不会启动 Catalyst 阶段。仅安装了可执行文件不代表界面阶段已经验证。';

  @override
  String get gyroClassificationDisabled =>
      '自动陀螺仪分类已禁用。不假定来源编码受支持；请使用真实预览产物进行浏览器播放。';

  @override
  String get inspectMetadataReturned => '工作进程返回的元数据';

  @override
  String dimensions(Object width, Object height) {
    return '尺寸：$width × $height';
  }

  @override
  String frameRate(Object fps) {
    return '帧率：$fps fps';
  }

  @override
  String frameCount(Object frames) {
    return '帧数：$frames';
  }

  @override
  String durationSeconds(Object duration) {
    return '时长：$duration 秒';
  }

  @override
  String metadataName(Object name) {
    return '名称：$name';
  }

  @override
  String videoCodec(Object value) {
    return '视频编码：$value';
  }

  @override
  String audioCodec(Object value) {
    return '音频编码：$value';
  }

  @override
  String pixelFormat(Object value) {
    return '像素格式：$value';
  }

  @override
  String bitDepth(Object value) {
    return '位深：$value';
  }

  @override
  String frameTiming(Object value) {
    return '帧时间：$value';
  }

  @override
  String get dimensionsNotFov => '尺寸不能证明完整输入视场。';

  @override
  String get gyroflowDialogTitle => '配置 Gyroflow 导出';

  @override
  String get gyroflowTemplateLabel => 'Gyroflow 工程模板（可选）';

  @override
  String get gyroflowTemplateHelper => '此项必须明确指定；不会将融合参考推断为导出模板。';

  @override
  String get typeProjectTemplatePath => '手动输入本地工程模板路径';

  @override
  String get projectTemplateLocalPath => 'Gyroflow 工程模板';

  @override
  String get projectTemplateLocalOnly => '工程模板必须使用本地绝对路径。';

  @override
  String get outputPreset => '输出预设';

  @override
  String get outputPresetHelper =>
      '请选择已批准的 reference_1080p 或 reference_720p 工作进程预设；不接受任意尺寸、编码或命令。';

  @override
  String get reference1080p => '参考 1080p';

  @override
  String get reference720p => '参考 720p';

  @override
  String get exportFullSource => '导出完整来源';

  @override
  String get fullSourceLonger => '可选，默认关闭；渲染完整来源可能耗时更长。';

  @override
  String get exportStartSeconds => '导出开始（秒）';

  @override
  String get exportEndSeconds => '导出结束（秒）';

  @override
  String get defaultReviewSegment => '默认审核片段：0–5 秒。请根据来源调整。';

  @override
  String get renderUnverifiedTitle => '渲染输出尚未验证';

  @override
  String get renderUnverifiedMessage => '进程成功退出并不能验证帧数、PTS 对齐或内容对齐。';

  @override
  String get createExportJob => '创建导出任务';

  @override
  String manualCatalystNotice(Object id, Object state) {
    return 'Catalyst 阶段 $id · $state。界面未启动任何自动操作。';
  }

  @override
  String jobCreatedNotice(Object kind, Object id, Object state) {
    return '已创建 $kind 任务 $id · $state。工作进程尚未报告结果。';
  }

  @override
  String previewJobCreatedNotice(Object id, Object state) {
    return '已创建预览任务 $id · $state。';
  }

  @override
  String validationJobCreatedNotice(Object id, Object state) {
    return '已创建媒体验证任务 $id · $state。';
  }

  @override
  String gyroflowJobCreatedNotice(Object id, Object state) {
    return '已创建 Gyroflow 导出 $id · $state。仍需验证帧数/PTS/内容对齐。';
  }

  @override
  String get sourceWindowInvalid => '请输入融合来源时间范围的开始和结束值。';

  @override
  String intervalNonNumeric(int row) {
    return '第 $row 个区间的开始和结束值必须是数字。';
  }

  @override
  String intervalNegativeStart(int row) {
    return '第 $row 个区间不能早于 0 秒开始。';
  }

  @override
  String intervalEndNotAfterStart(int row) {
    return '第 $row 个区间的结束时间必须晚于开始时间。';
  }

  @override
  String get intervalChronologicalOrder => '区间必须按时间顺序排列。';

  @override
  String intervalOverlap(int row) {
    return '第 $row 个区间与前一个区间重叠。';
  }

  @override
  String get invalidTimingValues => '时间值必须为有限数字，静稳 sigma 必须大于零，参考视场必须介于 1 到 4。';

  @override
  String get invalidReferenceFov => '参考视场归一化值必须是 1 到 4 之间的数字。';

  @override
  String get sessionRequiredBeforeJob => '创建任务前需要有效的启动器会话。';

  @override
  String get localPathsOnly => '仅使用本地绝对路径；不接受 URL 和相对路径。';

  @override
  String get legacyPathsMustBeAbsolute => '旧版缓存路径必须是本地绝对路径。';

  @override
  String get toolStatusNotReturned => '服务尚未返回工具能力状态。';

  @override
  String get ffmpegMissingHeld => '未检测到 FFmpeg 或其状态未知。融合输出已阻止。';

  @override
  String get selectActualPreset => '请选择服务返回的实际 C7037 预设。';

  @override
  String get bothLegacyPathsRequired => '所选预设请求必须包含两个旧版缓存路径。';

  @override
  String get reviewManualIntervals => '请对照这些来源审核人工指定的时间区间。';

  @override
  String get catalogFieldChanged => '目录请求字段已更改。请重新选择已批准的预设后再运行 cached_v9。';

  @override
  String get metadataOnlyCatalogError =>
      '此目录项仅包含元数据。请输入明确的实验文件夹路径并使用“发现预设”加载完整的已批准请求后再选择。';

  @override
  String get invalidReferenceInterval => '目录预设包含无效的参考区间。';

  @override
  String get nonFiniteReferenceInterval => '目录预设包含非有限的参考区间值。';

  @override
  String get missingReferenceIntervals => '目录预设没有 reference_intervals 数组。';

  @override
  String get missingCachedRequestField => '目录条目缺少必需的 cached_v9 请求字段。';

  @override
  String get catalogNonLocalPath => '目录请求包含非本地路径。';

  @override
  String get enterLocalAbsoluteFolder => '请输入本地实验文件夹绝对路径。';

  @override
  String get jobRequestKindRequired => '必须提供受支持的任务类型。';

  @override
  String get jobFieldsNested => '任务字段必须嵌套在 request 下。';

  @override
  String get jobRequestObject => '任务 request 必须是对象。';

  @override
  String get invalidArtifactOpen => '无法将此产物作为本地预览打开。';

  @override
  String get toolAvailability => '工具可用性';

  @override
  String get capabilitiesUnavailable => '能力信息不可用';

  @override
  String get toolStatusUnknown => '状态未知';

  @override
  String get capabilitiesNotProvided => '本地服务尚未为此会话提供能力数据。';

  @override
  String get waitingToolStatus => '正在等待本地工具状态。';

  @override
  String get toolAvailabilityProvenance => '工具可用性与来源';

  @override
  String workerVersion(Object version) {
    return '工作进程 $version';
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
  String get gyroflowBuild => 'Gyroflow 构建版本';

  @override
  String get cliStatus => 'CLI 状态';

  @override
  String get priorCliInvocation => '之前的 CLI 调用';

  @override
  String get savedPathProfileGuard => '已保存路径的配置文件保护';

  @override
  String get latestExportValidation => '最近一次导出验证';

  @override
  String get latestMediaExportVerified => '最近的媒体导出已验证';

  @override
  String get latestTrimMappingVerified => '最近的裁切映射已验证';

  @override
  String get profileSafety => '配置文件安全';

  @override
  String get exportHeldProfileSafety => '因配置文件安全检查而阻止导出';

  @override
  String get profileSafetyMismatchMessage =>
      '服务报告的可执行文件与已保存的 tool_paths.gyroflow 未同时匹配已验证的 CLI/配置文件保护检查。请保存经过审计的可执行文件路径并刷新能力状态后再导出。ChaSteady 会继续阻止导出。';

  @override
  String get boundedExportNeedsReview => '最近的有界导出需要审核';

  @override
  String get boundedExportNeedsReviewMessage =>
      '服务报告 needs_review。CLI 成功退出或之前的调用都不能验证此输出；媒体导出与裁切映射仍需分别检查。';

  @override
  String get exportNeedsVerification => '真实导出仍需验证';

  @override
  String get exportVerificationMessage =>
      '之前的 CLI/配置文件检查仅用于启动保护。每个新渲染都需要审核帧数、PTS 和内容对齐后才能信任。';

  @override
  String get catalystManualRequired => 'Catalyst 辅助导出 · 需要人工处理';

  @override
  String get catalystManualRequiredMessage =>
      '此界面不提供 Catalyst 自动化按钮。当前所属窗口探测未发现可用控件，且曾更改 Sony 配置文件日志；无论是否检测到安装，此阶段都必须人工处理。';

  @override
  String get someStagesUnavailable => '部分阶段可能不可用';

  @override
  String get missingToolsTruthful => '缺失或未知的可执行文件会如实显示。工具缺失时不会将任务标记为完成。';

  @override
  String get detected => '已检测到';

  @override
  String get notDetected => '未检测到';

  @override
  String get statusUnknown => '状态未知';

  @override
  String toolCapabilitySemantics(Object status) {
    return '$status工具能力';
  }

  @override
  String configuredPath(Object path) {
    return '已配置路径：$path';
  }

  @override
  String modeValue(Object mode) {
    return '模式：$mode';
  }

  @override
  String gyroflowBuildValue(Object value) {
    return 'Gyroflow 构建版本：$value';
  }

  @override
  String get verified => '已验证';

  @override
  String get notVerified => '未验证';

  @override
  String get unknown => '未知';

  @override
  String get reportedTrue => '报告为 true';

  @override
  String get reportedFalse => '报告为 false';

  @override
  String get blocked => '已阻止';

  @override
  String get unverified => '未经验证';

  @override
  String get verifiedMedia => '媒体已验证';

  @override
  String get cliBlocked => 'CLI 已阻止';

  @override
  String get notAudited => '未审计';

  @override
  String get required => '必需';

  @override
  String get notRequired => '非必需';

  @override
  String get savedPathMismatch => '已保存路径不匹配';

  @override
  String get cliProfileGuardUnavailable => 'CLI/配置文件保护不可用';

  @override
  String get verifiedForSavedPath => '已针对保存路径验证';

  @override
  String originalStatusLabel(Object value) {
    return '原始状态：$value';
  }

  @override
  String get screenSettingsSubtitle => '本地外观与已报告的运行状态。';

  @override
  String get appearance => '外观';

  @override
  String get preferencesLocalOnly => '偏好设置存储在本地服务中。不使用账户或云同步。';

  @override
  String get theme => '主题';

  @override
  String get themeSystem => '系统';

  @override
  String get themeLight => '浅色';

  @override
  String get themeDark => '深色';

  @override
  String get language => '语言';

  @override
  String get brandSeed => '品牌种子色';

  @override
  String get seedGreenGray => 'ChaSteady 灰绿色';

  @override
  String get seedMistBlue => '雾蓝';

  @override
  String get seedClay => '陶土色';

  @override
  String get seedSoftViolet => '柔紫色';

  @override
  String get systemAccentFallback => '系统强调色回退方案';

  @override
  String get systemAccentFallbackMessage =>
      '本地服务未提供经过验证的 Windows 强调色，因此改用已保存的 ChaSteady 种子色。';

  @override
  String get savedPreferencesUnavailable => '已保存的偏好设置不可用';

  @override
  String get preferencesNotSaved => '偏好设置未保存';

  @override
  String get savePreferences => '保存偏好设置';

  @override
  String get saved => '已保存';

  @override
  String get waitingPreferenceRecord => '正在等待本地偏好设置记录';

  @override
  String get executablePaths => '可执行文件路径';

  @override
  String get executablePathsSubtitle =>
      '配置已知的本地 FFmpeg、FFprobe、Gyroflow 和 Catalyst 工具。';

  @override
  String get privacyScope => '隐私与范围';

  @override
  String get mediaPathsLocal => '媒体路径为本地绝对路径；素材不会上传。';

  @override
  String get noCloudModels => '不使用云端模型、分析服务或远程字体资源。';

  @override
  String get browserPreviewOwned => '浏览器预览仅限本地拥有的 H.264/AAC 代理产物。';

  @override
  String get ffmpegExecutable => 'FFmpeg 可执行文件';

  @override
  String get ffprobeExecutable => 'FFprobe 可执行文件';

  @override
  String get gyroflowCliExecutable => 'Gyroflow CLI 可执行文件';

  @override
  String get catalystExecutable => 'Catalyst 可执行文件';

  @override
  String get toolPathsPersistedMessage =>
      '这些由应用管理的路径通过本地服务保存，并用于未来的任务；它们不是单个任务的命令覆盖项。';

  @override
  String get absolutePathClearHelper => '本地绝对路径；仅在清除此设置时留空。';

  @override
  String typeToolPath(Object tool) {
    return '手动输入本地 $tool 路径';
  }

  @override
  String clearToolPath(Object tool) {
    return '清除 $tool 路径';
  }

  @override
  String get toolPathRecordUnavailable => '工具路径记录不可用';

  @override
  String get toolPathRecordUnavailableMessage =>
      '服务未返回全部四个已知可执行文件路径。已禁用保存，以避免意外清除未知路径。';

  @override
  String get absoluteExecutablePaths => '请使用本地可执行文件绝对路径';

  @override
  String get invalidToolPathMessage => '不能将相对路径或 URL 保存为工具路径。';

  @override
  String get unsavedToolPaths => '工具路径尚未保存';

  @override
  String get unsavedToolPathsMessage => '保存偏好设置以持久化这些 ChaSteady 工具路径。';

  @override
  String get toolExecutableFallback => '工具可执行文件';

  @override
  String get screenJobsSubtitle => '此处仅显示本地工作进程返回的任务。';

  @override
  String get refreshJobs => '刷新任务';

  @override
  String get queueLoadFailed => '无法加载队列';

  @override
  String get waitingQueueData => '正在等待队列数据';

  @override
  String get serviceNoJobList => '服务尚未返回任务列表。';

  @override
  String get queueUnavailable => '队列不可用';

  @override
  String get queueUnknownNotEmpty => '当前没有活动的本地会话，因此任务列表未知，而不是空队列。';

  @override
  String get noJobsYet => '暂无任务';

  @override
  String get emptyQueueDescription => '本地服务返回了空队列。来源和所需工具准备就绪后，可从工作台创建任务。';

  @override
  String get latestJobDetailsUnavailable => '最近的任务详情不可用';

  @override
  String get screenJobsError => '无法加载任务详情';

  @override
  String get jobActivity => '任务活动';

  @override
  String get waitingLocalQueue => '正在等待本地队列';

  @override
  String realJobsCount(int count) {
    String _temp0 = intl.Intl.pluralLogic(
      count,
      locale: localeName,
      other: '$count 个真实任务',
      one: '1 个真实任务',
    );
    return '服务返回了$_temp0';
  }

  @override
  String get resizeJobActivityPanel => '调整任务活动面板大小';

  @override
  String get resizeJobSheet => '调整任务面板大小';

  @override
  String get queueCouldNotRefresh => '无法刷新队列';

  @override
  String get loadingLocalJobs => '正在加载本地任务';

  @override
  String get queueEmpty => '队列为空';

  @override
  String get noJobsReturned => '本地服务尚未返回任务。只有服务创建任务后，此处才会显示。';

  @override
  String get jobDetails => '任务详情';

  @override
  String get jobError => '任务错误';

  @override
  String get manualActionRequired => '需要人工操作';

  @override
  String get manualActionMessage => '不假定 UI 自动化已成功。请仅遵循本地工作进程返回的明确后续步骤。';

  @override
  String get reviewBeforeContinue => '继续前请审核';

  @override
  String get reviewPerceptualFovMessage => '工作进程尚未认证感知效果胜出或原始视场结果。';

  @override
  String get evidenceScopeLimited => '证据范围有限';

  @override
  String get verifiedMediaScopeMessage => '此状态仅确认媒体/几何证据，不代表感知效果胜出或原始视场已认证。';

  @override
  String get interpretationLimits => '解释限制';

  @override
  String get fusionScopeMessage => '来源视场未验证；CTB 仅描述输入矩形。本界面不会据此推断裁切情况或质量结论。';

  @override
  String get exportVerificationRequired => '仍需验证导出结果';

  @override
  String get exportVerificationDetails => '进程成功退出并不能验证帧数、PTS 对齐或内容对齐。来源视场仍未验证。';

  @override
  String get ownedOutputs => '本任务产物';

  @override
  String workerWarningsCount(int count) {
    return '工作进程警告 · $count 条';
  }

  @override
  String get workerResultDetails => '工作进程结果详情';

  @override
  String reportedScope(Object scope) {
    return '报告的范围：$scope。此值仅表示检查了哪些内容，不构成感知/内容对应关系或原始视场认证。';
  }

  @override
  String reportedReferenceFov(Object value) {
    return '报告的参考视场元数据：$value（仅用于分析）';
  }

  @override
  String get fovNotCropGuarantee => '视场元数据不保证无裁切';

  @override
  String get fovNoCropDetails => '参考归一化不会改变渲染缩放，也不能证明输出没有裁切。';

  @override
  String get artifactValidationScope => '产物验证范围';

  @override
  String get artifactPreview =>
      '本地 H.264/AAC 预览。浏览器通过字节范围请求读取此任务拥有的产物；不会传输原始素材。';

  @override
  String get previewCodecUnknown =>
      '预览编码元数据尚未确认。不假定浏览器解码器支持；请创建或检查真实的 H.264/AAC 预览。';

  @override
  String artifactWarningsCount(int count) {
    return '产物警告 · $count 条';
  }

  @override
  String get openLocalOutput => '打开本地输出';

  @override
  String get unsupportedBrowserPlayback =>
      '此平台不支持本地浏览器播放。请创建真实预览产物并使用 Web 工作台。';

  @override
  String get localPreviewSemantics => '本地 H.264/AAC 预览';

  @override
  String get jobStateQueued => '排队中';

  @override
  String get jobStateRunning => '运行中';

  @override
  String get jobStateNeedsManual => '需要人工处理';

  @override
  String get jobStateNeedsReview => '需要审核';

  @override
  String get jobStateFailed => '失败';

  @override
  String get jobStateCancelled => '已取消';

  @override
  String get jobStateVerifiedMedia => '仅媒体证据已验证';

  @override
  String unknownJobState(Object state) {
    return '状态：$state';
  }

  @override
  String get progressNotReported => '未报告进度';

  @override
  String get currentStage => '当前阶段';

  @override
  String stageProgressUnknown(Object stage) {
    return '$stage进度未知';
  }

  @override
  String stageProgressPercent(Object stage, int percent) {
    return '$stage进度 $percent%';
  }

  @override
  String get indeterminateProgress => '不确定进度';

  @override
  String get noWorkerPercentage => '工作进程尚未报告此阶段的百分比进度。';

  @override
  String stageValue(Object stage) {
    return '阶段：$stage';
  }

  @override
  String warningCount(int count) {
    String _temp0 = intl.Intl.pluralLogic(
      count,
      locale: localeName,
      other: '$count 条警告',
      one: '1 条警告',
    );
    return '工作进程报告$_temp0';
  }

  @override
  String get cancelJob => '取消任务';

  @override
  String get jobKindFusion => 'CTB 融合';

  @override
  String get jobKindPreview => '浏览器预览';

  @override
  String get jobKindGyroflowExport => 'Gyroflow 导出';

  @override
  String get jobKindCatalyst => 'Catalyst 辅助阶段';

  @override
  String get jobKindValidate => '媒体验证';

  @override
  String jobKindUnknown(Object kind) {
    return '原始任务类型：$kind';
  }

  @override
  String get toolStatusDetected => '已检测到';

  @override
  String get toolStatusMissing => '未检测到';

  @override
  String pickerChooseLocal(Object kind) {
    return '选择本地$kind';
  }

  @override
  String get pickerEnterLocal => '输入本地路径';

  @override
  String pathDialogTitle(Object label) {
    return '输入本地$label路径';
  }

  @override
  String get absoluteLocalPath => '本地绝对路径';

  @override
  String get pathStaysLocal => '文件保留在此电脑上。不使用浏览器文件上传。';

  @override
  String get usePath => '使用路径';

  @override
  String get cancel => '取消';

  @override
  String get workerStarting => '正在启动本地工作进程。';

  @override
  String get workerCancelledBeforeStart => '任务在开始处理前已取消。';

  @override
  String get workerCancellationRequested => '已请求取消；所属工作已停止。';

  @override
  String get workerInspectSource => '正在检查所选来源媒体。';

  @override
  String get workerInspectFusionInputs => '正在检查输入和所选来源帧的时间戳。';

  @override
  String get workerCachedTrajectory => '正在读取已批准的 C7037 历史轨迹；这不是新的测量。';

  @override
  String get workerComputeFusion => '正在计算双锚点全局刚性轨迹，不混合 Gyroflow 像素。';

  @override
  String workerRegistrationProgress(int current, int total) {
    return '正在配准第 $current/$total 帧。';
  }

  @override
  String workerRenderProgress(int current, int total) {
    return '正在渲染第 $current/$total 帧。';
  }

  @override
  String get workerVerifyOutput => '正在完整解码并验证视频及其对应的来源音轨。';

  @override
  String get workerPreviewInspect => '正在检查来源媒体以准备本地浏览器预览。';

  @override
  String get workerPreviewEncode => '正在编码 H.264/AAC 预览；编码器未提供经过验证的数值进度。';

  @override
  String get workerValidateMedia => '正在完整解码音视频，然后检查实际帧数和请求的帧率。';

  @override
  String get workerCatalystManual => 'Catalyst 自动化尚未验证；需要人工步骤。';

  @override
  String jobErrorCode(Object code) {
    return '错误代码：$code';
  }

  @override
  String serviceHttpError(int statusCode) {
    return '本地服务返回 HTTP $statusCode。';
  }

  @override
  String get mode => '模式';

  @override
  String get uiAutomationVerification => 'UI 自动化验证';

  @override
  String get stageStarting => '启动中';

  @override
  String get stageInspect => '检查媒体';

  @override
  String get stagePreviewEncode => '编码预览';

  @override
  String get stageMediaValidation => '媒体验证';

  @override
  String get stageCachedTrajectory => '加载已批准的缓存轨迹';

  @override
  String get stageFusion => '融合';

  @override
  String get stageRegistration => '帧配准';

  @override
  String get stageQuietTracking => '静稳区间跟踪';

  @override
  String get stageRender => '渲染';

  @override
  String get stageVerify => '验证输出';

  @override
  String get stageCatalystManual => 'Catalyst 人工交接';

  @override
  String get workerQueued => '正在本地工作进程队列中等待。';

  @override
  String get workerNeedsManual => '工作进程需要人工步骤；界面未执行任何自动操作。';

  @override
  String get workerNeedsReview => '工作进程要求审核此结果后才能信任。';

  @override
  String get workerFailed => '工作进程无法完成此任务。';

  @override
  String get workerCancelled => '工作进程已取消此任务。';

  @override
  String get workerVerifiedMedia => '媒体证据已验证；这不代表感知质量或原始视场已认证。';

  @override
  String workerQuietTrackingProgress(int current, int total) {
    return '正在跟踪静稳帧 $current/$total。';
  }

  @override
  String get workerErrorNeedsReview => '此结果需要人工审核，尚未认证。';

  @override
  String get workerErrorNeedsManual => '此任务需要人工步骤；界面未进行自动化处理。';

  @override
  String get workerErrorCancelled => '任务已取消。';

  @override
  String get workerErrorInterrupted => '所属工作进程在完成前中断。';

  @override
  String get workerErrorMissingCapability => '缺少必需的本地工具能力。';

  @override
  String get workerErrorProcessingFailed => '本地工作进程无法处理此请求。';

  @override
  String get playerLoading => '正在加载预览';

  @override
  String get playerPlay => '播放';

  @override
  String get playerPause => '暂停';

  @override
  String get playerSeek => '定位';

  @override
  String get playerVolume => '音量';

  @override
  String get playerMute => '静音';

  @override
  String get playerUnmute => '取消静音';

  @override
  String playerError(Object code) {
    return '播放器错误：$code';
  }

  @override
  String get playerFinished => '播放结束';

  @override
  String get nativeLeaseUnavailable => '本地媒体预览租约不可用。';

  @override
  String get nativeActionUnsupported => '此原生平台操作不受支持。';

  @override
  String get nativeProtocolUnsupported => '此原生平台协议版本不受支持。';

  @override
  String get nativeProtocolError => '无法完成原生平台请求。';

  @override
  String intervalStartLabel(int row) {
    return '开始 $row（秒）';
  }

  @override
  String intervalEndLabel(int row) {
    return '结束 $row（秒）';
  }

  @override
  String intervalExample(Object value) {
    return '例如 $value';
  }

  @override
  String removeInterval(int row) {
    return '删除区间 $row';
  }

  @override
  String get cliMode => 'CLI';

  @override
  String originalArtifactLabel(Object label) {
    return '工作进程提供的产物标签：$label';
  }

  @override
  String artifactFormat(Object kind, Object mime) {
    return '工作进程报告的产物类型：$kind · 媒体类型：$mime';
  }

  @override
  String artifactKindUnknown(Object kind) {
    return '原始产物类型：$kind';
  }

  @override
  String get desktopActionsUnavailable => '此平台不支持原生桌面操作。';

  @override
  String get invalidJobsList => '本地服务返回了无效的任务列表。';

  @override
  String get invalidPresetCatalog => '本地服务返回了无效的预设目录。';

  @override
  String get invalidServiceResponse => '本地服务返回了无效响应。';

  @override
  String get invalidLocalResourceId => '服务返回了无效的本地资源标识符。';

  @override
  String get missingJobRecord => '本地服务未返回任务记录。';

  @override
  String localConnectionFailed(Object appName) {
    return '无法连接到本地 $appName 服务。';
  }

  @override
  String get invalidApiJobKind => '必须提供受支持的任务类型。';

  @override
  String get apiJobFieldsNested => '任务字段必须嵌套在 request 下。';

  @override
  String get apiJobRequestInvalid => '任务 request 必须是对象。';

  @override
  String get invalidArtifactPreview => '无法将此产物作为本地预览打开。';

  @override
  String get catalogEntry => '未命名目录条目';

  @override
  String get unnamedArtifact => '未命名产物';

  @override
  String get nativeProtocolInvalidRequest => '原生协议请求无效。';

  @override
  String get nativeWorkerStopping => '本地工作进程正在停止。';

  @override
  String get nativeWorkerStopped => '本地工作进程已停止。';

  @override
  String get nativeWorkerStartup => '本地工作进程无法启动。';

  @override
  String get nativeWorkerBundle => '捆绑的工作进程资源不可用。';

  @override
  String get nativeWorkerDataRoot => '本地工作进程数据目录不可用。';

  @override
  String get nativeWorkerAlreadyRunning => 'ChaSteady 工作进程已经在运行。';

  @override
  String get nativeWorkerDiagnostics => '本地工作进程诊断流不可用。';

  @override
  String get nativeWorkerPipe => '本地工作进程通信管道失败。';

  @override
  String get nativeWorkerJob => '原生工作进程拒绝了任务请求。';

  @override
  String get nativeWorkerReady => '本地工作进程未能就绪。';

  @override
  String get nativeWorkerNotReady => '本地工作进程尚未就绪。';

  @override
  String get nativeWorkerRequestLimit => '原生工作进程请求超过了允许大小。';

  @override
  String get nativeWorkerProtocol => '原生工作进程协议请求无效。';

  @override
  String get nativeWorkerExited => '本地工作进程意外退出。';

  @override
  String get nativeWorkerTimeout => '本地工作进程未能在超时前响应。';

  @override
  String get nativePickerInvalidKind => '此本地文件选择器类型不受支持。';

  @override
  String get nativePickerFailed => '本地文件选择器无法完成操作。';

  @override
  String get nativeMediaInvalidArtifact => '此预览产物无效。';

  @override
  String get nativeMediaInvalidLease => '无法获取有效的本地媒体租约。';

  @override
  String get nativeMediaUnavailable => '原生媒体播放不可用。';

  @override
  String get nativeMediaInvalidPlayer => '无法创建原生媒体播放器。';

  @override
  String get nativeMediaInvalidPosition => '请求的定位位置无效。';

  @override
  String get nativeMediaInvalidVolume => '请求的音量值无效。';

  @override
  String get nativeMediaInvalidMuted => '请求的静音状态无效。';

  @override
  String get nativeMediaPlayerNotFound => '未找到原生媒体播放器。';

  @override
  String get nativeMediaDisposeFailed => '无法正常释放原生媒体播放器。';

  @override
  String get nativeMediaPlayerAction => '请求的原生媒体播放器操作失败。';

  @override
  String get nativeWebInvalidSession => '本地 Web 会话无效。';

  @override
  String get nativeWebOpenFailed => '无法打开 Web 会话。';

  @override
  String nativeErrorCode(Object code) {
    return '平台错误代码：$code';
  }

  @override
  String nativeOriginalPlatformMessage(Object message) {
    return '平台原始消息：$message';
  }

  @override
  String nativeOriginalHresult(Object value) {
    return '原始 HRESULT：$value';
  }

  @override
  String nativeOriginalPlatformArgs(Object args) {
    return '平台原始参数：$args';
  }

  @override
  String get stoppingProcessing => '正在停止处理。等待本地工作进程完成所属任务并安全关闭…';

  @override
  String get forcedShutdownTitle => '工作进程需要强制关闭';

  @override
  String get forcedShutdownMessage =>
      '本地工作进程未能在超时前正常停止。ChaSteady 仅关闭了其拥有的工作进程树；活动任务可能已中断，结果未经认证。';

  @override
  String get acknowledgeForcedShutdown => '继续关闭';
}
