# UI 自动还原 Agent

**版本：1.1.0 冻结发版（2026-10-17）**

从两类输入生成可编辑设计产物：

- **产品输入族**：DOM、image（用户截图或页面截图）
- **产品输出目标**：Figma、Axure
- **当前优先路线**：`DOM → Figma`、`image → Figma`（均限已声明证据范围）
- **当前产品阶段**：A-011 Axure current scope 通过
- **下一步任务**：等待选择 Axure 能力扩展或生产准入
- **后续路线**：A-006/A-008 保持历史失败；A-010 泛化声明仅限冻结三样本

Grounding、CV 和 hybrid 是 image 输入下的实现策略，不是与 DOM
并列的产品路线。当前 `auto/dom/grounding/cv` 参数只用于控制实现层选择。
image → Figma 已完成首个 owned-screenshot current-scope MVP：Grounding 默认、
真实 Figma 写入/回读/导出、critical text、原生文本编辑和 reference-only 图片
显示替换均有证据。该结论不表示任意截图或生产环境已通过。

本版为冻结源码版本：`tests/`、旧 `docs/`、历史 `HANDOFF_*.md`、`DESIGN.md`、`PLAN.md` 已移出项目并归档。回归结果、修复结论与剩余风险见 `HANDOFF_2026-10-17_release.md`。

## 核心能力

| 能力 | 状态 | 说明 |
|---|---|---|
| DOM 直出 | 当前范围可用 | Playwright 抓真实 DOM + computed style，不调用视觉模型 |
| SVG 输出 | 可用 | 无外部设计工具依赖，适合离线验收 |
| Figma 输出 | DOM 路线当前范围可用 | 需要先启动 bridge server 并运行 Figma 开发插件 |
| Axure RP 8 输出 | DOM/image 路线 current-scope 通过 | 从零生成确定性 `.rp`；真实 open/reopen publish 与独立 HTML 验收仅限 DQ-R02 和 IMG-MVP-01 |
| 多输入多页 | Axure 实现可用 | 重复 `--url` / `--image`；当前仅 `--tool axure` 支持 |
| VLM grounding | image 当前范围可用 | 截图/URL 语义结构候选，需 `VISION_API_KEY`；MVP 使用确定性像素样式层 |
| CV + OmniParser | image 兜底策略 | 需本地 OmniParser/OCR 依赖；仅在 Grounding 服务或配置不可用时进入 |
| 即时设计 / 墨刀 | 桩实现 | 适配器存在，但尚未接入正式 API |

## 环境要求

- Python 3.10+
- Windows 10/11（本版在 Windows + PowerShell 实测）
- Figma 桌面端或浏览器版（仅 Figma 输出需要）
- Axure RP 8（仅 Axure 输出/打开 `.rp` 需要）

本机验收环境：

```text
Python: C:\Users\lzq\.conda\envs\omni\python.exe
Conda env: omni
```

## 安装

在项目根目录执行：

```powershell
conda create -n omni python=3.11 -y
conda activate omni
pip install -r requirements.txt
python -m playwright install chromium
```

可选 OCR：

```powershell
pip install -r requirements-easyocr.txt
```

Tesseract 是可选外部程序；只有旧流程或显式 OCR 场景需要。

## 配置

复制模板：

```powershell
Copy-Item .env.example .env
```

最小 DOM → SVG 配置可以不填任何模型密钥：

```env
PROTOTYPE_TOOL=svg
OUTPUT_DIR=./output
ROUTE=auto
PLAYWRIGHT_HEADLESS=true
PLAYWRIGHT_VIEWPORT_WIDTH=1440
PLAYWRIGHT_VIEWPORT_HEIGHT=900
```

VLM 路线需要视觉模型密钥：

```env
VISION_BASE_URL=https://www.acctoken.com/v1
VISION_API_KEY=your-key
VISION_MODEL=qwen3-vl-plus
TEXT_BASE_URL=https://www.acctoken.com/v1
TEXT_API_KEY=your-key
TEXT_MODEL=deepseek-v4-flash
```

关键变量：

| 变量 | 说明 |
|---|---|
| `PROTOTYPE_TOOL` | `svg` / `figma` / `jsdesign` / `mockingbot` / `axure` |
| `OUTPUT_DIR` | 中间产物与原型输出目录 |
| `ROUTE` | `auto` / `dom` / `grounding` / `cv` |
| `VISION_API_KEY` | `grounding` 必需；`cv` 兜底本身使用本地视觉/OCR 依赖 |
| `figma_bridge.config.json` | Figma bridge 监听、journal、超时、写节流、认证和 legacy 策略 |
| `PLAYWRIGHT_HEADLESS` | URL 采集是否无头 |
| `PLAYWRIGHT_STORAGE_STATE` | 复用登录态 JSON |
| `PLAYWRIGHT_USER_DATA_DIR` | 真实会话降级时优先复用的持久化浏览器用户目录 |
| `PLAYWRIGHT_HEADED_FALLBACK` | 无头被拦截时是否用有头 Chromium 重试，默认 `true` |
| `TEXT_ALIGN` | SVG 文本基线 ±1px 微调，默认开 |
| `SOM_BATCH_*` | 长页面 SoM → DesignSpec 分批生成参数 |

`.env`、`login_state.json`、`*_state.json`、`output/`、`uploads/` 均不应进入发布包。

Figma bridge 默认从项目根目录的 `figma_bridge.config.json` 读取全部设置。
环境变量仅在该文件的 `allow_env_overrides` 为 `true` 时允许覆盖。
文件内 `server.tls` / `client.tls` 可启用 `wss://`、自定义 CA 和双向 TLS；
默认保持本地 `ws://` 开发模式。
设置 `server.plugin_token` 后，插件 UI 保存的 plugin token 会通过首帧认证连接
`/plugin`；token 不放在 URL 中。
`server.plugin_token_recheck_seconds` 控制 active token 轮换/撤销检查。
bridge secret 可使用 `env:VAR` 或 `file:path` 引用；生产可开启
`security.require_secret_references` 与 `security.require_secure_file_permissions`。
原子轮换示例：

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe `
  scripts\rotate_figma_bridge_config.py `
  --config figma_bridge.config.json `
  --plugin-token-file .\secrets\plugin-token.txt
```

## 产品路线与实现策略

产品规划只使用“输入族 × 输出目标”：

| 输入族 | 输出目标 | 状态 |
|---|---|---|
| DOM | Figma | 当前优先路线；仅限已声明证据范围 |
| image | Figma | current-scope MVP；一个 owned 截图和真实 Figma 样本已通过 |
| DOM | Axure | `pass-current-scope`（DQ-R02；单页真实 `.rp`、reopen publish 与独立验收通过） |
| image | Axure | `pass-current-scope`（IMG-MVP-01；真实 `.rp`、reopen publish 与独立验收通过） |

Axure 共享边界与 DOM 路线 current-scope 已通过。DQ-R02 生成了 647,034 字节
的确定性 `.rp`，Axure RP 8.0.0.3400 打开、重新打开并发布成功；页面为
`A002 DQ-R02 DOM Axure`，469 个 widget，54 个创建时图片载荷，独立发布验收
通过 3/3 关键文本、30/30 去重图片哈希和 99.3772% within-30 视觉门槛。

这仍是单一样本结论。Axure 不支持 runtime image replacement、原生
letter-spacing、Auto Layout、clip 和交互重建；44 个显示图是 reference-only
裁片，10 个图标是 generated approximation，均不冒充原图。Figma 验收不能转为
Axure 结论。证据见
`docs/v2_mentor/AXURE_DOM_ACCEPTANCE_2026-10-25.md`。

Image → Axure 也已复用同一 image MVP 与 shared IR 完成 current scope：
IMG-MVP-01 生成 58,296 字节确定性 `.rp`，22 个 widget，14/14 critical text，
1/1 reference-only 图片载荷，Axure published within-30 `96.5720%`。Axure
不支持 runtime replacement，产物只有 creation-time ImageBox。证据见
`docs/v2_mentor/AXURE_IMAGE_ACCEPTANCE_2026-10-25.md`。

A-005 已将覆盖扩展到 DQ-R01、DQ-R03 和 AX-IMG-H01。冻结输入首先暴露了
DQ-R01 IR/asset 绑定、DQ-R03 布局和 AX-IMG-H01 OCR/asset 缺陷；TDD 修复后
三个样本在阈值不变的情况下均通过，但同一 holdout 参与了修复，因此结果为
`partial-post-holdout-tuning`，不能作为干净泛化结论。见
`docs/v2_mentor/AXURE_HOLDOUT_ACCEPTANCE_2026-10-25.md`。

A-006 使用全新的 AX6-DOM-TEXTFLOW、AX6-DOM-FONTFALLBACK 和
AX6-IMG-OVERLAY。Font fallback 与 overlay 样本通过；mixed text flow 的发布
文本/资产/视觉也通过，但 `.rp` 中多出一个未投影的空 `360x96` Rect，导致
page/object mapping 硬门槛失败。总体结果为 `fail-unseen-holdout`，本轮未修复。
见 `docs/v2_mentor/AXURE_HOLDOUT_V2_ACCEPTANCE_2026-10-25.md`。

A-007 已确认该 Rect 是样式文本的派生背景层，不是幽灵或外来模板对象。
比较器现在只对已匹配 Text 的源外框做一对一辅助层归因；A-007 重新生成的
`.rp` 与 A-006 字节哈希完全一致，因此没有视觉变化或重新发布。由于 A-006
仍是修复前的干净失败，泛化结论必须等待 A-008 的新 untouched holdout。见
`docs/v2_mentor/AXURE_EXTRA_RECT_ATTRIBUTION_2026-10-25.md`。

A-008 使用全新的 iframe、partial-asset 和 320px mobile 样本，结果为
`fail-unseen-holdout`。Mobile 样本通过；iframe 样本的三个 `.rp`/发布/
重开门禁通过，但参考图审查发现 iframe 正文没有可见呈现，标题与 iframe
文本重叠，自动化 label-only critical text 没有捕获这一点。Partial-asset
输出与参考图 100% 一致且 2/2 图片哈希匹配，但冻结 manifest 只预期 1 个
资产，因此成为评估契约冲突而非干净 product fail。A-009 需先修复上游
iframe 子坐标和可见区域验收，再做新的 holdout。见
`docs/v2_mentor/AXURE_FRESH_HOLDOUT_A008_2026-10-25.md`。

A-009 已完成当前范围修复。iframe 坐标代码本身没有新改动；采集器的现有
回归已把 `Accessible iframe content` 放在 `(18,133)`，A-008 使用的是历史
DesignSpec `(16,37)`。A-009 从当前采集器重新生成输入，并为 Axure 验收新增
`critical_regions` ink 门禁：旧 A-008 渲染现在会被正确拒绝，repaired 渲染
在 iframe 内容区域保持 `7.01923%` ink。Partial-asset 契约更正为 2 个声明/
显示资产，且缺失原图 provenance 仍单独保留。两套 repaired 产物均确定性、
conformance、发布/重开和验收通过。见
`docs/v2_mentor/AXURE_A009_RENDERED_REGION_REPAIR_2026-10-25.md`。

A-010 使用全新的 assets、transparent-crop 和 nested-iframe 三组样本，结果为
`pass-unseen-holdout`。三份 `.rp` 均确定性且对象图无 mismatch；critical text、
资产哈希、visible critical regions、within-30 和参考图审查全部通过；六次
Axure 发布均为 `RESULT=OK`，重开后的页面 HTML 一致。该结论只覆盖冻结
三样本，不代表任意 DOM、Auto Layout、runtime replacement 或生产环境已通过。
见 `docs/v2_mentor/AXURE_FRESH_HOLDOUT_A010_2026-10-25.md`。

A-011 已完成当前范围 exit review，结论为 `pass-current-scope`：受控
`DOM -> Axure` 与命名 image 样本路线关闭，独立验收、确定性和 open/reopen
publish 均有证据。A-006/A-008 历史失败与 A-007/A-009 remediation 分开保留。
任意 DOM/image、Auto Layout、runtime replacement、clip、原生字距、交互、
save-back 和生产准入仍明确不声明。下一步需要显式选择能力扩展或生产准入。
见 `docs/v2_mentor/AXURE_CURRENT_SCOPE_EXIT_REVIEW_2026-10-25.md`。

上述路线内的结构解析策略：

| 策略 | 输入 | 角色 |
|---|---|---|
| `dom` | URL | DOM 输入的可信结构来源 |
| `grounding` | URL / image | image 输入的默认解析策略 |
| `cv` | URL / image | 仅在 Grounding VLM 不可用时使用的兜底 |
| hybrid | URL / image | 仅限基准实验；证明更优前不得成为默认 |

`--route` 和 `ROUTE` 是上述策略的实现层开关，不是产品路线命名。
当前 image `auto` 默认 Grounding。仅 Grounding 服务不可用或视觉模型配置缺失时
才进入 CV；Grounding 返回非法 JSON 或普通下游错误不会静默切换。

实现层说明：

- `dom` 只接受 URL。
- 截图输入使用 `auto` 时，如果没有 `VISION_API_KEY`，会尝试本地 CV 兜底；
  缺少 OmniParser/OCR 依赖时失败关闭。
- image 当前范围使用确定性、固定坐标、像素采样的呈现层，不再依赖第二次
  VLM 自由改写 bbox/style。
- URL 输入先做页面状态判定：
  - `content`：目标内容可访问。当前实现层候选链为 `dom → grounding → cv`，
    但产品层应表达为“DOM 优先；DOM 不可用或显式请求时进入 image 策略”。
  - `soft_block`：无头浏览器被重定向/反爬/验证码挡住，但真实浏览器会话仍可能看到内容。依次尝试 `PLAYWRIGHT_USER_DATA_DIR` 持久化会话、`PLAYWRIGHT_STORAGE_STATE`、有头 Chromium；拿到内容后转为页面截图输入。
  - `hard_login`：目标页面本身需要登录，截图也只能看到登录页。停止并提示用户先导出登录态，或手动上传目标页截图。
- 显式 `--route dom` 不会静默降级；被拦截时直接报错，并提示改用 `--route auto`。
- 验证码/人机验证不会自动破解；视为需要用户处理或手动上传截图的情况。

## Image → Figma MVP

可复现入口：

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe scripts/image_figma_mvp.py `
  --image tests/fixtures/image_mvp/simple_dashboard_v1.png `
  --truth tests/fixtures/image_mvp/simple_dashboard_v1.truth.json `
  --out output/_image_figma_mvp_2026-10-25_next `
  --prepare-only

C:\Users\lzq\.conda\envs\omni\python.exe scripts/image_figma_mvp.py `
  --image tests/fixtures/image_mvp/simple_dashboard_v1.png `
  --truth tests/fixtures/image_mvp/simple_dashboard_v1.truth.json `
  --out output/_image_figma_mvp_2026-10-25_next `
  --reuse-prepared `
  --origin-x 24000 `
  --origin-y 0
```

当前范围结果：

- Frame `77:4851`，`1200×800`；
- critical text `14/14`；
- native text edit/restore pass；
- reference-only image display replace/restore pass；
- Figma export within-30 `96.533125%`，冻结产品门槛 `90%`；
- 图片原图身份、原始字体、DPR/viewport、hidden regions 和 adaptive flow
  均不声称已验证。

证据：

- `docs/v2_mentor/IMAGE_FIGMA_MVP_ACCEPTANCE_2026-10-25.md`
- `docs/v2_mentor/IMAGE_FIGMA_MVP_LEDGER_2026-10-25.md`
- `output/_image_figma_mvp_2026-10-25_r4/acceptance.json`

## DOM 结构诊断

每次 URL 采集都会额外写 `00_dom_diagnostics.json`，用来区分两类问题：

| 字段 | 含义 |
|---|---|
| `capture_gaps.shadow` | 页面里有、但快照里没有的开放 Shadow DOM 节点数；当前采集会递归进入 open shadow root，非 0 时说明还有采集缺口 |
| `unsupported.grid` | 已进入快照、但 `layout_infer` 仍会 bail 的 Grid 容器数 |
| `unsupported.flex_wrap` | 已进入快照、但仍会 bail 的 `flex-wrap` 容器数 |
| `unsupported.gradient` | 使用 CSS 渐变的可见元素数（尚未进入 DesignSpec） |
| `unsupported.pseudo` | `::before` / `::after` 有可见装饰的元素数（目前只参与图标判定） |

`closed` 模式的 Shadow Root 对页面脚本不可见，无法采集；该限制会记录在诊断的
`notes.closed_shadow_roots_observable` 中。诊断只读页面，不改变截图或渲染结果。

## 快速开始

以下命令都从项目根目录执行：

```powershell
cd D:\LLM-Data\Figma_auto_agent
$env:PYTHONPATH='.'
$env:PYTHONIOENCODING='utf-8'
```

### 1. DOM → SVG（推荐先跑）

```powershell
python -m src.main `
  --url "https://www.dushu.com/" `
  --route dom `
  --tool svg `
  --output-dir output/_svg_dom
```

输出：

```text
output/_svg_dom/
├── 00_dom.json
├── 00_dom_diagnostics.json
├── 00_screenshot.png
├── 10_pagegraph.json
├── 11_som.json
├── 11_som.png
├── 12_design.json
├── prototype.svg
├── render.png            # 文本基线微调时可能生成
└── manifest.json
```

### 2. DOM → Axure RP 8

```powershell
python -m src.main `
  --url "https://www.dushu.com/" `
  --route dom `
  --tool axure `
  --output-dir output/_axure_dom
```

输出：

```text
output/_axure_dom/prototype.rp
```

用 Axure RP 8 打开即可。不要把 `assets/axure/rp8/` 删除，Axure 写入层依赖其中的文档模板。

A-002 的可复现证据入口：

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe scripts/axure_dom_output.py `
  --design output/_dom_figma_generated_icons_2026-10-25_r1/design.json `
  --ir output/_axure_shared_ir_2026-10-25_r1/DQ-R02-figma.ir.json `
  --out output/_axure_dom_acceptance_next `
  --source-kind dom `
  --page-name "A002 DQ-R02 DOM Axure" `
  --generate-twice
```

发布后用 `scripts/axure_acceptance.py` 读取 Axure HTML、原截图与 `.rp`
对象图，独立生成 `acceptance.json`。完整命令和当前限制见
`docs/v2_mentor/AXURE_DOM_ACCEPTANCE_2026-10-25.md`。

### Image → Axure RP 8

复用 image MVP 已准备的 DesignSpec，不在 Axure 路线重复图片理解：

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe scripts/image_axure_mvp.py `
  --design output/_image_figma_mvp_2026-10-25_r4/figma_design.json `
  --ir output/_axure_shared_ir_2026-10-25_r1/IMG-MVP-01-figma.ir.json `
  --out output/_axure_image_acceptance_next `
  --page-name "A003 IMG-MVP-01 Image Axure" `
  --generate-twice
```

Axure 的图片能力只到 creation-time `ImageBox`。不允许把 Figma runtime image
replacement 结果转移到 Axure。完整发布和 14 项关键文本验收命令见
`docs/v2_mentor/AXURE_IMAGE_ACCEPTANCE_2026-10-25.md`。

多输入多页：

```powershell
python -m src.main `
  --url "https://example.com/" `
  --url "https://example.com/about" `
  --route dom `
  --tool axure `
  --output-dir output/_axure_multi
```

每个输入生成一页：

```text
output/_axure_multi/
├── page_01_<name>/
├── page_02_<name>/
├── 12_design.json       # {"pages": [...]}
├── prototype.rp
└── manifest.json
```

当前只有 Axure 适配器声明 `supports_pages = True`；SVG / Figma 多输入会明确报错。

### 路线对比环境

跨路线比较必须冻结同一个 CSS viewport 和 DPR。不要用输入截图的像素尺寸
隐式覆盖 URL 采集断点；需要把截图作为参考时，显式传入 `--reference-image`，
其物理尺寸除以 DPR 后的 CSS 宽度必须与 `--viewport` 一致。

```powershell
python scripts/compare_routes.py `
  --url "https://example.com/" `
  --routes dom,grounding,cv `
  --viewport 1440x900 `
  --device-scale-factor 1 `
  --base-out output/_compare_1440
```

已有产物可先做 fail-closed 校验，不重新采集：

```powershell
python scripts/compare_routes.py `
  --check-only `
  --routes dom,grounding,cv `
  --viewport 1440x900 `
  --device-scale-factor 1 `
  --base-out output/_compare_1440
```

比较结果写入 `comparison_environment.json`。viewport、DPR、截图物理尺寸、
设计画布或参考图断点不一致时，命令返回 `2`，并且不会生成 `summary.json`。
纯图片输入没有浏览器 viewport，文件会明确记录
`not-applicable-image-input`，不会从图片宽度反推断点。

### 3. DOM → Figma

Figma 不是离线文件输出，必须保持桥接服务和插件运行。

终端 A：

```powershell
python -m src.app.services.bridge_server
```

终端 B / Figma：

1. 打开 Figma 桌面端或浏览器版。
2. `Plugins` → `Development` → `Import plugin from manifest...`
3. 选择 `figma_bridge/manifest.json`。
4. 运行插件，面板显示“已连接到桥接服务器”。

然后执行：

```powershell
python -m src.main `
  --url "https://www.dushu.com/" `
  --route dom `
  --tool figma `
  --output-dir output/_figma_dom
```

常见错误：

```text
[WinError 10061] 由于目标计算机积极拒绝，无法连接。
```

表示 `bridge_server` 没启动、端口不是 `8765`，或插件没有连接。先确认终端 A 正在运行，再重跑。

### 4. 截图 → VLM / CV

```powershell
python -m src.main `
  --image "uploads/screenshot.png" `
  --route grounding `
  --tool svg `
  --output-dir output/_image_grounding
```

`grounding` 需要 `VISION_API_KEY`。`cv` 使用本地 OmniParser/OCR 依赖；
当前 image MVP 的确定性呈现层不需要第二次 VLM 调用。

CV 路线还需要本地 OmniParser：

```text
OmniParser/OmniParser-master/
├── omnitool/
├── util/
└── weights/
```

源码冻结包刻意不包含 `OmniParser/`（约 1.1GB 模型与仓库）。需要 CV 路线时，把官方 OmniParser 放到上述路径，并准备权重。

### 5. 交互式入口

```powershell
python -m src.main --interactive
```

向导依次选择输入来源、路线和输出工具。直接回车使用默认项。

### 6. 登录态页面

先导出登录态：

```powershell
python -m src.main `
  --url "https://example.com/protected" `
  --login-state login_state.json
```

再运行：

```powershell
python -m src.main `
  --url "https://example.com/protected" `
  --storage-state login_state.json `
  --route dom `
  --tool axure `
  --output-dir output/_protected
```

如果站点会拦截无头浏览器，但你的持久化浏览器会话能看到目标页，可改用：

```powershell
python -m src.main `
  --url "https://example.com/protected" `
  --user-data-dir "C:\path\to\playwright-profile" `
  --route auto `
  --tool figma `
  --output-dir output/_protected
```

`--route auto` 会在无头采集被拦截时自动切到真实会话并继续；`--no-headed-fallback` 可关闭“全新有头 Chromium”这一层兜底（仍会尝试持久化目录/登录态）。

## 输出说明

单输入（扁平输出）：

| 文件 | 内容 |
|---|---|
| `00_dom.json` | DOM 路线采集到的节点与 computed style |
| `00_dom_diagnostics.json` | 结构诊断：页面实际存在的 grid / flex-wrap / Shadow DOM / gradient / 伪元素数量，与真正进入快照的数量 |
| `00_screenshot.png` | Playwright 截图 |
| `00_page_state.json` | 页面状态判定：最终 URL、`content/soft_block/hard_login`、命中信号、每次尝试与降级来源 |
| `capture_attempts/` | 每次浏览器会话的截图与 DOM 留档（无头 / 持久化会话 / 有头兜底） |
| `10_pagegraph.json` | 归一化页面结构图 |
| `11_som.json` | Set-of-Mark 语义标注 |
| `11_som.png` | SoM 可视化 |
| `12_design.json` | 最终 DesignSpec |
| `prototype.svg` | SVG 输出 |
| `prototype.rp` | Axure RP 8 输出 |
| `manifest.json` | 版本、路线、工具、输入、耗时、元素计数、回退记录 |

多输入（Axure）：

- 根目录保存合并后的 `12_design.json`、`prototype.rp`、`manifest.json`
- 每个输入在 `page_NN_<name>/` 下保留独立中间产物，便于单页复核

## 架构

```text
CLI (src/main.py)
  │
  ├─ PreciseAgent
  │   ├─ capture_page()                  URL → DOM + 截图
  │   ├─ route_order()                   auto / dom / grounding / cv
  │   ├─ providers/                      DOM / VLM grounding / CV
  │   ├─ PageGraph                       归一化结构
  │   ├─ SoM                             语义标注
  │   ├─ DesignSpec                      可渲染设计 IR
  │   └─ RenderingController
  │       ├─ SVGMockAdapter
  │       ├─ FigmaBridgeAdapter          WebSocket → Figma Plugin
  │       └─ AxureRPAdapter              `.rp` 二进制写入
  │
  └─ ReconstructAgent                    旧截图检测/OCR/LLM 流程（兼容保留）
```

核心目录：

```text
src/
├── main.py                            CLI
├── app/agents/precise_agent.py        主流程编排
├── app/services/structure/            DOM 采集、路由、站点 profile
├── app/services/som/                  SoM 与直出设计
├── app/services/rendering/
│   ├── adapter_base.py                DesignSpec 渲染基类
│   ├── svg_adapter.py
│   ├── figma_adapter.py
│   ├── axure_adapter.py
│   └── axure/                         `.rp` 低层写入
├── app/services/bridge_server.py      Figma WebSocket 桥
└── app/services/llm/                  VLM / 文本模型
figma_bridge/                          Figma 开发插件
assets/axure/rp8/                      Axure 文档模板
container_pipeline/                    CV 路线依赖
samples/                               小型 DOM/截图样例
site_profiles/                         站点级采集阈值
scripts/                               运维、重放、Axure 调试脚本
```

## CLI 参数

| 参数 | 说明 |
|---|---|
| `--url URL` | 网页输入，可重复；重复时生成多页 |
| `--image PATH` | 截图输入，可重复；重复时生成多页 |
| `--route {auto,dom,grounding,cv}` | 实现层结构策略，不是产品路线 |
| `--tool {svg,figma,jsdesign,mockingbot,axure}` | 输出工具 |
| `--output-dir PATH` | 输出目录 |
| `--storage-state PATH` | 复用 Playwright 登录态 |
| `--user-data-dir PATH` | 真实会话降级时优先复用的持久化浏览器用户目录 |
| `--headed-fallback` / `--no-headed-fallback` | 无头被拦截时是否用有头 Chromium 重试（默认开） |
| `--login-state PATH` | 交互登录并导出登录态，不跑管线 |
| `--interactive` | 交互式向导 |
| `--pick-crops` | image 解析策略的手工像素框选，写 `manual_crops.json` |
| `--debug` | 输出调试日志 |
| `--fast` / `--enrich` | 已废弃，仅为旧脚本兼容保留 |

## 已知限制

- `jsdesign`、`mockingbot` 仍是桩实现，不要用于正式交付。
- image 输入策略依赖外部模型密钥；其中 CV 兜底还依赖本地 OmniParser 权重。
- Figma 输出要求 bridge server 和插件同时在线；桥接未启动会报 `WinError 10061`。
- 多输入多页当前只支持 Axure；SVG / Figma 会把多页输入明确拒绝。
- 反爬/验证码不会自动破解；真实会话仍看不到目标内容时，请手动上传截图或先处理登录。
- Axure 按钮标题已改为消费 `textBox` 偏移，解决“图标盖住文字”的主路径；多行按钮、无 `textBox` 的按钮仍会回退到 Axure 原生排版，极端紧盒可能仍有轻微压字，但不会再引入折行或撑宽控件。
- `TEXT_ALIGN` 只对 SVG 生效；Figma / Axure 有自己的文字落点，不套用 SVG 的 ±1px 位移。
- 站点 profile 是经验阈值，换站点/改版后应重跑 DOM 直出并复核像素指标。
- `scripts/axure_publish_html.ps1` 会结束本机所有 `AxureRP8` 进程并删除目标 Tag 目录；运行前先存盘，且不要在有未保存文档时使用。

## 发布与归档

- 当前版本：`1.1.0`
- 版本唯一来源：项目根 `VERSION`
- 冻结发版交接：`HANDOFF_2026-10-17_release.md`
- 2.0 R5 实验交接：`HANDOFF_2026-10-19_v2_r5.md`
- 1.0.1 及更早测试/文档归档：`D:\LLM-Data\Figma_auto_agent_release_archive\v1.0.1_2026-10-17`
- 源码发布包不包含：`.env`、登录态、`output/`、`uploads/`、`.git/`、`OmniParser/`、开发缓存

## v2 规格与实验归档

- 导师问答、优化计划与 R1–R5 实验状态：`docs/v2_mentor/`
- R3 未决实验清单：`docs/v2_mentor/ROUND_03_OPEN_ITEMS.md`
- R5 导师问答（已回答）：问题 `docs/v2_mentor/ROUND_05_QUESTIONS.md`；回答 `docs/v2_mentor/ROUND_05_ANSWERS_FORMATTED.md`（原始归档 `docs/v2_mentor/ROUND_05_ANSWERS_RAW.txt`）；未决实验 `docs/v2_mentor/ROUND_05_OPEN_ITEMS.md`
- R1–R4 当前范围审计：`docs/v2_mentor/R1_R4_CURRENT_SCOPE_AUDIT.md`
- `R1-EXP-01`（离线 true-flow 写计划）：`completed-for-current-scope`，结论见 `docs/v2_mentor/R1_EXP_01_TRUE_FLOW_CONTRACT.md`
- `R1-EXP-02`（URL 三态与真实会话降级回归）：`completed-for-current-scope`，结论见 `docs/v2_mentor/R1_EXP_02_SESSION_FALLBACK.md`
- `R2-EXP-01`（五个 authored DOM 容器的 flow 扰动）：`completed-for-current-scope`，结论见 `docs/v2_mentor/R2_EXP_01_DOM_FLOW_PERTURBATION.md`
- `R3-EXP-08`（OCR、低清、压缩与文本阈值）：`completed-for-current-scope`，结论见 `docs/v2_mentor/R3_EXP_08_TEXT_ACCEPTANCE.md`
- `R3-EXP-09`（裁片来源、替换能力与共享图成本）：`completed-for-current-scope`，结论见 `docs/v2_mentor/R3_EXP_09_ASSET_CONTRACT.md`
- `R3-EXP-10`（截图 flow 扰动与 DOM 冲突隔离）：`completed-for-current-scope`，结论见 `docs/v2_mentor/R3_EXP_10_FLOW_PERTURBATION.md`
- `R3-EXP-11`（四项验收样例集与评分校准）：`completed-for-current-scope`，结论见 `docs/v2_mentor/R3_EXP_11_ACCEPTANCE_CALIBRATION.md`
- `R3-EXP-12`（多状态参考冲突与权威版本）：`completed-for-current-scope`，结论见 `docs/v2_mentor/R3_EXP_12_REFERENCE_STATES.md`
- `R3-EXP-13`（跨渲染器文本度量与基线）：`completed-for-current-scope`，结论见 `docs/v2_mentor/R3_EXP_13_CROSS_RENDERER_TEXT.md`
- `R3-EXP-14`（静态截图基线估计）：`completed-for-current-scope`，结论见 `docs/v2_mentor/R3_EXP_14_STATIC_BASELINE.md`
- `R3-EXP-15`（失败 SVG 的离线栅格回退）：`completed-for-current-scope`，结论见 `docs/v2_mentor/R3_EXP_15_RASTER_FALLBACK.md`
- `R4-EXP-01`（逐字段融合合同与来源审计）：`completed-for-current-scope`，结论见 `docs/v2_mentor/R4_EXP_01_FUSION_CONTRACT.md`
- `R4-EXP-02`（真实 OCR/CV 候选与 `screenshot-candidate` 通道）：`completed-for-current-scope`，结论见 `docs/v2_mentor/R4_EXP_02_OCR_CANDIDATES.md`
- `R4-EXP-03`（真实滚动、懒加载与动画相位的状态门）：`completed-for-current-scope`，结论见 `docs/v2_mentor/R4_EXP_03_STATE_GATE.md`
- `R4-EXP-04`（只读、版本化的字段级 provenance IR 回放）：`completed-for-current-scope`，结论见 `docs/v2_mentor/R4_EXP_04_PROVENANCE_IR.md`
- `R4-EXP-05`（跨 DPR、缩放与字体的 bbox 容差标定）：`completed-for-current-scope`，结论见 `docs/v2_mentor/R4_EXP_05_BBOX_CALIBRATION.md`
- `R4-EXP-06`（无稳定身份的一对一配对与歧义标定）：`completed-for-current-scope`，结论见 `docs/v2_mentor/R4_EXP_06_PAIRING_CALIBRATION.md`
- `R4-EXP-07`（资产来源解析与降级链）：`completed-for-current-scope`，结论见 `docs/v2_mentor/R4_EXP_07_ASSET_RESOLUTION.md`
- `R4-EXP-08`（多页面、多轮更新的权威链）：`completed-for-current-scope`，结论见 `docs/v2_mentor/R4_EXP_08_AUTHORITY_CHAIN.md`
- `R4-EXP-09`（混合来源字段的 Figma 写入合同）：`completed-for-current-scope`，结论见 `docs/v2_mentor/R4_EXP_09_FIGMA_WRITE_CONTRACT.md`
- `R4-EXP-10`（九阶段离线集成与 envelope 审计）：`completed-for-current-scope`，结论见 `docs/v2_mentor/R4_EXP_10_END_TO_END_INTEGRATION.md`
- `R5-EXP-01`（冲突字段默认交付与报告一致性）：`completed-for-current-scope`，离线 33 用例、10/10 检查、15/15 变异拒绝；不连接 Figma，不证明用户理解或价格正确；见 `docs/v2_mentor/R5_EXP_01_CONFLICT_DELIVERY.md`
- `R5-EXP-02`（写入失败注入、对账与补偿）：`completed-for-current-scope`，确定性 51/51、真实 Figma 23/23、30 步重放；结论与 bridge 缺口见 `docs/v2_mentor/R5_EXP_02_WRITE_FAILURE.md`
- `R5-EXP-03`（DOM / 截图字段权威矩阵）：`completed-for-current-scope`，8 个 authored Chromium 场景、50 字段行、19/19 检查、22/22 变异拒绝；OCR 只晋升文本候选，局部遮挡不恢复全局 z-order；见 `docs/v2_mentor/R5_EXP_03_AUTHORITY_MATRIX.md`
- `R5-EXP-04`（部分交付表达与 coverage map）：`completed-for-current-scope`，4 个同坐标变体、12 个区域、19/19 检查、24/24 变异拒绝；masked diff 为 0 仍保持 PARTIAL；见 `docs/v2_mentor/R5_EXP_04_PARTIAL_COVERAGE.md`
- `R5-EXP-05`（四维验收硬门禁与页面汇总）：`completed-for-current-scope`，19 case × 11 条记录、22/22 检查、30/30 变异拒绝；关键项闭包阻断，面积不参与发布分数；见 `docs/v2_mentor/R5_EXP_05_ACCEPTANCE_GATE.md`
- `R5-EXP-06`（IR 持久化、TTL、迁移与重放）：`completed-for-current-scope`，12 case、54 事件、21/21 检查、32/32 变异拒绝；写前失败零副作用，TTL/迁移/replay 语义分离；见 `docs/v2_mentor/R5_EXP_06_IR_PERSISTENCE.md`
- R5 收口审计：6/6 current-scope、118/118 检查、123/123 结构化变异拒绝、0 verified；见 `docs/v2_mentor/R5_CURRENT_SCOPE_AUDIT.md`
- Image I-004/I-005：CV fallback 已完成一次真实 Figma 路由与写回验收，但结果在 critical text、structure 与 asset 三项 `blocked-fail`；同一冻结样本上的 Grounding + CV conservative hybrid 无独立改善且耗时更高，决策为 `reject-hybrid`，Grounding 保持默认。见 `docs/v2_mentor/IMAGE_CV_HYBRID_BENCHMARK_2026-10-26.md`
- Image I-004-R2：完整 `PreciseAgent` CV fallback 路径在 owned sample 通过真实 Figma 门禁；随后冻结的三样本 holdout 为 `0/3`，因此 CV fallback 仅保留为 availability fallback，质量泛化结论不成立。见 `docs/v2_mentor/IMAGE_CV_FALLBACK_PRODUCT_ACCEPTANCE_2026-10-26.md`
- R5 生产切片：`P0-CONTRACT-CORE` 已实现当前范围；`P1-EVIDENCE-ADAPTER` 已完成 shadow、frame 子文档作用域、两轴 outcome、S07 条件候选、有限 barrier、first-party scope、独立 frame boundary 与 S06 导航时间线当前范围；旧 round3 strict 3/7、content 5/7 冻结，新 profile equivalent 2 / different 3 / inconclusive 2；真实 Figma 写入、生产存储与检测器校准仍未准入；见 `docs/v2_mentor/R5_PRODUCTION_BACKLOG.md`
- R5-P5/P4 门禁：Grounding reliability、fallback telemetry、generated-canary security、controlled collaboration、local-pilot operations 和 frozen dry run 已完成当前范围。真实 Figma 1h round 3 为 57,039/57,039、0 failure、exact cleanup；controlled 1h round 6 为 35,881 attempts、0 failure，并覆盖 429/503、12 reconnects 与 unknown recovery。P5 仍因 Q8-Q10 为 `blocked-pending-rulings`，24h/7d 与真实协作者未完成，生产决策仍为 `not-admitted`；见 `docs/v2_mentor/PRODUCTION_ADMISSION_HARDENING_2026-10-26.md` 与 `docs/v2_mentor/R5_PRODUCTION_ADMISSION_DECISION.md`
- P0 纯合同核心：`src/app/services/contracts/` + 20/20 单测；未接默认渲染或 bridge；见 `docs/v2_mentor/P0_CONTRACT_CORE.md`
- P1 当前主目标：固定 Chromium canonical 环境下的实际 SVG/Figma 输出保真。旧 full-visible strict 定义/证据保留，但实时 strict count 只作诊断。calibration 6 样例 `5 pass + 1 partial`；独立 holdout 5 例 SVG 5/5，visual 4 pass / 1 frame fail；data URI 与受控远程资产已校验 content SHA-256、natural size、object-fit source rect。Figma not-evaluated。全量 173/173；详见 `docs/v2_mentor/P1_CANONICAL_OUTPUT_FIDELITY.md`。
- 真实 Figma 冒烟 B（写入 + 回读，非生产路径）：`docs/v2_mentor/R4_SMOKE_B_READBACK.md`；脚本 `scripts/figma_readback_smoke.py`
- 真实 Figma 冒烟 C（`R4-EXP-09` 命令重放 + 回读，16/16，非生产路径）：`docs/v2_mentor/R4_SMOKE_C_WRITE_CONTRACT.md`；脚本 `scripts/figma_write_contract_smoke.py`
- 真实 Figma 冒烟 D（Auto Layout 重排、缺字体严格失败、部分遮挡/裁剪，26/26，非生产路径）：`docs/v2_mentor/R4_SMOKE_D_AUTOLAYOUT_FONT_OCCLUSION.md`；脚本 `scripts/figma_smoke_d.py`
- 元数据补齐（幂等，不升级结论）：R3 EXP-01–12 见 `output/_r3_supplements/r3_metadata_supplement.json`；R4 EXP-01–09 见 `output/_r4_experiments/r4_metadata_supplement.json`
- 实验原始结果：`output/_r1_experiments/r1_true_flow_contract.json`、`output/_r1_experiments/r1_session_fallback_regression.json`、`output/_r2_experiments/r2_dom_flow_perturbation.json`、`output/_r3_experiments/exp08_text_acceptance.json`、`output/_r3_experiments/exp09_asset_contract.json`、`output/_r3_experiments/exp10_flow_perturbation.json`、`output/_r3_experiments/exp11_acceptance_calibration.json`、`output/_r3_experiments/exp12_reference_states.json`、`output/_r3_supplements/r3_exp13_cross_renderer_text.json`、`output/_r3_supplements/r3_exp14_static_baseline.json`、`output/_r3_supplements/r3_exp15_raster_fallback.json`、`output/_r4_experiments/r4_fusion_contract.json`、`output/_r4_experiments/r4_ocr_candidates.json`、`output/_r4_experiments/r4_state_gate.json`、`output/_r4_experiments/r4_bbox_calibration.json`、`output/_r4_experiments/r4_pairing_calibration.json`、`output/_r4_experiments/r4_asset_resolution.json`、`output/_r4_experiments/r4_authority_chain.json`、`output/_r4_experiments/r4_figma_write_contract.json`、`output/_r4_experiments/r4_end_to_end_integration.json`
- `R4-EXP-04` 的原始结果与产物：`output/_r4_experiments/r4_provenance_ir.json`、`output/_r4_experiments/r4_provenance_artifacts/`、`output/_r4_experiments/r4_ir_flow.png`、`output/_r4_experiments/r4_ir_coverage.png`、`output/_r4_experiments/r4_ir_replay.png`
- `R4-EXP-05` 的原始结果与产物：`output/_r4_experiments/r4_bbox_artifacts/`、`output/_r4_experiments/r4_bbox_heatmap.png`、`output/_r4_experiments/r4_bbox_distribution.png`、`output/_r4_experiments/r4_bbox_overlay.png`
- `R4-EXP-06` 的原始结果与产物：`output/_r4_experiments/r4_pairing_artifacts/`（含 24 张捕获）、`output/_r4_experiments/r4_pairing_matrix.png`、`output/_r4_experiments/r4_pairing_thresholds.png`、`output/_r4_experiments/r4_pairing_cases.png`
- `R4-EXP-07` 的原始结果与产物：`output/_r4_experiments/r4_asset_artifacts/`（含 20 张裁片与下载字节）、`output/_r4_experiments/r4_asset_flow.png`、`output/_r4_experiments/r4_asset_outcomes.png`、`output/_r4_experiments/r4_asset_cost.png`、`output/_r4_experiments/r4_asset_contact_sheet.png`
- `R4-EXP-08` 的原始结果与产物：`output/_r4_experiments/r4_authority_artifacts/`（含 15 个页面修订）、`output/_r4_experiments/r4_authority_chain.png`、`output/_r4_experiments/r4_authority_matrix.png`、`output/_r4_experiments/r4_authority_conflicts.png`
- `R4-EXP-09` 的原始结果与产物：`output/_r4_experiments/r4_figma_write_artifacts/`（含 `write_plan.json`、`commands.json`、`decisions.json` 与 3 个 PNG 资产）、`output/_r4_experiments/r4_figma_write_flow.png`、`output/_r4_experiments/r4_figma_write_matrix.png`、`output/_r4_experiments/r4_figma_write_occlusion.png`、`output/_r4_experiments/r4_figma_write_assets.png`
- `R4-EXP-10` 的原始结果与产物：`output/_r4_experiments/r4_end_to_end_artifacts/`（含 `stage_bundle.json`、`stage_envelopes.json`、`mutations.json`）、`output/_r4_experiments/r4_end_to_end_stages.png`、`output/_r4_experiments/r4_end_to_end_evidence.png`、`output/_r4_experiments/r4_end_to_end_mutations.png`
- `R5-EXP-03` 的原始结果与产物：`output/_r5_experiments/r5_exp_03_authority_matrix/`（含 `result.json`、`matrix.json`、`mutations.json`、fixture、逐场景截图、M0/M1 整页截图）、`r5_exp_03_authority_matrix.png`、`r5_exp_03_evidence_report.png`、`r5_exp_03_contact_sheet.png`、`r5_exp_03_stack_sample.png`
- `R5-EXP-04` 的原始结果与产物：`output/_r5_experiments/r5_exp_04_partial_coverage/`（含 `result.json`、`canvas.json`、`report.json`、`manifest.json`、`coverage_map.json`、`mutations.json`、reference/mask/逐 case 图）、`r5_exp_04_case_contact_sheet.png`、`r5_exp_04_coverage_map.png`、`r5_exp_04_coverage_matrix.png`、`r5_exp_04_mask_denominator.png`、`r5_exp_04_delivery_report.png`
- `R5-EXP-05` 的原始结果与产物：`output/_r5_experiments/r5_exp_05_acceptance_gate/`（含 `result.json`、`contracts.json`、`checks.json`、`page_summaries.json`、`release_ledger.json`、`mutations.json`、reference/price-error/diff 图）、`r5_exp_05_check_matrix.png`、`r5_exp_05_page_summary.png`、`r5_exp_05_area_vs_critical.png`、`r5_exp_05_release_profiles.png`、`r5_exp_05_price_error_evidence.png`
- `R5-EXP-06` 的原始结果与产物：`output/_r5_experiments/r5_exp_06_ir_persistence/`（含 `result.json`、`runtime_ir.json`、`audit_bundle.json`、`replay_results.json`、`migration.json`、`retention.json`、`events.json`、`mutations.json`、`store/`）、`r5_exp_06_replay_matrix.png`、`r5_exp_06_lifecycle_timeline.png`、`r5_exp_06_migration_integrity.png`、`r5_exp_06_retention_timeline.png`、`r5_exp_06_bundle_separation.png`
- P1 严格状态对齐与 frame 扩面产物：`output/_p1_dual_sidecars/real_pair_matrix_round2.json`、`output/_p1_dual_sidecars/real_pair_matrix_round3.json`、`output/_p1_evidence_shadow_webkit_round2/cross_browser_summary.json`、`output/_p1_evidence_shadow_webkit_real_round3/cross_browser_summary.json`；round3 原始 DOM/截图/sidecar 保留在 `output/_p1_dual_capture/dual-P1-*-frame-*/` 与 `output/_p1_dual_sidecars/dual-P1-*-frame-*/`。
- P1 outcome 与 S07 条件产物：`output/_p1_dual_sidecars/real_pair_matrix_outcome_round1.json`、`output/_p1_engine_conditions/s07_condition_probe.json`、`docs/v2_mentor/P1_OUTCOME_CONTRACT.md`；原始 outcome capture 保留在 `output/_p1_dual_capture/dual-P1-*-outcome-*` 与 `output/_p1_dual_sidecars/dual-P1-*-outcome-*`。
- P1 frame barrier A/B 产物：`output/_p1_frame_barrier/experiment_round1.json`、`docs/v2_mentor/P1_FRAME_BARRIER_EXPERIMENT.md`；原始 capture/sidecar 保留在 `output/_p1_frame_barrier/captures/` 与 `output/_p1_frame_barrier/sidecars/`。
- P1 first-party scope 产物：`output/_p1_first_party_scope/experiment_round1.json`、`docs/v2_mentor/P1_FIRST_PARTY_SCOPE.md`、`output/_p1_engine_conditions/s07_condition_probe_round2.json`、`s07_condition_probe_round3.json`；原始 capture/sidecar 保留在 `output/_p1_first_party_scope/captures/` 与 `sidecars/`。
- P1 rendered frame boundary 产物：`output/_p1_rendered_frame_boundary/experiment_round1.json`、`docs/v2_mentor/P1_RENDERED_FRAME_BOUNDARY.md`；原始 capture/sidecar 保留在 `output/_p1_rendered_frame_boundary/captures/` 与 `sidecars/`。
- P1 S06 navigation timeline 产物：`output/_p1_navigation_timeline/s06_timeline_round1.json`、`docs/v2_mentor/P1_OUTCOME_CONTRACT.md`；部分 capture/sidecar 保留在 `output/_p1_navigation_timeline/captures/` 与 `sidecars/`。
- P1 S07 导航恢复与 feature-shim round4：`output/_p1_engine_conditions/s07_navigation_recovery_round1/`、`output/_p1_engine_conditions/s07_condition_probe_round4.json`；继续 candidate-only，不写已确认根因。
- P1 boundary authored holdout：`tests/fixtures/p1/frame_boundary_holdout.json`、`output/_p1_frame_boundary_holdout/result.json`、`scripts/p1_frame_boundary_holdout.py`；9/9 通过，false equivalence 0。
- P1 S06 navigation-only：`output/_p1_navigation_only/s06_round1.json`、`s06_round2.json`、`scripts/p1_navigation_only_probe.py`；固定 2 attempts × 2 engines，不生成 DOM/截图/sidecar。
- P1 S01 generation drift 审计：`output/_p1_s01_generation_drift/s01_round1.json`、`scripts/p1_s01_generation_drift_audit.py`；9 attempts 中 execution instability 5、capture 3、navigation failure 1，generation drift 不升级为根因。
- P1 canonical output fidelity：`docs/v2_mentor/P1_CANONICAL_OUTPUT_FIDELITY.md`、`tests/fixtures/p1/canonical/manifest.json`、`scripts/p1_canonical_output_fidelity.py`；首轮 3 样例基线 `output/_p1_canonical_output_fidelity/round1.json`，当前 6 样例基线 `output/_p1_canonical_output_fidelity_round14/round1.json`。
- P1 canonical visual holdout：`tests/fixtures/p1/canonical/visual_policy.json`、`tests/fixtures/p1/canonical/holdout/manifest.json`、`output/_p1_canonical_visual_holdout_round5/round1.json`；视觉阈值冻结后运行，当前 4 pass / 1 frame fail，不与 calibration 分母混算。
- R5 收口审计结果：`output/_r5_closeout/result.json`、`production_slices.json`、`r5_closeout_matrix.png`、`r5_production_slices.png`

## 许可证

MIT
