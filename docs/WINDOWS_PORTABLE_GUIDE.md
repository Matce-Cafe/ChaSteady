# ChaSteady Windows 便携版 / Portable Windows app

ChaSteady 是暂用名称。本工具在本机处理视频，不上传素材。请以随包构建及验收记录为准：只有源码、Web 构建或缺少 Worker 的目录，不是已经可用的 Windows 程序。

## 中文

### 启动与目录

- 保留整个解压目录，双击 `ChaSteady.exe`。不要只移动这一个 EXE；Flutter 资源、`Worker` 与 `web` 目录都是程序组成部分。
- 完整目录包不要求另装 Python、Flutter 或开发工具。FFmpeg/ffprobe、Gyroflow、Sony Catalyst Browse 不默认捆绑。
- 程序资源和可写用户数据分开存放。桌面版使用当前 Windows 用户的独立本机数据目录；不会把任务写入只读资源目录，也不会静默迁移或改写旧数据权限。
- 本地候选未签名。遇到系统安全警告时先核对来源与摘要，不要关闭 Defender/SmartScreen，也不要把“能运行”当作发布安全认证。

### 工具与任务

1. 在“设置”中按需选择已有的本地 FFmpeg/ffprobe、Gyroflow 可执行文件或 `.gyroflow` 导出模板。工具路径、视频参考路径和工程模板是不同用途。
2. 在工作台选择原片、CTB 输入和 GF 参考视频，填写明确时间范围。只引用本地绝对路径，不能输入网络 URL。
3. “严格新测量”与“缓存 v9”不是同一模式。缓存复现需要明确选择现有实验目录并通过发现/来源绑定/固定缓存摘要校验；素材、实验缓存不随便携包分发。
4. 以实际任务状态为准。`needs_manual` 表示需要人工步骤；`needs_review` 不是已验证成功。未知或未认证的 GF 不会仅因选择了路径就获得自动导出资格；CTB 仍为人工导出。
5. 首页不显示任务活动浮窗。切换到“任务”页面查看队列、状态和进度，或取消活动任务；任务仍在后台执行，不必让浮窗覆盖工作台。

### 播放与质量边界

- 内嵌播放器用于本工具生成并验证的 H.264 8-bit / AAC 预览，默认静音、不自动播放。它不承诺直接播放所有 HEVC、10-bit 或 HDR 原片。
- 方案允许黑边，不通过动态裁切或估计缩放隐藏边缘。但上游 CTB/GF 已经丢失的视场或位深不能恢复。
- 帧数、PTS、音轨与当前 CTB 输入角点验证，不等于原片全视场、4K/10-bit 母版或感知效果胜出的认证。

### 网页版与语言

- 从“文件 → 打开 Web 会话”进入保留的网页版。两端连接同一个桌面 Worker，共享任务队列和设置，不另起处理服务。
- 关闭桌面程序会停止其拥有的本机服务，网页端也会断开。活动任务会先提示确认并等待清理。
- “视图 → 语言”提供“跟随系统 / 简体中文 / English”。显式选择在两端共享；“跟随系统”分别使用 Windows 或浏览器语言，其他语言回退 English。
- 外部工具的原始诊断保留原文，不自动翻译或改写技术证据。

## English

Keep the complete extracted directory and launch `ChaSteady.exe`; do not move the EXE alone. A complete bundle includes Flutter resources, `Worker`, and the offline `web` assets. It does not require a separately installed Python or Flutter. External media tools are not bundled by default.

Configure existing local tools in Settings, then select local video paths and explicit intervals. A reference video is not a `.gyroflow` project template. Cached v9 reproduction requires explicit discovery of existing experiment data and provenance checks; footage and experiment caches are not included. CTB remains a manual export workflow, and unverified GF exports remain subject to review.

The home workspace has no floating job-activity panel. Open **Jobs** to inspect the queue, state and progress or cancel an active job; processing continues in the background without an overlay covering the workspace.

The embedded player targets verified H.264 8-bit/AAC previews, starts muted, and does not autoplay. Media/PTS/audio/current-input-corner verification is not certification of original FOV, a 4K/10-bit master, or perceptual superiority. Upstream cropping and bit-depth loss cannot be reversed.

Use **File → Open Web session** for the retained Web interface. It shares the desktop-owned worker, queue, and preferences. Closing the desktop app disconnects the Web interface. **View → Language** offers **System default / 简体中文 / English**; explicit choices are shared, while system mode resolves separately on Windows and in the browser. Unsupported system languages fall back to English. Original external diagnostics remain untranslated.

Local candidates are unsigned. Check their provenance and hashes rather than disabling Windows protection. See `LICENSE`, `THIRD_PARTY_NOTICES.md`, and the accompanying `licenses` directory for copied notices and outstanding distribution-review limits. Successful local execution is not public-release or legal clearance.
