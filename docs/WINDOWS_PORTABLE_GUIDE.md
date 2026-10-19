# ChaSteady Windows 便携指南

本指南对应 0.2.0 开发候选；是否已构建、哪些真实流程通过，以随包 BUILD_STATUS、版本及配套本机验收记录为准。仅有源码、Web 构建或缺少 Worker 的目录，不是完整 Windows 应用。

## 启动

- 保留整个目录，双击 **ChaSteady.exe**。不要只移动 EXE；Flutter 资源、Worker、web 和许可证目录都是组成部分。
- 完整目录包不要求另装 Python、Flutter、Visual Studio 或开发工具；没有保证完全缺少 VC++ 运行库的干净 Windows 可直接运行。
- FFmpeg／ffprobe、Gyroflow、Sony Catalyst 不默认捆绑。VS Code 播放器是独立项目，其后端不等于本应用已经捆绑。
- 若旧版仍运行，请先正常退出，再启动新版。不同解压目录默认仍共享当前 Windows 用户数据和单实例限制，不是独立 profile。
- 本地候选未签名。先核来源和摘要，不关闭 Defender／SmartScreen，不把能运行当作公开分发或法律认证。

## 日常使用

1. 首次进入**设置**配置已有的工具；Sony 软件按正常要求登录、激活和取得相应许可。未知引擎不会仅因选择路径便得到已验证资格。
2. 在**工作台**选择或拖入原片，使用推荐配置；需要时展开高级参数。视频引用、GF 参考视频和工程模板不是同一种输入。
3. 点击开始，查看实际阶段。应用管理任务中间产物，不要求日常为每个任务手填 CTB／GF／运行目录。
4. 宽工作区右侧可查看内嵌任务内容，其他宽度进入**任务**页；不会用首页活动浮窗遮挡内容。
5. 在任务详情查看错误、取消、输出及已验证预览。未知进度保持不定状态，不显示虚构质量分。

**当前自动管线仍有阻塞：**CTB 自动导出为 0；生产 GF 模板管理及严格全长 fresh 测量也尚未打通。人工 continuation 会创建带父来源的新任务，保留原人工状态，不算自动生产。旧三路融合／历史缓存属于高级验证用途，不代表单原片全自动已经完成。

## 导航与窗口

- 小于 800 逻辑像素时使用底部导航，其他宽度使用侧栏；Windows 和 Web 采用同一宽度原则。
- 侧栏支持仅图标／图标加本地化文字，切换应立即生效；宽窄变化保留草稿及用户选择。
- 原“文件／视图／帮助”功能集中在**设置**；常用页面也可使用 Ctrl+1／2／3。
- 顶部为原创窗口栏。最大化／还原、拖动、resize 和正常退出需以真实输入验收，独立方法测试不等于这些交互全部通过。
- 普通关闭走确认、媒体释放和自有 Worker 正常收尾，不接管或强关用户已有程序。

## 拖入与浏览器限制

- Windows 拖入只接受单个实体媒体文件，操作是 COPY 引用，不移动或修改原片。
- 拖入、文件选择和手输使用同一检查链。目录、快捷方式、程序、网络 URL、设备路径及无效输入应拒绝，不执行拖入内容。
- 只读硬链接媒体与 reparse／快捷方式不同；输入不得因存在合法硬链接就被误认为可覆盖目标，输出仍必须排除源文件及其别名。
- 浏览器不能由文件名获取任意本机绝对路径。Web 使用已声明的本机选择／路径能力，不使用 fakepath，不暗中上传素材。

## Web 会话与语言

- 从**设置 → 打开 Web 会话**进入保留的本机 Web 界面，两端共享桌面拥有的 Worker、队列和设置，不另起外部处理服务。
- 正常退出桌面会停止对应服务，Web 端随之断开。不要共享会话链接、向局域网开放端口或反向代理该服务。
- **跟随系统／简体中文／English** 即时保存，不要求先保存工具路径。显式语言选择在两端共享；系统模式分别按 Windows／浏览器语言解析，其余语言回退 English。
- 外部工具原始技术诊断保留原文，不以翻译改写证据。

## 预览和质量

内嵌播放器针对通过声明检查的 H.264 8-bit／AAC 预览，默认静音、不自动播放。不保证直接播放所有 HEVC、10-bit 或 HDR 原片。

要求无裁切、允许黑边；不借动态裁切、逐帧 scale、局部 mesh 或重复视频帧制造稳定。但上游已裁掉的 FOV、位深和细节不能恢复；当前 CTB 矩形、PTS、音轨或角点通过不是原片完整视场、原生 4K10-bit 母版或主观质量认证。

needs_manual 是人工阻塞，needs_review 是未通过或证据不足，不是已验证成功。候选静稳模式和未新处理基线分别标记，不把旧缓存说成新测量。

## 高级：创建独立验收 profile

只有包含并通过对应接线验证的版本才可使用：

```powershell
.\ChaSteady.exe --new-profile-root "<新的私有绝对路径>"
```

把占位符替换成自己可写、父目录已存在而目标目录尚不存在的路径。目标不能与默认用户数据根或程序资源目录重叠；路径、归属、ACL、reparse 或参数无效时直接失败，不能回退默认数据根。

此参数仅选择新实例的数据位置，不关闭认证、许可、媒体或数学门禁，也不接受外部 HWND。普通用户无需填写它。修改 LOCALAPPDATA 或换解压位置不能替代此隔离机制。

## English

Keep the complete directory and launch **ChaSteady.exe**. The bundle includes Flutter resources and its Python Worker; external media tools are not bundled by default. A clean Windows installation without the required VC++ runtime has not been certified.

The 0.2.0 candidate moves toward a single-original workflow with managed intermediate artifacts. CTB automation, production template management and strict full-length fresh measurement remain blocked. Manual continuation, mocked tests and historical-cache reproduction are not automatic end-to-end success.

Navigation switches to the bottom below 800 logical pixels and uses a sidebar otherwise. Settings contains the former menu actions and immediate language selection. Wide workspaces have an embedded task column, not a floating activity overlay.

Preview targets verified H.264 8-bit/AAC and starts muted. Check the exact build and runtime acceptance record; an unsigned local candidate is not original-FOV, 4K/10-bit, perceptual or legal certification. Preserve all third-party notices and do not disable Windows protection.
