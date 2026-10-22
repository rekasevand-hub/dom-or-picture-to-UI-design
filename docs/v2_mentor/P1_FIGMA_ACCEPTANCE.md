# P1 Figma 独立验收与真实编辑探针

> 状态：`acceptance-chain-implemented / canonical-figma-holdout-5-of-5-pass`，2026-10-21。  
> 范围：固定 canonical frame、真实 Figma readback、真实 Figma PNG、原生文本编辑探针和独立图片填充替换探针。  
> 结论：5 个 canonical Figma holdout 均在原冻结 policy 下通过独立四维验收；单行文本显式 `line-height` 已落地，Figma 图片 fill 字节与本地 payload SHA-256 一致，Auto Layout 父级传播已通过真实 probe。

## 1. 为什么新增独立验收器

旧 `figma_replay.py` 只输出整图像素差和回读树，不能回答：

- 文本是否真实存在且内容完整；
- 画板和语义节点的几何是否仍在容差内；
- 字体是否发生回退；
- 文本是否真的可编辑并触发布局变化；
- 图片填充是否可替换和恢复；
- 视觉指标是否掩盖了内容、字体或资产失败。

新链路把每个维度独立记录。任何必需维度失败或缺少证据，都不会被其他维度的通过抵消。

## 2. 输入合同

独立验收器要求以下真实产物：

- fixed canonical `12_design.json`；
- canonical `00_screenshot.png`；
- 真实 Figma `readback_tree.json`；
- 真实 Figma `figma_render.png`；
- canonical truth；
- 可选的 Figma `font_report.json`；
- 可选的 native text `edit_probe`；
- 可选的 image fill `asset_probe`。

所有输入都会记录绝对路径、字节数和 SHA-256。报告自身记录 `content_hash`。

实现：

- `src/app/services/rendering/figma_acceptance.py`
- `scripts/p1_figma_acceptance.py`

## 3. 冻结策略

结构策略：

- policy id：`p1-figma-structure/1.0`
- 文本起点容差：`1px`
- 容器、图片和非文本节点尺寸容差：`2px`
- 字号容差：`0.1px`
- 状态：`provisional`

视觉策略：

- policy id：`p1-figma-frame-v1`
- max mean：`3.0`
- max ink mean：`100.0`
- max over30：`2.5%`
- max bad pixels：`14000`
- 要求尺寸一致：`true`
- 状态：`provisional`

策略文件：

- `tests/fixtures/p1/canonical/figma_structure_policy.json`
- `tests/fixtures/p1/canonical/figma_visual_policy.json`

阈值只用于当前 canonical frame，不继承 SVG policy，也不外推到其他页面或 Figma 文件。

## 4. 检查维度

### 4.1 内容

- 比较 canonical text 与真实 Figma `TEXT.characters`；
- 检查缺失、多余和禁止出现的文本；
- 文本多集必须一一匹配；
- 内容失败直接阻断 structure。

### 4.2 几何

- 比较画板尺寸；
- 匹配文本、容器、图片、矩形和椭圆；
- 检查 semantic node count、root descendant membership、重叠节点的 paint order 和可见性；
- 文本检查起点与容器内包含关系；
- 非文本节点检查 `x/y/width/height`；
- 每个节点记录 expected、actual 和 delta。

### 4.3 字体

- 比较请求 family、实际 resolved family、style 和 fontSize；
- 记录每个文本节点的 bbox、bottom 和 center-y delta；
- generic CSS family 通过 Chromium `CSS.getPlatformFontsForNode` 记录实际平台 face；
- 只有单一平台字体时才替换为具体 family，多字体文本保持 `ambiguous-platform-font`；
- 字体检查不把 bbox 差异归因成字体引擎差异；
- 当前 scope 只能证明 resolved family/style/size，不证明最终 glyph identity。

### 4.4 原生文本编辑

真实探针必须证明：

- node type 保持 `TEXT`；
- characters 被修改；
- font face 保持；
- 节点本地 bbox 因内容变化；
- characters、font 和 bbox 恢复到原值。

Probe：

- `scripts/figma_edit_probe.py`
- bridge action：`set_text`

Auto Layout 父级重排仍未验证，报告中保持 `parent_layout_propagation=not-evaluated`。

### 4.5 资产

真实图片替换探针必须证明：

- node type 保持；
- IMAGE `imageHash` 改变；
- `scaleMode` 保持；
- 恢复后 hash 回到源图片 hash。

Probe：

- `scripts/figma_asset_probe.py`
- bridge action：`replace_image_fill`

## 5. Canonical frame 当前结果

验收报告：

`output/_p1_figma_acceptance_frame_round14/figma_acceptance.json`

| 维度 | 状态 | 证据 |
|---|---|---|
| structure | `pass` | 4/4 文本匹配；7/7 几何行通过；节点数量、顺序、可见性通过 |
| visual | `pass` | `mean=1.9057`、`ink_mean=79.5434`、bad pixels `11477` |
| edit | `pass` | native text 编辑通过；字体解析为 Microsoft YaHei |
| asset | `not-required` | canonical frame 不包含图片资产 |

整体：

```text
acceptance_status: pass
blocking_dimensions: []
figma_attempted_count: 1
figma_evaluated_count: 1
composite_score_used: false
```

视觉指标排除了 `38400` 个 opaque frame 内部像素。Figma 仍与 canonical 参考存在整图和抗锯齿差异，不能写成逐像素等价。

字体逐节点结果：

- h1：Times New Roman / Bold / 32，通过；
- 普通段落：Times New Roman / Regular / 16，通过；
- accessible child 文本：请求 `sans-serif`，Chromium 与 Figma 均使用 Microsoft YaHei / Regular / 16；
- frame 边界说明：Times New Roman / Regular / 16，通过。

### 5.1 Canonical asset sample

验收报告：

`output/_p1_figma_assets_acceptance_round3/figma_acceptance.json`

| 维度 | 状态 | 证据 |
|---|---|---|
| structure | `pass` | 2/2 文本、3/3 图片节点和几何通过 |
| visual | `pass` | `mean=0.8587`、`ink_mean=13.8883`、bad pixels `6726` |
| edit | `pass` | native text 编辑与恢复通过 |
| asset | `pass` | 3/3 IMAGE fill、3/3 payload SHA-256、替换探针通过 |

整体：

```text
acceptance_status: pass
figma_evaluated_count: 1
payload_sha256_status: pass
replacement_probe: pass
composite_score_used: false
```

`image_fill_report` 从真实 Figma 节点读取 fill 原始字节，并与各 DesignSpec `imageBase64` 解码后的 SHA-256 逐项比较。该检查证明 Figma 收到的本地渲染 payload 未变化；它仍不证明这些 PNG payload 与原始 SVG source bytes 身份相同。

### 5.2 Figma holdout 汇总

历史聚合报告：

`output/_p1_figma_holdout_round1/round1.json`

当前聚合报告：

`output/_p1_figma_holdout_round2/round1.json`

| 样例 | 状态 | 结果 |
|---|---|---|
| holdout-frame | `pass` | structure/visual/edit pass；asset not-required |
| holdout-assets | `pass` | 四维 pass；3/3 payload SHA-256 pass |
| holdout-text | `pass` | structure/visual/edit pass；asset not-required |
| holdout-overlay | `pass` | 四维 pass；本地 payload SHA-256 pass |
| holdout-remote-asset | `pass` | 四维 pass；payload SHA-256 pass |

汇总：

```text
sample_count: 5
pass_count: 5
blocked_count: 0
figma_evaluated_count: 5
composite_score_used: false
```

round1 中 `holdout-remote-asset` 的视觉失败指标只有 `bad_pixel_count=14520 > 14000`；该历史失败保留。round2 在不修改阈值的前提下，`bad_pixel_count` 降为 `12769`，`mean=1.4795`、`over30=2.0268%`，四维通过。差异集中在文字行盒/抗锯齿，不是远程资产 fill。

### 5.3 单行文本 line-height 修复

根因：

- 多行文本分支原先会设置显式 `lineHeight`，单行文本被落到 Figma 默认行盒；
- Figma 默认行盒使字形相对 Chromium CSS 行盒整体偏上；
- 远程资产样例逐区域分析显示图片区域逐像素差为 0，全部超阈值差异位于三行文本；
- 三行文本的最佳垂直修正分别约为 `2px / 1px / 2px`；离线按元素最佳竖向位移重放后，`bad_pixel_count` 从 `14520` 降到 `11088`，证明主因是竖向行盒映射而非资产边缘。

修复：

- `figma_bridge/code.js` 在进入单行/多行分支前统一应用显式 `lineHeight`；
- 不修改 DesignSpec、reference、fixture truth 或 frozen visual policy；
- 行为测试：`tests/v2/test_figma_bridge_text_metrics.py` 与 `tests/bridge/test_text_line_height.js`。

当前五样例视觉结果：

| 样例 | mean | ink_mean | over30 % | bad pixels | 结果 |
|---|---:|---:|---:|---:|---|
| frame | 1.9057 | 79.5434 | 1.9400 | 11477 | pass |
| assets | 0.7092 | 11.9635 | 1.0084 | 6353 | pass |
| text | 1.4193 | 58.8138 | 2.0103 | 12665 | pass |
| overlay | 1.0270 | 33.0558 | 1.5454 | 9736 | pass |
| remote-asset | 1.4795 | 32.6628 | 2.0268 | 12769 | pass |

`holdout-text` 首次热重载后的独立运行曾出现 `212 -> 242` 的宽度瞬态并导致一次 restore probe 失败。该失败报告保留在 `output/_p1_figma_text_edit_probe_round2/`；随后两次独立重放均稳定为 `242×40`，编辑恢复通过。最终聚合只使用稳定重放，不把瞬态失败删除或改写成 pass。

## 6. 真实编辑和资产探针结果

Native text：

- 报告：`output/_p1_figma_edit_probe_round5/figma_edit_probe.json`
- node：`28:18`
- 修改后宽度从 `306` 到 `561`
- 字体保持 Times New Roman / Bold
- 已恢复原文和原 bbox
- `status=pass`

远程资产与 text holdout 的最新编辑探针：

- `output/_p1_figma_remote_asset_edit_probe_round2/figma_edit_probe.json`
- `output/_p1_figma_text_edit_probe_round3/figma_edit_probe.json`
- `output/_p1_figma_overlay_edit_probe_round2/figma_edit_probe.json`
- 三者均为 `status=pass`

Auto Layout parent propagation：

- 报告：`output/_p1_figma_autolayout_edit_probe_round1/figma_autolayout_edit_probe.json`
- probe root：`26:135`
- 初始：frame height `120`、text height `36`、sibling y `64`
- 编辑后：frame height `156`、text height `72`、sibling y `100`
- 恢复后：全部回到初始值
- `status=pass`

Image fill replacement：

- 报告：`output/_p1_figma_asset_probe_round4/figma_asset_probe.json`
- node：`24:107`
- source/replacement image hash 不同
- scaleMode 保持 `FILL`
- 恢复后回到 source hash
- `status=pass`

资产探针使用独立 owned root `P1 Asset Probe Root`，不依赖 canonical frame 的资产数量。canonical asset sample 另行通过 `image_report.json` 校验本地 payload SHA-256。

## 7. 复现命令

Canonical frame 验收：

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
  --out output\_p1_figma_acceptance_frame_round14
```

Native text probe：

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe scripts\figma_edit_probe.py `
  --readback output\_p1_figma_canonical_frame_round2\readback_tree.json `
  --out output\_p1_figma_edit_probe_round4
```

Asset replacement probe：

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe scripts\figma_asset_probe.py `
  --out output\_p1_figma_asset_probe_round4
```

Canonical asset acceptance：

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe scripts\p1_figma_acceptance.py `
  --design output\_p1_canonical_visual_holdout_round16\samples\holdout-assets\12_design.json `
  --truth tests\fixtures\p1\canonical\holdout\assets.truth.json `
  --readback output\_p1_figma_assets_round2\readback_tree.json `
  --reference output\_p1_canonical_visual_holdout_round16\samples\holdout-assets\00_screenshot.png `
  --render output\_p1_figma_assets_round2\figma_render.png `
  --font-report output\_p1_figma_assets_round2\font_report.json `
  --visual-policy tests\fixtures\p1\canonical\figma_visual_policy.json `
  --structure-policy tests\fixtures\p1\canonical\figma_structure_policy.json `
  --edit-probe output\_p1_figma_assets_edit_probe_round2\figma_edit_probe.json `
  --asset-probe output\_p1_figma_asset_probe_round4\figma_asset_probe.json `
  --image-report output\_p1_figma_assets_round2\image_report.json `
  --parent-layout-probe output\_p1_figma_autolayout_edit_probe_round1\figma_autolayout_edit_probe.json `
  --out output\_p1_figma_assets_acceptance_round3
```

## 8. 当前边界

- 视觉策略是当前 frame 的 provisional policy，没有跨样本校准。
- 字体 identity 只证明 Figma resolved family/style/size，不证明最终 glyph 来源。
- 抗锯齿差异保留在 visual，不与字体度量混算。
- Auto Layout probe 覆盖当前垂直固定宽度流式布局；Grid、wrap、component 和复杂嵌套传播仍未验证。
- Asset payload 检查证明 Figma 本地 fill 字节，不证明原始 SVG source bytes 身份。
- 当前只覆盖单 Figma 文档、单 Windows 环境、单 client。
- Bridge 仍缺 request id、事务、回滚、并发隔离和完整恢复语义。

## 9. 不得宣称

- 不得把当前 5 个 canonical holdout 写成所有 Figma 页面或所有场景已通过。
- 不得把该结果外推到其他 Figma 文档、平台或未采集的字体栈。
- 不得把单一字体解析写成 mixed-font glyph identity 已证明。
- 不得把 visual pass 抵消 edit fail。
- 不得在看到结果后回调查冻结阈值；本次修复未修改 `tests/fixtures/p1/canonical/figma_visual_policy.json`。
- 不得把当前 Auto Layout probe 写成所有 Auto Layout、Grid、wrap 或 component 传播行为通过。
- 不得把本地 PNG payload SHA-256 写成原始 SVG source identity 已完成。

## 10. 验证状态

- 全量 unittest：`226/226 passed`；
- `ruff check`：通过；
- `ruff format --check`：通过；
- `py_compile`：通过；
- `node --check figma_bridge/code.js`：通过。

最终聚合报告：`output/_p1_figma_holdout_round2/round1.json`。
