# P2 Figma 扩面：DPR、移动、字体、frame 与资产边界

> 状态：`p2-current-scope-completed / p2-extended-current-scope`，2026-10-21。  
> 范围：DPR 2、移动视口、字体、mixed run、nested iframe、transparent crop、partial asset、真实站点观测。  
> 结论：11 个独立 P2 Figma holdout 为 `10 pass + 1 partial + 0 blocked`；字体和真实站点扩展边界见 `P2_EXTENDED_CLOSURE.md`。

## 1. 本轮目标

P1 只覆盖固定 `900×700`、DPR 1 和五个 canonical 样例。P2 验证以下容易破坏输出语义的边界：

- 物理截图像素与 DesignSpec 逻辑坐标分离；
- 非白画布的 SVG/Figma 背景；
- missing-font fallback 下的原生文本、几何和编辑能力。
- 同一段落内的 mixed family/weight run 与边界空白；
- 两层嵌套可访问 frame；
- 透明覆盖与右半裁片；
- 一个有效资产加一个缺失资产槽的 partial delivery。
- italic / oblique 与 variable named instance；
- ambiguous 多平台字体 fallback；
- 320–430 移动宽度矩阵；
- React、Dushu、Shoelace 与 W3Schools 有界真实站点观测。

## 2. 关键修复

### 2.1 DPR 2 逻辑坐标

实现：

- `src/app/utils/svg_raster.py`
- `src/app/services/rendering/text_align.py`
- `src/app/services/som/direct_design.py`
- `src/app/services/som/design_crops.py`
- `src/app/agents/precise_agent.py`

规则：

- DesignSpec 画布保持 CSS 逻辑尺寸，例如 DPR 2 的 `900×700`；
- 浏览器截图保持物理尺寸，例如 `1800×1400`；
- SVG 栅格化使用同一 DPR，输出 `1800×1400`；
- 图片裁剪把逻辑 bbox 映射到物理截图；
- 文本基线微调按 DPR 缩放元素框和 `±DPR` 位移；
- Figma 回放 DPR 2 时使用 `figma_replay.py --scale 2`；
- 逻辑画布和像素比写入 DesignSpec：`canvas=900×700`、`_meta.pixelRatio=2`。

### 2.2 画布背景

- `SVGMockAdapter` 现在会为非白 `backgroundColor` 输出底层 rect；
- Figma `create_frame` 同时接受 `fillColor` 与 `backgroundColor`；
- 白背景保持旧输出语义，不额外改变历史 SVG 字节。

### 2.3 跨视口视觉策略

P2 canonical policy：

`tests/fixtures/p1/canonical/p2/visual_policy_dpr_aware.json`

规则：

- `max_mean`、`max_ink_mean`、`max_over30_pct` 和尺寸匹配继续门禁；
- `bad_pixel_count` 保留为观测值，但跨 DPR/视口不按绝对像素数门禁；
- 原因是绝对计数同时受面积和字体墨量影响，不能用一个面积缩放同时适配大 DPR 与小视口。

Figma flat policy：

`tests/fixtures/p1/canonical/p2/figma_visual_policy.json`

- DPR 2 与 missing-font 使用 P1 Figma 比例边界；
- 绝对 `bad_pixel_count` 只记录，不门禁。

Mobile policy：

`tests/fixtures/p1/canonical/p2/figma_mobile_visual_policy.json`

- `max_mean=3.0`；
- `max_ink_mean=55.0`；
- `max_over30_pct=3.5`；
- 绝对 `bad_pixel_count` 只记录；
- 先用 `mobile-layout` calibration，再冻结并用独立 `360×800` mobile holdout 验证。

Mixed-font policy：

`tests/fixtures/p1/canonical/p2/figma_mixed_font_visual_policy.json`

- calibration 后冻结；
- 两个不同视口和文案的独立 mixed-font holdout 验证；
- 只覆盖显式 family/weight run，不覆盖 italic 或最终 glyph identity。

### 2.4 Mixed-font run

- DOM capture 保留 run 的首尾空白；
- SVG 对边界空白输出 `xml:space="preserve"`；
- parent 文本、Times run、中文回退分别保留为原生 TEXT 节点；
- Figma acceptance 允许 measured run 使用完整 `lineHeight × textEmLines` 行盒高度。

### 2.5 Nested iframe

- file:// 子 frame 是 opaque origin，失败作为边界证据保留；
- 递归 holdout 使用两层 `srcdoc`，确认 depth 1 与 depth 2 都可访问；
- child/grandchild 文本均进入 DesignSpec、SVG 和真实 Figma。

### 2.6 Transparent crop

- 右侧裁片、半透明覆盖和白色文字均通过；
- source crop、display box、local payload SHA-256 和替换探针分别通过；
- 不改动全局 z-order 结论。

### 2.7 Partial asset

- 有效资产与缺失槽分开记录；
- `minimum_asset_count` 满足时资产维度保持 `partial`；
- 整体 `acceptance_status=partial`，`acceptance_passed=true`，并计入 evaluated；
- holdout summary 单独统计 `partial_count`，不混入 pass 或 blocked。

### 2.8 Extended closure

详见：`P2_EXTENDED_CLOSURE.md`。

- italic 与 bold italic 通过；
- variable named instances 可解析，任意 axis 保持 unsupported；
- ambiguous fallback 保留双平台字体并 fail-closed；
- 320/375/430 移动 calibration + 412 独立 holdout 通过；
- React/Dushu 当前 comparison profile equivalent，Shoelace different，W3Schools inconclusive；
- Firefox 环境仍为 `spawn UNKNOWN`，未用其他引擎替代。

## 3. Canonical 结果

| 样例 | 环境 | 结果 | 报告 |
|---|---|---|---|
| DPR2 text | `900×700 @2x` | pass | `output/_p2_dpr2_probe_round6/round1.json` |
| DPR2 assets | `900×700 @2x` | pass | `output/_p2_dpr2_probe_round6/round1.json` |
| mobile calibration | `390×844 @1x` | pass | `output/_p2_mobile_probe_round3/round1.json` |
| mobile holdout | `360×800 @1x` | pass | `output/_p2_mobile_holdout_probe_round2/round1.json` |
| missing-font holdout | `900×700 @1x` | pass | `output/_p2_font_holdout_probe_round1/round1.json` |
| mixed-font holdout A | `960×320 @1x` | pass | `output/_p2_mixed_font_holdout_probe_round2/round1.json` |
| mixed-font holdout B | `880×320 @1x` | pass | `output/_p2_mixed_font_holdout2_probe_round1/round1.json` |
| nested iframe | `900×500 @1x` | pass | `output/_p2_nested_iframe_probe_round3/round1.json` |
| transparent crop | `900×500 @1x` | pass | `output/_p2_transparent_crop_probe_round2/round1.json` |
| partial asset | `900×500 @1x` | partial | `output/_p2_partial_asset_probe_round1/round1.json` |
| italic font | `900×400 @1x` | pass | `output/_p2_italic_font_probe_round1/round1.json` |
| mobile 320/375/430 | mobile calibration | pass | `output/_p2_mobile_{320,375,430}_probe_round*/round1.json` |
| mobile 412 | mobile holdout | pass | `output/_p2_mobile_412_probe_round1/round1.json` |

DPR2 的截图和 SVG render 均为 `1800×1400`，DesignSpec 仍为 `900×700`。

## 4. Figma 结果

聚合报告：

`output/_p2_figma_holdout_round4/round1.json`

| 样例 | Structure | Visual | Edit | Asset | mean | over30 % | Overall |
|---|---|---|---|---:|---:|---|
| DPR2 text | pass | pass | pass | not-required | 1.4066 | 1.3079 | pass |
| DPR2 assets | pass | pass | pass | pass | 0.4833 | 0.5500 | pass |
| mobile holdout | pass | pass | pass | pass | 2.2322 | 3.4969 | pass |
| missing-font holdout | pass | pass | pass | not-required | 1.3992 | 2.0110 | pass |
| mixed-font holdout A | pass | pass | pass | not-required | 3.0292 | 3.1211 | pass |
| mixed-font holdout B | pass | pass | pass | not-required | 3.3266 | 3.4915 | pass |
| nested iframe | pass | pass | pass | not-required | 1.5786 | 2.4229 | pass |
| transparent crop | pass | pass | pass | pass | 1.0344 | 1.5749 | pass |
| partial asset | pass | pass | pass | partial | 1.0035 | 1.3862 | partial |
| italic font | pass | pass | pass | not-required | 2.0478 | 2.0422 | pass |
| mobile 412 | pass | pass | pass | pass | 1.4576 | 2.2025 | pass |

聚合：

```text
sample_count: 11
pass_count: 10
partial_count: 1
blocked_count: 0
figma_evaluated_count: 11
composite_score_used: false
content_hash: 34bbf5428fac46b9896e566251d92444eac978a305410829eb0bb5a4ddac8a9f
```

Mobile calibration 单独保留：

- `output/_p2_figma_mobile_calibration_acceptance_round1/figma_acceptance.json`
- mean `2.0856`、over30 `2.9475%`、bad `9702`
- calibration 不进入独立 holdout 聚合。

## 5. 已知瞬态与失败

- DPR2 第一次运行把物理截图尺寸当成 DesignSpec 画布，产生 `3600×2800` render；失败产物保留。
- old absolute `bad_pixel_count` 在 DPR2 assets 下出现 `7089 > 3000`；后续 policy 改为比例型门禁，历史失败不删除。
- missing-font calibration fixture 的 3 行文本放在 56px 盒中，发生文本重叠；P2 新建了行高正确的独立 holdout。
- mixed-script text 在 Figma 字体激活前可能出现宽度瞬态；稳定运行需要先激活字体，再回读和导出。
- file:// iframe 子页是 opaque origin，不能当作同源递归证据；P2 使用 srcdoc 验证 depth 2。
- italic 已落地；variable font 只支持命名实例，不能精确复现任意 axis。
- 多行文本高度大于设计盒时，桥接现在保持 top edge，不再负向居中。
- 当前仍不证明 Figma 最终 glyph identity 与 Chromium bit-exact。

## 6. 尚未完成

- 任意 variable axis 的 Figma 精确复现；
- ambiguous platform-font run 的逐 glyph face split；
- Firefox 字体渲染；
- 更多移动宽度与桌面 responsive breakpoint；
- Figma DPR2 的 image payload / crop identity 扩展矩阵；
- 跨 Figma 文档和跨平台字体库验证。

## 7. 验证

- 全量 unittest：`253/253 passed`；
- `node --check` 与三个 bridge 行为测试通过；
- `ruff check`、`ruff format --check`、`py_compile` 通过；
- `git diff --check` 无空白错误；
- 测试日志：`output/_p2_figma_holdout_round4/unittest-final.log`。

## 8. 不得宣称

- 不得把 11 个 P2 holdout 写成所有 DPR、移动端、字体或真实站点场景已通过。
- 不得把 absolute bad-pixel count 的取消门禁写成视觉要求降低。
- 不得把 missing-font fallback 写成 glyph identity 已验证。
- 不得把 mobile calibration 样本算入独立 holdout。
- 不得把稳定字体激活后的结果转发成首次回读也稳定。
- 不得把 partial asset 写成 complete pass。
- 不得把显式 mixed family/weight 写成 mixed glyph identity 已验证。
- 不得把 variable named instances 写成任意 axis 支持。
- 不得把 React 单次 equivalent 写成所有真实站点等价。
