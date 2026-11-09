# Image → Figma 泛化收尾 · 交接文档（2026-11-09）

**日期：** 2026-11-09
**性质：** 当日工作交接（目标 / 完成 / 文件 / 测试 / 遗留 / 下一步 / 禁改项）
**前置文档：**
- `IMAGE_FIGMA_GENERALIZATION_DIAGNOSIS_2026-11-08.md`（契约层诊断，已落地）
- `IMPLEMENTATION_ROADMAP_2026-11-08.md`（路线图，Phase 0–5，当日执行其中 0/1/2/4 及收尾项）
**当日提交：** `2dc9b93 feat: generalize image-to-Figma fidelity via evidence-driven rules and family benchmarks`（26 files，+47140/-3）
**运行环境：** `C:/Users/lzq/.conda/envs/omni/python.exe`（easyocr/websockets/openai 齐备）；流水线须带 `GROUNDING_FIDELITY_MODE=high IMAGE_ENRICHMENT_MODE=apply`（封装于 `scripts/run_image_pipeline.sh`）

---

## 1. 本次任务的目标

让 image → Figma 流水线摆脱"FlexWeaver 蒸馏过拟合、换图就崩"的状态，在**任意新截图**上达到「Figma Make 级观感 + 项目级内容忠实 + 可编辑结构」。当日具体执行路线图的 Phase 0（基准固化）、Phase 1（字号常量→规则）、Phase 2（表格策略）、Phase 4（门禁标定）及遗留收尾项 ②④。

核心方法论（三铁律，出自路线图，必须继续遵守）：
1. **常量 → 规则**：修复必须是读图自证的推断，禁止新增单样本特判；
2. **三族回归门禁**：任何修复合入前跑三族基准，任一回归即打回；
3. **VLM 提议，度量裁决**：模型判断只是候选，裁决权在冻结数值门禁（fail-closed）。

## 2. 已经完成的内容

### Phase 0：基准固化 ✅
- **三族黄金稿基准集**（`tests/fixtures/benchmark_families/`，均为 Figma Make 产物冻结）：
  | 族 | 参考图 | 黄金稿 frame | gold scale | 流水线基线 run |
  |---|---|---|---|---|
  | light-form（FlexWeaver） | IMG-FLEXWEAVER-ADMIN.png（sha c0180587, 1920×826） | `2:523` | 1.0 | `output/_image_figma_flexweaver_20261109_r6` |
  | light-table（工时确认） | IMG-TIMESHEET-CONFIRM.png（sha ece8effc, 2544×1336, 2x） | `32:2520` | 1.325（1920 逻辑空间） | `output/_image_figma_timesheet_confirm_20261108_r7` |
  | dark-card-grid（ACCTOKEN 模型广场） | input.png（sha 674d733f, 2544×1336） | `35:2909` | 1.0 | `output/_image_figma_acctoken_20261109_r5` |
- **一键三族回归门禁** `scripts/check_benchmark_families.py`：within30 + 答案键（字号比/dy/字重失配）+ 结构 + 位图计数 + critical，任一回归退出码非 0；`--register` 注册基线；`--rerun [--policy 2.1]` 感知冻结重跑（复制冻结 pipeline + `--reuse-prepared`，零 VLM 调用，实测产出**逐字节相同**指标）。
- **黄金稿可达上界测量** `scripts/measure_gold_bound.py`（报告 `output/_benchmark_families/gold_bound.json`）：用 native gate 的度量机器量三族黄金稿自身——light-form 金稿 edgeF1 中位 0.969（54/78 ≥0.95）；dark 金稿中位 0.679（4/51）；light-table 金稿中位 0.0（它是语义重设计而非像素答案键，流水线同图像素忠实度反超金稿）。**结论：edgeF1≥0.95 连 Figma Make 都拦；普适可达维度是位置/尺寸。**
- **并排参考图工具** `scripts/place_reference_beside.py`（写 Figma 后把源截图放到输出 frame 旁，仅评审用，禁止作为 underlay 进入导出）。
- 环境固化 `scripts/run_image_pipeline.sh`。

### Phase 1：字号 → 墨迹自校准闭环 ✅（核心）
- `calibrate_ink_convergence_from_render`：不再依赖一次性测量，改为**闭环**——参考墨迹在元素 `ink_bbox` ±4px 扩窗重测源图（救回紧框裁剪），渲染墨迹在 Figma 回读节点实际 bounds ±4px 扩窗实测，按比值调 fontSize。跳带 [0.85,1.175]、单步钳 [0.7,1.5]（几何收敛）、fs 钳 [8,96]，逐元素报告全程可追溯。注册为末位校准组 `ink-convergence`（恒跑，全残差全区域）。
- 效果：light-table within30 92.00→**93.50**（+1.5pp）；light-form font_ratio 0.891→**1.014**（回到黄金稿水平）；dark 方向正确（`¥1.16` 32→44 上调）；三族无回归。
- **style_resolver 的自适应阈值+行带选择实验已回退**（`git checkout`）——修好了 light-table 墨迹膨胀却把 FlexWeaver 表列数字 10.5→30-40，净效果为负。其增益已由闭环安全替代。教训：一次性测量调优 = 打地鼠，正解是闭环。

### Phase 2：表格行锚定 ✅（y 方向）
- `_anchor_table_rows`：唯一文本（日期/表头标签）匹配 grounded 条目 → 实测行带；歧义文本就近吸附；**单调性拒错**（VLM 错位实例被丢弃改用插值）；未锚行插值。
- **一致性守卫**：检测网格与 grounded 证据一致时锚定收手（保护本来就对的表，FlexWeaver 6/6 一致 → no-op，与对照实验逐位相同）。
- 效果：timesheet 表 bbox y 177→426（鬼影表头带消除，12 边界单调且与真实行对齐）；light-table native 8/89→21/79、**chrome fail→pass**（表头坏像素 9.12%→1.97%）；dark dy 中位 114→**4.5**、font_ratio 0.643→0.906。
- **资产重叠去重** `_dedupe_overlapping_assets`（遗留④落地）：全量 asset 类按面积降序、IoU>0.5 吸收合并 evidence_refs——VLM 嵌套重复枚举（logo 双层、横幅 2-3 层）不再叠放。dark 位图 15→**9**，within30 94.89 持平。

### Phase 4：门禁标定 ✅
- **Policy 2.1**（`IMAGE_MVP_POLICY_V21`，2.0 冻结不动）：position ≤2px、尺寸容差 3px/3%、coverage [0.75,1.35]、**edgeF1 ≥0.55**，策略内嵌三族金稿中位数出处。CLI `--acceptance-policy 2.1` 已接线。
- 验证（冻结设计）：同输出在 2.1 门下 native 32/79 vs 2.0 门 21/79——已兑现改进获评，门保持鉴别力。
- light-table native 全弧线：8/89（昨日基线）→ 21/79（锚定）→ 32/79（标定门视角）。

### 重要过程性发现（影响后续决策）
- **基线是 VLM 样本相关的**：FlexWeaver 96.22→91.34 的"回归"经对照实验（旧代码+同今日样本 = 91.34 逐位相同）证明 100% 是 VLM 采样方差（今日缓存未命中拿到新枚举，text_candidates 42→47）。**对策已落地：门禁 `--rerun` 感知冻结模式。**
- Figma Make 的幻觉是版式相关的：密集表格上改写+幻觉（`关键字→关键词`、凭空 `wangxy`），深色卡网格上忠实 26/27——内容契约护城河集中在密集表格场景。
- FlexWeaver 的历史好成绩来自"用 FlexWeaver 蒸馏 Figma Make"（同一样本蒸馏 = 最强过拟合）；工时确认图上活下来的能力全部来自诊断文档的契约层，崩的是蒸馏残留常量。

## 3. 已修改的文件

**修改（M）：**
- `src/app/services/structure/fidelity/inventory.py`
- `src/app/services/structure/fidelity/text_calibration.py`
- `src/app/services/structure/fidelity/calibration_strategies.py`
- `src/app/services/evidence/image_figma_acceptance.py`
- `scripts/image_figma_mvp.py`

**新增（A）：**
- `scripts/check_benchmark_families.py`
- `scripts/measure_gold_bound.py`
- `scripts/place_reference_beside.py`
- `scripts/run_image_pipeline.sh`
- `docs/v2_mentor/IMPLEMENTATION_ROADMAP_2026-11-08.md`
- `tests/fixtures/benchmark_families/`（三族 × {reference.png, truth.json, gold_tree.json, family.json} + README）
- `tests/fixtures/timesheet_confirm_20261108/`（IMG + truth + ocr_texts）

**保持干净（实验后回退）：** `src/app/services/structure/fidelity/style_resolver.py`（当日曾改自适应阈值+行带选择，净效果为负已 `git checkout` 回退，未入提交）。

## 4. 每个文件修改了什么

| 文件 | 修改内容 |
|---|---|
| `inventory.py` | ① 新增 `_anchor_table_rows`：grounded 文本锚定表行边界（唯一文本匹配→歧义吸附→单调性拒错→插值），evidence 记录 row_bands/anchored_rows；接入 `build_geometry_manifest` 的表处理分支。② 一致性守卫：多数带落在检测行区间内则锚定收手（保护检测正确的表）。③ 新增 `_dedupe_overlapping_assets`：全量 asset 项按面积降序、IoU>0.5 吸收合并，evidence_refs 归并，在 `_coalesce_items` 前对 items 全量执行。合计 +258 行。 |
| `text_calibration.py` | 新增 `calibrate_ink_convergence_from_render` 及辅助 `_ink_convergence_gray`/`_ink_height`（极性无关对比掩码 + 扩窗墨迹测量）：渲染墨迹 vs 源墨迹逐元素收敛调 fontSize。合计 +151 行。 |
| `calibration_strategies.py` | import 新校准函数；新增 `_ink_convergence` runner；`CALIBRATION_GROUPS` 末位注册 `ink-convergence` 组（render_suffix `figma_ink_converged`，always=True，全残差词表全区域）。 |
| `image_figma_acceptance.py` | 新增 `IMAGE_MVP_POLICY_V21`（基于黄金稿可达上界实测标定的阈值，含 calibration 出处字段）；`IMAGE_MVP_POLICY_V2` 一字未动。 |
| `image_figma_mvp.py` | import `IMAGE_MVP_POLICY_V21`；`--acceptance-policy` choices 增加 "2.1"；策略选择分支化。 |
| `check_benchmark_families.py`（新） | 三族基准门禁：measure（within30/答案键/结构/位图/critical）→ `_gate` 与 family.json 基线对照（含 font_ratio 单调改进门）→ `--register` 注册、`--rerun` 感知冻结重跑（复制 pipeline + reuse-prepared）、`--family` 过滤。当日两次自身修 bug：fontSize 缩放归一（gold fs ×scale）、`_gate` 嵌套键展平。 |
| `measure_gold_bound.py`（新） | 对三族黄金稿导出图跑 native_text_quality 度量机器，产出可达上界分布（gold_bound.json）。 |
| `place_reference_beside.py`（新） | 通过 bridge 把源截图作为图片节点放到输出 frame 右侧（x 偏移 +80），仅评审用途。 |
| `run_image_pipeline.sh`（新） | 封装 omni 解释器 + `GROUNDING_FIDELITY_MODE=high IMAGE_ENRICHMENT_MODE=apply` 的流水线启动。 |
| `IMPLEMENTATION_ROADMAP_2026-11-08.md`（新） | 路线图定稿（三铁律 + Phase 0–5 + 完成定义 + 当日修订：三族门禁、Phase 4 完成标记、ACCTOKEN 黄金稿数据）。 |
| `tests/fixtures/*`（新） | 三族基准夹具 + timesheet 样本（含 124 条 EasyOCR 观测冻结）。 |

## 5. 已运行的测试及结果

**单元测试（全部通过，omni python + `-p no:cacheprovider`）：**

| 测试文件 | 结果 |
|---|---|
| `tests/v2/test_grounding_style_resolver.py` | 8 passed |
| `tests/v2/test_fixed_canvas_compiler.py` + `test_grounding_scene_compile.py` | 35 passed |
| `tests/v2/test_grounding_fidelity_contracts.py` + `test_grounding_fidelity_integration.py`（锚定） | 14 passed |
| 同上两文件 + `test_inventory_emission_contract.py`（资产去重） | 63 passed |
| `tests/v2/test_grounding_scene_plan.py` 等（去重回归） | 44 passed |
| `tests/v2/test_calibration_strategies.py`（墨迹收敛注册） | 7 passed |
| `tests/v2/test_image_figma_cli_defaults.py` + `test_image_figma_acceptance.py`（Policy 2.1） | 16 passed |

**端到端（三族门禁，`check_benchmark_families.py`）：**

| 族 | within30 | font_ratio（对金稿） | dy 中位 | 位图 | critical |
|---|---|---|---|---|---|
| light-form | 91.32% | 1.014 | 1.0px | 34 | 24/24 |
| light-table | 93.50% | 1.199 | 40.5px | 11 | 29/29 |
| dark-card-grid | 94.89% | 0.906 | 4.5px | 9 | 25/27 |

（门禁全 pass；基线为当日最终 run 注册。注意 light-form 91.32 vs 昨日 96.22 是 VLM 采样方差，非代码回归——对照实验已证。）

**感知冻结验证：** `--rerun` 模式重跑 light-table，指标逐字节相同（93.50/1.199/40.5）——VLM 方差归零。
**对照实验：** FlexWeaver 旧代码 + 同今日 VLM 样本 = 91.34，与锚定代码逐位相同（守卫 no-op 证明）。

## 6. 当前仍存在的问题

1. **native gate 绝对值仍低**（light-table 32/79、dark 尚低）：字号维度已闭环，剩余阻塞集中在位置精度（dy 中位 40.5，light-table 列向错位）与字形边缘（edgeF1 本质上界有限，已按 2.1 门缓解）。
2. **列锚定未做**（Phase 2 只锚了 y）：表列 x 坐标仍用合成网格，light-table 列错位（`持续时长`列 dx≈84）待列锚定解决。
3. **字重系统性欠发射**（Phase 1 剩余）：dark 26/43 字重失配（流水线全 Regular vs 金稿 Bold/Black/Medium/Serif/Mono），笔画密度证据推断未实现。
4. **多轮收敛未启用**：ink-convergence 每组只跑一轮迭代（几何收敛设计支持 2-3 轮再压一截）。
5. **dark 今日样本 dy 偏移**：VLM 方差导致的部分文本位置偏移，待列锚定/位置校准覆盖。
6. **Phase 3 感知增强未开始**：ACCTOKEN 9 条 critical 缺失（抑制/短单元合并/感知枚举）未修；两遍式 grounding、VLM 视觉裁判标定未做。
7. **Phase 5 结构发射未开始**：输出仍扁平 1 层 vs 黄金稿 5-8 层 FRAME + 52 auto-layout（可编辑性主菜）。
8. **分轨指标未转正**：within30 仍为混合口径（含位图兜底区域），native-only bad pixel 只是旁路。
9. `.vision_cache` 是样本相关资产：基线复现依赖缓存命中，需当作需备份的资产对待。
10. light-form 位图 34 处仍偏高（位图判据收紧属 Phase 5）。

## 7. 下一步应该从哪里继续

按路线图优先级：

1. **Phase 2 列锚定**（建议首先）：把 `_anchor_table_rows` 的同法扩展到 x 方向（列头唯一文本 → 实测列带 + 一致性守卫），直接解决 light-table dy/dx 位置主诉。复用当日全部基建（纯函数可在冻结 bundle 上先验证，再 `--rerun` 门禁）。
2. **Phase 3a 两遍式 grounding**：先版式描述草稿再吐 bbox，以 ACCTOKEN 9 条缺失为考卷测召回提升（critical 是 acceptance 硬阻塞）。
3. **多轮 ink-convergence 迭代**（小改动，几何收敛再压一档）。
4. **Phase 1 字重推断**（笔画密度证据 → Bold/Medium/Mono，dark 族收益大）。
5. **Phase 5 结构发射**（parents→FRAME、重复组→auto-layout、位图判据收紧——可编辑性核心，对标黄金稿 5-8 层）。
6. 每步合入前：`scripts/check_benchmark_families.py --rerun` 感知冻结门禁（铁律 2 的执行体）。

工作流提示：新样本跑流水线用 `scripts/run_image_pipeline.sh`；改代码后验证用 `check_benchmark_families.py --rerun [--policy 2.1]`；bridge 服务 `python -m src.app.services.bridge_server`（omni python，ws://localhost:8765，插件自动重连）。

## 8. 哪些内容禁止再次修改

1. **冻结 truth 与黄金稿**：`tests/fixtures/benchmark_families/*/truth.json`、`gold_tree.json`、`reference.png`，以及三族黄金稿 Figma frame（`2:523`/`32:2520`/`35:2909`）——它们是答案键/裁判，改了等于改考卷。truth 的错字修正（如诊断文档 P1 项）须经显式审批并记录版本。
2. **Policy 2.0（`IMAGE_MVP_POLICY_V2`）**：冻结口径，历史 run 的可比性依赖它；一切新阈值走新 policy 版本（如 2.1），且阈值必须有黄金稿实测出处，禁止拍脑袋回调。
3. **已回退的 style_resolver 实验路线**：不要再用"自适应阈值/行带选择"修一次性测量——当日已证净效果为负（FlexWeaver 表列数字 10.5→30-40）；字号问题的正解是已落地的墨迹闭环，调优应发生在闭环策略里。
4. **基线的语义**：family.json 的 baseline 只能用 `--register` 刷新（且建议只在感知冻结 rerun 后刷新），禁止手编 JSON 数字粉饰门禁。
5. **契约层的 fail-closed 纪律**：VLM/模型判断永远只是候选修复，不得直接写入门禁判定或绕过 `build_image_acceptance_report` 出分。
6. **`visible_full_screenshot_underlay: blocked`**：禁止把源截图垫到输出 frame 下面刷 within30；并排参考图只能放 frame **旁边**且不进入导出。
7. **门禁脚本的度量口径**：`check_benchmark_families.py` 的字号比必须做 gold scale 归一（当日修过的 bug，勿回归）；`_gate` 必须读展平后的嵌套键（当日修过的静默跳过 bug，勿回归）。
