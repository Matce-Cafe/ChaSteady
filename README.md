# ChaSteady

本地优先的视频增稳工作台。ChaSteady 是暂用名称，不是已经确定的最终品牌。

**目标形态：Flutter Windows x64 原生程序＋自包含 Worker＋保留的本机 Web 界面。** 本项目仍处于实验阶段：构建成功不等于原生播放器、完整操作流程或感知增稳质量已经通过验收，请以产物中的 `BUILD_STATUS.json` 为准。

原创代码采用 [MIT](LICENSE)。第三方依赖、字体及媒体工具保留各自许可证，见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。MIT 不会将这些依赖重新许可。

## 界面与工作方式

- 原创 Flutter / Material 3 界面，适应窄窗口与桌面布局，支持明暗主题。
- 简体中文和 English，默认跟随系统；不支持的系统语言回退 English。
- 首页不显示遮挡内容的任务活动浮窗。任务状态、进度和取消操作在独立“任务”页面。
- 原生菜单可打开同一 Worker 提供的 Web 会话；两端共享设置和单任务队列。
- 桌面进程拥有 Worker 生命周期；关闭桌面程序会使对应 Web 会话断开。
- 原生播放器采用原创 Windows Media Foundation / D3D11 / Flutter Texture 接线，不使用 libmpv、MDK 或 WebView 套壳。当前观看预览目标为 H.264 8-bit / AAC，初始静音、不自动播放；不承诺直接播放所有 HEVC、10-bit 或 HDR 原片。

设计只参考通用 Material You 与连续交互原则，没有复制 FlClash 的 GPL 代码、资源或页面布局。

## 端到端自动导出目标

目标是选择原片后，由工具自行合法调用 CTB 与 GF 完成各自导出，校验输出与原片的帧／时间对应关系，再接入 V9 融合并输出带音频的成片。GF 读取原片，不读取 CTB 输出；不能先切掉 Sony 陀螺元数据后将短片冒充完整输入。

**当前尚未达到此目标：**CTB 执行器仍需人工步骤，GF 短段导出尚有帧数／内容对应问题。已有 CTB/GF 文件的融合能力、能够启动外部软件、单独的数值回归或 Windows 打包成功，都不等于端到端自动导出已完成。自动化先在独立小范围真实导出中验证，再接入应用；不通过修改“已验证”标志跳过实际执行与媒体检查。

## 当前增稳路线

当前 V9 实验路线只使用 **CTB 像素**；GF 只作为同一时刻的整体运动参考，不混合 GF 的 RGB 画面。

- 融合中心位移和旋转，使用双锚点刚性 SE(2) 控制。
- 不施加逐帧估计缩放、局部网格、插帧或动态裁切。
- 允许黑边，以恒定画布容纳变换后的当前 CTB 输入矩形。
- 人工指定的已知区间与严格新测量分开记录；自动 RAW 陀螺分类保持禁用。
- 缓存复现需要显式发现并通过来源绑定和摘要校验，不能将任意文件冒充批准缓存。
- 跟踪、配准或时间戳闸门不通过时保留诊断并标记 `needs_review`，不能用虚构测量冒充成功。

**边界：**上游 CTB/GF 已丢失的视场、位深或细节不能恢复。当前输入角点、帧数、PTS 和音轨通过，不等于原片全视场、4K/10-bit 母版、无果冻或感知效果胜出的认证。

## 外部媒体工具

在设置中选择已有的本地 FFmpeg、ffprobe、Gyroflow 可执行程序及需要的导出模板。参考视频与 `.gyroflow` 项目模板是不同输入。

本项目不默认分发外部 FFmpeg/ffprobe、Gyroflow 或 Sony Catalyst 的可执行程序。Python 科学依赖可能自带第三方原生库，其许可另行保留。

Sony Catalyst Browse 继续采用正常 UI 的人工导出流程；不绕过账号、激活、Prepare entitlement 或厂商许可。GF 自动导出需要实际能力和时间映射校验，不能仅因进程退出码为 0 就视为成功。

## 构建与产物

仓库：[Matce-Cafe/ChaSteady](https://github.com/Matce-Cafe/ChaSteady)

Windows 云构建按手动触发方式准备，不因每次 push 自动发布，也不自动创建 GitHub Release。目标是官方稳定工具链；SDK 内部精确锁定的依赖保留官方配套版本，不以强制 override 冒充“全部最新”。实际版本、源码摘要和构建结果随产物记录。

完整目录包的目标结构：

```text
ChaSteady/
  ChaSteady.exe
  flutter_windows.dll
  data/
  Worker/
    Worker.exe
    ...
  web/
  licenses/
  README.md
  BUILD_STATUS.json
```

这不是单文件 EXE。必须保留整个目录；不能将 Worker.exe 单独当作 GUI 主程序。完整包不要求最终使用者安装 Python、Flutter、Visual Studio 或开发工具，外部媒体工具仍需按需配置。

构建包默认未签名，且可能仅完成构建与文件完整性检查，尚未进行原生运行验收。遇到系统安全提示时核对来源与摘要，不要关闭 Defender / SmartScreen，也不要把“能运行”当作发布安全认证。

## 数据与安全

- 素材在本机通过路径引用，不上传到外部增稳处理服务。
- 公开仓库和云构建不包含用户视频、实验缓存、profile、凭据、私有开发配置或整个 `private` 目录。
- 本机服务只监听 `127.0.0.1`，使用随机端口、会话 Bearer 与只读媒体 cookie。不要共享会话链接，也不要通过反向代理或局域网暴露端口。
- 资源目录与可写用户数据目录分离，不能把“目录名叫 private”当作操作系统级隔离保证。
- 新输出使用独立目录，不覆盖原片或已有导出，只清理本任务拥有的子进程。

## 状态含义

- `queued` / `running`：等待或处理中。
- `needs_manual`：需要外部软件的正常人工操作。
- `needs_review`：测量或媒体闸门未通过，不是验证成功。
- `failed` / `cancelled`：失败或取消。
- `verified_media`：报告范围内媒体证据通过，不是原片全视场或主观质量证书。

无法取得真实数值进度时使用不定进度，不显示虚构质量分。

## English

ChaSteady is an experimental local-first stabilization workbench targeting a native Flutter Windows x64 app, a self-contained processing worker and a retained offline Web interface. The name is provisional.

The current V9 route uses CTB pixels with same-time GF global-motion references, not RGB blending. It uses rigid rotation/translation, allows black borders and avoids dynamic cropping or estimated-scale application. Upstream crop and bit-depth losses cannot be reversed.

Media, experiment caches, profiles and credentials do not belong in this repository or cloud builds. Original code is MIT; dependencies and external media applications retain their own terms. A build-only, unsigned ZIP is not evidence of native playback, perceptual superiority or complete redistribution clearance. Consult the artifact's build status and retained third-party notices.
