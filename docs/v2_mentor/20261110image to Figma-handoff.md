# Image → Figma · 交接文档（2026-11-10）

**日期：** 2026-11-10（上午：Phase 2/3a；下午—晚间：Phase 1 字重 + 字号口径 + light-table 金稿换代）
**性质：** 当日工作交接（目标 / 完成 / 文件 / 修改明细 / 测试 / 遗留 / 下一步 / 禁改项）
**前置文档：**
- `20261109image to Figma-handoff.md`（Phase 0/1/2/4 交接）
- `IMPLEMENTATION_ROADMAP_2026-11-08.md`（路线图）
- `20261110_column_anchoring_handoff.md` / `20261110_suppression_split_handoff.md`（上午两份详细交接）
- `20261110_font_weight_evidence.md`（**本轮主证据文档**：字重/字号/金稿几何的全部实测数据与否定性结论）

**当日提交：**
- `941cf5c` 列锚定 / `679a1eb` 抑制拆分 / `50f912f` dark truth 勘误（上午）
- `41f089f` **feat(v2): structural font weight, ink-ratio size metric, light-table gold renewal**（本轮，24 files，+25671/−23601）

**运行环境：** `C:/Users/lzq/.conda/envs/omni/python.exe`
**Bridge：** `python -m src.app.services.bridge_server`（ws://localhost:8765，插件自动重连）。**交付时已关闭**（端口 8765 已释放），下次跑 Figma 写入前需重新启动。

---

## 0. 本轮速览（要只读一段就读这里）

本轮做三件事，全部落地且三族门禁 PASS（`--rerun --policy 2.1`，退出码 0）：

| # | 事情 | 结果 |
|---|---|---|
| 1 | **Phase 1 字重**：像素推断被实测否证，改走结构规则 | dark `style_mm` 24/39 → **21/39**，另两族逐位不变 |
| 2 | **字号口径变更**：`font_ratio` 降级为诊断，`ink_ratio` 成为主指标 | dark `ink_ratio` 0.944、light-form 1.000、light-table 1.000 |
| 3 | **light-table 整族换代**：新基准图 + 原生金稿 | 金稿框落在文字上 39.0% → **100%**，文本一致率 47.3% → **93.9%** |

三族终态：

| 族 | within30 | ink_ratio | style_mm | dy_med | critical |
|---|---|---|---|---|---|
| dark-card-grid | 94.72% | 0.944 (n=37) | 21/39 | 4.5 | 27/27 |
| light-form | 92.19% | 1.000 (n=74) | 16/75 | 1.0 | 24/24 |
| light-table | **95.00%** | **1.000 (n=100)** | 14/105 | **5.9**（旧 42.4） | **30/30** |

---

## 1. 本次任务的目标

### 本轮（下午—晚间）

用户指令依次为：「从 Phase 1 的字重证据链开始」→「先搞字号」→「批准改口径」→「让 Figma Make 重新生成金稿」。

1. **Phase 1 字重**：路线图要求把 dark 的字重失配从 26/43 压到 ≤8/43。先做只读证据链，再决定实现载体。
2. **Phase 1 字号**（另一半）：`font_ratio` 收敛到 1.0±0.05，先判断这个指标本身是否可信。
3. **口径治理**：若指标本身失真，改指标而不是改代码。
4. **light-table 金稿**：诊断该族字号指标长期"不可评估"的根因，并修复。

### 上午（已完成，简述）

Phase 2 列锚定（x 方向）与 Phase 3a 感知收尾（抑制拆分 + 审计不变量重写），详见两份独立 handoff。

---

## 2. 已经完成的内容

### 2.1 Phase 1 字重：像素路两条全部否证，结构规则落地 ✅

**先做只读证据链**（`scripts/p1_font_weight_evidence.py`，三族 gold 的 `variationSettings.wght` 作真值）。四个否定性发现：

1. **笔宽必须用覆盖率积分**，二值掩膜只有 0.5px 分辨率；16px 文本 Regular→Bold 只差 0.4–0.9px。
2. **框几何噪声 > 字重信号**：同一批文本，金稿框与运行时感知框的 `stroke/ink_height` 比值 p05–p95 = 0.458–1.438（只有 61.3% 落在 ±10% 内），而 400→700 的真实步长只有 +35%。
3. **Otsu 的 `eta` 不是双峰检验**：单峰高斯在均值切开就是 2/π≈0.637；light-table 全页 151/154 是 Regular 却给出 0.86。无锚点的页内自适应必然造出假 Bold。
4. **Medium(500) 在笔画证据上不可分**：dark CJK 的 400>500 AUC 只有 0.846，样本内作弊三切分仍剩 8/34 错。

**实现载体一（失败，已回退）**：`calibrate_text_weight_from_render`，同框渲染-源图墨迹差分。dark 实测改动 19 条**只有 4 条命中 gold**，`style_mm` 24/39 → **25/39（变差）**。根因量化：页内归一化后各字重的密度比 Regular 1.000 / Medium 0.905 / Bold 1.027 / Black 0.894，组内离散 ±15%——**墨迹密度携带的字体替换与抗锯齿差异，量级不小于它携带的字重信息**。注册已完全回滚（`calibration_strategies.py` 与 HEAD 零差异），函数与 9 个单测保留并注明"未接线 + 失败数据"。

**实现载体二（落地）**：`apply_display_weight_by_scale`，纯结构规则：

1. `body` = 页面**自由文本**的众数字号（排除表格单元格/控件）；
2. 字号 ≥ **1.8 × body** → 展示级 → 提升到 Bold；
3. 只提升当前为 400 的 owner（不覆盖其它策略显式设的 Light）；
4. `table-cell` / `table-header` / `control` 一律不参与。

**实测陷阱**：第一版没有角色过滤，light-table 的 `(选填)` / `请输入0~` 因 `fontSize` 被输入框高度放大（48.5–78.75）被误提为 Bold，`within30` 94.07 → **93.68 回归**。加角色过滤后归零——`imageMVP.role == "table-cell"` 是结构证据，不是文本特判。

**阈值选择**（离线扫描，clean baseline）：1.4/1.5/1.6 时 dark 更好但 light-table 回归；**1.8 时 dark 19、另两族 0 候选**，只有这个点同时满足"有收益"和"零回归"。

**未采纳**：`≥2× body → Black` 二级档能把 `模型广场`/`本期好价` 再收 2 条，但完全由这 2 条样本拟合，且同一档会把 `5.8折` 判成 Black。不追单样本分数。

### 2.2 字号：闭环参数已到局部最优，改的是指标不是代码 ✅

先判断 `font_ratio 0.906` 的性质：dark 逐条字号比 p10–p90 = 0.567–1.308（分布很宽，不是统一偏小）。

**两次实验都回退**：

| 改动 | dark font_ratio | light-table within30 | 判定 |
|---|---|---|---|
| 基线 | 0.906 | 94.07 | — |
| 死区收紧到路线图口径 1±0.05 | 0.919（仅 +0.013） | **93.33 回归** | 回退 |
| 极端比值弃权（不钳位） | 0.906 | **93.44 回归** | 回退 |

第二条反直觉：light-table 有 27/46 条改动的比值撞在钳位边界（0.7/1.5），看着像测量失败，丢掉它们 within30 反而掉 0.63——**它们在修正真实过大的字号**。极端比值不等于错误。

**结论：`ink-convergence` 的死区与钳位都是承载性参数**，已在 docstring 标注 re-tested，并由 `tests/v2/test_ink_convergence_band.py`（5 例）锁定。

**口径试算**（`scripts/size_metric_probe.py`）：

| 族 | 可测对 | `size_ratio`（旧 font_ratio） | `ink_ratio` | `font_metric` |
|---|---|---|---|---|
| dark | 37 | 0.906（±10% 内 48.6%） | 0.944（**56.8%**） | 0.976（0.929–1.133） |
| light-form | 74 | 1.016（85.1%） | 1.000（86.5%） | 0.985（0.971–1.017） |
| light-table | 11 | 1.186（9.1%） | 0.889（18.2%） | 0.718 |

这否证了"约 9% 字体度量差"的旧说法：真实量级是 **1.5–2.4%**（light-form 的 `font_metric` p25–p75 仅 0.971–1.017）。

**口径变更（用户批准后落地）**：

| 项 | 改前 | 改后 |
|---|---|---|
| 字号主指标 | `font_ratio_median` | **`ink_ratio_median`**（同一金稿框内的渲染/源图墨迹高度，几何自抵消） |
| `font_ratio` | 判回归 | **仅诊断**，漂移写 `gate_notes`，不进退出码 |
| 不可评估族 | 无此概念 | `family.json` 可声明 `size_metrics.evaluable: false`；另加硬前置 `ink_ratio_pairs >= 20` |
| 基线注册 | `--register` 重置全部 | 新增 `--register-ink`，只增/刷墨迹基线 |

**边界条件（重要）**：`ink_ratio` 的"几何抵消"只在**框正确套住文字**时成立。实测把修正因子从 1.00 调到 1.05，同一批文本的 `ink_ratio` 从 1.000 变成 1.050（正好跟着 f 走）。所以它只能用在已对齐的金稿上，**不能反过来用它验证金稿对不对齐**。

### 2.3 light-table 整族换代 ✅

**诊断**：154 个金稿框只有 **39.0%** 落在参考图的文字上。三次排查：

1. `scale 1.325` 没算错（2544/1920 = 1.3250，1336/1008 = 1.3254，与配置一致）；
2. 不是"Figma Make 重建稿必然对不齐"——dark/light-form 同为重建稿，`ink_fraction` 都是 100%；
3. 全局缩放治不了：修正因子 1.05 只把可测率提到 62%，因为误差**逐行累积**（横向偏移与纵坐标相关系数 +0.63）。

**根因**：旧金稿 `32:2520` 是 1920×1008 的重建稿，重画时把表格布局重算过——行距 57 逻辑像素（75.5 物理）而截图是 81，20 行累积错开 110px；同时**表头列名被语义改写**（`项目代码`→`项目编号`、`绩效评估说明`→`备注说明`、`填报日期`→`日期`），筛选页签也被改写（`未确认(0)`→`待确认(0)` 等）。

**修复**：用户按建议用 Figma Make 重新生成 layer「日工时确认 · 截图逐字还原」，输入 2544×1336 PNG（8 行/1 页签的当前状态）+ 逐字还原 prompt。新金稿 `77:42771`：

| 指标 | 旧 `32:2520` | 新 `77:42771` |
|---|---|---|
| 尺寸 / scale | 1920×1008 / 1.325 | **2544×1336 / 1.0** |
| TEXT 数 | 154 | 109 |
| **框落在文字上** | **39.0%** | **100%（109/109）** |
| **文本一致率** | **47.3%** | **93.9%** |
| 表头 / 筛选页签 / 按钮 | 改写 | **逐字还原** |
| 表格行距 | 75.5px（截图 81，差 5.5） | **81px（与截图一致）** |

**换代后族指标**：

| 指标 | 换代前 | 换代后 |
|---|---|---|
| within30 | 94.07% | **95.00%** |
| **ink_ratio** | 0.889（n=11，噪声） | **1.000（n=100）** |
| font_ratio（诊断） | 1.186 | **1.005** |
| dy_median | 42.4 | **5.9** |
| critical | 29/29 | **30/30** |

两条最值得注意：`ink_ratio` 从"11 个噪声样本"变成"100 个真实样本且恰好 1.0"——**这一族的字号本来就没问题，之前全是测量失效**；`font_ratio 1.186` 那个"字号偏大 18%"的幽灵是 `scale 1.325 × 金稿布局错误`的复合产物，换原生尺寸后自动归零。

**连带修复**：`light-form/family.json` 的 `gold.frame_id` 从已删除的 `2:523` 更新为 `12:1223`（重导出前后 `font_ratio 1.0 → 1.016`，`within30`/`critical` 不变，门禁 PASS，无需重注册）。

### 2.4 门禁自身的两个缺陷（期间暴露并修复）✅

**一、复跑失败被静默吞掉。** `_rerun_family` 只检查子进程退出码，而 `image_figma_mvp.py` 在环境故障时返回 2（`blocked-environment`）也算"正常"。门禁于是继续读 `figma/` 阶段的残留产物（**校准之前**的渲染），拿它对比**校准之后**的基线，得出「within30 94.28 < 95.00 回归」——一条完全虚构的回归。

修法：读 `acceptance.json`，按**证据可用性**判定而非状态字符串：

| acceptance 状态 | 含义 | 处理 |
|---|---|---|
| `blocked-environment` | 无有效产物 | 判 `rerun-fail`，提示重载 Figma 插件 |
| `blocked-fail` | 产物完整，只是某个门没过（native text 三族都未达标） | **接受**，照常计分 |
| `visual.within30_pct` 或 `critical_text.matched_count` 为空 | 测量不成立 | 判 `rerun-fail` |

第一版把 `blocked*` 一律拒绝，反而误杀了正常的 `blocked-fail`——判据必须是"有没有证据"。

**二、`--register` 漏写 `ink_ratio`。** 新族注册后报「ink_ratio measured but no baseline registered」，主字号门被静默禁用。现在两个注册入口写同一组字段。

### 2.5 上午（Phase 2 / 3a，简述）

列锚定（`_anchor_table_columns`，DP 选候选竖线子序列 + 中位数聚合）与抑制拆分（`scene_plan` 派生 `:split` 节点 + `emission_contract` 不变量 3 重写）。三族 critical 全部满分。详见两份独立 handoff，本文不重复。

---

## 3. 已修改的文件

**修改（M，11 个）：**
- `scripts/check_benchmark_families.py`
- `src/app/services/structure/fidelity/calibration_strategies.py`
- `src/app/services/structure/fidelity/text_calibration.py`
- `tests/fixtures/benchmark_families/README.md`
- `tests/fixtures/benchmark_families/dark-card-grid/family.json`
- `tests/fixtures/benchmark_families/light-form/family.json`
- `tests/fixtures/benchmark_families/light-form/gold_tree.json`
- `tests/fixtures/benchmark_families/light-table/family.json`
- `tests/fixtures/benchmark_families/light-table/gold_tree.json`
- `tests/fixtures/benchmark_families/light-table/reference.png`
- `tests/fixtures/benchmark_families/light-table/truth.json`

**新增（A，13 个）：**
- `docs/v2_mentor/20261110_font_weight_evidence.md`
- `scripts/audit_gold_tree.py`
- `scripts/export_gold_tree.py`
- `scripts/figma_pages_report.py`
- `scripts/p1_font_weight_evidence.py`
- `scripts/size_metric_probe.py`
- `tests/v2/test_audit_gold_tree.py`
- `tests/v2/test_benchmark_gate_size_metric.py`
- `tests/v2/test_display_weight_by_scale.py`
- `tests/v2/test_font_weight_evidence.py`
- `tests/v2/test_ink_convergence_band.py`
- `tests/v2/test_size_metric_probe.py`
- `tests/v2/test_text_weight_convergence.py`

**不入库（按设计）：** `.env`（含 `VISION_API_KEY`）、`output/`（run 产物）、`.workbuddy/`（工作区记忆）。

---

## 4. 每个文件修改了什么

### 核心代码

| 文件 | 修改内容 |
|---|---|
| `text_calibration.py` | ① 新增 `apply_display_weight_by_scale`：body = 自由文本众数字号；≥1.8×body → Bold；只提升 400；排除 `table-cell`/`table-header`/`control`。② 新增 `calibrate_text_weight_from_render`（**未接线**）+ `_weight_for_ink_ratio`/`_normalize_font_weight`/`_ink_stats`/`_element_source_bbox`：同框渲染-源图墨迹差分，docstring 写明失败数据（19 改 4 中，24→25）。③ `calibrate_ink_convergence_from_render` 的 docstring 补记两次收紧实验与"死区/钳位是承载性参数"。 |
| `calibration_strategies.py` | 挂载 `display-weight` 策略到 `font-initial` 组首位（`always=True`，不增加渲染次数）。策略声明"结构而非统计：页面自身排版系统决定谁是展示级"。 |
| `check_benchmark_families.py` | ① `_flatten_texts` 补 `width`/`height`（构造 bbox）。② 新增 `_ink_ratio_metrics`：同一金稿框内渲染/源图墨迹高度比，<3px 墨迹跳过。③ `_answer_key` 增 `ink_ratio_median`/`ink_ratio_pairs`/`ink_ratio_within10pct`，pairs 带 `bbox`。④ 新增 `_size_metrics_scope`：`size_metrics.evaluable: false` 或 `ink_ratio_pairs < 20` 时弃权。⑤ `_gate` 改返回 `(regressions, notes)`；`ink_ratio` 判回归（容差 0.05，含 1e-9 边界 epsilon 修浮点问题）；`font_ratio` 降级为 note。⑥ 新增 `--register-ink`；`--register` 补写 `ink_ratio_median`/`ink_ratio_pairs`。⑦ `_rerun_family` 增证据可用性守卫（拒绝 `blocked-environment` 与无 within30/critical 的产物，提示重载插件）。 |
| `dark-card-grid/family.json` | `baselines` 追加 `ink_ratio_median: 0.944`、`ink_ratio_pairs: 37`、`ink_ratio_registered_from: "rerun"`；其余基线未动。 |
| `light-form/family.json` | `gold.frame_id` `2:523` → `12:1223`，补 `previous_frame_id`/`reexported_at`/`reexport_reason`/`answer_key_at_reexport`；`baselines` 追加 ink 三项（1.000 / 74）。 |
| `light-form/gold_tree.json` | 从实时帧 `12:1223` 重新导出（159→202 节点，TEXT 79 不变，深度 4→5）。 |
| `light-table/family.json` | **整族换代**：`sample`/`gold`（`32:2520` → `77:42771`，scale 1.325 → 1.0，补 `previous_frame_id`/`reexport_reason`）/`pipeline_run` 全部换新；删除 `size_metrics.evaluable: false`（新金稿可评估）；`baselines` 全部重注册；`history` 追加换代链路。 |
| `light-table/gold_tree.json` | 换成 `77:42771` 原生 2544×1336 节点树（252 节点 / 109 TEXT / 深度 5）。 |
| `light-table/reference.png` | 换成 8 行/1 页签的当前状态截图（`e0eefc67`，2544×1336 PNG）。旧图备份在 `output/_gold_new/backup/`。 |
| `light-table/truth.json` | `sample_id` → `IMG-TIMESHEET-CONFIRM-20261110`；`critical_texts` 重写为 30 条（侧边栏 7 + 搜索 3 + 筛选 4 + 表头 10 + 数据 6）；`image_sha256` 更新；`derived_from`/`derivation_note` 说明换代原因。 |
| `benchmark_families/README.md` | 表格 frame id 与缩放更新；新增 light-table 换代说明与"换金稿前先跑 `audit_gold_tree.py`，验收线 ≥80%/≥80%"；新增字号指标口径表（ink_ratio 主 / font_ratio 诊断）。 |

### 新增工具

| 文件 | 作用 |
|---|---|
| `audit_gold_tree.py` | **换金稿前的体检门**。三项判据：框落在文字上（`ink_fraction` ≥80%）、文本一致率（金稿字符串 vs 流水线输出 ≥80%）、行距（等距 FRAME 序列 vs 截图文字行众数）。输出 `usable` / `not-usable`。旧 light-table 金稿在这三项上全挂，但在 Figma 画布里肉眼看不出来——这是它存在的理由。 |
| `export_gold_tree.py` | 从 Figma 节点导出 `gold_tree.json`。**帧尺寸必须等于 `reference.png`** 才允许写入（否则 `scale_to_reference` 会静默出错）；支持 `--dry-run`/`--force`。 |
| `figma_pages_report.py` | 只读工具：列页面/顶层 FRAME、导出指定帧的 TEXT 样式。只发 `get_node_tree`，不写 Figma。 |
| `p1_font_weight_evidence.py` | Phase 1 字重只读探针。以金稿 `variationSettings.wght` 为真值，测笔画几何（覆盖率积分亚像素笔宽）、框几何敏感性、Otsu/Fisher/二分规则与二分上界。 |
| `size_metric_probe.py` | 字号三联指标探针：`size_ratio` / `ink_ratio`（同一金稿框）/ `font_metric`（= ink/size，字体度量常数）。含亚像素墨迹高度对照（实测更差）。 |

### 新增测试

| 文件 | 覆盖 |
|---|---|
| `test_display_weight_by_scale.py` | 结构规则：阈值边界、角色排除（table-cell/control 永不提升）、body 众数计算、只提升 400。 |
| `test_text_weight_convergence.py` | 渲染差分策略的失败复现（未接线函数），9 例。 |
| `test_font_weight_evidence.py` | 指标性质：亚像素笔宽、Otsu 不是双峰检验、AUC 边界、框几何敏感性。 |
| `test_ink_convergence_band.py` | **回归保护**：死区容忍 10%、极端比值钳位而非丢弃（5 例）。 |
| `test_size_metric_probe.py` | 配对逻辑（一对一、最近位置）与墨迹测量。 |
| `test_benchmark_gate_size_metric.py` | 门禁口径：ink 漂移超 0.05 才失败、font 漂移只记 note、不可评估与可测对不足都弃权、像素指标独立判定、边界 epsilon（14 例）。 |
| `test_audit_gold_tree.py` | 三族均为 `usable`；改写金稿与错位金稿用合成数据验证能被识别（9 例）。 |

---

## 5. 已运行的测试及结果

**单元测试**（omni python + `-p no:cacheprovider`）：

| 范围 | 结果 |
|---|---|
| 本轮 9 个相关文件：`test_benchmark_gate_size_metric` + `test_audit_gold_tree` + `test_display_weight_by_scale` + `test_ink_convergence_band` + `test_size_metric_probe` + `test_font_weight_evidence` + `test_text_weight_convergence` + `test_calibration_strategies` + `test_fixed_canvas_compiler` | **97 passed** |
| `test_audit_gold_tree.py` 单独 | 9 passed |
| `test_benchmark_gate_size_metric.py` 单独 | 14 passed |

**端到端 / 门禁：**

| 实验 | 结果 |
|---|---|
| dark `--rerun`（加 text-weight 渲染差分） | `style_mm` 24→**25（变差）**，回退 |
| dark/light-form/light-table `--rerun`（显示级规则，无角色过滤） | light-table `within30` 94.07→**93.68 REGRESSION**，加角色过滤 |
| 三族 `--rerun`（显示级规则 + 角色过滤） | **全 PASS**，dark 24→21 |
| 三族 `--rerun`（死区收紧 1±0.05） | light-table 93.33，回退 |
| 三族 `--rerun`（极端比值弃权） | light-table 93.44，回退 |
| light-table 全量 run（新图 + 新 truth） | within30 **95.0007**、critical **30/30**；`acceptance.status = blocked-fail`（唯一阻塞项 native text 33/60） |
| 三族 `--rerun --policy 2.1`（换代后终验） | **全 PASS，退出码 0**：dark 94.72 / light-form 92.19 / light-table 95.00 |
| light-table `--register` + `--register-ink` | 基线写入：95.0007 / 1.000(n=100) / 5.9 / 30/30 |
| 复跑一致性 | light-table 复跑结果与基线**逐位一致**，证明 `--rerun` 对同一份 pipeline 是确定性的 |

**审计与勘察（只读）：**

| 工具 | 结论 |
|---|---|
| `audit_gold_tree.py`（三族） | dark：100% / 83.0%；light-form：98.7% / 94.9%；light-table（旧）：39.0% / 47.3% → **not-usable**；light-table（新）：**100% / 93.9% → usable** |
| `figma_pages_report.py` | 文档 1 页、420 个顶层 FRAME；核实三个金稿帧位置与文本样式与冻结稿一致（dark/light-table 逐条相同，light-form 属旧代次，已重导出） |
| `p1_font_weight_evidence.py` | 见 §2.1 四条否定性发现 |
| `size_metric_probe.py` | 见 §2.2 三联表 |

---

## 6. 当前仍存在的问题

1. **native text gate 三族都未达标**（政策要求 100%）：light-table 新 run 为 33/60 = 55%，是 `acceptance.status = blocked-fail` 的唯一阻塞项。这不是本轮引入的，`within30` / `critical` / 结构 / 保真四个维度全 pass，不影响 run 作为基线。
2. **dark `style_mm` 仍 21/39**：剩余 8 条是 Medium（导航项，尺寸约 1.37× body，卡在展示级 1.8× 阈值之下）。需要第二个结构信号——"同一行上重复出现的水平文本组"（导航条形状），该信号同样是结构推导而非点名。
3. **dark `ink_ratio 0.944`**（约 −5.6%，接近 0.05 容差边缘）：这是真实差距。要收它需要更可靠的墨迹测量（更多可测对、更稳的对比度阈值），不是调闭环参数。
4. **light-table `style_mm` 14/105**：新金稿可评估了，字重失配才第一次被真正量出来。这是新暴露的、待处理的真实缺口（不是回归，此前根本测不到）。
5. **`calibrate_text_weight_from_render` 未接线**：保留为失败复现。任何"重新接上试试"的想法先读它的 docstring（19 改 4 中，24→25）。
6. **Figma 插件回调表会在长会话/三族连跑后失效**（`Attempted to invoke callback with invalid id`）：重启 bridge 无效，必须在 Figma 里重载插件。门禁已能识别并给出提示，但无法自动恢复。
7. **`.vision_cache` TTL 300s**：全量 run 样本稳定性依赖缓存存活；跨天 run 必须做对照实验归因。
8. **`--rerun` 对结构层改动仍是盲区**：`--reuse-prepared` 连 `10_geometry_manifest` 一起冻结；结构层改动验证路径 = 全量 run + 对照实验 + 节点级 diff。
9. **输出仍是扁平 1 层**（金稿 5–8 层）：Phase 5 结构发射完全未做，可编辑性主菜。

---

## 7. 下一步应该从哪里继续

**优先级从高到低：**

1. **dark 的 8 条 Medium 导航项**（Phase 1 字重收尾，收益最确定）
   金稿 100% 对齐，规则一落地就能量准。做法：检测"同一行上 ≥3 个水平排列、等距、同字号的短文本组"→ 判为导航条 → 默认 Medium。验收：dark `style_mm` 21 → 13 以内，另两族不动。
2. **light-table 的 14/105 字重失配**（新暴露）
   先看这 14 条是什么形态（表头？按钮？），再决定是走结构规则还是复用导航条规则。
3. **Phase 5 结构发射**（可编辑性主菜）
   parents→FRAME、重复组→auto-layout、位图判据收紧，对标金稿 5–8 层。改动面大，建议单独立项。
4. **多轮 ink-convergence**（低优先级）
   几何收敛已支持 2–3 轮；但 §2.2 证明死区/钳位是承载性参数，只能在"更可靠的墨迹测量"上做文章，不要动这两个数。

**开工前必读：**
- 改字号/字重 → 先读 `docs/v2_mentor/20261110_font_weight_evidence.md`
- 换金稿 → 先跑 `scripts/audit_gold_tree.py`（验收线 80%/80%）
- 跑门禁 → `check_benchmark_families.py --rerun --policy 2.1`，跑前清 `output/_benchmark_families/rerun/`
- 需要写 Figma → 先启动 bridge（当前已关闭），并确认插件是刚重载的

---

## 8. 哪些内容禁止再次修改

**延续 11-09/上午交接的全部禁改项**（truth/黄金稿/金稿 frame 的语义、Policy 2.0、已回退的 style_resolver 路线、baseline 语义、fail-closed 纪律、`visible_full_screenshot_underlay: blocked`、门禁度量口径、dark truth 勘误既成事实、`_anchor_table_columns` 方差守卫语义、列锚点中位数聚合、split 节点必须同时进 accepted 与 kept、审计的包含剩余检查先于 `suppression_allowed`、`family.json` 的 history 链），另加本轮新增：

1. **不要**把 `calibrate_text_weight_from_render` 重新接进 `calibration_strategies`。实测 24→25（19 条改动只中 4 条），函数只作失败复现保留。
2. **不要**让 `table-cell` / `control` 进入展示级字重规则。实测 light-table `within30` 94.07→93.68 回归；`imageMVP.role` 是结构证据，不是文本特判。
3. **不要**在无新证据时加 `≥2× body → Black` 二级档。由 2 条样本拟合，且会把 `5.8折` 误判成 Black。
4. **不要**再动 `ink-convergence` 的死区 `[0.85,1.175]` 与钳位 `[0.7,1.5]`。两次"收紧"都让 light-table 回归（93.33 / 93.44），已由 `test_ink_convergence_band.py` 锁定。
5. **不要**把 `font_ratio` 重新接回门禁判定。它是两个声明字号之比，混着 1.5–2.4% 的字体度量差；只作诊断。
6. **不要**用 `ink_ratio` 反过来验证金稿对不对齐。框错了比值会跟着错（f 1.00→1.05 时比值 1.000→1.050），而且错得"很合理"，从数字上看不出异常。
7. **不要**在换金稿前跳过 `audit_gold_tree.py`。旧 light-table 金稿 39% 框落在空白、47% 文本被改写，在 Figma 画布里肉眼完全看不出来。
8. **不要**在 light-table 上恢复 `size_metrics.evaluable: false`。新金稿三项体检全过（100% / 93.9% / 行距 81），字号指标可用且 `ink_ratio = 1.000`。
9. **不要**让 `_rerun_family` 只看退出码。`blocked-environment` 的残留产物是校准前的，拿它比校准后的基线会造出假回归；判据必须是"有没有有效证据"。
10. **不要**以为 `ReadTransferCount` 能判断网络是否停滞（Windows 不统计 socket）。也别用小 prompt 测 VLM 速度——真实请求 90 秒，`reply ok` 是 2 秒。
