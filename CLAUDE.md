# CLAUDE.md — ChaSteady

## 项目定位与事实边界

ChaSteady 是面向 Windows 的本地视频增稳工作台，使用 Flutter／Material 3 桌面界面、自包含 Python Worker，并保留本机 Web 界面。原创代码为 MIT；第三方依赖、字体和外部媒体软件保留各自许可。

当前正在实施 0.2.0 迭代。界面、单原片编排与算法实验分别验收，不得把构建成功、模拟测试或人工续跑写成自动增稳全流程已完成。

- CTB 自动导出目前为 0；没有已验证的合法无人值守执行器。标准 UIA／MSAA root-only 不是导出能力。
- GF 完整 C7037 自动导出及独立完整帧数／PTS／AV 解码已有真实成功，但不能据此认证全源逐帧内容对应或生产集成已经完成。
- 现有 C7037 全长候选仍是 CTB baseline 加三段 V9／needs_review，不是严格全片 fresh V9。
- 原始数据、历史失败、旧成片和旧验收不得覆盖或回填。

## 源码与运行结构

- ui/lib/：Flutter 界面、平台适配和本地化。
- ui/windows/runner/：原创 Win32 窗口、Worker 监督、原生媒体与私有通信接线。
- worker/cha_stabilizer/：请求校验、队列、作业存储、媒体检查、外部引擎及刚性增稳。
- worker/tests/、ui/test/、tools/：后端、界面、冻结及构建回归。
- docs/：验证范围、便携使用及构建说明。
- private/、dist/：本机工作资料及产物，不等于可公开提交内容。

应用源码目录与素材目录不是 Git 仓库，不初始化 Git。公开源码操作仅在已确认的独立发布 clone 中进行。发布始终使用显式 source-only 白名单，不复制项目整根或整个 private。

## 稳像约束

- 要求无裁切，允许黑边；保留当前 CTB 输入矩形不等于恢复上游已丢失的原片 FOV。
- V9 使用 CTB 像素，GF 只提供同时间全局运动参考，不混 GF RGB。
- 不使用局部 mesh、逐帧 scale、动态裁切、插帧或冻结／重复视频帧来制造稳定。
- 自动 RAW 分类保持禁用；不得将 C7037 的人工窗口推广为通用自动判断。
- 新 CTB／GF 产物不得套用旧轨迹。历史复现、人工导入、新测量及未处理基线必须区分来源。
- 缺测、时间线或配准门禁失败即保留诊断；不能 identity 填洞、放阈值、删插帧或换 golden 凑通过。
- 不把观看预览冒称原生 4K10-bit 母版、原片完整视场或感知效果认证。

## 进程、路径与用户数据安全

- 桌面拥有 Worker 生命周期；关闭沿用共享确认、媒体租约释放、shutdown、stdout EOF 且自有进程结束的链路。会话失败、CloseJob 或 Stop 返回不证明资源终态；终态清账必须绑定同代次的原始自有进程对象并确认其已 signaled，强制结束仍不能登记为正常退出。
- 只操作本次 own PID、创建时间、映像、HWND 和 Job；不按程序名终止进程，不接管用户现有窗口。
- 普通窗口命令不得直接销毁应用或终止 Worker；不绕 Sony 登录、激活、EULA 或 entitlement。
- 子进程使用参数数组和 shell:false 等价方式，不把路径拼进 shell，不执行拖入的快捷方式或程序。
- Windows 媒体子进程必须在创建时绑定自有 Job 并挂起启动，确认原 process／thread HANDLE、实际归属和登记／取消状态后才 Resume；不得先运行后纳管或在赋 Job 失败时降级放跑。取消或自然 discard 的收尾未确认必须明确报错并保留 owner，不能先丢句柄再吞错，不能把关闭请求当成清理完成。
- 下载、解包、自产脚本各用独立目录；下载／解包目标必须是新空目录。读取不可信数据的 Python 使用 -I，不从媒体、下载或解包目录启动解释器。
- 默认用户数据根不是只读空间；启动 JobStore 可能修改 queued／running 记录。不同解压目录和 LOCALAPPDATA 环境变量不是隔离证明。
- 本轮新增 profile 接线必须在启动 Worker 前完成严格校验，无效不得退回生产根；不得通过 Dart／HTTP 任意切换数据根。
- 不上传媒体、缓存、profiles、凭据或原始本机报告到公共仓库、CI 或外部处理服务；公开验证信息只含审查过的摘要。
- 严格 TLS，不改全局 Python／Git／PATH、代理／DNS／信任库，不 force 安装、清 PendingFileRenameOperations 或自动重启。
- 不截图；不调用 browser.close() 或 page.close()。

## 界面与测试

- FlClash 仅作响应式导航和交互参考，不复制 GPL 源码、logo、资源或具体实现。
- 新增文案使用中英本地化；语言保存不依赖工具路径。原生窗口能力与受管退出能力分开。
- 导航形态改变不得丢失草稿或选中状态。任务面板共享控制器和唯一轮询器，避免隐藏页面重复持有原生播放器或租约。
- picker、手输和拖入经过相同的源变更／失效／Worker 验收链。Web 不得用 fakepath 假装取得本机绝对路径。
- Widget 点击不能直接调用 onPressed／onChanged 代替命中和滚动；原生最大化必须包含真实鼠标路径，真实拖入必须覆盖 OLE，而非只调 handler。
- 模拟引擎、真实 Worker、真实 GUI 和完整媒体流程分开记录。没有实际运行的测试不得写“通过”；强关后的清理不能登记为正常退出成功。

## 数学绑定与构建

worker/cha_stabilizer 下 Python 源及冻结／回归／入口工具属于数学来源绑定；新增模块同样会改变清单，不能因为“只改接口”便继续沿用旧摘要。

- 变动后实际重跑后端测试和原三个 golden 案例，生成新 sidecar／freeze 证据。
- matrix 容差 1e-9、weight 容差 1e-10 保持不变，不修改旧 golden 或手改旧报告 hash。
- CI 消费本地数学摘要不等于 CI 重跑了私有 golden。
- 原生 stdio protocol 1、ready 精确字段、请求白名单与 capability 隔离必须保持契约，不随意加字段。
- 产品版本以 ui/pubspec.yaml 为唯一来源；Windows PE、About、清单和包名应一致。Worker 组件版、协议版和 Python 运行时版另行标注。
- 运行／测试命令以实际工具链和脚本参数为准；不假装本机已有 Flutter／MSVC，不用编译替代 GUI 验收。
- Windows CI 的 PATH Python 仅用于 bootstrap；Full／UI 的 owned 子进程阶段必须交接该次已审 fresh CPython 3.15.0，并绑定 receipt、EXE 与路径配置。窗口专项诊断保留零下载，当前预装解释器不匹配则明确阻塞，不自动放宽 Worker 私有签名或改用无 Job 启动。Flutter BAT 仅通过固定系统入口、有限无歧义参数及私有 child 环境启动；调用失败也须按完整 registry 清账并保留未确认 owner。

## Git 提交规范

严格参考相邻 Matce 项目，提交信息格式为：

```
【页面标题】功能标题 / 更改概述

- 更改项 1
- 更改项 2
```

- 【】内为页面名称，非单一页面改动写【框架】，多页面用顿号分隔。
- 功能标题可省略；标题后必须空一行，每个说明项以 - 开头。
- 中文与英文／数字之间留空格，新增或改动代码注释使用中文，保留第三方许可证原文。
- 向用户展示提交信息时使用代码块，便于复制。
- 根据每条真实 diff 书写，不虚构历史操作、测试或发布事实。
- commit、push 和历史重写须有相应用户授权。此次用户已明确要求全部 22 条历史重写，包括带签名 root：保留旧历史与签名私有备份，新 root 不伪造或沿用旧签名。
- 历史重写先备份 refs／bundle／old→new 映射，核对逐条 tree 不变；仅对已确认远端旧 SHA 使用 --force-with-lease，不裸 force，不覆盖并行新提交，不动其他仓库／分支／tags。
- 旧 Actions、ZIP、manifest 和验收继续绑定旧 SHA，不按历史映射篡改它们。

## 文档与版本同步

每次修改功能、配置或架构，同步维护本文件及相关 README、CHANGELOG、验证与使用说明。

CHANGELOG 层级严格采用：# 版本号 → ## 日期 → ### 模块 → #### 新增／修复／变更。日期使用 YYYY-MM-DD。未发布／未验收内容明确标注，不能补造历史发布日期或把未来计划写成已完成。

不自行创建 GitHub Release、Marketplace 发布、签名或修改 billing／仓库权限。
