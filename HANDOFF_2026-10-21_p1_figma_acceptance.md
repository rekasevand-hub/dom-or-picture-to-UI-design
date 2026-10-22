# HANDOFF - P1 Figma 独立验收、平台字体与 Auto Layout 传播

**日期：** 2026-10-21  
**工作目录：** `D:\LLM-Data\Figma_auto_agent`  
**分支：** `feature/precise-agent-router`  
**状态：** 5 个 canonical Figma holdout 均为独立四维 pass；原冻结 visual policy 未修改  
**仓库状态：** 未 commit、未新建分支；工作树有大量本轮之前就存在的 modified/deleted/untracked 文件

---

## 1. 一句话状态

当前 fixed canonical 环境下，SVG holdout 为 `5/5`，Figma canonical holdout 为 `5 pass / 0 blocked`。单行文本显式 CSS `line-height` 现在会写入 Figma；remote-asset 的 `bad_pixel_count` 从 `14520` 降到 `12769`，在原 `14000` 阈值下通过。Auto Layout 父级传播已用真实 Figma probe 证明，`sans-serif` 已通过 Chromium platform-font provenance 解析为 Microsoft YaHei。

---

## 2. 新会话必读顺序

1. 本文件：当前状态、证据、边界和下一步。
2. `docs/v2_mentor/P1_FIGMA_ACCEPTANCE.md`：Figma 验收合同、真实探针和当前结果。
3. `docs/v2_mentor/P1_CANONICAL_OUTPUT_FIDELITY.md`：canonical 环境、SVG/Figma 目标与历史修复。
4. `output/_p1_figma_holdout_round2/round1.json`：当前 5 个 Figma holdout 的聚合结论。
5. `output/_p1_figma_acceptance_frame_round15/figma_acceptance.json`：canonical frame 四维报告。
6. `output/_p1_figma_assets_acceptance_round4/figma_acceptance.json`：canonical assets 四维报告。
7. `HANDOFF_2026-10-21_p1_frame_figma.md`：更早的 frame holdout 修复与 bridge 演进记录。

---

## 3. Canonical 基线

| 项目 | 当前值 |
|---|---|
| Engine | Chromium |
| Browser build | `151.0.7922.34` |
| OS | Windows 11 `10.0.26300` |
| Viewport | `900 x 700` |
| DPR | `1` |
| Locale | `zh-CN` |
| Timezone | `Asia/Shanghai` |
| Headless | `true` |
| Python | `C:\Users\lzq\.conda\envs\omni\python.exe` |
| Python version | `3.12.0` |
| Capture contract | `capture_page_with_fallback+dom-direct-svg` |

结论只适用于这套固定环境和当前 authored/controlled 样例，不能外推到任意真实站点。

---

## 4. 当前 Figma 验收矩阵

| 样例 | Structure | Visual | Edit | Asset | Overall |
|---|---|---|---|---|---|
| holdout-frame | pass | pass | pass | not-required | pass |
| holdout-assets | pass | pass | pass | pass | pass |
| holdout-text | pass | pass | pass | not-required | pass |
| holdout-overlay | pass | pass | pass | pass | pass |
| holdout-remote-asset | pass | pass | pass | pass | pass |

聚合：

```text
sample_count: 5
pass_count: 5
blocked_count: 0
figma_evaluated_count: 5
composite_score_used: false
```

关键视觉指标：

| 样例 | mean | ink_mean | over30 % | bad pixels |
|---|---:|---:|---:|---:|
| frame | 1.9057 | 79.5434 | 1.9400 | 11477 |
| assets | 0.7092 | 11.9635 | 1.0084 | 6353 |
| text | 1.4193 | 58.8138 | 2.0103 | 12665 |
| overlay | 1.0270 | 33.0558 | 1.5454 | 9736 |
| remote-asset | 1.4795 | 32.6628 | 2.0268 | 12769 |

Frozen visual policy：

```text
max_mean: 3.0
max_ink_mean: 100.0
max_over30_pct: 2.5
max_bad_pixel_count: 14000
require_size_match: true
```

round1 的 remote-asset 失败是真实历史结果；round2 在未修改阈值的前提下修复了单行文本行盒。图片区域逐像素差为 0，超阈值差异仍全部位于文字；剩余视觉差继续按抗锯齿边界保留。

---

## 5. 本轮新增能力

### 5.1 Chromium platform-font provenance

实现：

- `src/app/services/structure/font_provenance.py`
- `src/app/services/structure/capture.py`
- `src/app/services/structure/frames.py`
- `src/app/services/structure/providers/dom.py`
- `src/app/services/som/direct_design.py`

流程：

1. `DOM_JS` 只为 generic font stack 文本写临时 probe marker。
2. Chromium CDP 调用 `CSS.getPlatformFontsForNode`。
3. 单一平台字体时，把 CSS generic family 替换成实际 face。
4. 保存：
   - `fontFamilyRequested`
   - `fontFamilyResolution`
   - `platformFonts`
5. 多字体文本保持 `ambiguous-platform-font`，不强行压成一个 face。
6. 探针结束后移除 temporary marker，包括开放 Shadow DOM。

当前 canonical frame：

```text
sans-serif -> Microsoft YaHei
```

Figma 的实际字体回读也为 Microsoft YaHei / Regular / 16。

### 5.2 Figma 四维验收器

核心：

- `src/app/services/rendering/figma_acceptance.py`
- `scripts/p1_figma_acceptance.py`

独立检查：

- 内容：真实 TEXT characters、缺失/多余文本；
- 结构：canvas、semantic node count、root descendant membership、重叠节点 paint order、visibility、bbox；
- 字体：CSS requested family、resolved family、实际 face、style、size、bbox delta；
- 编辑：native text 修改、字体保持、本地 bbox 响应、恢复；
- 资产：IMAGE fill、节点几何、payload SHA-256、替换/恢复；
- 视觉：frozen policy 下的独立视觉门禁。

不使用 composite score。视觉通过不能补偿内容、结构、编辑或资产失败。

### 5.3 Figma image payload identity

新增 bridge action：

```text
image_fill_report
```

`figma_replay.py` 会写 `image_report.json`。验收器将 Figma IMAGE fill 的原始字节与 DesignSpec `imageBase64` 解码后的 SHA-256 比较。

canonical assets：

```text
3/3 IMAGE fill
3/3 payload SHA-256
replacement/restore: pass
```

边界：这只证明本地 PNG payload 身份，不证明原始 SVG source bytes 身份。

### 5.4 Auto Layout 父级传播

实现：

- `scripts/figma_autolayout_edit_probe.py`

真实结果：

```text
text height:    36 -> 72
sibling y:      64 -> 100
parent height:  120 -> 156
restore:        pass
```

probe root 使用实验 action `set_layout_flow`。它证明当前垂直固定宽度 Auto Layout 的文本变更传播；不证明 Grid、wrap、component、复杂嵌套或生产 `set_autolayout` 的通用传播。

### 5.5 独立画板命名

`scripts/figma_replay.py` 新增：

```text
--screen-name
```

每个样例使用独立根名，避免重放时删除已经通过的 canonical frame。

当前已创建的 Figma 根包括：

- `Screen 900×700 · 6/11 (100%)`
- `P1 Assets Acceptance`
- `P1 Text Acceptance`
- `P1 Overlay Acceptance`
- `P1 Remote Asset Acceptance`
- `P1 Auto Layout Edit Probe`
- `P1 Asset Probe Root`
- `SmokeB Root`
- `P1 Frame Acceptance R3`
- `P1 Assets Acceptance R4`
- `P1 Text Acceptance R3`
- `P1 Overlay Acceptance R3`
- `P1 Remote Asset Acceptance R2`

不要批量删除这些根节点，除非用户明确要求并确认用途。

### 5.6 单行文本 line-height 落地

实现：

- `figma_bridge/code.js`
- `tests/v2/test_figma_bridge_text_metrics.py`
- `tests/bridge/test_text_line_height.js`

根因是显式 `lineHeight` 原先只在多行分支设置，单行块级文本使用 Figma 默认行盒，字形相对 Chromium 偏上。修复在单行/多行分支之前统一应用 `lineHeight`，未修改 DesignSpec、reference、truth 或 frozen policy。

离线定位证据：

- remote-asset 图片区域 `changed=0`、`bad=0`；
- 三行文本最佳竖向修正约为 `2px / 1px / 2px`；
- 离线按元素最佳竖向位移重放后，`bad_pixel_count` 从 `14520` 降到 `11088`，确认主因是行盒映射。

真实 Figma 结果：

- remote-asset：`mean 1.9694 -> 1.4795`，`bad 14520 -> 12769`，四维 pass；
- assets：`bad 6726 -> 6353`；
- text：`bad 13992 -> 12665`；
- overlay：`bad 10917 -> 9736`；
- frame：通过且指标不变。

环境瞬态：

- `holdout-text` 首次热重载后独立运行曾出现文本宽度 `212 -> 242`，导致一次 restore probe 失败；
- 失败报告保留在 `output/_p1_figma_text_edit_probe_round2/`；
- 随后两次独立重放稳定为 `242×40`，编辑恢复 pass；
- 该瞬态限制了“任意首次热重载均可稳定恢复”的声明。

---

## 6. 验证结果

最终命令：

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe -m unittest discover -s tests -p "test*.py" -v
```

结果：

```text
226/226 passed
```

其他检查：

- `ruff check`：通过；
- `ruff format --check`：新增文件通过；
- `py_compile`：通过；
- `node --check figma_bridge\code.js`：通过；
- `git diff --check`：无 blank/whitespace error。

测试日志：

- `output/_p1_figma_holdout_round2/unittest-final.log`

日志中会看到一条负向测试预期输出：

```text
[FAIL] artifact must contain a JSON object
```

该用例测试 CLI 对非对象 JSON 的拒绝，unittest 本身通过。

---

## 7. 关键证据与哈希

| 证据 | 状态 | evaluated | content_hash |
|---|---|---:|---|
| `output/_p1_figma_acceptance_frame_round15/figma_acceptance.json` | pass | 1 | `3af574422e62e27263e803add46f86c2f31f49c1baa557ef037a5996d775698a` |
| `output/_p1_figma_assets_acceptance_round4/figma_acceptance.json` | pass | 1 | `645500b55b8a042315e4d14167199292b2c72fbe401c810060c3645e72aab3e7` |
| `output/_p1_figma_text_acceptance_round3/figma_acceptance.json` | pass | 1 | `084671290d5db71f50aba66fc7394bc753fd7ae2d5053d6411067a422a43a1be` |
| `output/_p1_figma_overlay_acceptance_round3/figma_acceptance.json` | pass | 1 | `22f1981c1b52d58b6497fc3829c6719ea520547ce31c7f39ceba6c79f877181c` |
| `output/_p1_figma_remote_asset_acceptance_round2/figma_acceptance.json` | pass | 1 | `ad6800cfe0e4a9cbbfcacee5a3ca4cdc708f2610af99e06f9362cfff17b7ec68` |
| `output/_p1_figma_holdout_round2/round1.json` | 5 pass / 0 blocked | 5 | `acbc80ef851bd8bfe1864a787b4d17b868233dc4f55c7230efd394b443bca389` |
| `output/_p1_figma_autolayout_edit_probe_round1/figma_autolayout_edit_probe.json` | pass | - | `96743b9653ce7b35dd1a1485827c66ea91ce0585460e1e380a14a78f426a1ca1` |

历史失败证据保留：

- `output/_p1_figma_remote_asset_acceptance_round1/figma_acceptance.json`：`blocked-fail`，content hash `e03062291c366de6bdec23e314998a2cdf1400d677b9a2fc460227f9acadde54`；
- `output/_p1_figma_holdout_round1/round1.json`：`4 pass / 1 blocked`，content hash `a2e9aa0e0cf7c5c195769c9e30e8f95c082b6fcb0a8acab6ad82b60a91323aa9`；
- `output/_p1_figma_text_edit_probe_round2/figma_edit_probe.json`：一次 `212 -> 242` 宽度瞬态导致 restore fail。

其他输入：

- canonical holdout：`output/_p1_canonical_visual_holdout_round16/round1.json`
- calibration：`output/_p1_canonical_output_fidelity_round17/round1.json`
- Figma canonical frame replay：`output/_p1_figma_canonical_frame_round3/`
- Figma assets replay：`output/_p1_figma_assets_round3/`
- Figma text replay：`output/_p1_figma_text_round3/`
- Figma overlay replay：`output/_p1_figma_overlay_round2/`
- Figma remote replay：`output/_p1_figma_remote_asset_round2/`

---

## 8. 当前 bridge 与 Figma 环境

写入本文件时：

- 本轮真实重放时 bridge 已监听，Figma 插件连接成功；
- Figma 桌面端已运行；
- 新会话仍应现场检查端口与 Established 状态，不能假定连接一直存在。

启动 bridge：

```powershell
$out = 'output\_p1_figma_bridge'
New-Item -ItemType Directory -Force -Path $out | Out-Null
Start-Process `
  -FilePath 'C:\Users\lzq\.conda\envs\omni\python.exe' `
  -ArgumentList @('-m','src.app.services.bridge_server') `
  -WorkingDirectory 'D:\LLM-Data\Figma_auto_agent' `
  -WindowStyle Hidden `
  -RedirectStandardOutput "$out\bridge.stdout.log" `
  -RedirectStandardError "$out\bridge.stderr.log"
```

检查：

```powershell
Get-NetTCPConnection -LocalPort 8765 -ErrorAction SilentlyContinue
Get-Content -Raw output\_p1_figma_bridge\bridge.stdout.log
```

只有看到已建立的 plugin connection 后再运行真实写入。

---

## 9. 复现命令

### 9.1 Figma 最小烟测

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe scripts\figma_readback_smoke.py `
  --out output\_p1_figma_smoke_rerun
```

### 9.2 Canonical holdout

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe scripts\p1_canonical_output_fidelity.py `
  --manifest tests\fixtures\p1\canonical\holdout\manifest.json `
  --out-root output\_p1_canonical_visual_holdout_round17
```

### 9.3 Figma frame 四维

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe scripts\p1_figma_acceptance.py `
  --design output\_p1_canonical_visual_holdout_round16\samples\holdout-frame\12_design.json `
  --truth tests\fixtures\p1\canonical\holdout\frame.truth.json `
  --readback output\_p1_figma_canonical_frame_round2\readback_tree.json `
  --reference output\_p1_canonical_visual_holdout_round16\samples\holdout-frame\00_screenshot.png `
  --render output\_p1_figma_canonical_frame_round2\figma_render.png `
  --font-report output\_p1_figma_canonical_frame_round2\font_report.json `
  --visual-policy tests\fixtures\p1\canonical\figma_visual_policy.json `
  --structure-policy tests\fixtures\p1\canonical\figma_structure_policy.json `
  --edit-probe output\_p1_figma_edit_probe_round4\figma_edit_probe.json `
  --parent-layout-probe output\_p1_figma_autolayout_edit_probe_round1\figma_autolayout_edit_probe.json `
  --out output\_p1_figma_acceptance_frame_rerun
```

### 9.4 Holdout 聚合

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe scripts\p1_figma_holdout_summary.py `
  --report output\_p1_figma_acceptance_frame_round14\figma_acceptance.json `
  --report output\_p1_figma_assets_acceptance_round3\figma_acceptance.json `
  --report output\_p1_figma_text_acceptance_round1\figma_acceptance.json `
  --report output\_p1_figma_overlay_acceptance_round2\figma_acceptance.json `
  --report output\_p1_figma_remote_asset_acceptance_round1\figma_acceptance.json `
  --out output\_p1_figma_holdout_rerun
```

### 9.5 Auto Layout probe

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe scripts\figma_autolayout_edit_probe.py `
  --out output\_p1_figma_autolayout_edit_probe_rerun
```

---

## 10. 已知风险与不得宣称

### 10.1 Visual

- Figma visual policy 是 provisional，只适用于当前 900x700 canonical scope；
- remote-asset round1 的 `bad_pixel_count=14520` 是真实历史 fail，round2 在原阈值下通过；
- 图片区域逐像素差为 0，剩余差异集中在文字栅格化；
- 没有 glyph mask 归因，不能写成字体引擎已完全解释；
- `holdout-text` 首次热重载后的宽度瞬态仍保留为环境风险；
- 不得在看到新结果后回调冻结阈值。

### 10.2 Font

- 当前证明了 Chromium resolved platform family 和 Figma resolved family/style/size；
- 未证明最终 glyph identity 或 bit-exact glyph source；
- mixed-font run 保持 ambiguous，不能强行选择单一字体；
- 未知字体策略、跨平台字体库和字体版本差异仍未覆盖。

### 10.3 Auto Layout

- 当前只覆盖垂直固定宽度、AUTO height、文本高度增长和 sibling/parent 重排；
- Grid、wrap、component、复杂嵌套、约束冲突和恢复失败未覆盖；
- 使用实验 `set_layout_flow`，不是生产 `set_autolayout` 语义。

### 10.4 Asset

- canonical assets 的本地 PNG payload SHA-256 已通过；
- 原始 SVG source bytes 的 Figma 内部身份未证明；
- data URI、本地 source identity、source crop 和 display payload 是不同证据层，不能混写；
- remote 生产站点下载、SSRF、CDN 变化和跨域策略未覆盖。

### 10.5 Bridge

- 服务端仍是单 `_plugin_ws` / 单 inbox；
- 无 request id 一对一关联；
- 无生产级并发、事务、幂等、回滚和恢复；
- 父节点缺失语义仍需 fail-closed 强化；
- 当前仅适合本地单客户端实验。

### 10.6 Repository

- 工作树有大量既存 modified/deleted/untracked 文件；
- 不要执行 `git reset --hard`、`git checkout --`、`git clean`；
- 不要批量删除 `output/`、Figma 登录态或已有画板；
- 不要自动 commit、push、建分支或建 PR，除非用户明确要求。

---

## 11. 下一步优先级

### P1：已完成当前范围

- 单行文本显式 `line-height` 已落地；
- remote-asset 在原冻结 policy 下通过；
- 5 个 canonical Figma holdout 为 `5 pass / 0 blocked`；
- 历史失败和 text 宽度瞬态均保留。

### P2：扩大 Figma holdout（下一步）

- DPR 2；
- 移动视口；
- 多行和 font fallback；
- iframe nested；
- transparent crop；
- partial-asset；
- fallback/missing font；
- mixed-font run。

### P3：完善编辑能力

- Grid/wrap Auto Layout；
- component instance 与 override；
- parent/sibling 多级传播；
- partial edit failure 与恢复；
- 编辑权限、锁和并发冲突。

### P4：Bridge 生产化

- request id；
- response correlation；
- 多客户端隔离；
- plugin 断连/重连状态；
- parent missing fail-closed；
- ownership marker；
- 幂等、事务、回滚和 partial-write 报告。

### P5：真实站点持续观测

- 冻结 canonical profile；
- 真实站点只作为外部有效性观测；
- 动态站点状态变化不直接当产品回归失败。

---

## 12. 新会话启动检查

1. 运行 `git status --short --branch`，不要清理工作树。
2. 阅读本文件与 `docs/v2_mentor/P1_FIGMA_ACCEPTANCE.md`。
3. 检查 `127.0.0.1:8765` 是否监听。
4. 未监听时启动 bridge。
5. 在 Figma Development 中 Run/Reload `UI Reconstruct Bridge`，确认 Established。
6. 先跑最小烟测，再跑对应 holdout。
7. 每个样例使用独立 `--screen-name`。
8. 资产样例必须提供 `image_report.json` 和 asset probe。
9. 编辑验收需带 local edit probe 与 parent-layout probe。
10. 任何新阈值先冻结再运行，失败后不回调。
11. Figma 通过不能回写为 SVG 通过，反之亦然。

---

## 13. 当前最终结论

- SVG canonical holdout：`5/5` 视觉通过；
- 5 个 canonical Figma 样例均为 structure/visual/edit 及所需 asset 维度通过；
- Figma 总 holdout：`5 pass / 0 blocked`，`figma_evaluated_count=5`；
- remote-asset：`bad_pixel_count 14520 -> 12769`，未修改 `14000` 阈值；
- canonical assets：3/3 payload SHA-256 通过；
- 全量 unittest：`226/226 passed`；
- 下一目标是 P2 扩面：DPR 2、移动视口、多行/fallback、iframe、裁剪与 mixed-font。
