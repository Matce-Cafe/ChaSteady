# ChaSteady

基于 Flutter 的 Windows 本地视频增稳工作台，整合原片导入、任务管理、处理状态和预览，并保留本机 Web 界面。

**当前开发版本：0.2.0+2，尚未完成本轮发布验收。** 源码中的日常入口已简化为单原片任务；CTB 自动导出和严格全长 fresh V9 仍有实质阻塞，不能称为完整一键增稳。构建成功、文件检查、真实界面操作和增稳质量是不同验收层，分别以实际记录为准。

## 快速开始

1. 获取完整 Windows x64 目录包，运行其中的 **ChaSteady.exe**，不要只复制一个 EXE，也不要把 Worker.exe 当作图形界面。
2. 如果旧版仍在运行，先正常退出旧版；默认启动共享同一 Windows 用户的数据根和单实例约束，不会热替换旧窗口。
3. 首次在侧栏／底栏的**设置**中配置已有的 FFmpeg、ffprobe、Gyroflow 等工具。Sony 软件仍需正常安装、登录和取得相应许可。应用不会绕过厂商授权。
4. 在**工作台**选择或拖入原片，使用推荐配置，按需展开高级参数，然后开始任务。
5. 在宽工作区右侧或**任务**页查看实际阶段、错误、取消操作和产物。遇到 `needs_manual` 或 `needs_review`，按具体原因处理，不能把它当作已验证成片。

0.2.0 的交互正在验证中；本文描述该开发候选的使用目标与边界，不表示已有可下载且完整验收的 0.2.0 发行包。

## 界面与任务

- 小于 800 逻辑像素使用底部导航，其余使用侧栏；侧栏文字按用户选择显示或隐藏，宽窄切换保留草稿和选择。
- 原“文件／视图／帮助”操作集中在设置，支持关于、许可证、语言、正常退出和用户主动打开 Web 会话。
- 宽工作区按扣除侧栏后的实际空间显示内嵌任务列；不恢复遮挡内容的首页活动浮窗。
- 界面支持跟随系统、简体中文与 English；语言更改独立即时保存，不要求先补齐工具路径。
- Windows 文件拖入采用原生 OLE，只复制文件引用，不移动或修改原片。选择、手输、拖入共享输入变更和媒体验收流程。
- 浏览器不能凭文件名取得任意本机绝对路径。Web 保留已声明的本机选择／路径能力，不使用 `fakepath`，不暗中上传视频。
- 同一选中任务只允许一个原生预览会话；切页和布局变化必须正确释放旧租约。

窗口栏是原创 Win32／Flutter 接线；只参考通用 Material 设计和自适应交互，不复制 FlClash 的 GPL 源码、logo 或资源。最大化、拖放和窗口生命周期必须以真实输入验收，不能只凭图标或方法级测试宣称可用。

## 单原片处理与当前阻塞

目标是只导入原片，由应用生成、核验和管理 CTB、GF、轨迹及成片，不要求每个任务手填中间文件目录。推荐配置和实际参数应冻结到作业记录，后续默认值升级不能悄悄改变旧任务。

流程设计为：

**原片检查 → 引擎能力预检 → CTB → GF → 时间／内容对应检查 → fresh 测量 → 刚性融合 → 渲染 → 最终验证 → 独立预览。**

CTB 与 GF 都读取同一原片；GF 不读取 CTB 输出，也不能先切掉 Sony 陀螺元数据后把短片冒充完整输入。

当前仍有以下边界：

- **CTB 自动导出为 0。** 已测试的标准 UIA／MSAA 只有根对象，当前没有合法可靠的无人值守执行器。不会使用盲坐标、猜快捷键、私有 Qt、注入或授权绕过。
- **GF 完整自动导出已有真实成功。** C7037 的独立完整帧数、PTS 和 AV 解码检查通过；内容对应证据仍只是有限抽样，生产身份／模板管理等接线不能因此视为已经完成。本轮本机进程身份检查仍有无法确认项，保持阻塞，不通过猜测系统进程或提权来放行。
- **strict 全长 fresh V9 尚未通过。** 固定测量门禁下的不可观测区间保留失败，不补 identity、不删插帧、不放阈值或更换 golden。
- 人工导出 CTB 后的 continuation 是明确的新任务，保留父任务失败／人工状态和来源。它减少重复路径操作，但**不是 CTB 自动生产**。
- 旧三路融合和 C7037 历史复现保留在高级验证范围，不能将任意新 CTB／GF 直接套旧轨迹。

因此，本轮界面简化与单原片编排基础，不等于真正的一键自动管线已经完成。

## 增稳路线与输出含义

当前 V9 路线只使用 **CTB 像素**，GF 仅提供同时间全局运动参考；采用双锚点刚性旋转／平移，不混合 GF 的 RGB。

- 要求无裁切、允许黑边，以恒定画布容纳当前 CTB 输入矩形。
- 不使用局部 mesh、逐帧 scale、动态裁切、插帧或冻结视频帧制造稳定。
- 已知人工窗口与新测量分开，自动 RAW 分类保持禁用。
- 静稳保持／运镜释放已做两轮独立有界试验，但没有方案通过晋升，默认不启用未获证据支持的新模式。应保留真实摇移与光学变焦，不能以压低指标为由冻住运动内容。
- 上游 CTB／GF 已丢失的视场、位深或细节不能恢复。当前矩形角点、帧数和 PTS 通过，不等于原片完整 FOV、原生 4K10-bit 母版或主观质量认证。

现有 Worker 观看预览以 H.264 8-bit／AAC 为目标，不承诺直接播放所有 HEVC、10-bit 或 HDR 原片；默认静音、不自动播放。预览与最终处理的验证范围分别记录，不通过改标签取得原生播放资格。

## 运行依赖与数据

完整包包含 Flutter 运行资源和 Python Worker，不要求最终用户安装 Flutter、Python、Visual Studio 或开发工具。**尚未保证完全缺少 VC++ 运行库的干净 Windows 可直接运行。**

外部 FFmpeg／ffprobe、Gyroflow 和 Sony Catalyst 不默认随 ChaSteady 分发。VS Code 播放器是独立项目，其内置 FFmpeg 不表示本应用已经捆绑同一后端。

- 素材在本机引用，不发送到外部增稳处理服务；原片不写、不移动、不覆盖。
- 中间产物、任务日志和参数属于应用可写数据；程序资源根与数据根分离。
- 默认用户数据根通过 Windows Known Folder 和 SID 确定；更改 `LOCALAPPDATA` 或解压目录不构成隔离。
- 本机 Web 服务只监听 `127.0.0.1`，使用随机端口和会话凭据。桌面拥有 Worker 生命周期，正常退出后其 Web 会话断开；不要共享会话链接或暴露到局域网／反向代理。
- 媒体、缓存、profiles、凭据、私有配置和原始本机诊断不上公共仓库或 CI。

开发候选新增的 `--new-profile-root` 仅供显式创建隔离实例：目标必须是新的、绝对且私有的目录，与生产数据根和程序资源根不相交；无效即失败，不回退默认数据根。它不关闭认证、质量或许可检查。仅在对应版本真正构建并验收后使用，细节见便携指南。

## 状态含义

| 状态 | 含义 |
| --- | --- |
| `queued` / `running` | 等待或处理中，数值进度不可得时使用不定进度 |
| `needs_manual` | 需要外部软件的正常人工步骤，不是自动成功 |
| `needs_review` | 测量、对应或媒体门禁未通过／证据不足 |
| `failed` / `cancelled` | 失败或取消，保留真实历史 |
| `verified_media` | 报告所声明范围内的媒体检查通过，不是完整 FOV 或感知质量证书 |

## 构建、验证与维护

公开源码仓库：[Matce-Cafe/ChaSteady](https://github.com/Matce-Cafe/ChaSteady)。Actions 手动触发，不因每次 push 自动发布，也不自动创建 GitHub Release。失败历史不被后续成功改绿；专项检查成功不等于生成完整包。

以下早期构建与 UI 专项的失败／待验收描述按当时时点保留：

本轮首次 0.2.0 完整构建在解释器／进程管理前置契约处失败，未产生新包；相关 CI 运行时交接、批处理入口与清理已做源码修复和有界验证。后续 UI 专项检查在测试夹具路径守卫处失败，尚未执行 Flutter；仅规范化夹具后本地 93 项纯回归通过，没有放宽生产校验。随后新提交的 [UI 专项检查](https://github.com/Matce-Cafe/ChaSteady/actions/runs/39228160625) 已通过运行时交接、Flutter 身份及界面分析／测试；完整原生构建与打包未在该专项执行。旧 0.1 包不是这些检查的产物，新的 Windows 包仍待整合与验收。

### 2026-10-19 后续：Full 构建与本地数据交付

[完整构建 39233475590](https://github.com/Matce-Cafe/ChaSteady/actions/runs/39233475590)／attempt 1 已成功，实际 CI 源码为 `7082e0676510db4e0251e59892f9a901bbfdaec3`；唯一 artifact 为 `12180437313`（`ChaSteady-0.2.0+2-Windows-x64-39233475590-1`）。产品版本为 `0.2.0+2`，主程序 PE 的数值 FileVersion／ProductVersion 均为 `0.2.0.2`，字符串均为 `0.2.0+2`。

artifact 内的应用 ZIP `ChaSteady-Windows-x64.zip` 为 `157127435 B`，SHA-256 为 `46c09c6fa7e96a192a9f443e71b971d9681a2129e6236266b9e46acbf9f97221`，不是外层下载传输容器的摘要。1228 个文件的数据审计、受控提取及完整逐文件摘要回比通过；独立测试副本受控提取保留 `ChaSteady/` 前缀，1228 个文件合计 `383881616 B`；另行本地交付应用 ZIP 及清单／摘要。未启动应用、Worker 或 GUI。

同包真实 GUI 尚未验收；CTB 自动导出仍为 0，GF 生产身份／模板管理和 strict 全长 fresh V9 仍阻塞。当前本机仅对包内一个 Python DLL 取得 fresh `Valid`；manifest 的源签名状态仍为 `null`，不回填。主程序／整包未签名、未获法律分发认证，没有 GitHub Release／Marketplace 发布；私有数学 golden 未上传 CI。

本段是构建之后的文档跟进，不是该 run 的构建源码；后续文档提交不改变包的 `7082` 来源，也不重写原包内文档、manifest 或 BUILD_STATUS。

产品版本以 [ui/pubspec.yaml](ui/pubspec.yaml) 为准；Worker 组件版、通信协议及 Python 运行时版分别标记。未签名、构建或文件审计成功不等于完整本机验收。核对来源和摘要，不关闭 Defender／SmartScreen。

本轮当前源码的本地后台回归为 234 项（233 项执行通过、1 项既有平台跳过，0 失败／错误），原三案例数学 golden 按原阈值通过并生成新来源摘要。界面回归 77 项通过，最大化新路线也已在私有 Win32 窗口完成两次真实点击验证，该路线与受管关闭接线现已合入源码，但同包真实 GUI 验收尚未完成；这些测试不代表自动 CTB／GF／fresh V9 全流程通过，详细范围见 [验证记录](docs/VERIFICATION.md)。

- [更新日志](CHANGELOG.md)
- [维护与 Git 规范](CLAUDE.md)
- [验证范围](docs/VERIFICATION.md)
- [Windows 便携指南](docs/WINDOWS_PORTABLE_GUIDE.md)
- [云构建说明](docs/CI_BUILD.md)

## 许可证

原创代码采用 [MIT](LICENSE)。第三方依赖、字体及媒体工具保留各自许可证，见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。MIT 不会重新许可这些依赖，进程隔离也不是自动取得第三方分发许可的理由。

## English

ChaSteady is an experimental local-first Windows stabilization workbench built with Flutter and a self-contained Python worker, with a retained local Web interface. Version 0.2.0+2 is under implementation and acceptance, not a completed automatic pipeline release.

The intended default workflow imports one original source and manages intermediate artifacts internally. CTB automation and strict full-length fresh V9 remain blocked. The current route uses CTB pixels with same-time GF global-motion references, rigid translation/rotation and a constant padded canvas, not RGB blending, dynamic cropping or frame duplication. Upstream FOV and bit-depth losses cannot be restored.

Original code is MIT; third-party terms remain applicable. User media, profiles, caches and credentials are not part of the public repository or CI. Build, runtime, media and perceptual claims must remain separate.
