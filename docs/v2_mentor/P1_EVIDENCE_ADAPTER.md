# P1-EVIDENCE-ADAPTER · 样本范围、保留策略与 shadow 实现

> 状态：`shadow-implemented-current-scope`（2026-10-20），不是 P1 生产验收，也不是 `verified`。  
> 范围：定义 P1 样本矩阵与本地证据保留策略，并把一次 capture 转成 P0 `RuntimeIR`、audit bundle 和本地证据侧车。  
> 边界：只读输入；不接默认渲染路径；不执行 OCR、资产下载或 Figma 写入。

## 1. 样本范围

### 1.1 默认矩阵

默认范围版本为 `p1-sample-scope/1.0`。它要求 7 个场景，每个场景至少 2 次 capture，其中至少 1 次来自真实页面；受控 fixture 只能占另一个名额。控制页可以公开访问，也可以是获授权的自有页面。

| ID | 类别 | 必含信号 | 最低运行数 |
|---|---|---|---:|
| `P1-S01` | iframe | 可访问 iframe、sandboxed/不可访问 iframe | 2 |
| `P1-S02` | shadow-dom | open shadow、closed shadow 边界 | 2 |
| `P1-S03` | canvas | canvas 文本、叠字或截图-only 外观 | 2 |
| `P1-S04` | dynamic-state | M0 壳、M1 水合后内容 | 2 |
| `P1-S05` | ocr | 低对比、小字号或只能从截图看到的文本 | 2 |
| `P1-S06` | assets | img、background-image、SVG/icon | 2 |
| `P1-S07` | capture-fallback | soft-block、hard-login | 2 |

因此第一批 P1 样本是 **至少 14 次完整 capture**，且每个类别至少有一个真实页面样本。没有真实页面时，该类保持 `not-evaluated`，不能用一个同名 fixture 冒充。

### 1.2 选择规则

- 页面状态：`content / soft_block / hard_login` 都必须覆盖；非 `content` 只保留证据和 unknown，不生成内容字段。
- 浏览器：Chromium 已覆盖 14 个样本；WebKit 已覆盖 7 个受控样本与 7 个真实样本的 page-state/marker；Firefox 仍未覆盖，不默认为通过。
- 输入：每个样本必须来自 `capture_page_with_fallback`，至少保留 `00_screenshot.png` 与 `00_page_state.json`；内容页还应保留 `00_dom.json`，有诊断时保留 `00_dom_diagnostics.json`。
- 安全：样本不得使用真实密码、cookie、token、支付信息或其他凭据。未经授权的页面不纳入真实样本。
- 失败样本也要保留：拦截页、登录页、空壳和缺 DOM 的截图-only 结果不能为了“好看”删除。

## 2. 证据保留策略

默认策略为 `p1-evidence-store/1.0`：

| 项目 | 默认值 |
|---|---|
| 存储位置 | 本地 sidecar 目录 |
| replay evidence | 30 天 |
| audit metadata | 180 天 |
| 证据字节 | 复制截图、DOM、page_state、diagnostics 到 sidecar |
| 外部 URL | 不下载、不持久化为证据 |
| 单次证据预算 | 512 MiB |
| 访问权限 | 本地读取、materialize、audit summary |

策略通过 `EvidenceStorePolicy` 生成 P0 `RetentionPolicy`。`captured_at` 必须带时区；sidecar 的 `evidence_expires_at` 与 `audit_metadata_expires_at` 因此可复算。TTL 清理 worker、对象存储、权限服务和生产备份仍未实现。

当前 sidecar 会在本地保留原始 DOM 文本。样本摄入必须排除凭据和敏感个人信息；manifest 只输出 page_state 摘要和敏感键策略，不把 cookie/token 等内容复制进摘要。对原始 DOM 的通用自动脱敏尚未实现，不能用这个 shadow 版本承接敏感生产页面。

## 3. Shadow 实现

新增包：

```text
src/app/services/evidence/
  __init__.py
  adapter.py
  retention.py
  sample_registry.py
  sample_scope.py
```

主要 API：

- `DEFAULT_SAMPLE_SCOPE`：7 类样本范围与最低运行数。
- `validate_sample_scope()`：重复 ID、空信号、非真实来源等失败关闭。
- `EvidenceStorePolicy.to_contract()`：生成 30/180 天 retention。
- `adapt_capture()`：只读地把 capture 转成 P0 `RuntimeIR` 与 audit bundle。
- `write_evidence_sidecar()`：复制并校验证据字节，写 `runtime_ir.json`、`audit_bundle.json`、`manifest.json`。
- `load_sample_registry()` / `validate_sample_registry()`：读取并校验 `docs/v2_mentor/p1_sample_registry.json`。
- `scripts/p1_sample_runner.py`：批量 capture、生成 sidecar、写 `run_summary.json`；不进入默认渲染路径。
- `scripts/p1_sample_signal_audit.py`：只读统计 iframe/shadow/canvas/asset 信号，写 `sample_signal_summary.json`。
- `scripts/p1_cross_browser_compare.py`：对受控样本比较 Chromium/WebKit 的节点数、文本序列、结构计数和几何差值。
- `scripts/p1_ocr_probe.py`：对指定截图/裁剪区域运行 EasyOCR 或 Tesseract，输出 candidate-only OCR 证据。
- `scripts/p1_asset_download_probe.py`：从 sidecar 的 `reference-only` 资产中受限下载，校验 URL 私网、大小、MIME、图片魔数并保留本地字节。
- `scripts/p1_asset_materialize.py`：把下载结果合并成新的 sidecar 副本，更新 RuntimeIR assets、evidence、audit 顺序和 manifest。
- `scripts/p1_dual_browser_capture.py`：并发启动 Chromium/WebKit 采集同一 URL，先过状态门再比较几何；可选 `--rendered-frame-boundary-profile`。
- `scripts/p1_real_pair_matrix.py`：聚合 7 个真实成对样本的 strict/content/blocked 结果与失败分类。
- `scripts/p1_engine_condition_probe.py`：重复会话 + 交叉 UA 条件探针，只输出 engine/UA/session 归因候选。
- `scripts/p1_frame_barrier_experiment.py`：固定预算比较无/有 frame-tree barrier 的采样时序收益与成本。
- `scripts/p1_first_party_scope_experiment.py`：显式中断跨源 frame document，并与 full-visible profile 固定预算 A/B。
- `scripts/p1_rendered_frame_boundary_experiment.py`：并列 full-visible、first-party 与 `rendered-frame-boundary-strict/1.0` 的固定预算 A/B。
- `scripts/p1_navigation_timeline_probe.py`：S06 document request/response/failure/commit timeline 诊断，并支持部分 capture/sidecar 恢复。
- `scripts/p1_frame_boundary_holdout.py`：URL 换位、内容变化、opaque placeholder、代次/阶段漂移的确定性 authored holdout。
- `scripts/p1_navigation_only_probe.py`：不生成 DOM、截图或 sidecar 的轻量 navigation-only probe。
- `scripts/p1_s01_generation_drift_audit.py`：只读 S01 failure 优先级与 frame generation drift 审计。
- `scripts/p1_canonical_output_fidelity.py`：固定 Chromium canonical 环境，执行 DOM→SVG 并分别报告内容、关键几何、资产、native text 与视觉指标。
- `scripts/p1_glyph_bbox_audit.py`：生成浏览器 canvas 字符度量真值，与 Tesseract 字符 bbox 做序列和位置误差比较。
- `src/app/services/structure/capture_state.py`：共享 URL/文本/节点/语义结构签名与 strict/content 状态门。
- `src/app/services/structure/frames.py`：frame inventory、同源子文档递归采集、opaque-frame 边界与 frame 导航状态。
- `src/app/services/structure/navigation_timeline.py`：每个 engine/attempt 最多 128 个 document 事件，记录 frame document generation。
- `src/app/services/structure/frame_boundary.py`：拓扑优先、URL 仅作观测字段的 rendered frame boundary comparison。

输出目录：

```text
sidecar/
  runtime_ir.json
  audit_bundle.json
  manifest.json
  evidence/
    screenshot.png
    dom.json
    page_state.json
    dom_diagnostics.json
    screenshot_m0.png        # optional
    dom_m0.json              # optional
    assets/
      asset-...              # data URI bytes
```

字段策略：

- DOM 节点生成 `geometry / text-content / text-style / text-box / background / role / asset-hint / stacking-hint` 观测。
- 所有字段的 decision 都是 `OBSERVED`、`release_eligible=false`，保留来源证据，不提前做权威选择。
- page-level 观测使用 `FieldAuthority.NONE`；OCR、截图权威和 release 由后续阶段处理。
- diagnostics 中的 shadow 缺口记为 `unknown`；grid、flex-wrap、gradient、pseudo-element 记为 `unsupported`。
- DOM 中的 `assetSrc` 与背景图 URL 生成 `AssetRecord`；data URI 解码后写入 `evidence/assets/` 并计算 SHA-256，http/https 只标 `reference-only`，不下载。
- 非渲染 SVG 定义容器（`defs/clipPath/mask/symbol/pattern/gradient/filter/marker`）不作为可见 DOM 采集，避免 WebKit 对 `<clipPath><rect>` 报告伪布局框。
- frame inventory 保留每个 frame 的 URL、尺寸、sandbox、同源/跨源、可访问性、opaque 原因、导航状态、`document_generation/document_commit_count/navigation_phase`；同源且父文档可访问的 frame 递归采集，子文档坐标叠加到宿主 frame，并写入 `framePath/frameDepth`。
- 跨源、sandbox opaque origin、父级 opaque 或运行期不可访问的 frame 标为 `opaque-frame`，只保留边界证据，不声称读到了其内部 DOM。
- strict 比较“可渲染 frame tree”：可见 frame 使用稳定 `scope_path`；0×0/隐藏 tracker 仍写入完整 inventory 作为证据，但不参与可视状态门。这不是放宽 strict，而是与既有可见 DOM 口径一致。
- 快照前状态签名同时覆盖主文档与可渲染同源子文档；子 frame 导航会改变签名并触发成对重试。
- `about:blank` 先保留为 `blank-document`；只有目标要求非空、导航预算耗尽且仍未提交目标文档时才归为 `browser-navigation-failed`。networkidle 后仍为空白时只做一次有界 `domcontentloaded` 重导航；失败仍保留。
- 文本差分为纯符号 `dynamic-glyph` 时只写归因证据，不提升为 strict/content 通过；导航失败优先于 DOM 差，glyph 归因优先于 frame scope 显示。
- `first-party-frame-strict/1.0` 是独立实验 profile：只阻塞跨源 frame document，保留宿主导航/几何/opaque 边界，并记录被阻断 URL；它不是 full-visible strict，默认采集不变。
- `rendered-frame-boundary-strict/1.0` 是独立比较 profile：frame 身份使用 `scope_path/parent_chain/visible_index/depth`，比较宿主几何、可见性、sandbox/opaque 边界、文档代次与导航阶段；URL/src 只作观测属性。opaque 内部内容保持不可观测，不参与相等推断。
- 快照前先做有界 `document.fonts` 等待，再要求可见状态签名连续稳定；导航替换文档造成的瞬时探针异常会重试，不会直接中断整页采集。
- closed shadow root 对页面 DOM 探针不可见；样本需要外部 ground truth 记录它存在，adapter 不能从“没看到”推断它不存在。
- 截图-only、登录墙或 soft-block 只产生 page-state 证据和 unknown，不从截图猜内容字段。
- `screenshot_only=true` 的 `content` 页也不会从 DOM 生成内容字段；DOM 只保留为证据，并记录 `dom-content / screenshot-only`。
- 可选 M0 证据：`capture_early_state=true` 时保存 `00_screenshot_m0.png` / `00_dom_m0.json`；默认关闭，最终 M1 仍按原路径采集。

默认路径隔离：

- 不导入 `PreciseAgent`、`RenderingController` 或 `FigmaBridgeAdapter` 的运行时路径。
- 不生成 Figma 命令，不连接 `ws://localhost:8765`。
- 任何缺失必需证据、哈希不一致或证据预算超限都失败关闭。

## 4. 当前验证

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe -m unittest tests.v2.test_p1_evidence_adapter -v
```

当前结果：P1 adapter 15/15、OCR 对比 8/8、资产下载 4/4、资产 materialize 1/1；全量 180/180 通过（含 browser-engine、frame capture、capture-state、outcome contract、条件探针、barrier A/B、first-party scope、frame boundary holdout、navigation timeline、navigation-only、S01 drift 审计与 canonical output fidelity 测试）。

用仓库已有受控 capture 跑一次 shadow：

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe scripts\p1_evidence_shadow.py `
  "output/_fixture_final" `
  --out "output/_p1_evidence_shadow/fixture_final" `
  --captured-at "2026-10-19T00:00:00+00:00" `
  --job-id "p1-shadow-fixture-final"
```

本次输出：

- `field_count=96`
- `unknown_count=4`
- `content_hash=ec51be6959659c6a532a14f1d913795e475b59f7a201389a932fae48c59cab62`
- `runtime_ir` 与 `audit_bundle` 校验均为 0 issue
- 证据文件实际复制到 `output/_p1_evidence_shadow/fixture_final/evidence/`

这只是受控 fixture 的 shadow 结果，不证明真实站点、跨浏览器、OCR 或 Figma 写入。

### 4.1 14 槽样本运行

按 `docs/v2_mentor/p1_sample_registry.json` 运行 Chromium 首轮：

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe scripts\p1_sample_runner.py
```

结果写入 `output/_p1_evidence_shadow/run_summary.json`：14 个样本、14 个 page-state 匹配、14 个 sidecar 生成；结构 marker 审计为 14/14 通过。结构信号核对如下：

| 场景 | 受控样本信号 | 真实样本信号 | 尚未完成 |
|---|---|---|---|
| iframe | 2 个 iframe | W3Schools 5 个 iframe | 子文档字段与父页面隔离审计 |
| shadow DOM | 2 个 open-shadow 节点；truth 声明 1 个 closed root、不可观察 | Shoelace 55 个 shadow 节点 | 真实站点 closed shadow 仍不可观察 |
| canvas | 1 个 canvas | W3Schools 8 个 canvas | canvas 文本未做 OCR 质量验收 |
| 动态状态 | M0 6 节点 shell → M1 8 节点 hydrated 内容，文本变化已核对 | React 页面 content | 真实页面 M0/M1 未单独捕获 |
| OCR | canvas-only 文本 | W3Schools 3 个 canvas | OCR 引擎未运行 |
| 资产 | img/svg/background-image 各 1 | Dushu 45 个 img、10 个 icon | 原图哈希、下载与替换契约未完成 |
| fallback | soft_block | GitHub login 为 hard_login | 真实反爬变体与权限链未覆盖 |

`14/14` 只表示 registry 声明的页面状态与结构 marker 通过，不等于真实页面 M0/M1、OCR 质量、远程资产字节、跨浏览器或生产存储验收通过。

结构信号报告由以下命令生成：

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe scripts\p1_sample_signal_audit.py
```

输出为 `output/_p1_evidence_shadow/sample_signal_summary.json`。该报告记录 capture 事实、声明 marker 检查、M0/M1 文本变化与受控 closed-shadow ground truth；真实站点这两个信号仍不在该门禁内。

受控 closed shadow 的外部真值文件为 `tests/fixtures/p1/shadow_dom.truth.json`，审计状态为 `declared-unobservable`；这不是从 DOM 推断出来的结果。

### 4.2 WebKit 受控对比

WebKit 首轮只跑 7 个受控样本，使用独立目录：

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe scripts\p1_sample_runner.py `
  --source-kind controlled `
  --browser-engine webkit `
  --sample-root "output/_p1_samples_webkit" `
  --sidecar-root "output/_p1_evidence_shadow_webkit"
```

结果：

- 7/7 page-state 匹配
- 7/7 声明 marker 通过
- 7/7 DOM 节点数一致
- 7/7 可见文本序列一致
- 7/7 iframe/shadow/canvas/img/svg/background-image 计数一致
- 7/7 样本几何最大差值不超过 1px
- `P1-S02-C1` 最初的 16–20px host 高度差由 custom element 未声明 display 导致；夹具加 `display: block` 后重采，差值降为 0px
- `P1-S04-C1` 在 Chromium 与 WebKit 都记录了 M0 shell 到 M1 hydrated 内容的文本变化

报告：`output/_p1_evidence_shadow_webkit/cross_browser_summary.json`。

2026-10-20 用最终状态签名代码重跑受控样本（`output/_p1_samples_round2/` 对 `output/_p1_samples_webkit_round2/`）：page-state、节点数、文本序列、结构计数和 strict 门均 7/7；23/23 文本节点匹配、平均覆盖 100%。报告：`output/_p1_evidence_shadow_webkit_round2/cross_browser_summary.json`。

另做了一次公开内容页基线采样（无头、禁止真实会话降级）：

- URL：`https://www.dushu.com/`
- capture 状态：`content`，1 次 attempt，截图 `1440×2544`
- sidecar：`output/_p1_evidence_shadow/dushu_home/`
- `field_count=1256`，`unknown_count=1`（`visual.pseudo-element`，diagnostics 报 10 个）
- `content_hash=f7a1c5ab6bdb469777def0205686b5edcbdc59d574fa7cfb4498cb55a6023bf8`
- `runtime_ir` 与 `audit_bundle` 校验均为 0 issue

该页面只作为公开内容页基线和一个证据适配样本，不满足 iframe、shadow DOM、canvas 或截图-only OCR 场景，因此不能替代矩阵中的真实样本。

### 4.3 资产证据

- 受控 `P1-S06-C1`：2 个 data URI 资产（img 与 background-image）解码后写入 sidecar，合计 230 bytes；Chromium 与 WebKit 的 SHA-256 一致。
- 真实 `P1-S06-R1`（Dushu）：45 个 `img` URL 全部记录为 `reference-only`，不下载远程字节。
- `runtime_ir.assets` 与 manifest 均保留资产状态；本地资产同时生成 `asset-bytes` evidence record。

### 4.4 OCR 证据

EasyOCR 在受控 `P1-S05-C1` 的 canvas 裁片（`8,132,640,120`）上运行：

- Chromium：2/2 预期短语命中；2 行，confidence `mean 0.76 / min 0.68 / max 0.83`，耗时约 1.6 秒（reader 已缓存）。
- WebKit：2/2 命中；2 行，confidence `mean 0.78 / min 0.74 / max 0.83`，耗时约 1.6 秒。
- 真实 `P1-S05-R1` 的第一个 canvas 裁片识别出 `Hello World`，1/1 命中；1 行，confidence `0.98`，耗时约 1.4 秒。
- OCR 结果只写 `ocr_probe*.json`，标记 `candidate-only; not selected as final text`；没有自动晋升正文。
- EasyOCR 路径输出行级 bbox 和 confidence；Tesseract 补充词级与字符级 bbox，见下。

Tesseract 补充词级/字符级探针：

- Chromium 受控 canvas：10 个词，词级 confidence `mean 95.7 / min 95`，57 个字符 bbox，归一化字符序列匹配，54/54 字符，耗时约 0.26 秒。
- WebKit 受控 canvas：10 个词，confidence `mean 95.8 / min 95`，57 个字符 bbox，54/54 字符匹配，耗时约 0.25 秒。
- 真实 W3Schools canvas：2 个词，confidence `mean 95.5`，10 个字符 bbox，10/10 字符匹配，耗时约 0.22 秒。
- 字符 bbox 已提取，但字符框位置精度、旋转/竖排和跨字体 glyph 形状仍未标定。

字符框位置审计：

- Chromium：57/57 字符序列匹配；最大轴误差 15px，P95 5px，41/57 字符框四项轴误差均 ≤2px，7 个超过 4px。
- WebKit：57/57 字符序列匹配；最大轴误差 15px，P95 5px，37/57 字符框 ≤2px，9 个超过 4px。
- 结论是字符序列与 OCR 文本可用，但字符框位置尚未通过验收；不能把字符 bbox 当作已标定的排版真值。
- 全局中位轴偏移校准：Chromium offset `x=1, y=0, w=-2, h=0`，2px 内提升到 44/57，但最大残差 17px、P95 5px；WebKit offset `x=1, y=0, w=-1, h=0`，2px 内提升到 42/57，但最大残差 16px、P95 5px。
- 校准只消除了部分系统性 bias，局部 ink-box/字体差异仍存在；这不是 holdout 验证。
- 合并框分类：两端各识别 1 个 suspect 字符框（显著宽于 ground truth）；剔除后可信字符 56/57，Chromium 最大残差降到 8px、P95 4px、41/56 在 2px 内；WebKit 最大残差 8px、P95 5px、37/56 在 2px 内。
- 位置验收仍未通过。当前可以可靠报告字符序列和 suspect 框，但不能把 Tesseract 字符 bbox 写成最终排版真值。

结果文件：

- `output/_p1_evidence_shadow/ocr_probe_s05_c1.json`
- `output/_p1_evidence_shadow_webkit/ocr_probe_s05_c1.json`
- `output/_p1_evidence_shadow/ocr_probe_s05_r1_canvas1.json`

当前只验证文本内容命中，尚未标定断行、文本框、逐字框/字形与置信度阈值。

### 4.5 远程资产下载

`scripts/p1_asset_download_probe.py` 只处理 sidecar 中显式存在、且 `local_bytes_present=false` 的来源 URL。默认策略：

- 只允许 http/https，拒绝 file 和其他 scheme。
- 拒绝 loopback、私网、link-local、reserved、multicast 地址。
- 单资产 2 MiB，单批最多 5 个，默认 10 秒超时。
- 只允许 `image/*`；校验 Content-Type 与 PNG/JPEG/GIF/WebP/SVG 魔数一致。
- 下载后写本地文件并重新计算 SHA-256。

本次验证：

- Dushu 前 3 个图片 URL 返回 HTTP 403，失败路径正确记录。
- W3Schools 图片 URL TLS handshake 超时，失败路径正确记录。
- 受控 `remote_asset.html` 指向 `https://httpbin.org/image/png`，下载 8090 bytes，`image/png`，本地 SHA-256 `541a1ef5...` 与报告一致。
- 下载结果先写 `output/_p1_evidence_shadow_remote_asset/asset_downloads/asset_downloads.json`；原始 sidecar 保持不变。
- materialize 后生成 `output/_p1_evidence_shadow_remote_asset_materialized/`：`local_bytes_present=true`、`local_sha256`、`mime` 与 `local_expires_at` 写入 RuntimeIR assets；audit 顺序增加 `ev-asset-0005-img` 和 `ev-asset-download-report`；字段决策未改变。
- 文件级 materialize 已完成，生产对象存储/TTL worker 仍未实现。

### 4.6 真实页面 WebKit 与 M0/M1

真实页面 WebKit 重采（2026-10-20，`output/_p1_samples_webkit_real_round3/`）：

- 7/7 真实样本最终 page-state 与声明 marker 通过；S01/S03/S07 首轮受导航或字体截图超时影响，后续在新的采集目录重试成功。
- S01/S02 最初因 WebKit 字体等待导致截图 30 秒超时，但 DOM 已有 2940/456 个元素和完整正文；分类逻辑已改为“内容可读但截图异常仍保留 content，并记录 screenshot_error”。
- 独立重采对比（Chromium `output/_p1_samples_real_round2/` 对 WebKit round3）：page-state 7/7 匹配；strict 1/7（仅 S02）；content gate（含 strict）3/7（S02、S03、S06）；DOM 节点数一致 3/7。
- 独立重采不是同步 A/B；差异可能来自采集时刻、动态内容、懒加载、字体或反爬，不能全部归因于浏览器。
- React 独立重采两端均 1415 节点，但正文快照文本不完全一致；成对重试后 strict 通过，见 4.7/4.9。

真实 React M0/M1：

- Chromium：M0/M1 都是 1415 节点、529 条文本，未观察到文本变化。
- WebKit 旧采集：节点数从 1419 变到 1483，但 529 条文本未变化；修复 `clipPath` 过滤后可见基线为 1415。
- 目前只有受控动态 fixture 明确验证了 M0 shell → M1 hydrated 的文本变化；真实页面仍需要稳定状态门或同步双浏览器采集。

### 4.7 并发双浏览器采集

`scripts/p1_dual_browser_capture.py` 使用两个线程并发调用现有 capture，每个引擎独立启动 Playwright：

- 受控 `shadow_dom.html`：状态门通过，几何最大差 0px。
- 真实 React（`dual-react-strict-round3`）：第 1 轮 strict 通过；两端 1415 节点、529 条文本、相同结构哈希；文本节点 322/322 匹配，覆盖 100%，最大差 2px。
- 真实 Dushu（`dual-dushu-strict-round6`）：第 1 轮 `node-count-mismatch + structure-mismatch`；第 2 轮两端进入同一轮播相位，484 节点、165 条文本、相同结构哈希，strict 通过。
- 真实 Shoelace（`dual-P1-S02-R1-round2`）：strict 通过；463/463 节点，文本覆盖 100%，文本节点最大差 2px。
- 成对真实样本汇总：strict 3/7（S02、S04、S06）；text-only content 另加 S01、S03，共 5/7；S05、S07 blocked。报告：`output/_p1_dual_sidecars/real_pair_matrix_round2.json`。
- S01/S03 的 strict 阻断仍来自子文档/懒加载差异：iframe 计数分别为 `5 vs 1`、`4 vs 1`，文本序列可对齐但 DOM 节点与结构不能写成等价。
- 轮次选择按 `strict > content > blocked`，优先保留成功引擎更多的轮次；不会因为最后一轮网络失败覆盖更可比的先前轮次。

并发启动和稳定签名减少但不消除内容漂移；结果仍明确标记“不是 frame-synchronized A/B”。可选的 navigation/snapshot barrier 已实现并做确定性测试，但默认关闭：当一端导航失败时，强制屏障会让另一端等待，成对重试更稳健。

### 4.8 真实页面文本节点对齐

跨浏览器工具新增 `text-tag-nearest` 一对一匹配，仅用于匹配文本节点的探索性几何比较：

- 先按 `(tag, normalized-text)` 匹配唯一节点。
- 重复文本只按中心距离 ≤64px 做一对一配对。
- 严格状态门仍独立保留；文本匹配不会把未匹配结构节点伪造成等价。

结果：

- 受控样本：23/23 文本节点匹配，平均覆盖率 100%。
- 独立真实重采：1857 个文本节点匹配，平均覆盖率 95.88%。
- strict 成对样本：Shoelace 220/220、React 322/322、Dushu 164/164 文本节点匹配，覆盖均 100%；最大差分别为 2px、2px、1px。
- Dushu index-aligned 整页几何最大差 13px、5 个轴差超过 2px；这不影响 strict 状态通过，但说明非文本/结构节点仍不能写成整页几何等价。
- W3Schools iframe/canvas 页：覆盖率 96%–100%，但文本最大差分别为 379px、46px，只能做 text-node content-scope 比较。
- GitHub login 本轮 WebKit 落到 `about:blank`，甚至没有进入内容门。

以下为 round2 的双层状态门历史结果：

- 严格门要求 URL、文本哈希、节点数和语义结构哈希全一致；round2 成对真实 3/7。
- 内容门要求 URL、文本哈希一致且文本节点覆盖 ≥95%；成对真实 5/7。
- content-scope 的 S01/S03 只能做 text-node 比较，不能写成整页等价。
- S05 文本数量 363/364 不一致，WebKit 多出一个导航箭头 `span|❯`；S07 WebKit 到 `about:blank`，两者都连内容门也被阻断。

round3 strict 另要求可渲染 frame inventory 与状态稳定性一致；内容门仍不看 frame/node/structure。

以上是 round2 历史结果。加入 frame inventory、子文档递归与空白导航重试后的 round3 结果为：

- strict 仍为 3/7（S02、S04、S06），content 5/7（strict 3 个加 S03、S05），blocked 2/7（S01、S07）。
- 目标是提升 strict，但本轮没有达成；原因不是降低了验收，而是同源子文档与真实广告/登录 DOM 被纳入后，原先未观察到的差异被正确暴露。
- S01：4 次成对尝试，选中第 1 轮；主示例 iframe `default.asp` 与嵌套同源 frame 已递归采集，但两端广告 iframe、动态广告文案和可渲染 frame tree 不同；最终 1260/1196 节点、699/698 条文本，strict 因 text/node/structure/frame/state-unstable 阻断。
- S03：主同源 tutorial frame 已递归采集；最终 716/683 节点、477/477 条文本、覆盖 100%，因此是 content；node/structure/rendered-frame inventory 仍不同，不能通过 strict。更早一轮曾观察 WebKit 单独多出 `❯`。
- S05：第 3 轮出现 `span|❯` 并归因 `dynamic-glyph`，第 4 轮 glyph 消失且文本 365/365、覆盖 100%，说明它是可出现/消失的动态差异；最终 613/584 节点，node/structure/rendered-frame inventory 仍不同，因此只有 content，不是 strict。
- S07：空白文档重导航后 WebKit 已到 `https://github.com/login`，导航状态恢复 `ok`；最终 78 vs 49 节点、16 vs 12 条文本，WebKit 缺少 `Continue with Apple`、`Continue with Google`、`Sign in with a passkey` 与 `or`，归因为真实 DOM 状态差。
- 报告：`output/_p1_dual_sidecars/real_pair_matrix_round3.json`。

### 4.9 严格真实页面状态对齐实现（2026-10-20）

已定位并修复两类真实漂移：

1. **WebKit SVG 非渲染几何污染**：React 的差异全部来自 4 个 `<clipPath><rect>`。Chromium 对它们报告 0×0，WebKit 报告 24×24/59×59，旧采集因此得到 Chromium 1415、WebKit 1419 个可见节点。现在 DOM 遍历与状态签名都跳过非渲染 SVG 定义容器；React 两端恢复 1415/1415，且结构哈希一致。
2. **Dushu 轮播相位漂移**：同一页面会交替出现直接图片、`ul.slide` 幻灯片与不同指示点状态；旧门只看总元素数（806 保持不变），无法识别这两种可见状态。现在快照前等待字体、禁用 CSS 过渡，并要求“可见节点数 + 语义结构 token”连续稳定。该轮曾使用后续最佳轮次；outcome profile 已改为首次 execution-ready 即接受，旧记录只作历史证据。

该轮严格门没有被放宽，反而新增了两项约束：

- `structure_sha256` 覆盖标签、父索引、class、role、aria/title/alt、文本、asset source、背景 URL、图标/交互/shadow 标记；
- 双浏览器工具可要求两端都具备 `capture_stability.stable=true`，否则报 `state-unstable`。

状态稳定策略：

- `document.fonts` 最多等待 3000ms；超时只记录状态，不伪造字体已就绪。
- 禁用 transition/animation 后等待 400ms，再以 100ms 间隔采样可见状态；连续 600ms 不变才算稳定，最长 5000ms。
- 页面导航替换文档时，瞬时 `getComputedStyle` 异常按样本重试，不中断整个采集。
- 内容门始终只看 URL、文本哈希与 text-node 覆盖；strict 通过也不代表截图整页像素等价或全部布局几何等价。

### 4.10 两轴 outcome 合同与 S07 条件候选（2026-10-20）

导师回复后的修正记录在 `P1_OUTCOME_CONTRACT.md`：

- 旧 round3 strict `3/7`、content `5/7` 冻结，作为历史基线。
- 新 profile 分开 `execution_status` 与 `comparison_result`；`different` 不再和 navigation-failed/inconclusive 混写。
- 首次 execution-ready 成对结果直接接受，不再挑选后续更容易通过的一轮；每个 attempt 都保留。
- 新矩阵 `real_pair_matrix_outcome_round1.json`：equivalent `2`、different `3`、inconclusive `2`，不解释为旧 strict 升降。
- S07 12 个有效条件会话显示四个文案随 engine 稳定出现/缺失，交叉 UA 未改变结果，因此只写 `engine-conditioned-candidate`，`confirmed_root_cause=false`。

### 4.11 有限 frame barrier A/B（2026-10-20）

记录见 `P1_FRAME_BARRIER_EXPERIMENT.md`：

- 固定 3 attempts，S01/S03 比较无/有 frame barrier。
- barrier 未会合：`frame-barrier-mismatch`，执行态 `state-unstable/inconclusive`。
- 已会合但 frame tree 不同：`frame-barrier-divergence`，执行态 ready，比较结果 `different`。
- S03 文本数 `477/505 -> 477/477`，覆盖 `75.11% -> 100%`，说明部分原文来自采样时序；node/frame 差异仍在，最终仍 different。
- S03 耗时 `88.69s -> 113.94s`，约增加 28.5%；S01 未受益。
- 当前只保留 `--frame-barrier` 实验能力，默认关闭，不继续泛化加 barrier。

### 4.12 First-party frame scope 与 S07 feature-shim（2026-10-20）

记录见 `P1_FIRST_PARTY_SCOPE.md`：

- 新增 `first-party-frame-strict/1.0`，显式中断跨源 frame document，保留宿主边界与拦截清单。
- S01 未形成 ready 对；S03 full/first-party 均为 different，但节点差 `690 -> 31`、文本差 `477 -> 1`；S05 节点差保持 33、文本差 0。
- 新 profile equivalent 0，false equivalence 0；不能写成旧 full-visible strict 提升。
- S07 feature-shim round2/3 均只有 1/21 有效会话，导航失败占绝大多数；feature-conditioned 结论保持 `unresolved`，不增加根因强度。

### 4.13 Rendered frame boundary 与 S06/S07 复测（2026-10-20）

记录见 `P1_RENDERED_FRAME_BOUNDARY.md`：

- 新增独立 `rendered-frame-boundary-strict/1.0`，不替换旧 strict；frame 身份按可见拓扑/父链，URL 只作观测，opaque 内部保持 `unknown/not-observable`。
- S01/S03/S05 固定 3-attempt A/B：full-visible `diff 1 / inc 2`、first-party `diff 2 / inc 1`、boundary `diff 2 / inc 1`；三 scope 均 equivalent 0，false equivalence 0。
- boundary 汇总排除不可渲染 frame 130 次、记录 opaque 不可观测项 9 个；总耗时 full `341.501s`、first-party `208.453s`、boundary `253.938s`。
- S06 独立时间线中 WebKit 在 `15015ms` 报 `document-request-failed: Load request cancelled`，最终 `about:blank`，无 response/commit；分类为 navigation-failure。外层 360s 超时后用部分 capture/sidecar 恢复，未冒充稳定 DOM 差异。
- S07 native 导航门双端有效后，round4 小批 7/7 有效；feature shim 未改变四项文案，继续 `engine-conditioned-candidate`、feature unresolved。
- 默认采集/渲染路径未改变；未实现生产对象存储/TTL 或 Figma 写入。

### 4.14 Boundary holdout 与轻量 navigation-only（2026-10-21）

记录见 `P1_RENDERED_FRAME_BOUNDARY.md`：

- boundary authored holdout `9/9`：新增混合可访问/opaque 层级与 sandbox opaque；同 URL 换位仍按路径配对，opaque 内部保持不可观测。
- holdout 中 content changed 且 boundary equivalent `4`，false equivalence `0`，page equivalence claim `false`，result SHA-256 `61fa3ab3...`。
- navigation-only S06 固定 2 attempts × 2 engines，不生成 DOM/截图/sidecar；4/4 observation 有效。
- 第 1 attempt 两端 HTTP 200、`navigation=ok`、readyState complete；第 2 attempt 两端 `about:blank` 导航失败。主 attempt 保留为 `navigation-comparable`，后续失败单列，`stable_dom_difference_claimed=false`。
- round2 primary 为 capture-failure（Chromium worker timeout、WebKit navigation timeout），第 2 attempt 双端恢复；later recovery 不替换 primary。

### 4.15 S01 generation drift 审计（2026-10-21）

- 9 个已有 attempts：capture failure `3`、execution instability `5`、navigation failure `1`、stable comparable `0`。
- full-visible attempt 1 有 4 条 generation drift paths；first-party 未观察到 matched drift；boundary 三个 attempts 均有 generation drift（5/5/4 paths）。
- full/boundary timeline 多数达到 128-event 上限，说明 frame 持续导航。
- execution instability 优先，不能把 generation drift 写成已确认根因；也不得在没有共同稳定参考时声明 S01 different。
- 报告：`output/_p1_s01_generation_drift/s01_round1.json`。

### 4.16 Canonical Chromium 输出保真（2026-10-21）

导师确认产品主目标转向固定 Chromium canonical 环境下实际 SVG/Figma 输出保真；旧 full-visible strict 不再作为产品主优化指标。

- 实跑 canonical Chromium `151.0.7922.34`、Windows 11、900×700、DPR1、zh-CN。
- 首轮 3 个受控输入：text-flow、assets、iframe；各自独立 truth。
- calibration SVG 为 `5 pass + 1 partial`，独立 visual holdout 为 5/5；视觉阈值仍为 provisional；Figma 已完成真实写入/回读/PNG 导出，但四维验收仍未完成。
- 修复 hidden tracking frame 抢占 iframe host 导致的子文档偏移；iframe `mean 2.6854→2.6372`、`ink_mean 66.6029→64.4276`。
- 修复 flow 文本忽略 padding 与重复 paint；text-flow `mean 3.1386→2.8559`、`ink_mean 73.9762→69.2888`、bad px `16582→15537`。
- 修复浏览器实测分行在 SoM 层丢失：text-flow `mean 2.8559→0.7348`、`ink_mean 69.2888→15.2487`、bad px `15537→4788`。
- canonical suite 扩到 6 样例：SVG `5 pass + 1 partial`；新增字体 fallback、透明 overlay + 图片裁剪、缺失资产 partial delivery。
- 资产验收补显示盒/1px 容差/local bytes region checks；source asset identity 与 object-fit 源矩形仍未验证。
- 独立视觉 policy `p1-canonical-visual-policy/1.0` 先冻结后运行 4 例 holdout；visual gate 4/4 pass，calibration/holdout 分母独立。
- data URI 资产新增 MIME、byte length、natural size、content SHA-256、object-fit 与 source rect；calibration 与 holdout 资产 identity/crop 均通过。
- canonical 远程资产用受控 loopback server 验证 MIME/size/content SHA-256；生产下载策略仍拒绝私网。visual holdout 5 例为 5 pass；frame 已达到 `mean=0.0011`、bad pixels=12，仍保留非零残差。
- 实时 matrix 新增 gate contract：动态 legacy strict count 只作诊断，canonical output fidelity 为产品主目标。

详见 `P1_CANONICAL_OUTPUT_FIDELITY.md`、`output/_p1_canonical_output_fidelity_round16/round1.json`、`output/_p1_canonical_visual_holdout_round14/round1.json` 与 `output/_p1_figma_canonical_frame_round1/readback_tree.json`。

## 5. 下一步

1. 以 canonical SVG/Figma 输出保真为主计划，继续补字体缺失、资产失败、透明叠放与 partial delivery。
2. 标定视觉阈值并继续处理 text-flow 自动换行差异；不得把 measured-not-gated 写成视觉通过。
3. 标定 OCR 的断行、文本框、逐字框/字形与置信度；补真实页面 M0/M1 与 closed-shadow ground truth。
4. 把文件级 materialize 接入生产对象存储 retention/TTL worker；当前只生成新的本地 sidecar 副本。
5. S06 已拆出轻量 navigation-only probe；后续仅做小量重复，不增加全局重试。
6. 在 P1 结构信号与跨浏览器边界验收通过后，才进入 P2 的 partial delivery 和 detector 状态接入。

## 6. 不得宣称

- 不得把本 shadow 实现写成 P1 已完成生产验收。
- 不得把受控 `_fixture_final` 结果写成真实站点准确率。
- 不得把 `OBSERVED` 字段写成已选权威或可发布字段。
- 不得把 30/180 天策略写成已部署的 TTL worker。
- 不得把本地 sidecar 写成生产数据库或远程证据存储。
- 不得把 content scope 写成整页等价；它只约束 URL、文本哈希和文本节点覆盖。
- 不得把 React/Dushu 的 strict 状态通过写成整页像素或全部布局几何通过；Dushu index-aligned 几何仍有 13px 最大差。
- 不得把并发启动写成 frame-synchronized rendering A/B；可选屏障仍是实验能力。
- 不得把同源 frame 递归写成全部 frame DOM 可见；跨源和 sandbox opaque frame 只有边界证据。
- 不得把 non-rendered tracker 的完整 inventory 写成 strict 输入；它保留为证据，可视状态门只使用可渲染 frame tree。
- 不得把 `dynamic-glyph` 归因写成 strict/content 通过，也不得忽略它仍存在结构差的事实。
- 不得把 `rendered-frame-boundary-equivalent` 写成整页、内容或 Figma 交付等价。
- 不得用 boundary 相同、URL 相同或 placeholder 相同证明 opaque frame 内部内容相等。
