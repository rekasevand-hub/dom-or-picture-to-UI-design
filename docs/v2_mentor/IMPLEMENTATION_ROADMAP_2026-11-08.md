# Image → Figma 泛化收尾路线图（最终实施建议）

**日期：** 2026-11-08（晚）／ **修订：** 2026-11-09（晨，三族黄金稿齐备后更新）
**性质：** 实施路线图，基于当日全量实验证据
**前置文档：** `IMAGE_FIGMA_GENERALIZATION_DIAGNOSIS_2026-11-08.md`（契约层已落地并验证）
**目标：** 流水线在任意新截图上达到「Figma Make 级观感 + 项目级内容忠实 + 可编辑结构」，不依赖逐图蒸馏、不依赖 Figma Make。

---

## 0. 三条治理铁律（每个改动都要过）

1. **常量 → 规则**：任何修复必须是"读图自证的推断"，禁止新增针对单样本的手写常量/特判。
2. **三族回归门禁**：任何修复合入前，必须同时跑 FlexWeaver（1x 浅色表单）、工时确认（2x 浅色表格）、ACCTOKEN（2x 深色卡网格）三样本，任一族回归即打回。
3. **VLM 提议，度量裁决**：VLM/LLM 产生的一切判断（包括未来的视觉复审）只能是候选修复，最终裁决权永远在冻结数值门禁（fail-closed）。

---

## 1. 当日基线（2026-11-08/09 实测，作为回归起点）

| 指标 | FlexWeaver（蒸馏样本） | 工时确认（未见样本） | ACCTOKEN（深色族） |
|---|---|---|---|
| critical text | 44/48（历史最佳） | **29/29** | 18/27 |
| within30 | 96.77%（含 47% 位图兜底） | 92.10%（裸跑） | 94.15% |
| native gate | 14/33 | **8/89**（字号 ×1.5~3.46） | 0/37（edgeF1 墙） |
| 答案键字号比（流水线/黄金稿） | ~1.0（0.75px 中位差） | **×1.5~3.46 偏大** | **×0.64 偏小** |
| 结构 | 扁平 1 层 | 扁平 1 层 | 扁平 1 层 |
| Figma Make 黄金稿 | ✓（2:523，within30 97.20%，ink_mean 6.05） | ✓（32:2520，91.89%，ink_mean 82） | ✓（35:2909「模型广场」，**95.72%，ink_mean 4.44**，critical 26/27） |

**关键事实（含 2026-11-09 三族黄金稿齐备后的更新）：**
- 诊断文档的契约层（坐标/内容/感知）在工时确认图上原样生效——泛化已验证 ✓
- 剩余失败 = 蒸馏残留常量：**字号系数（双向错误）、表格形状假设、短单元后缀表、字重推断**
- **字号误差是双向的**：浅色 2x 表格图上 ×1.5~3.46 偏大，深色卡网格上 ×0.64 偏小——同一病灶（一次性 ink→fontSize 系数）在不同图像特征下向两个方向崩，进一步坐实 Phase 1 的"闭环自校准"修法
- **0/37 edgeF1 归因已裁决（2026-11-09）：真实渲染缺陷，非度量失真**——ACCTOKEN 黄金稿在同源图上 ink_mean 仅 4.44、critical 26/27，证明近逐像素的文字保真在深色主题上完全可达；流水线 0/37 是自己渲染错了（字号 ×0.64 + 字重全 Regular）
- **字重系统性欠发射**：ACCTOKEN 答案键 26/43 字重失配（黄金稿按语义用 Bold/Black/Medium/Noto Serif SC/JetBrains Mono，流水线几乎全 Regular）——深色族的额外失败维度，纳入 Phase 1 范围
- **edgeF1≥0.95 可达性结论修正**：工时确认黄金稿（Arimo 替身，ink_mean 82）过不了，但 ACCTOKEN 黄金稿（ink_mean 4.44）大概率能过——可达性是样本/字体相关的，门禁重标定按"各族黄金稿实测上界"做，不做全局一刀切
- **Figma Make 幻觉是版式相关的**：密集表格（工时确认）上改写+幻觉 5+ 处；深色卡网格（ACCTOKEN）上忠实 26/27——内容契约的护城河集中在密集表格场景，恰好是流水线 29/29 全中的强项

---

## 2. Phase 0：基准固化（0.5 天，先做）✅ **已完成（2026-11-09）**

**目的：把临时拼装的测量工具变成一键回归。**

| 任务 | 产物 | 状态 |
|---|---|---|
| 黄金稿基准集注册 | `tests/fixtures/benchmark_families/`：三族（light-form / light-table / dark-card-grid），每族 `reference.png + truth.json + gold_tree.json + family.json`（含缩放系数与基线） | ✅ |
| 一键回归脚本 | `scripts/check_benchmark_families.py`：三族 → within30 + 答案键（字号比/dy/字重失配）+ 结构统计 + 位图计数；`--register` 注册基线，默认门禁模式任一族回归退出码 1 | ✅ 首跑注册 + 门禁复验通过 |
| 环境固化 | `scripts/run_image_pipeline.sh`（封装 omni 解释器 + `GROUNDING_FIDELITY_MODE=high` + `IMAGE_ENRICHMENT_MODE=apply`，`OMNI_PYTHON` 可覆盖） | ✅ |
| 画布并排参考图 | `scripts/place_reference_beside.py`（frame 旁放置参考图节点，仅评审用，不进导出；已验证） | ✅ |

**已注册基线（2026-11-09，`--register` 产出，报告存 `output/_benchmark_families/report.json`）：**

| 族 | within30 | font_ratio | dy_med | 字重失配 | 节点/深度/位图 | critical |
|---|---|---|---|---|---|---|
| light-form | 96.22% | **1.0** | 1.0 | 17/75 | 157 / 1 / 32 | 24/24 |
| light-table | 92.10% | **1.5** | 76.4 | 3/100 | 241 / 1 / 11 | 29/29 |
| dark-card-grid | 94.15% | **0.643** | 114.0 | 26/43 | 75 / 1 / 10 | 24/27 |

注意 light-form 的 font_ratio=1.0——字号误差确证为 **2x 分辨率与深色主题专属**（1x 浅色不触发），Phase 1 归因时可据此缩小范围。light-form 的位图 32 处是 flexweaver 位图兜底（47% 画布）的直接计数，Phase 5 收紧。

---

## 3. Phase 1：字号/字重常量 → 自证规则（1–2 天，性价比最高）

**归因（2026-11-09 已完成，比预想更深）：**
- light-table 巨型文字根因 = **双轨发射**：VLM 把内容面板当表格（表 bbox `[470,177,1906,803]` vs 真实 `[470,~440,…]`）→ 均匀网格合成 10 个表头在 y=177 鬼影带（fs 48.5–90.75）；同时 grounded 真表头在 y=444（fs=20 正确）**两套都发射**（不同 contentRef、不重叠 → 现有去重/审计均不触发）。→ 主修在 Phase 2（表几何锚定到 grounded 文本）。
- dark 欠小根因 = **元素框紧裁剪**：20px 高的框装 22px+ 的字（gold fs 26），一次性测量物理上被框裁掉；另有少数错位框量到无关内容（如蓝色链接）。→ 主修 = fs 自校准闭环（渲染墨迹 vs 源墨迹收敛）。
- style_resolver 测量层放大器已修（2026-11-09）：固定阈值 24 → 自适应 Otsu（clamp 6–32）+ 主墨迹行带选择（松框内 chrome 不再计入 ink 跨度）。效果：light-table 灾难膨胀 22→10 例；单测 8+35 全过。
- light-form（1x 浅色）字号本来就对（ratio 1.0）——误差确证为 2x/深色/表几何三个触发条件的并集。

**修复（做成规则，不是新常量）：**
- 字号推断改为**墨迹高度自洽闭环**：每轮渲染后比对「渲染墨迹高度 vs 源图墨迹高度」，比值收敛到 1±0.05 才停——双向误差都被同一个闭环纠正，参考答案每张图自带，无需外部输入。
- 字重推断改为**笔画密度证据**：墨迹覆盖率（ink 面积/字面面积）分档映射字重，阈值按图像自身墨迹分布自适应（Otsu 同思路），不引入全局常量。

**验收（三族回归）：**
- 工时确认：font ratio 中位 1.5 → **1.0±0.1**；native gate 8/89 → **≥50/89**
- ACCTOKEN：font ratio 0.64 → **1.0±0.15**；字重失配 26/43 → **≤8/43**；native gate 0/37 → **≥15/37**
- FlexWeaver：native gate 14/33 不得回退；within30 不降
- 预期副产品：edgeF1 失败数大幅下降（两族的 size/weight 错误是其直接死因）

---

## 4. Phase 2：表格策略形状假设 → 证据驱动（1–2 天）

- 表格行列结构从**OCR 行聚类 + 墨迹行带检测**推导（行数、行高、列边界全部实测），替换 `calibrate_table_fonts_from_render` / scene plan 中的行数/行高假设。
- 表格 cell 文本与输入框控件（`请输入0~`、`(选填)`）走统一 owner 裁决，不因形状差异走特殊分支。
- 验收：工时确认 10×10 表与 FlexWeaver 5 行表双通过；表格 cell 位置 dy 中位 < 8px。

---

## 5. Phase 3：感知增强（两项实验并行，各自独立验收）

**5a. 两遍式 grounding（"草稿纸"）：**
- 改造 `grounding_vlm.py` 的 prompt：第一遍输出版式结构描述（区域、表格行列估计、菜单项清单），第二遍逐区域吐 bbox；两遍结果合并进既有解析管线。
- **考场：ACCTOKEN**（9 条缺失关键文本是现成考卷）。
- 验收：critical text 18/27 → **≥24/27**；无新增幻觉条目（内容契约继续把关）。持久缓存使成本只发生一次。

**5b. VLM 视觉裁判离线标定：**
- 用工时确认的 **89 个已知失败 owner** 当考卷：给 VLM 看（参考裁片, 渲染裁片），输出结构化缺陷判断，离线比对真值。
- 及格线（不达标绝不进环）：真缺陷检出率 ≥80%，误报率 ≤10%。
- 及格后接入校准环：每轮（参考, 导出）→ VLM 缺陷清单 → 作为候选修复（仍受数值门禁裁决，迭代上限 2 轮控制成本）。

---

## 6. Phase 4：门禁重标定 + 口径收口（0.5–1 天）

- ~~ACCTOKEN 黄金稿补一张~~ **已完成（2026-11-09，`35:2909`「模型广场」，Figma Make，1:1 尺寸）**；0/37 归因已裁决：真实渲染缺陷（黄金稿 ink_mean 4.44 证明可达）。
- 用**三族黄金稿分别**计算 edgeF1/inkCoverage 可达上界：ACCTOKEN 黄金稿大概率可达 0.95 级（ink_mean 4.44），工时确认黄金稿不可达（Arimo 替身，ink_mean 82）——阈值按族标定或改为"相对黄金稿基线"的相对指标，不做全局一刀切。
- 分轨指标（native-only bad pixel，剔除位图兜底区域）进正式验收旁路；within30 混合口径标注"含位图兜底"字样。
- ACCTOKEN 三族回归自本版起生效（铁律 2 已更新）。

---

## 7. Phase 5：结构发射——对齐黄金稿的可编辑性（1–2 天，质量达标后做）

- `scene_plan` parents → Figma FRAME 层级映射（`fixed_canvas_compiler.py` + bridge `apply_batch` 已支持 parentId）。
- 重复组（表单字段行、表格行、按钮组）→ `set_layout_flow` auto-layout（bridge 已有 `set_autolayout`/`set_layout_flow`/grid 覆盖，probe 脚本已验证）。
- 位图降级判据收紧：仅照片/logo 类区域允许 IMAGE fill；图标走 `image_enrichment/vector_icons.py`。
- 验收：结构统计对标黄金稿（深度 ≥4、FRAME ≥ 50、VECTOR > 0、位图 ≤ 个位数），双族像素指标不回退。

---

## 8. 执行顺序与依赖

```
Phase 0（基准固化）────────────┐
Phase 1（字号规则）→ Phase 2（表格规则）→ Phase 4（门禁标定）→ Phase 5（结构）
Phase 3a（草稿 grounding）── 独立，随时可跑 ──┘
Phase 3b（VLM 裁判）── 标定独立；进环依赖 Phase 1 完成（字号对了才测得出真残差）
```

## 9. 风险与边界

- **VLM 成本**：两遍式 grounding 与裁判调用使单图 VLM 调用数上升约 2–3 倍；持久缓存 + 有界迭代（≤2 轮）控制。
- **新族扩展**：看板/仪表盘等新版式族仍需 1 张 Figma Make 黄金稿学习族习惯（**每族一次**的扩展成本，非每图）；学到的必须是规则。
- **不做的事**：不逐图蒸馏、不追单图 SOTA 分数、不给单样本加特判、不把 Figma Make 输出混入运行时链路。
- **完成定义（项目级）**：任取一张浅色表单族新图，全流程无人工介入，critical text 全命中、native gate ≥60%、结构深度 ≥4、无巨型文字——此时该族宣告"脱离 Figma Make 独立运行"。

---

## 附：当日环境备忘

- 运行环境：`C:/Users/lzq/.conda/envs/omni/python.exe`（easyocr/websockets/openai 齐备；D:\LLM_condas 缺 easyocr）
- 流水线命令模板：
  `GROUNDING_FIDELITY_MODE=high IMAGE_ENRICHMENT_MODE=apply python scripts/image_figma_mvp.py --image <img> --truth <truth> --out <out> --acceptance-policy 2.0`
- bridge 服务：`python -m src.app.services.bridge_server`（ws://localhost:8765，插件自动重连）
- 答案键工具与存档（`output/_bridge_inspect/`）：
  - FlexWeaver：`answer_key_diff.py` / `text_answer_key_diff.json`
  - 工时确认：`timesheet_answer_key.py` / `timesheet_answer_key_diff.json`（含 1.325 缩放归一）
  - ACCTOKEN：`acctoken_gold_tree.json` / `acctoken_gold_export.png` / `acctoken_answer_key_diff.json`
  - 三方像素测量：`gold_vs_pipeline_within30.json`
- 三族黄金稿 frame：FlexWeaver `2:523`（1920×826）、工时确认 `32:2520`（1920×1008，×1.325 归一）、ACCTOKEN `35:2909`（2544×1336，1:1）
- ACCTOKEN 源图（sha 674d733f）：`output/_image_figma_acctoken_models_20261108_rerun_full_high/input.png`
- 流水线 ACCTOKEN 对账基线：`output/_image_figma_acctoken_models_20261108_rerun_full_high/figma_font_calibrated/readback.json`（字号 ×0.64、字重 26/43 失配、文本串如『半20.24 起』『看详情 →』暴露短单元合并/后缀问题）
