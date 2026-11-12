# Native Text Gate 取证（2026-11-11）

**性质：** 只读取证。未修改 `src/`、未改门禁阈值、未改金稿与 `family.json`、未写 Figma 画布。
**唯一新增：** `scripts/p1_native_text_gate_probe.py`（只读探针）+ `output/_p1_native_gate/`（探针产物与对比裁片）。
**输入产物：** `output/_benchmark_families/rerun/{dark-card-grid,light-form,light-table}`（11-11 17:16–17:23 的终验 `--rerun`）。
**门禁实际读取的文件：** `figma_ink_converged/readback.json` 与 `figma_ink_converged/export.png`（不是 `figma/` 那一份）。

---

## 0. 速览（只读这一段）

| 问题 | 答案 |
|---|---|
| 门禁怎么判"原生文字" | `nativeText = 设计串 ∈ {readback TEXT 节点的 characters}`，**整串精确匹配**；再叠加四个几何维度，任一不过即 fail |
| 三族现状 | dark **1/30**、light-form **30/33**、light-table **34/59** |
| 是"门禁太严"还是"实现没好" | **两者都有，但主体是后者**：dark 30 条里只有 4 条属门禁口径问题，10 条属参考真值不可用，**16 条是真缺陷** |
| 最强的反证 | 同一套门禁，light-form 30/33 通过。门禁本身能过；dark 是离群族 |
| 真缺陷的量级（金稿真值） | dark 字号中位 **0.948**（nav 实测 0.917、墨迹高 0.897）、字重错 **10/20**、字族错 4/20；light-form 字号 1.029、字族 0/33 |

一句话：**1/30 不是"门禁坏了"的结果，而是"dark 族的字号/字族/字重确实不对 + 参考真值有 1/3 不可用 + 门禁有 4 条口径硬伤"三者叠加。**

---

## 1. 门禁的判定链（代码事实）

`src/app/services/evidence/native_text_quality.py`：

1. **原生判定**（`build_native_text_quality`）：
   ```python
   native_characters = {node["characters"] for node in _text_nodes(readback)}
   nativeText = (design_element["text"] in native_characters)
   ```
   集合里放的是**整串**。所以 `"5.8折"` 对 `"5.8\n折"` 判否。

2. **四个几何维度**（`_evaluate_native_text_gate`，policy 2.1 实际生效值）：

   | 维度 | 判据 | 2.1 阈值 | 计量方式 |
   |---|---|---|---|
   | position | \|dx\|,\|dy\| ≤ 2px | 2 | 渲染墨迹框 vs **styleEvidence.ink_bbox** |
   | size | \|dW\| ≤ max(3, 3%)、\|dH\| ≤ max(3, 3%) | 3px / 3% | 同上 |
   | coverage | 在参考墨迹框 + 2px halo 内 渲染墨量/参考墨量 | 0.75–1.35 | 渲染侧**固定阈值 50**，参考侧 **Otsu** |
   | edgeF1 | 边缘 F1 | 0.55 | 同上 |

3. **通过条件**：`nativeText ∧ 四维全过`；且 scope 内**任一** owner 不通过 → `gate.status=fail` → `acceptance.status=blocked-fail`。**没有"通过率"概念，就是 100%。**
4. `native_text_baseline_required = False`：30 条 owner 的 `baseline` 全是 `unknown`，但这**不**构成 blocker。

---

## 2. dark 族 30 条 critical owner 的分解

| 分类 | 条数 | 说明 |
|---|---|---|
| 门禁口径：整串匹配被换行打断 | **2** | `5.8折` / `8.8折`，画布上是 `"5.8\n折"` / `"8.8\n折"` |
| 门禁口径：无可测墨迹证据 | **2** | `复制模型 ID` / `看详情`，`styleEvidence` 有 `reason` 无 `ink_bbox`，**永远无法通过** |
| 参考真值不可用（框是整格/多 token） | **10** | 6 条是多 token（`¥20.24` 等），4 条是"参考墨迹比节点还窄" |
| **真实缺陷** | **16** | 其中 1 条通过（见 §3），15 条在字号/字族/字重/对齐上确实不对 |

同族的对照：非 critical 的实测 owner 18 条，通过 1 条（5.6%）——**不是"只有 critical 卡"，是全族性问题**。

三族横向对照（同门禁、同探针）：

| 族 | scope | native | measured | pass | 对称重测 pass | 参考框 per-text / 多 token |
|---|---|---|---|---|---|---|
| dark | 30 | 28 | 28 | **1** | 3 | 18 / 6（+4 窄框、2 未知） |
| light-form | 33 | 33 | 33 | **30** | 32 | 31 / 2 |
| light-table | 59 | 59 | 58 | **34** | 37 | 40 / 18 |

---

## 3. 唯一通过的那条

`社区`（nav）：`ink_bbox` 参考 `[1204,42,59,29]`、渲染 `[1205,42,59,29]`——**逐像素相同**，coverage 0.909、edgeF1 0.812。

值得警惕：它是 30 条里**唯一**参考框与渲染框完全重合的样本；而且它的**墨迹宽 59px 超过了它自己的节点宽 55px**，说明量到的墨迹框里混进了相邻内容（框与邻居重叠）。同一字号的 `首页` 墨迹只有 53×26。所以这条"通过"更像一次测量巧合，**不宜当作"达标样板"**。

---

## 4. 门禁侧的问题（4 条硬伤，按可修性排序）

### 4.1 整串精确匹配 vs 多行发射（2/30）

换行是在**字校准阶段**引入的，不是初写：

| 阶段 | `5.8` 节点 |
|---|---|
| `figma/readback.json` | `'5.8折'`，fontSize 86.5 |
| `figma_font_calibrated/readback.json` | `'5.8\n折'`，fontSize `None`（按行字号） |
| `figma_ink_converged/readback.json` | `'5.8\n折'` |

设计串是 `5.8折`，门禁拿它做 `in` 判定 → 判"非原生"。**同一条文本，初写时算原生、按行拆字后就不算了**——这不是渲染问题，是判定口径问题。

### 4.2 无墨迹证据的 owner 结构上不可能通过（2/30）

`复制模型 ID` / `看详情`（15px 小字，深色底）：`styleEvidence` 只有 `reason`，没有 `ink_bbox`。`register_unmeasured_owners` 只在 `--emission-contract repair` 时登记，登记后 `status=unmeasurable-missing-evidence`，**永远不计入 pass**。它们进了 scope，就必然贡献 blocker。

### 4.3 参考真值有的是"整格"，不是"这条文本"（dark 10/30、light-table 18/59）

`styleEvidence.ink_bbox` 是**接地框内所有墨迹像素的并集**。接地框是整格时，真值就横跨多个 token：

`¥20.24` 实测：参考墨迹 `[1333,961,270,33]`，画布节点宽 **143px** → 参考真值宽 270px。裁片对照（`output/_p1_native_gate/cmp_3.png`）左边是 `¥20.24 起 ¥23.0…` 三个 token，右边只有 `¥20.24`。

**在这类 owner 上，任何渲染器都不可能过 3% 宽度容差。** 这 10 条不是"实现差 10%"，是"分母不是同一句话"。

### 4.4 计量方法两侧不对称（每族损失 2–3 条）

- 参考墨迹：`ink_support()` → 边框环估计背景 + **Otsu** 阈值；
- 渲染墨迹：`_contrast_mask()` → 全区域中位数背景 + **固定阈值 50**。

用同一套方法（固定 50 或亮度掩膜）重测，三族通过数从 1/30→**3**、30/33→**32**、34/59→**37**。

**亮度掩膜对照（剔除截图的亚像素彩边）只把 coverage 中位数从 0.636 抬到 0.674**，说明彩边是二阶因素，不是主因——这点否掉了"都是抗锯齿差异"的解释。

补充观察：`position` 用**墨迹框**代理版式，中位 \|dx\| 在三族分别正好是 2.0 / 1.0 / 1.0px，容差是 2px。**版式正确、字体不同，墨迹框边缘也会移动几像素**——position 维度里混着字体形状，不纯是位置。

---

## 5. 真实缺陷（用金稿声明值量化）

把每族 `readback` 的 TEXT 节点与 `gold_tree.json` **按文本 + 几何中心一对一配对**（≤40px，忽略空白）：

| 族 | 配对/金稿 TEXT | 字号比 中位 | p10–p90 | 字族不符 | 字重不符 |
|---|---|---|---|---|---|
| dark | 20/51 | **0.948** | 0.848–1.271 | 4 | **10/20** |
| light-form | 33/79 | 1.029 | 1.000–1.047 | 0 | 13/33 |
| light-table | 51/109 | 0.971 | 0.917–1.029 | 10（多为数字/英文） | 5/51 |

配对率低本身要留个心（dark 只有 20/51 能在 40px 内配上），所以**下面逐条点名的例子比聚合中位数更可靠**。字号比与墨迹高度比是两条独立路径，它们互相吻合：dark nav `fontSize 27.5 / 金稿 30 = 0.917`，同一节点墨迹高 `26 / 29 = 0.897`。

逐条案例（金稿 → 流水线，均已按坐标核对节点）：

| 文本 | 金稿 | 流水线 | 问题 |
|---|---|---|---|
| `首页` / `社区` | Noto Sans SC Medium **@30** | Noto Sans SC Medium **@27.5** | 字号 −8.3% |
| `模型广场`（nav） | Noto Sans SC **Bold @30** | Noto Sans SC **Medium** @27.5 | 字重错 + 字号 |
| `模型广场`（大标题） | **Noto Serif SC Black @96**（350×105） | **Noto Sans SC** Bold @87.5（350×105） | **字族错**（衬线→无衬线），裁片 `cmp_2.png` 肉眼可辨 |
| `本期好价` | **Noto Serif SC Black @52** | Noto Sans SC **Regular** @47.5 | 字族 + 字重 + 字号 |
| `¥20.24` | **JetBrains Mono Bold @44** | **Open Sans** Regular @45.5 | 字族 + 字重 |
| `去画布试 →` | 粗、左对齐、ink 150×20 | 细、居中、ink 93×17，dx **+25** | 对齐方式 + 字重 + 字号 |

**另有一条门禁抓到的真缺陷**（light-table）：`项目代码` 节点存在（`[505,444,96,29]`、`#252525`、Noto Sans SC），但**最终画布上该框内墨迹像素 = 0**（上一阶段 `figma/export.png` 有 933px）。即最后一步把它盖住/丢掉了——这是 z 序或重发射回归，与门禁口径无关。

---

## 6. 结论

| 层 | dark 占比 | 能否靠调门禁解决 | 处置 |
|---|---|---|---|
| 判定口径（换行、无证据 owner） | 4/30 | 能 | 改判定：按空白归一化比较、无证据 owner 单列而不是塞进 scope |
| 参考真值不可用（整格框） | 10/30 | **不能**，越调越假 | 换真值来源：按节点框/单 token 重构参考墨迹 |
| 真实缺陷（字号/字族/字重/对齐） | 16/30 | 不能 | 回到实现：dark 的字号偏小、字族（衬线/等宽）与字重是真账 |

**必须写下来的一条**：11-10 的结论是"字号闭环已达局部最优，问题在指标不在代码"，于是把 `font_ratio` 降级为诊断、改用 `ink_ratio`。本次取证用**金稿声明值**与**墨迹高度**两条独立路径，都量到 dark 字号系统性偏小（中位 −5%，nav −8.3%，墨迹高度 −10%）。`ink_ratio` 的 0.944 一直被读成"接近容差边缘的真实差距"，但它其实是同一笔账的温和版本。**这个结论需要被重新审视，而不是继续用它给口径背书。**

---

## 7. 建议的下一步（三选一，按性价比）

| 选项 | 内容 | 影响面 | 风险 |
|---|---|---|---|
| **A（推荐先做）** | 重做参考真值的框来源：`ink_bbox` 由**该 owner 自己的节点框**决定，或按 token 切分后取本 token 的墨迹 | 直接解锁 10/30 dark、18/59 light-table 的"不可能通过" | 只改度量，不改发射；但会让 gate 数字一次性跳变，需要重新登记基线 |
| B | 修判定口径两条：空白归一化比较 + 无证据 owner 单列 | 4/30 dark，另两族各 1–2 条 | 极小；但只治表面，dark 仍 5/30 上下 |
| C | 认账 dark 的字号/字族，回到 Phase 1 收尾 | 16/30 dark，且是肉眼真差距 | 改动面回到 `text_calibration` / 字族选择，需三族重跑 |

**不建议**：把"100%"改成"≥X%"。那会把 §5 的衬线/等宽/字重缺陷一起合法化，而这些正是肉眼最刺眼的差异。

---

## 8. 复现

```bash
PY="C:/Users/lzq/.conda/envs/omni/python.exe"
# 单族（含对称与亮度两种对照）
$PY scripts/p1_native_text_gate_probe.py \
  --run-dir output/_benchmark_families/rerun/dark-card-grid \
  --label dark-card-grid --symmetric

# 三族
for f in dark-card-grid light-form light-table; do
  $PY scripts/p1_native_text_gate_probe.py \
    --run-dir output/_benchmark_families/rerun/$f --label $f --symmetric
done
```

产物：`output/_p1_native_gate/<family>.json`（逐 owner 全量指标）、`<family>.txt`（表格）、`cmp_*.png`（参考图/导出裁片对照）。

---

## 9. 本次改动边界

- **新增**：`scripts/p1_native_text_gate_probe.py`（只读；只消费已有 run 产物，不触发流水线、不连 bridge）。
- **新增产物**：`output/_p1_native_gate/`。
- **未改**：`src/**`、`tests/**`、`tests/fixtures/benchmark_families/**`、门禁阈值、`family.json` 基线、Figma 画布。
- **bridge**：本次仅启动（`ws://localhost:8765`），未产生任何写操作。
