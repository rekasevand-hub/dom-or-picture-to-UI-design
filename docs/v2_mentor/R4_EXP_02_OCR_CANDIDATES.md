# R4-EXP-02 · 真实 OCR/CV 候选接入 `screenshot-candidate` 通道（受控实验）

> 状态：`completed-for-current-scope`（2026-10-18），不是 `verified`。  
> 范围：1 个合成页面、12 个单行文本用例、1 个重复卡片标题块、5 个 CV 目标、25 条 OCR 候选、32 条 CV 轮廓候选、13 项检查。  
> 证据：`output/_r4_experiments/r4_ocr_candidates.json`、`output/_r4_experiments/r4_ocr_artifacts/ocr_candidates.json`、`cv_candidates.json`、`gate_results.json`、`capture_s0.png`、`crops/` 18 张裁片，以及 `r4_ocr_matrix.png`、`r4_gate_flow.png`、`r4_ocr_confidence.png`、`r4_cv_boxes.png`。  
> 边界：OCR 只在实验者给定的元素框内运行，不是端到端文本检测；CV 只给视觉框，不推断角色、可编辑性或原始资产。门限是实验合同值，不是通用标定。

## 1. 目的与边界

本实验回答五个问题：

1. 真实 Tesseract / EasyOCR 候选进入 `screenshot-candidate` 通道后，低置信度是否仍保持未验证。
2. 单引擎结果、双引擎分歧、重复文本和遮挡，是否都不能被自动升级为已验证事实。
3. 双引擎一致且达到门限时，能否只提升文本内容，而不提升 `editability / role / asset_source`。
4. OpenCV 轮廓框能否作为视觉候选参与几何核对，同时不宣称语义角色或原始资产。
5. 朴素“取最高置信度”策略是否会在本夹具上产生可测误升级。

本实验使用真实渲染的 1200×900 CSS 页面、DPR 2 截图和真实 OCR/CV 执行。它验证的是**候选门与字段边界**，不是 OCR 产品准确率、真实站点分布或生产交付能力。

未修改 `src/`、`figma_bridge/`，未执行 Figma 写入。

## 2. 环境与可复现性

| 项目 | 值 |
|---|---|
| 操作系统 | Windows 11（`10.0.26300`） |
| Python | 3.12.0（`C:\Users\lzq\.conda\envs\omni\python.exe`） |
| Chromium | 151.0.7922.34（Playwright headless） |
| Pillow | 12.2.0 |
| OpenCV | 4.10.0 |
| Tesseract | 5.5.0.20241111，`chi_sim+eng` |
| EasyOCR | 1.7.2，`["ch_sim", "en"]`，GPU（RTX 4060 Laptop） |
| 视口 / DPR | 1200×900 CSS px / 2 |
| 合成页面 | `output/_r4_experiments/r4_ocr_artifacts/site/index.html` |

重跑命令：

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe output/_r4_experiments/r4_ocr_candidates.py
```

脚本会重建页面、截图、18 张裁片、四份 JSON 与四张图；本次完整重跑约 6.1 秒（模型已缓存）。

## 3. 方法

### 3.1 夹具与裁片

- 12 个单行文本用例 `O01–O12`，覆盖清晰标题、混排、小字、低对比度、模糊、旋转、反白、遮挡、金额和重复块。
- 1 个重复卡片标题块 `O13`，块内两行文本均为 `重复卡片标题`。
- 5 个 CV 目标 `B01–B05`：按钮、卡片、徽标、封面、1 px 分隔线。
- 18 张裁片 = 12 个文本用例 + 1 个块用例 + 5 个 CV 目标；OCR 只读取前 13 张识别裁片。
- 每个裁片按 DPR 2 从真实截图裁出，四周各留 6 px；裁片只标 `pixel-crop-for-recognition`，`cannot_claim` 包含 `original-asset / native-editability / detected-identity`。

### 3.2 引擎

| 引擎 | 配置 | 输出 |
|---|---|---|
| Tesseract | 单行走 `--psm 7`，重复块走 `--psm 6`，`chi_sim+eng` | 文本、置信度、词框并集 |
| EasyOCR | `ch_sim + en`，GPU，关闭详细日志 | 文本、置信度、检测框 |
| OpenCV | 灰度 → Gaussian blur → Canny(40, 120) → 3×3 dilate → 轮廓外接框 | 视觉框候选，面积 3000 px²–50% 页面 |

- OCR 候选统一记录 `engine / engine_version / line_index / raw_text / normalized_text / confidence / bbox_crop / bbox_page_css / verified=false / editability=unverified / role=not-inferred`。
- CV 候选统一记录 `source=cv-contour / role=unknown / editability=not-observable / asset_source=flat-raster-crop`；`cannot_claim` 包含 `original-asset / native-editability / semantic-role / dom-identity`。

### 3.3 候选门

门顺序固定为：

1. `occlusion-gate`：遮挡比例 > 30% 直接阻断。
2. `two-engine-gate`：少于两个引擎返回候选时保持 `screenshot-candidate`。
3. `exact-text-gate`：块内重复文本或双引擎规范化文本不等时保持 `screenshot-candidate-ambiguous`。
4. `confidence-gate`：两引擎最小置信度必须 ≥ 0.85。
5. `geometry-gate`：两引擎裁片坐标 bbox IoU 必须 ≥ 0.50。
6. `promote-text-content`：只提升文本内容；`editability / role / asset_source` 永不提升。

实验合同值：

| 参数 | 值 | 说明 |
|---|---|---|
| `confidence_min` | 0.85 | 实验门限，不是通用阈值 |
| `engine_bbox_iou_min` | 0.50 | 跨引擎裁片框对齐门限 |
| `occlusion_max` | 0.30 | 遮挡先于置信度检查 |
| `require_two_engines` | true | 单引擎不提升 |
| `require_exact_normalized_text` | true | 只做空白归一化，不做语义补全 |

状态语义：

| 状态 | 含义 |
|---|---|
| `promoted-text-content` | 双引擎 exact、置信度与几何都过门；只升级文本内容 |
| `screenshot-candidate` | 单引擎、低置信度或几何未过门；文本保持未验证 |
| `screenshot-candidate-ambiguous` | 双引擎分歧，或块内重复文本无法唯一配对 |
| `screenshot-candidate-occluded` | 遮挡超限，置信度不得覆盖遮挡 |
| `unknown` | 无任何候选；本夹具未触发 |

### 3.4 ground truth 隔离

候选门只接收 `id / is_block / occlusion_ratio` 三个输入字段，不读取真值文本。13 个用例的 `gate_used_ground_truth` 均为 `false`，泄漏 0 例。真值只在门后的评估阶段用于计算 exact、字符准确率和误升级。

## 4. 结果

### 4.1 总览

| 指标 | 结果 |
|---|---|
| 识别裁片 | 13（12 单行 + 1 重复块） |
| OCR 候选 | 25（Tesseract 12 + EasyOCR 13） |
| CV 候选 | 32 |
| 状态 | `promoted-text-content=2`、`screenshot-candidate=4`、`screenshot-candidate-ambiguous=6`、`screenshot-candidate-occluded=1`、`unknown=0` |
| 升级数 / 误升级 | 2 / 0 |
| 升级精度 | 1.00（2/2） |
| Tesseract exact | 7/12，平均字符准确率 0.7391 |
| EasyOCR exact | 6/12，平均字符准确率 0.8360 |
| 双引擎 exact 交集 | 4/12（O01、O06、O09、O11） |
| 检查 | 13/13 通过 |
| 重复过门哈希 | 一致（`0ddfe73d782aae5f`） |

融合预览（门后附加，不参与门控）：`agreement=2`、`dom-preferred=9`、`screenshot-candidate=1`、`ambiguous=1`。只有 `O06`、`O11` 出现 DOM 与升级文本一致；其余有 DOM 的用例仍以 DOM 为权威。

### 4.2 逐用例

| 用例 | 条件 / 真值 | Tesseract | EasyOCR | 门状态 |
|---|---|---|---|---|
| O01 | 清晰标题 `设计系统融合实验` | `设计系统融合实验` 0.955 | `设计系统融合实验` 0.665 | `screenshot-candidate` |
| O02 | 混排 `真实 OCR 与 CV 候选接入` | `真实OCR5CV候选接入` 0.839 | `真实 OCR 与 CV 候选接入` 0.730 | `screenshot-candidate-ambiguous` |
| O03 | 低置信度用例 `低置信度必须保持未验证` | `低置信度必须保持未验证` 0.931 | `低置信度必须保持末验证` 0.904 | `screenshot-candidate-ambiguous` |
| O04 | 金额 `¥ 1,299.00` | `¥1,299.00` 0.945 | `半1,299.00` 0.777 | `screenshot-candidate-ambiguous` |
| O05 | 反白按钮 `立即购买` | `[` 0.690 | 无结果 | `screenshot-candidate` |
| O06 | 低对比度 `低对比度辅助说明` | `低对比度辅助说明` 0.914 | `低对比度辅助说明` 0.979 | `promoted-text-content` |
| O07 | 轻微模糊 `轻微模糊的正文` | `轻微模糊的正文` 0.940 | `轻徽模猢的正文` 0.106 | `screenshot-candidate-ambiguous` |
| O08 | 遮挡 `被遮挡的提示文字` | `SETS让局"Gd` 0.258 | `遮挡层occluded被遮挡的提示文字` 0.884 | `screenshot-candidate-occluded` |
| O09 | 旋转 `旋转两度的标题` | `旋转两度的标题` 0.832 | `旋转两度的标题` 0.702 | `screenshot-candidate` |
| O10 | 中英混排 `Design Lift 2.0 · Figma 融合` | `DesignLift2.0-Figma融合` 0.920 | `Design Lift 2.0Figma 鬲合` 0.491 | `screenshot-candidate-ambiguous` |
| O11 | 10 px 小字 `十像素小字测试` | `十像素小字测试` 0.932 | `十像素小字测试` 0.925 | `promoted-text-content` |
| O12 | 无 DOM 反白提示 `按 Ctrl+K 打开搜索` | 无结果 | `按 Ctrl +K 打开搜索` 0.674 | `screenshot-candidate` |
| O13 | 重复卡片标题块 | 块文本 0.960 | 两条重复行 0.728 / 0.746 | `screenshot-candidate-ambiguous` |

两个升级项均为真值正确：

- `O06 → 低对比度辅助说明`
- `O11 → 十像素小字测试`

### 4.3 被门挡住的典型情况

| 情况 | 用例 | 结果 | 原因 |
|---|---|---|---|
| 双引擎 exact 但置信度不足 | O01、O09 | 保持 candidate | O01 EasyOCR 0.665；O09 两引擎 0.832 / 0.702 |
| 单引擎结果 | O05、O12 | 保持 candidate | O05 只有 Tesseract 的 `[`；O12 只有 EasyOCR，且置信度 0.674 |
| 双引擎分歧 | O02、O03、O04、O07、O10 | ambiguous | 字符、标点、货币符号或中英混排差异 |
| 遮挡先于置信度 | O08 | occluded | 遮挡比例 0.45 > 0.30；EasyOCR 0.884 也不得覆盖 |
| 重复文本 | O13 | ambiguous | 3 条候选只有 2 个唯一文本，内容不足以唯一配对 |

O08 同时说明“高置信度”不等于“内容完整”：EasyOCR 把遮挡层文字和底层文字合在了一起，若只按置信度就会得到错误文本。

需要注意，O03 的主题是低置信度，但本次两引擎都返回了 0.90 以上的置信度，实际低置信度分支由 O01（EasyOCR 0.665）和 O09（两引擎 0.832 / 0.702）触发；O03 最终因双引擎分歧保持 `ambiguous`。

### 4.4 朴素最高置信度基线

如果忽略双引擎、exact、遮挡和几何，仅取每个裁片置信度最高的候选并按 0.85 升级：

| 指标 | 结果 |
|---|---|
| 升级 | 8 例（O01、O03、O04、O06、O07、O08、O10、O11） |
| 正确 | 6 例 |
| 误升级 | 2 例（O08、O10） |
| 精度 | 0.75 |

错例：

- `O08`：EasyOCR 0.884 把遮挡层文字并入底层文本；遮挡门必须先阻断。
- `O10`：Tesseract 0.920 丢失中点并改变连字符，字符级准确率 0.952 但 exact 不通过；置信度不能替代严格文本比较。

本实验的保守门把升级数从 8 降到 2，换取 2/2 的升级精度。这是精确率—召回率取舍，不是更高准确率本身。

### 4.5 CV 轮廓框

| 指标 | 结果 |
|---|---|
| CV 候选 | 32 |
| 目标数 | 5 |
| 匹配目标 | 4/5（IoU ≥ 0.50） |
| 歧义目标 | B02、B03 |
| 未命中目标 | B05（1 px 分隔线） |

- B01 按钮：最佳 `CV-021`，IoU 0.9646。
- B02 卡片：最佳 `CV-029`，IoU 0.9883、containment 1.0；另有两条完全被包含的轮廓候选，保持 `ambiguous=true`。
- B03 徽标：最佳 `CV-014`，IoU 0.9889；另一条近似框同时命中，保持 `ambiguous=true`。
- B04 封面：最佳 `CV-020`，IoU 0.9855。
- B05 分隔线：无候选；1 px 低对比度线在 Canny/面积过滤链中未形成可用轮廓。

CV 候选的高 IoU 只证明“视觉框位置接近”，不证明按钮、卡片、徽标等语义角色，也不证明原始资产。全部 CV 候选保持 `role=unknown`、`asset_source=flat-raster-crop`。

### 4.6 检查项

13/13 检查通过：

1. OCR/CV 均来自真实引擎。
2. 候选门不读取 ground truth（输入字段仅 `id / is_block / occlusion_ratio`）。
3. 低于置信度门限的候选不升级（0 例越级）。
4. 单引擎候选不升级（0 例越级）。
5. 引擎分歧不升级（0 例越级）。
6. 遮挡在置信度之前阻断升级（O08）。
7. 升级文本内容无错误（2/2）。
8. 所有候选的可编辑性保持未验证（0 例越权）。
9. CV 框不推断语义角色（0 例越权）。
10. CV 框不宣称原始资产（0 例越权）。
11. 重复文本保持歧义而非强配（O13）。
12. 同一候选集重复过门结果一致（门投影 SHA-256 一致）。
13. 朴素最高置信度策略会产生可测误升级（2 例）。

## 5. 解释与边界

### 5.1 可以支持的判断

1. 双引擎 exact 是有效但不足够的过滤条件：12 个单行用例中只有 4 个双引擎 exact，其中 2 个仍因置信度或几何门保持未验证。
2. 遮挡必须在文本比较和置信度之前处理；否则高置信度的合成文本会污染内容。
3. 跨引擎 bbox IoU 不是内容证据。O01 两个引擎都 exact，但 EasyOCR 检测框明显更松，IoU 0.484，未过 0.50 几何门。框对齐只能证明位置相近，不能证明识别正确。
4. 10 px 小字和低对比度文本可以在双引擎一致时被升级，但不能据此推导通用可读性阈值。
5. CV 轮廓对规则矩形目标有效，但对 1 px 分隔线失效；高 IoU 不等于语义理解。
6. 重复文本必须保持 `ambiguous`；内容相同不能替代空间或 DOM 配对证据。

### 5.2 不能支持的判断

- 不能把 2/2 升级精度写成通用 OCR 精度或生产接受率。
- 不能把 `0.85 / 0.50 / 0.30` 写成跨站点、跨字体、跨 DPR 的通用阈值。
- 不能宣称 OCR 已具备端到端文本检测能力；所有裁片框都是实验者给定的。
- 不能把 `promoted-text-content` 写成可编辑文本、语义角色或原始资产已验证。
- 不能把 CV 候选写成按钮/卡片/徽标等角色识别结果。
- 不能把本实验写成真实站点、生产融合 API 或 Figma 写入已验证。

### 5.3 限制

- 单页、13 个识别用例，样本量小；`unknown` 状态没有被真实触发。
- OCR 只在给定框内运行；没有覆盖检测框缺失、框偏移、重叠文本和复杂背景。
- EasyOCR 使用 GPU；不同 CUDA/模型版本可能改变置信度与框，复现需固定环境。
- 只覆盖 Tesseract 与 EasyOCR 两个引擎；第三种引擎、语言包和方向检测未验证。
- 没有覆盖滚动、动画、懒加载、响应式布局和真实站点噪声。
- 门限是实验合同值，不是从缺陷样本拟合出的通用参数。

## 6. 可写入 2.0 规格的结论

可以写入：

1. OCR 候选进入 `screenshot-candidate` 通道时，必须保留引擎、版本、原始文本、规范化文本、置信度、裁片框、页面框和 `verified=false`。
2. 遮挡、单引擎、双引擎分歧、重复文本和几何未对齐都不得自动升级文本内容。
3. 只有双引擎 exact、置信度与几何同时过门时，才允许升级 `text-content`；`editability / role / asset_source` 始终保持未验证或未推断。
4. 遮挡门必须先于文本比较与置信度门；高置信度不得覆盖遮挡。
5. 重复文本无法唯一配对时必须保持 `ambiguous`，不得按首个候选强配。
6. CV 轮廓框只能作为 `visual-box-candidate`，不得推断语义角色、可编辑性或原始资产。
7. 升级结果必须保留 `reason` 与逐步门记录；未升级候选仍保留原始证据。

仍不能写入：

- 通用 OCR 置信度、IoU、遮挡阈值；
- 端到端 OCR 检测与版面分析方案；
- 生产 IR 的候选 schema 与存储格式；
- 真实站点、跨 DPR、跨浏览器、跨语言的接受规则；
- Figma 写入策略与自动交付白名单。

## 7. 下一步候选

以下仅为候选，本实验不自动开启：

- `R4-EXP-03`：把状态门扩展到真实滚动、懒加载和动画帧。
- `R4-EXP-04`：设计生产 IR 的字段级 provenance，并做只读回放验证。
- `R4-EXP-05`：多引擎/多语言矩阵与跨 DPR bbox 可比性标定。

## 8. 产物清单

| 产物 | 路径 |
|---|---|
| 脚本 | `output/_r4_experiments/r4_ocr_candidates.py` |
| 总 JSON | `output/_r4_experiments/r4_ocr_candidates.json` |
| OCR 候选 | `output/_r4_experiments/r4_ocr_artifacts/ocr_candidates.json` |
| CV 候选 | `output/_r4_experiments/r4_ocr_artifacts/cv_candidates.json` |
| 门结果 | `output/_r4_experiments/r4_ocr_artifacts/gate_results.json` |
| 截图 | `output/_r4_experiments/r4_ocr_artifacts/capture_s0.png` |
| 裁片 | `output/_r4_experiments/r4_ocr_artifacts/crops/`（18 张） |
| 结果矩阵 | `output/_r4_experiments/r4_ocr_matrix.png` |
| 门产出流程 | `output/_r4_experiments/r4_gate_flow.png` |
| 置信度图 | `output/_r4_experiments/r4_ocr_confidence.png` |
| CV 框 | `output/_r4_experiments/r4_cv_boxes.png` |
