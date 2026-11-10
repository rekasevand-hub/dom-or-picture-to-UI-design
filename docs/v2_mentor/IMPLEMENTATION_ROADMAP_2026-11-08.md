# Image → Figma 泛化收尾路线图（最终实施建议）

**日期：** 2026-11-08（晚）／ **修订：** 2026-11-09（晨，三族黄金稿齐备）／ **2026-11-10（Phase 5 纳入 Figma 官方 skill 原则 + 结构基线实测）**
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

> **注**：下表是 2026-11-08/09 的历史基线，作为回归起点保留。工时确认族已于 2026-11-10 **整族换代**（新基准图 + 原生金稿 `77:42771`），其当前值为 within30 **95.00**、critical **30/30**、`ink_ratio` **1.000 (n=100)**，历史数字不可跨代次引用。

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

> **2026-11-10 修订（务必先读）**：本节原方案有两处已被实测推翻，照着重走会白费功夫。
> 字重「笔画密度证据」**不可行**；同框渲染差分也**不可行**；实际落地的是**结构规则**。
> 字号「闭环收敛」已达局部最优，真正的问题是指标失真，口径已改。全部实测数据见 `20261110_font_weight_evidence.md`。

**归因（2026-11-09 已完成，比预想更深）：**
- light-table 巨型文字根因 = **双轨发射**：VLM 把内容面板当表格（表 bbox `[470,177,1906,803]` vs 真实 `[470,~440,…]`）→ 均匀网格合成 10 个表头在 y=177 鬼影带（fs 48.5–90.75）；同时 grounded 真表头在 y=444（fs=20 正确）**两套都发射**（不同 contentRef、不重叠 → 现有去重/审计均不触发）。→ 主修在 Phase 2（表几何锚定到 grounded 文本）。
- dark 欠小根因 = **元素框紧裁剪**：20px 高的框装 22px+ 的字（gold fs 26），一次性测量物理上被框裁掉；另有少数错位框量到无关内容（如蓝色链接）。→ 主修 = fs 自校准闭环（渲染墨迹 vs 源墨迹收敛）。
- style_resolver 测量层放大器已修（2026-11-09）：固定阈值 24 → 自适应 Otsu（clamp 6–32）+ 主墨迹行带选择（松框内 chrome 不再计入 ink 跨度）。效果：light-table 灾难膨胀 22→10 例；单测 8+35 全过。
- light-form（1x 浅色）字号本来就对（ratio 1.0）——误差确证为 2x/深色/表几何三个触发条件的并集。

**修复状态（2026-11-10 逐条核对）：**

| 原计划 | 状态 | 实测结论 |
|---|---|---|
| 字号：墨迹高度自洽闭环 | ✅ 已在用 | 死区 `[0.85,1.175]` 与钳位 `[0.7,1.5]` 都是**承载性参数**：收紧死区 light-table 94.07→93.33，丢弃极端比值→93.44，两次都回退 |
| 字重：笔画密度证据（Otsu 自适应阈值） | ❌ **否证** | 框几何噪声（`stroke/ink_height` p05–p95 = 0.458–1.438，±55%）大于字重步长（+35%）；`eta` 不是双峰检验（单峰高斯即 0.637）；Medium(500) 不可分（AUC 0.846） |
| 字重备选：同框渲染-源图墨迹差分 | ❌ **否证** | dark 改动 19 条只中 4 条，`style_mm` 24/39 → **25/39**；页内归一化后各字重密度比 Regular 1.000 / Medium 0.905 / Bold 1.027 / Black 0.894，组内离散 ±15% |
| 字重实际方案：**结构规则** | ✅ 已落地 | `apply_display_weight_by_scale`：字号 ≥1.8× 自由文本众数 → Bold，排除 table-cell/table-header/control。dark `style_mm` **24/39 → 21/39**，另两族逐位不变 |

**验收（2026-11-10 修订，原口径有两处失效）：**

| 族 | 原验收 | 修订后 | 原因 |
|---|---|---|---|
| 工时确认 | font ratio 1.5 → 1.0±0.1 | **改看 `ink_ratio` ≈ 1.0**；该族 2026-11-10 已整族换代，旧 font_ratio 口径作废 | font_ratio 除的是两个声明字号，混着字体度量差，已降级为诊断 |
| ACCTOKEN | font ratio 0.64 → 1.0±0.15 | font ratio 仅作诊断；主看 `ink_ratio`（现状 0.944） | 同上 |
| ACCTOKEN | 字重失配 26/43 → **≤8/43** | **≤14/43**（= 允许 Medium 全错 + 少量边界错） | 8 条 Medium 在笔画证据上不可分，单这一项就吃满全部名额 |
| ACCTOKEN | native gate 0/37 → ≥15/37 | 维持，但需先解决字重（edgeF1 部分改善不足以单靠它过线） | — |
| FlexWeaver | native gate 14/33 不回退；within30 不降 | 维持（现状 24/24 critical、92.19% within30） | — |

**剩余空间（2026-11-10 现状）**：dark `style_mm` 21/39 中仍有 8 条 Medium（导航项，约 1.37× body，卡在 1.8× 阈值下），需第二个结构信号「同一行重复的水平文本组」；light-table 新金稿可评估后首次量出 14/105 字重失配。

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

> **2026-11-10 更新**：纳入 Figma 官方 skill 的画布组织原则，并补上三族金稿与输出的结构实测基线。本节现在的口径是「**先取证，再升级**」——不是「照着 skill 的样子改」。

### 7.0 外部先验的定位：官方 skill 对各 Phase 的价值分布

Figma 官方在 MCP 文档里说 "Agents can write to the canvas or build from designs with MCP tools and skills"，这句话包含两层能力：**连接层**（MCP 工具：读写画布）与**指令层**（skills：如何组织画布）。对本项目的价值分布完全不同：

| Phase | 官方 skill 的价值 | 判断依据 |
|---|---|---|
| Phase 1 字重/字号推断 | **低** | skills 讲画布组织，不讲「从像素推字号」 |
| Phase 2 几何与表格 | **低** | 同上 |
| Phase 3 视觉裁判 | **低–中** | 只能提供缺陷分类的术语参考 |
| **Phase 5 结构发射** | **中高** | 直接对应「输出扁平 1 层」这个卡点 |

三条边界必须写清楚，否则会被误用：

1. **它是设计工具层先验，不是图像感知能力。** 不帮助看懂图，只帮助按 Figma 原生方式组织已经看懂的内容。
2. **它解决「怎么组织」，不解决「结构应该是什么」。** 一坨元素该识别成卡片、表格还是列表，仍取决于 grounding 与规则推断。
3. **它可能压过证据。** 官方倾向「组件化 + Auto Layout」，但原图未必具备这些语义。必须坚持「有证据才升级结构」。

**MCP 连接层本身对本项目无增益**：仓库已有自建插件桥（`figma_bridge/` + 本地 WebSocket），写入、回读、幂等与清理控制比通用 MCP 更细。MCP 只在「拿 Figma Make 产物做对照评估」时有间接用途，不作为泛化突破口。

### 7.1 三族结构基线（2026-11-10 实测，Phase 5 的真实起点）

| 族 | 金稿 depth | 金稿 FRAME | 金稿 layoutMode | 输出 depth | 输出 FRAME |
|---|---|---|---|---|---|
| dark-card-grid | 8 | 69 | VERTICAL 7 / HORIZONTAL 45 / NONE 17 | 1 | 1 |
| light-form | 5 | 86 | HORIZONTAL 52 / NONE 34 | 1 | 1 |
| light-table | 5 | 55 | **NONE 55（全绝对定位）** | 1 | 1 |

**一条反直觉的实测，必须记住**：

- light-table **新**金稿 55 个 FRAME 全是 `NONE`（零 Auto Layout），几何对齐 **100%**（109/109 框落在文字上）、文本一致率 93.9%；
- light-table **旧**金稿同样全是 `NONE`，几何只有 **39%**。

→ **Auto Layout 既不是几何对齐的充分条件，也不是必要条件。** 结构升级的目标是「对齐该族金稿的可编辑性」，不是「让 layoutMode 字段好看」。

### 7.2 原则 → 规则：四层切分

**L1 无证据也必须满足（结构底线，任何族都不例外）**

1. 单一根 Frame；其余内容全部归入语义父子树，无孤立顶层元素；
2. 文本一律原生 TEXT，禁止整页截图作为交付层；
3. 所有写入可回读（readback 非空、节点数与 design 一致、无静默丢弃）；
4. 无文字裁切、无父子溢出（子节点 bbox ⊆ 父节点 bbox，容差 2px）。

**L2 有证据才启用（结构升级，逐条独立验收）**

| 规则 | 证据形式 | 现有能力 |
|---|---|---|
| 相邻同轴元素 → Auto Layout | ≥3 元素共享同一轴，且间距 CV ≤5% | `layout_plan.py`（目前仅 DOM 路线） |
| 重复结构 → 本地组件 + 实例 | 结构签名（类型 + 尺寸 + 子结构）一致 ≥3 次 | 无，需新建 |
| 表格行/列 → Grid 或行列布局 | 行/列等距序列（`_row_pitches` 已能识别） | 部分 |
| 颜色/间距 → 变量或样式 | 同一值重复 ≥5 次 | 无 |

**L3 无证据保持绝对定位**

不得为「符合 skill」强行 Auto Layout。判据：容器内元素间距 CV >5% 或主轴不唯一 → 保持 `NONE`。**这条是防止结构升级破坏现有像素稳定性的闸门。**

**L4 不可承诺（验收口径不得要求）**

截图无法证明的东西：真实设计系统复用、源组件身份、变量 token 身份、交互行为。把它们写进验收会逼着实现去猜。

### 7.3 原有四条要点（仍然有效）

- `scene_plan` parents → Figma FRAME 层级映射（`fixed_canvas_compiler.py` + bridge `apply_batch` 已支持 parentId）。
- 重复组（表单字段行、表格行、按钮组）→ `set_layout_flow` auto-layout（bridge 已有 `set_autolayout`/`set_layout_flow`/grid 覆盖，probe 脚本已验证）。
- 位图降级判据收紧：仅照片/logo 类区域允许 IMAGE fill；图标走 `image_enrichment/vector_icons.py`。
- 验收：结构统计对标黄金稿，双族像素指标不回退。

**与 7.2 的关系**：第二条要受 L2/L3 约束——「重复组」先要过结构签名证据，才允许 auto-layout；否则保持绝对定位。

### 7.4 落地顺序（每步独立可回退）

1. **结构契约审计器（只读，零风险）** —— 扩 `scripts/audit_gold_tree.py` 或新建 `scripts/audit_structure.py`，量化 L1 四项 + 7.5 全部指标，先回答「现在到底差多少」。不改任何发射逻辑。
2. **层级接入**：`scene_plan` parents → FRAME 父子树。只做层级，不做组件化，不做 auto-layout。门禁只看「像素不回退 + L1 全过」。
3. **Auto Layout 候选**：复用 `layout_plan` 对截图容器做同轴检测，接入 L2 第一条规则，设视觉不回退门（within30 ≥ 基线 −0.3）。
4. **组件实例化实验**：只对「结构签名一致 ≥3 次」的组做，先在一个族验证。
5. **结构指标进三族门禁 + 独立 holdout**，证明不是只对三族过拟合。

### 7.5 验收指标（替代原来的「深度 ≥4、FRAME ≥50」单一门槛）

| 指标 | 现状 | 目标 | 说明 |
|---|---|---|---|
| depth | 1 | ≥4 | 金稿 5–8，取各族金稿值 −1 作为下限更严谨 |
| FRAME 数 | 1 | ≥30 | 金稿 55–86，不以「越多越好」为目标 |
| Auto Layout 覆盖率 | 0 | **对标该族金稿**（dark 75% / light-form 60% / light-table 0%） | 不设统一目标，按族取证 |
| 父子溢出 | 未测 | 0 | L1 第 4 条 |
| 孤立顶层元素 | 未测 | 0 | L1 第 1 条 |
| 回读一致性 | 已满足 | 保持 | readback 节点数 = design 节点数 |
| 像素不回退 | — | within30 ≥ 基线 −0.3 | 铁律 2 |

---

## 8. 执行顺序与依赖

```
Phase 0（基准固化）────────────┐
Phase 1（字号/字重规则）→ Phase 2（表格规则）→ Phase 4（门禁标定）→ Phase 5（结构）
Phase 3a（草稿 grounding）── 独立，随时可跑 ──┘
Phase 3b（VLM 裁判）── 标定独立；进环依赖 Phase 1 完成（字号对了才测得出真残差）

Phase 5 内部（7.4）：结构审计（只读）→ 层级 → Auto Layout → 组件化 → 门禁
                     ↑ 结构审计可与 Phase 1 剩余项并行，零风险
```

## 9. 风险与边界

- **VLM 成本**：两遍式 grounding 与裁判调用使单图 VLM 调用数上升约 2–3 倍；持久缓存 + 有界迭代（≤2 轮）控制。
- **新族扩展**：看板/仪表盘等新版式族仍需 1 张 Figma Make 黄金稿学习族习惯（**每族一次**的扩展成本，非每图）；学到的必须是规则。
- **不做的事**：不逐图蒸馏、不追单图 SOTA 分数、不给单样本加特判、不把 Figma Make 输出混入运行时链路。
- **结构过度拟合（Phase 5 新增）**：官方 skill 倾向「组件化 + Auto Layout」，但原图未必具备这些语义。若为「让 layoutMode 好看」而强行 auto-layout，会以像素稳定性换取结构指标，违反铁律 2。闸门是 §7.2 的 L3：无证据保持绝对定位。
- **结构指标不等于可编辑性**：depth/FRAME 数是可以刷的——空 FRAME 也能堆深度。验收必须同时看「父子语义合理（L1 第 1 条）」与「像素不回退」，单看计数会被绕过。
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
- 三族黄金稿 frame（2026-11-10 换代后）：FlexWeaver `12:1223`（1920×826，原 `2:523` 已删除）、工时确认 `77:42771`（2544×1336 原生，1:1；原 `32:2520` 为 1920×1008 重建稿，几何仅 39% 已弃用）、ACCTOKEN `35:2909`（2544×1336，1:1）
- **换金稿前必跑** `scripts/audit_gold_tree.py`（验收线：框落在文字上 ≥80%、文本一致率 ≥80%、行距对齐）；旧工时确认金稿三项全挂，但在 Figma 画布里肉眼看不出来
- ACCTOKEN 源图（sha 674d733f）：`output/_image_figma_acctoken_models_20261108_rerun_full_high/input.png`
- 流水线 ACCTOKEN 对账基线：`output/_image_figma_acctoken_models_20261108_rerun_full_high/figma_font_calibrated/readback.json`（字号 ×0.64、字重 26/43 失配、文本串如『半20.24 起』『看详情 →』暴露短单元合并/后缀问题）
