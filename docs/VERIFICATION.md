# 本机验证记录 — 2026-10-14

这是执行证据记录，不是效果或许可证认证。本轮本机MVP的构建、主链路与有界外部导出能力检查已完成；未通过的GF截取、CTB自动化、FOV及分发许可边界按事实保留。

## 已完成：数学与真实媒体

新 Python worker 已独立复现 C7037 三个批准的 V9 窗口，不依赖 N 盘脚本作为运行时代码（历史 NPZ 是明确的只读输入）。

| 源范围 | 新媒体 | 帧数 / fps | 画布 | 最小角点边距 |
|---|---|---|---|---:|
| 140–156 s | regression-fe7c90e10ce64d3b8ecb832f594f78e5 / zoomin-140-156 / preview.mp4 | 800 / 50 | 1412×814 | 4.543 px |
| 212–228 s | 同 trial / fixed400-212-228 / preview.mp4 | 800 / 50 | 1382×808 | 4.526 px |
| 230–246 s | 同 trial / zoomout-230-246 / preview.mp4 | 800 / 50 | 1590×950 | 4.071 px |

三者均通过视频实际帧数、完整 AV 解码与当前 CTB 输入角点包含检查。AAC 都是48kHz双声道、首PTS0、时长16.000s；来自原片对应范围，不交付额外 MP3。

与旧 V9 黄金轨迹最大误差分别为 1.137e-13、0、5.684e-14，实际融合权重误差均0。这只证明数学移植一致，不证明感知效果胜出。

证据在 `private/runs/regression-fe7c90e10ce64d3b8ecb832f594f78e5/regression.json` 及各窗口 manifest。

### 从实际输出画面独立回测

`tools/assess_port.py` 重新解码旧实验 V9 与新 worker 输出，不读生成轨迹作测量真值。使用原来的两个上部鼓架 ROI、有效对交集、连续有效段频带分析，不插值/补零。

| 源范围 | 共同有效对 | 旧V9 / 新worker：3–12Hz位移RMS（1280px尺度） |
|---|---:|---:|
| 218–222 | 199/199 | 0.2749 / 0.2622 px |
| 222–224 留出段 | 97/99；频谱89对 | 0.2819 / 0.2796 px |
| 224–228 | 199/199 | 0.2714 / 0.2761 px |

差异很小，支持安静目标移植一致，不把0.01px左右的差别包装成改善。154–156强抖代理仅有37/99共同有效对，无可用频谱；证据不足，不称其比原V9更好或无果冻。此处方法不同于之前的高抖 phase checker，不能混用有效对或RMS作排名。

报告：同 regression 目录的 `independent_pixel_readback.json`。

## 已完成：严格 fresh 路径的有界试验

新 trial：`private/runs/fresh-trial-9752c896b16d4675ab97dc5129ca3fbd/`。

- 218–222安静段：199个增量重新测量、通过闸门，输出200帧/50fps媒体并通过角点/AV验证。未把第一帧坐标基准当测量零运动。
- 独立画面回测共同有效199/199，3–12Hz位移旧V9 0.2749px / fresh 0.2686px。不是显著获胜，不据此推广。
- 154–156强抖段：新CTB跟踪遇到实际可信闸门失败，停在 `needs_review`，没有identity填空或旧缓存偷偷替代，没有生成“成功”的强抖新媒体。
- 决策：fresh保留实验标签；C7037完整已知缓存预设仍是交付回归基线。

证据：`trials.json`、`fresh_quiet_pixel_readback.json`、失败段 `failure.json`。

## 已完成：实际 HTTP 工作进程链路

启动真实 CLI `tools/worker_cli.py --port 0 --no-browser`，不是 mock server。`tools/smoke_http.py` 经会话鉴权执行：

1. 配置只属于本工具的 FFmpeg/ffprobe 路径（未改全局PATH）。
2. 真实原片媒体探测。
3. POST固定长焦完整 cached V9任务，真实作业进入 `verified_media`。
4. 用只读媒体cookie读取已注册preview，Range返回206、1024bytes。

job ID：`4f8c1ffb-a98e-49f6-b16a-f13f2c1dbd7a`。

证据：`private/runs/4f8c1ffb-a98e-49f6-b16a-f13f2c1dbd7a/http_smoke.json`。完成严格PTS、全部相关AV解码及新DACL保护后重新启动真实worker并复测，也通过；新job `4a951b4e-61cd-48ed-a31f-51c2ffe54410` 的 `http_smoke.json` 记录同一实际链路。这是HTTP端到端，不冒充浏览器按钮测试。

## 修复的实际问题

- ffprobe在 `-read_intervals start%end` 下会少吐出末端重排B帧：原片800对齐，CTB只799、GF798。改为略向范围末端之后探测，再严格选取范围内800帧并检查起尾PTS；没有放宽缺帧标准或补帧。
- 单位旋转校验显式 `rtol=0`，不让默认相对容差接受微小缩放。
- 音轨存在不等于尾段完整：新增起点/尾段时长闸门与截断测试。
- 新CTB跟踪增添源/目标点空间覆盖和残差闸门，不让局部运动小团点轻易代表整体相机运动。
- 界面第一轮编译虽通过，但发现扁平job请求、nested preset与配置路径接线问题，要求修复真实HTTP契约后重建；不能把仅stub通过当交付依据。
- 服务器必须服务实际 `ui/build/web`，不是Flutter模板 `ui/web`。

## 单元测试与界面构建

- 新core：15项几何/双锚/参考配准/缺失拒绝测试通过。
- 新媒体证据：6项PTS覆盖/缺帧/音轨尾段/认证范围测试通过。
- 完成GF双版本/720p预设、请求幂等性、DACL、严格PTS/色彩/封面流、零权重分支与单实例锁后，主进程最终全套：82项全部通过（2026-10-14，5.548s）。GF mock通过不等于全源运行或内容映射认证；3秒真实试验仍needs_review。
- Flutter首轮8项测试/build之后发现实际API接线与结果布局问题，已修复并重新构建。最终analyze无问题、14项widget/HTTP契约测试通过，release web在ui/build/web，最终lock已保存，合法Noto Sans SC/OFL/provenance本地。
- 实际Edge/CDP：完整预设发现→Fixed空参考区间→真实POST202任务59e81229...→verified_media→16s播放器播放/seek8s，中文结果及所有页面资源无外部HTTP请求。360/800/1440布局、主题保存、真实sheet吸附及JSON默认折叠已检查；无截图、未关闭/接管其他页面。详见UI_E2E_20261014.md。
- 实际Start.cmd --no-browser启动成功；第二次CLI与批处理启动均exit2并提示already running，不新建server/恢复JobStore。worker_cli和Start.cmd均显式传递退出码。单实例锁在server生命周期持有，重启后3个完成作业状态保留。

## 外部软件与未完成认证

- Catalyst实际UIA不可用，且启动有已披露的普通profile副作用；自动启动已停止。保留人工步骤，不把installed/root-window当自动导出已验证。
- 新GF真实3秒试验已完成：商店MSIX版本直接创建进程被PermissionError阻止，无正式CLI alias，未改权限/升权/GUI激活。独立已审计Nightly 1.6.3(gh2811)则实际CLI exit0，生成1920×1080/50fps/H.264输出并通过完整解码；请求212–215秒150帧，实际152帧/3.04s，PTS0–3.02，因此严格trim映射未通过、保留needs_review。
- GF试验workdir：`private/runs/d79cff8d-eef3-4200-a6c7-a0892a52a417/`。媒体SHA-256：`ea026ef9d5d56d1e0c34495926eb1281cc7a3adbc50607517ac00fdb0c43b783`。5个profile文件恢复到运行前字节摘要，settings未改，camera_presets摘要未变，无新cache/.dmp/GF残留进程；具体备份与restore guard见 `docs/gyroflow_export_probe.json`。
- CFR/帧数证据不证明画面内容逐帧对应，`content_correspondence_verified`保持false。全源参考仅增加可选低分辨率preset代码支持；本轮没有运行全源导出，不把它描述为已验证fallback。
- 原片全FOV、全351.84秒4K/10-bit母版、任意相机通用稳定性、无果冻和许可完整性均未认证。
- 没有发布、commit/push、上传素材或额外授权安装系统原生C++工具链。

## 后续补充：2026-10-19 开发迭代

以上是 2026-10-14 当时的执行记录，不把后续成功回填进旧试验，也不将当时的“未执行”误当成项目永久状态。

### GF 完整导出的后续证据

- 2026-10-16 已在已审计的独立 Nightly 上真实自动导出完整 C7037，直接读原片，没有预切源或请求 trim。
- 独立后验检查中，源与输出均为 17,592 帧，首 PTS 为 0，相对 PTS 最大误差为 0；全视频与全部音轨解码通过。
- 内容抽样为 18 帧，其中 6 帧可唯一定位、12 帧 unknown；这不等于全源逐帧内容对应认证。
- 输出是实验性 1080p、8-bit H.264 参考，不是最终 V9 或原生 4K10-bit 母版；原适配器先前的 300 秒 PTS 探测失败记录没有被改写。
- CTB 自动导出仍为 0，完整 CTB→GF→fresh V9 生产链仍未完成。

### 桌面构建与交互证据的区别

- 2026-10-17 的完整云构建 39035365573 成功，原始 head 为 acfa0635af567d5ef1795c7b2d57e3d22a50e467。UI 检查、Windows/Web Release、原生方法夹具、Worker、协议和文件清单的成功不是本机完整交互认证。
- 用户随后实际运行该桌面候选并报告最大化、文字显隐和窄窗导航问题。0.2.0 正在修复这些交互，真实鼠标、OLE、profile 隔离和正常关闭必须补充独立证据。
- 本轮历史文案重写不得修改旧构建、ZIP、manifest 或上述 head 归属；原提交及签名保留私有备份。
- 新 Worker 源码及新增模块改变了旧数学来源绑定。必须重新运行原三个 golden 和后端回归，不能仅修改旧 31 源摘要或将 unit/mock 结果写成真实自动稳像通过。

### C7037 静稳保持第一轮

- 旧全长候选仍为 CTB baseline＋三个已验证 V9 窗口及明确过渡；processing_coverage 为 partial_v9_windows、strict_full_v9_verified 为 false。
- 新静稳试验首轮使用六组固定参数、预声明窗口、CPU-only 和独立背景读回，没有全片参数搜索。
- 头、拉近／强抖和中段最初只取得不足的区间 PTS，未进入新运动测量；这是实验采集器遗漏既有 demux guard 的问题，不能当作原片缺帧或 quiet 模式失败。新容器时间台账仍须与像素／内容证据区分。
- 已实际评估的拉远段中，四组 hold 控制没有进入 HOLD，未证明改善；尾段在 343.68 秒触发真实覆盖门禁失败，旧 7886–7893 不可观测证据也仍保留。
- 第一轮无候选晋升。新全长候选和 351.84 秒全片六宫格尚未生成，内部短段不算最终交付。

### 本轮已执行的源码与数学检查

- 最终 Flutter analyze 无问题；完整 widget／模拟 API-channel 回归 73 项通过，另一次 About 测试实际注入 0.2.0+2 编译定义通过。测试包含实际 tester.tap、滚动及异步竞态，但不等于真实 OLE、Flutter release 窗口或解码认证。
- 后台完整测试共 168 项：167 项执行通过、1 项原有平台条件跳过，无 failure／error。测试覆盖认证 HTTP、owned fake executable 和只读 PE 等，不是实际 CTB／GF 自动端到端。
- 原三个数学 golden 实际只运行一次、未请求 render，matrix 误差依次为 1.1368683772161603e-13、0、5.684341886080802e-14；weight 误差为 0、0、1.1102230246251565e-16。原 1e-9／1e-10 阈值与旧答案未改。
- 本次 31 个 package Python 加 3 个工具共 34 源，逐文件 canonical UTF-8/LF 与 raw SHA 在回归前后不变；新摘要直接从真实报告和当前源码生成并通过既有 CI 校验，不复用旧 31 源摘要，不声称已构建新冻结 Worker。
- 构建／版本／维护 helpers 共 145 项通过，含 mock 构建参数和版本守卫；尚未执行真实新 PE 版本核对或新发行包验收。

### PTS 采集器的单次真实修正验证

- CTB 头段保留原分析区间 [0,10)，demux 只增加到 10.5 秒；返回 525 条元数据后严格选回原 500 条，首 PTS 为 0、末为 9.98 秒。
- 全部 500 条逐值匹配独立容器整数时间台账，expected 500 与 1e-6 精度均未改变；旧 498 条失败报告及源文件 SHA／stat 保持不变。
- 该步骤没有 RGB 提取、运动分析或候选渲染，只证明采集器 guard 修正。它不能冲销尾段真实测量失败，也不是静稳改善证据。

### 最后第二轮静稳裁决

- PTS 修正后，头段、拉近和中段原 context 分别完整取得 500、1,200、1,000 条时间戳，没有改变原区间或帧数标准。
- 严格运动测量仍失败：头段 6.80 秒覆盖 cells 为 5、小于 6；拉近 155.50 秒 inlier ratio 为 0.22477、小于 0.30；中段 212.12 秒 inliers 为 12、小于 18，ratio 为 0.10435。
- 未切掉失败前缀再单测后段 quiet，未补 identity 或放宽门禁。拉近先在 155.50 秒拒绝，不声称重新测过 157.72 秒的旧不可观测区间。
- 两轮、六组试验结束，无 winner，新增获准静稳覆盖为 0 帧；首轮拉远和尾段真实结论不变。优化目标本轮未达成。
- 全长六宫格继续制作，第六格明确标注“本轮静稳未晋升：沿用当前混合”；与第五格相同是公开的基线保留，不生成或复制旧片冒称新静稳候选。完整宫格尚未交付。

### 集成复核后的补充修复与仍在进行的检查

- 失焦外部拖入的红测真实失败后，将可见导入区与前台预览／轮询分开；可见 inactive 状态接受外部拖入，hidden／paused／detached、切页、选择器、关闭及锁定仍撤销。定向 9 项、analyze、完整 75 项分别一次通过，旧 picker 失焦结果回归保留。这仍是 widget／channel 层，不是 Explorer/OLE release 认证。
- 原生 profile 夹具实际发现 attributes-only 目录句柄不能阻止改名；原 49 项断言未改，加入 FILE_LIST_DIRECTORY 后新版本 49 项全部通过，旧 5 个失败与 owned 测试数据保留。
- 隐藏 OLE 数据／注入夹具 111 项通过，包括实际注册／撤销生命周期及只读硬链接的 file ID、size、mtime、SHA 不变；它不证明可见 Explorer 拖入。新原生源码已通过补充 MinGW 编译／监督器语法检查，不冒称正式 MSVC／Flutter release。
- 独立复核另发现 Native 预览释放失败后的租约重试问题，以及后台并发引擎身份、元数据持久化、十进制时长、备份目录重叠、能力降级与模板身份问题，正在定向修复。复核前的 168 项／三案例及 34 源摘要只对应当时源码；修复后的发布必须使用新完整测试、数学回归和新来源绑定，不能沿用旧摘要。

### 完整六宫格已实际交付

- 新的本机观看比较视频为 2880×1160、351.84 秒、50 fps、17,592 帧；第五、六格明确同源同刻，标注本轮静稳未晋升、沿用当前混合，没有新静稳候选，也没有复制旧混合充当候选。
- 五个唯一输入均自然 EOF 解码完整帧数，整数 PTS 原点 0、末 351.82 秒逐帧匹配 50 fps；输出 frame／packet PTS、完整 AV 严格解码通过，编码 dup/drop 为 0。无 fps 滤镜、变速或帧数／时长截断。
- 固定等比 fit/pad、中文标题画外；只一条原 PCM 转 AAC 320k／48 kHz 双声道。原 PCM 每声道 16,888,320 样本，AAC skip priming 1,024，显式 discard 0、呈现窗外解码 padding 512；呈现尾部完整覆盖，未伪造 discard 字段。
- 40 组有限同刻内容锚点中 31 组接受、9 组 unknown：175.92 秒的四源、233 秒的历史 GF Default、351.82 秒的四源。未知不等于已证错位，不能认证全源逐帧内容同步，未做时间修复强凑。
- 单次完整运行及全部 QC 用时 28 分 7.6 秒，GPU0；源与旧证据不变，自有进程自然收尾。主会话独立重算交付视频完整 SHA 与报告一致，仅作为文件身份复核，没有冒称重复 AV 质检。
- 该媒体交付通过不改变两轮静稳无晋升、CTB 自动导出为 0 或严格全长 fresh V9 未完成的结论；视频及原始本机报告未上传公共仓库／外部处理服务，不是原生 4K10-bit 母版或 FOV／感知认证。

### 跨字段选择器与最新界面回归

- 原生选择器导致窗口禁用时会撤销 OLE 目标；此前其他字段取消选择后，原片组件仍把同一几何当作已注册，实际没有恢复目标。红测真实复现旧回调还能改变原片的问题后，增加所有合法原生选择器共享的忙态与代次，开始时撤销、结束后重新配置。
- 修复后定向 28 项、analyze、完整 77 项分别通过；独立只读复核确认该跨字段问题已消除。这是 widget／channel 的模拟边界验证，不算可见 Explorer/OLE 或同包 release 通过。

### 真实鼠标窗口诊断：问题已复现，尚未修复

- 首个真实输入夹具因加载阶段缺少 COMCTL32 的具名导入而退出，未观察到 owned HWND，不据此判断窗口路由；原失败保留，未重复运行同一版本。
- 新版本只给私有 Win32 夹具增加 documented Common Controls v6 激活清单，生产 manifest、窗口代码及输入源码保持不变；数据检查确认嵌入清单和输入导入，随后实际运行一次。
- 新窗口在输入前已由原始进程 HANDLE、创建时间、映像、线程和 owned HWND 验证，处于可见前台且无其他按键活动，DPI 为 192；单次 MOVE／DOWN／UP 三项全部接受，没有 partial 输入或补偿。
- 实际 trace 为 child HTTRANSPARENT → owner HTMAXBUTTON → WM_NCLBUTTONDOWN → 默认非客户区处理，但没有产生最大化系统命令，第一手势未最大化，测试为 FAIL。约 1.84 秒后原进程自然退出且 owned Job 为零，没有强制清理。
- 这条真实失败只约束该独立夹具；其激活上下文不同于 MSVC 生产程序，不认证 Flutter、Snap、resize 或多显示器，也不证明根因已经全部排除。后续修复必须保持单一路由并在同一实际 release 再验。
- 随后分离 UP 时机的私有诊断进入未确认输入释放的被动保留状态，并在用户中断后结束；没有完整 NC／SC 结果、原始进程正常退出或实际 Job 归零证明，结果为 INCOMPLETE_INTERRUPTED_NOT_PASS。后续原身份句柄不可得，不按旧 PID 重新接管或强清，也不重复运行该版本碰通过。
- 新的持久日志夹具完整返回功能 FAIL，并确认输入释放、原始进程自然结束与实际 Job 为零。日志发现旧 64 位标记的高位未在观察消息中保留，导致认领失败，实际走保护性 250ms 分支；该次不能用于否定预期 50ms 时序。只调整为完整可保留的非零标记并通过 63 项纯验证后，另一新版本实测成功认领，DOWN→UP 为 63ms、scheduler succeeded／can_finish 为 true；仍未产生最大化 SC，因而本次排除了“仅调整该夹具的 UP 时机便能修复”的假设，而非认证真实 Flutter 路由或宣称最大化修复。两次新试验均无强制终止；stock 几何查询缺少成功 BOOL，仍不作为唯一根因。

### 单一路径 capture 候选的真实鼠标补证

- 新私有候选不再把自定义最大化按钮的 DOWN 送入默认 NC tracker，也不叠加 Dart toggle；使用原生 capture 按压状态机，并在通知重入后重新检查关闭状态、epoch 和命令资格。旧源的重入红测真实失败，新源 445 项受控隐藏检查、原 22 项 pure 通过，独立精确复核未发现该补丁的新具体残余。这些检查本身不算物理输入验收。
- 随后仅执行一次新二进制的真实鼠标试验：两次手势分别完成最大化和还原，maxSC=1、restoreSC=1；每次 MOVE／DOWN 前缀 2/2、唯一 UP 1/1，两个 scheduler succeeded／can_finish 均为 true，incomplete 均为 false。不是直接调用 ToggleMaximize 或发送 SC 代替点击。
- 源先输出等待释放证明的保守 incomplete 提示，随后给出 generation 2 的 source_released；父侧两次独立严格释放观测相隔约 102.525ms。只有后续实际释放证明才授权 FINISH，未把早期提示、诊断或日志解析当作关闭授权。
- 约 3.732 秒后原始进程 HANDLE 已结束、实际 Job 为零，termination_attempted=false，41 份冻结输入前后不变。持久日志 129 个事件、6 个原始 chunk 与 122 行 source 逐项一致，无半行尾部；只认证采集前缀，不声称观察到全流 EOF。
- 首个私有离线解析器漏识别既有的 pre-resume 身份记录而失败，原脚本和失败保留；新解析器增加该记录核对后通过，没有重跑真实输入、修改日志或重放控制。真实 Flutter 发布程序、Snap、多显示器与同包退出均未获该次认证。
- 同一 WindowChrome CPP／header 与已复核的关闭接线先在全新私有副本组合。使用现有 Flutter 3.47.7 的 18 个真实 vendor 头文件闭包，对 NativeBridge、WindowChrome 两个 TU 独立执行 release 模式 -Wall／-Wextra／-Werror 语法检查，均通过，实际依赖确认没有误取旧 header；无 stub、无 SDK 执行或新输入。这是 LLVM 源码检查，不是 MSVC 链接或正式构建。
- 随后先独占备份三份原件，再将同一候选字节精确合入应用源码；实际 diff 与已审组合逐字节相同。72 个原输入中恰好 3 个计划变化，其余 69 个及 52 个受保护私有源码／旧证据不变。生产集成已完成到源码层，完整云构建与同包运行结果仍须另行记录；Worker 与数学绑定没有因此变化。

### 后台独立复核与来源绑定状态

- 首轮独立复核的六项问题包括改名引擎并发识别、超限元数据持久化、十进制时长舍入、备份目录自包含、能力降级及模板实际身份。首轮修正后完整 185 项（含 1 项原有平台跳过）和原三案例通过，但复核仍发现进程身份与其他 mutator 写失败的残余，因此该轮摘要不是最终发布绑定。
- 后续存储改为 candidate → 原子写成功 → 发布内存／索引，必要 validation 结果有界摘要；持续存储错误使用 per-job、非持久化的 unavailable 诊断，不修改已提交记录，也不把未保存的 failed／verified 冒称落盘。独立静态复核确认原反例已消除；最终完整回归与源码绑定尚待收口。
- 后续进程审计使用自身 TokenUser／session 与 WTS primary-owner 信息交叉，已消除静态上的一律误封条件。唯一实际只读诊断仍遇到无法安全排除的必要映像，结果为 unverified；没有启动引擎、写 profile、恢复日志或控制现有进程，不能认证正常主机会话已经可用。
- 空 SID、名字、父进程为零或 CPU 时间不构成反向系统身份认证；未采用这类跳过推断，也不提权。新的文档化 owner 方法补证与最终回归须分别报告，不沿用旧数学摘要或将 mock／静态 resolved 写成真实 GF 通过。

### 随后的整套回归失败与安全调查

- 后续精确布尔 full_source、startup 读取故障及 preview 状态保存故障的定向 26 项通过，独立差异复核未确认新残余；这不替代整套回归。
- 新完整回归实际 211 项，1 failure、0 error、1 项原有平台跳过；失败是取消后的后代退出断言，WaitForSingleObject 返回 WAIT_TIMEOUT 而非 WAIT_OBJECT_0。原数学 golden 因整套失败没有启动，实际次数为 0；没有生成可发布的新数学摘要。
- 旧测试通过数值 PID 重新打开 child 句柄，finally 清理也没有保存原始 child HANDLE、创建时间或映像，因此此次失败不能区分准入遗漏、退出尚未完成或身份复用；不能声称旧清理已经证明只针对同一 incarnation。已停止复用该测试路线，不追查旧数值 PID。
- 只读检查确认 production 使用 Popen 运行后再 Assign Job，并存在赋 Job 失败时的降级窗口；已有最长 5 秒收尾轮询，但部分 BOOL、查询失败及截止结果未向上明确报告。尚不能由静态缺口认定此次 failure 的唯一原因。
- 新安全调查已单次执行两个 fake-only 场景：受控 Job 准入后 GO 的场景中，原始／明确转交 child HANDLE 的创建时间、映像及 exact Job membership 一致，取消后原 HANDLE signaled 且 Job active=0；这只证该次已准入后的收尾。
- 独立反例用事件保证 child 已出生、原 HANDLE 已转交后才给 parent Assign Job：parent 属于该内层 Job，child 不属于；取消后 parent 已结束、内层 Job active=0，但同一 child 原 HANDLE 仍为 WAIT_TIMEOUT、创建时间未变。由此确认旧生产准入顺序确可遗漏早出生的后代，不是仅靠静态猜测，也不证明历史 211 项失败必定由同一分支造成。
- 反例随后仅通过原 child HANDLE 强制清理，并明确记录 forced_cleanup，不计正常 PASS；两场景的外层 owned guard 均最终归零。旧源码、原测试和既有失败记录保持不变；后续生产修复和新回归另行绑定，不延长任意 sleep 或删除原退出要求。
- 第二次只读 owner 方法补证也为 unverified：PowerShell 没有返回可验收的方法字段，实际方法调用次数未知，不能把初始化计数 0 当作零调用证据。原报告和追加解释分别保留，未接入 production，也不据此宣称全机无并发引擎。
- 独立原生终态修复另有 366 项纯状态检查和 Supervisor 语法检查通过，包含启动失败已收尾、但尚未 ready 的关闭边界；完整 Flutter bridge、真实 Worker 启动失败页与同包 GUI 关闭仍未实际验收。

### 创建时进程归属修复与最终验收准备

- Windows 子进程改用 documented STARTUPINFOEX 的 Job／handle 属性列表，在 CreateProcessW 创建时绑定自有 Job 并挂起；保存原 process／thread HANDLE，实际检查归属、登记与取消状态后才 Resume。不在赋 Job 失败时放跑，也不再先运行后纳管。
- 修复版本的一次立即派生真实 fake-only 场景通过：没有应用 GO，父进程恢复后立即创建后代；原 child HANDLE、创建时间、映像及 exact Job 一致，取消后该原对象 signaled，外层 Job 自然归零。首次私有夹具缺少 threading 导入的失败保留；该成功只绑定当时的正常路径版本。
- 后续再修复包装原 HANDLE 时 MemoryError 的异常交接，预先登记原生 owner 并保留未确认资源；16 项纯测试和独立精确差异复核通过。该版本仍须实际完整回归，不能把前一版本真实正常路径成功直接重绑过来。
- 最终私有父启动器第一次执行在导入 Worker 时失败，耗时约 0.63 秒，发生在任何子进程创建前；完整 suite、ownership fixture、8 次只读临时 ACL query 和原三案例 golden 均未运行。保留失败与全部 34 源／19 测试前后不变证据；逻辑 launch_attempts=1 不冒称实际创建或测试执行。后续仅最小修复可信导入路径，先作零子进程预检，再独立记录剩余验收。

### 当前源码的最终后台与数学来源绑定

- 修正私有父启动器可信导入路径并完成零子进程预检后，完整 suite 实际仅运行 1 次：发现／运行 234 项，233 项执行通过、1 项既有 Windows 平台条件跳过，0 failure、0 error。两条确切 ownership fixture 分别约 0.148 秒、0.128 秒，原退出与归属要求未删改。
- 8 次 icacls 均只查询本次新临时夹具路径，显式固定 System32 工具身份，不修改 ACL；native CreateProcessW 门禁记录 22 次调用，阻断事件为 0。父、suite 与 golden 的实际入口均为可信 APP cwd、审计 CPython 3.15.0 和 -I -B；既有固定 Python fixture 缺少部分 flags 的情况原样保留并单独记录，不宣称所有后代均使用隔离参数。
- 仅完整 suite 成功后，原三例 golden 实际运行 1 次、无 render；matrix 仍按 1e-9、weight 仍按 1e-10。三例最大 matrix 误差分别为 1.1368683772161603e-13、0、5.684341886080802e-14，weight 分别为 0、0、1.1102230246251565e-16，均通过原 checker。这是既有矩阵缓存的数学复现，不是 fresh 媒体测量或感知改善。
- 含首次启动器失败和零子进程预检，累计执行约 26.07 秒，小于原 180 秒预算；两次监督均确认原进程 HANDLE 结束、实际 Job 为零、管道结束和句柄关闭，无 timeout／forced cleanup。完整 34 源文件与 19 测试文件前后不变，历史失败证据不回填。
- 从该次真实证据生成全新的 [数学来源摘要](worker_math_golden_summary_20261019_16fb594d2e694096b442832ebf6c66cb.json)，摘要 SHA256 为 87544426b92b5459c6e2aa26c847a3dbff5012e3f1e0e8de645a15850b573344，既有 CI validator 通过。公开 34 源清单遵照既有末尾 LF 协议，摘要为 cb23c2b70e8080504a9072152a79092e750477d943bf4d735955d6018d1acc0c；私有无末尾 LF 的摘要另行计算，不混用。布局转换另有 16 项纯测试通过，转换过程未重跑 suite／golden。
- 当前后台来源绑定已收口，但真实 GF 可用性仍 unverified、自动 CTB 为 0，最大化和同包真实 GUI 尚未完成。新摘要不升级这些层级的结论，也不代表新发行包已生成。

### 已发布源码与首次新云构建

- 已按获批范围仅对 main 执行固定旧提交保护的 force-with-lease：22 条规范重写历史加 4 条实现提交，共 26 条，GitHub 回读为 0f1f86cd0328ba0f350e533093575775cf9a3723。原历史 bundle 摘要在推送前重新核对，原工作区未改，未创建 Release、标签或 Marketplace 发布。
- 唯一新完整构建 39216128663／attempt 1 的首次执行真实失败于 Flutter bootstrap 前置契约，官方 artifact 数为 0；UI、VS/SDK 更新及生产编译尚未执行。不是新包已交付，也不能以旧 0.1 包代替。
- 相关修复保留 Worker 3.15／创建时 Job 守卫，改为 Full／UI 交接 fresh 受管解释器，并固定有限 BAT 桥及私有 COMSPEC；窗口专项诊断保留预装、零下载，契约不满足明确阻塞。独立复核发现并修复空 leader snapshot 漏掉创建期 owner 的清理问题，完整 quiescence 与未确认引用保留均已接线，独立精确复核收口。
- 初版相关测试分为 156 项纯 Python／static 及 3 项固定 PowerShell 的隔离数据解析，均实际通过；此前长 TEMP 和禁止子进程导致的 159 项失败批保留。随后 COMSPEC 及 owner 清理各自保留红绿并通过对应 88／92 项 CI helper 回归，不把分批结果说成一次全套运行。
- Main 另实测自写 ASCII BAT 的 bootstrap/version 两例，固定系统 Cmd、参数及 child COMSPEC 均正确，传入环境不变；原进程对象 signaled、实际 Job 归零、终止计数为 0，约 0.228 秒。测试只执行自有回显脚本，不是 Flutter SDK、真实产品或云构建验收；空 Job 仍遵循既有 TerminateJobObject 策略，未伪称从未调用该 API。私有入口的一字摘要转录错误在零子进程预检被拦截，按既有最终 manifest 核实后纠正，原失败与源码保留。

### UI guard 失败与测试夹具的独立跟进

- 上述 CI 运行时／BAT／清理修复已普通追加为第 27 条提交，远端回读为 1e1fa0e6c4c2e7b7eadc33b914f749fc7e0ac4b7，没有再次改写历史。随后唯一 UI-only 检查 39225218101／attempt 1 真实失败于 CI guard 测试；尚未进入 fresh 运行时交接、Flutter SDK、UI 检查或打包。这次不是旧 3.15 契约错误重现，也没有新 Windows 包。
- 失败批中 provisioning 13 项、assets 12 项、build helper 24 项通过；CI helper 92 项出现 4 failure／11 error。正向临时夹具路径被未改的有限 BAT 路径校验拒绝，后续 mock 断言连锁失败；原日志没有实际路径，不猜具体拼写或字符。
- 仅修改测试文件，优先使用已存在且规范化的 RUNNER_TEMP，再对新夹具根 resolve(strict=True) 并实际检查有限语法。新增回归证明 raw≠canonical 时正向 SDK／Cmd 使用 canonical，诊断仅固定布尔和长度；原负例、生产路径守卫、window-only 零下载语义、Worker 及数学摘要保持不变。
- 真实红测 1 项失败、绿测 1 项通过，随后 CI helper 完整 93/93 通过，0 skip、0 实际子进程，新增测试共约 2.239 秒。旧失败和证据保留；这些结果不是实际 Flutter、云端成功、真实 GUI 或产品验收。新源码的云端结果另行记录。
- 随后新提交 1b5419076f819b3c7a11a27e9bbd1922f29fbbac 的唯一 UI-only 检查 39228160625／attempt 1 实际成功。官方 run/job API 确认 CI guard、fresh 运行时交接、固定 Flutter 身份和 UI 分析／测试步骤通过；没有以本地纯测试代替该结果。完整构建、Worker 冻结、打包和上传按 UI-only 设计 skipped，artifact 为 0，不是新 Windows 包或真实窗口验收。

### 2026-10-19 后续：7082 完整构建与同包数据核对

以下为同日更晚阶段的新记录；上述失败及当时的“未执行／未生成／未验收”结论不改写，也不以新结果回填旧 run。

- [Full 39233475590](https://github.com/Matce-Cafe/ChaSteady/actions/runs/39233475590)／attempt 1 实际 completed／success，CI 构建源码为 `7082e0676510db4e0251e59892f9a901bbfdaec3`。唯一 artifact 为 `12180437313`，名称为 `ChaSteady-0.2.0+2-Windows-x64-39233475590-1`；不是旧失败 run 的 retry，也不是先前 artifact 为 0 的 UI-only 专项。
- 产品版本为 `0.2.0+2`；主程序的 PE 数值 FileVersion／ProductVersion 均为 `0.2.0.2`，静态读取的两个版本字符串均为 `0.2.0+2`。artifact 内应用 ZIP `ChaSteady-Windows-x64.zip` 为 `157127435 B`，SHA-256 为 `46c09c6fa7e96a192a9f443e71b971d9681a2129e6236266b9e46acbf9f97221`；该摘要不指外层 GitHub 下载传输容器。
- 包内 1228 个文件的安全路径、CRC、manifest 清单与逐文件摘要及来源绑定数据审计通过；受控提取后整树逐文件摘要再次一致。独立测试副本受控提取保留 `ChaSteady/` 前缀，1228 个文件合计 `383881616 B`；另行本地交付应用 ZIP 及清单／摘要。App／Worker 字节身份另经独立复核，封存源码四文档及其他源文件未因此修改。没有启动应用、Worker 或 GUI，没有创建运行 profile；文件数据检查不代替同包运行验收。
- fresh 签名补证仅针对本机当前这一个包内 Python DLL，结果为 `Valid`；manifest 源记录及审计中的 source status 仍为 `null`，没有回填。该结果不是主程序／整包已签名或安全、运行、法律认证；主程序／整包仍未签名、未获法律分发认证，没有创建 GitHub Release／Marketplace 发布。
- 同包真实 GUI、最大化、拖入、预览和退出仍未完成验收。CTB 自动导出仍为 0，GF 的生产身份／模板管理仍阻塞或 unverified，strict 全长 fresh V9 仍未通过；历史 GF 完整导出和私有 Win32 点击成功不升级为这些层级已通过。私有三案例 golden 未上传 CI，本轮数据审计／提取也没有重跑它们。
- 此处是构建后的文档跟进；未来文档提交不等于该 run 的 `7082` 构建源码，原包内文档、manifest、BUILD_STATUS 和旧失败记录保持原样。没有新增同包 GUI 或自动 CTB／GF→V9 成功声明。

本轮后续新报告继续区分源码／unit、真实 GUI、真实引擎、媒体完整性、内容对应和感知范围；没有实际执行的层级不写“通过”。
