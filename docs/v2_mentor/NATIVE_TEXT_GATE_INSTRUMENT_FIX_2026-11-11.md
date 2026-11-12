# Native Text Gate：关旁路 + 修口径（2026-11-11）

**性质：** 行为变更（门禁口径 + 校准输入来源）。按用户指令执行「1 → 2」。
**前置：** `NATIVE_TEXT_GATE_EVIDENCE_2026-11-11.md`（取证，只读）。

---

## 1. 关掉的旁路（3 处）

| 位置 | 原行为 | 现行为 |
|---|---|---|
| `calibration_strategies._adjudicated_conflicts` | 从图片路径切出 `benchmark_families/<family>`，加载 `output/_conflict_decisions/<family>.json` | **只**读 `<run>/conflict_adjudication/decisions.json`：证据必须随 run 走 |
| `text_calibration.apply_adjudicated_conflicts` | `status == "move"` 即搬运节点，不看 `agreement`（如实测 4 条全 `agreement=false` 仍生效） | `move` 必须 `agreement is True` 才应用 |
| `scripts/conflict_adjudicator.py` | `_gold_positions()` 读 `gold_tree.json`，把金稿 bbox 当 `move_to` | 删除该函数；不再产出 `move`，无法安全处理的一律 `needs-human` |

归档：`output/_conflict_decisions/light-table.json` → `light-table.json.gold-derived-deprecated`（该目录已无运行时读取方）。

**为什么**：那 4 条被搬运的文本（`工时管理`/`个人信息`/`展开查询`/`我的工时看板`）全在 critical 名单里，位移 162–437px；`个人信息` 在 light-table 门禁里 `dx=dy=0`，坐标正是金稿的。这条链路让"基准跑"不等于"用户会拿到的流水线"。

---

## 2. 修的三条口径

`src/app/services/evidence/native_text_quality.py`

### 2.1 原生判定：整串精确匹配 → 去空白紧凑形

新增 `_compact_gate_text()`（标点折成空格后再删全部空白）。`5.8折` 与画布上的 `5.8\n折` 现在视为同一段原生文字。
实测：dark `native` 28→**30**。

### 2.2 测量框：接地框 → 发射节点自己的框（+4px）

新增 `_text_node_boxes()` / `_select_node_box()`：
- 从 readback 取 TEXT 节点的**绝对框**（根帧坐标系）；
- 重复文本按"与元素中心最近"配对（只用于配对，不参与测量）；
- 无节点时回退接地框，并启用**细线抑制**（只吃 ≤2px 厚、跨框 80% 的横/竖线）。

**为什么**：`¥20.24` 的接地框宽 270px（含 `起 ¥23.0`），节点只有 143px——旧的"真值"横跨三个 token，任何渲染都过不了 3% 宽度容差。`样式证据` 仍然保留在报告里（`measureBBox`/`measurementSource`），但不再充当尺子。

### 2.3 无证据 owner：单列，不再永久阻塞

`_evaluate_native_text_gate` 把 `unmeasurable-*` 的 owner 收进 `nativeText.unverified`（含 `contentRef`/`text`/`reason`），不计 pass、也不再产生 blocker。报告新增 `unverifiedCount`。

**注意**：这不是"放行"。它们仍然不可测，只是从"永远 fail"变成"可见的盲区"。实测三族 `unverifiedCount` 均为 **0**（因为 2.2 的兜底测量把它们测出来了）。

---

## 3. 同一批渲染产物上的仪器换代对照

不重跑流水线，直接用已有 `figma_design.json` + `figma_ink_converged/{readback,export}.png` 重算：

| 族 | 旧 pass | 新 pass | 变化 | 说明 |
|---|---|---|---|---|
| dark | 1/30 | **1/30** | 0 | 两条换行标签从"非原生"变"原生"，但仍卡在字重/字族/字号 |
| light-form | 30/33 | **23/33** | **−7** | 见下 |
| light-table | 34/59 | **35/59** | +1 | 多 token 框的问题被节点框消除 |

light-form 掉 7 条，**不是新口径变严，是旧口径被裁剪掩盖**。以 `名称` 为例：

| 量 | 值 |
|---|---|
| 元素/节点框原点 | 379 |
| 参考墨迹起点 | **384** |
| 渲染墨迹起点 | **380** |
| 旧口径测量框起点 | 381（`source_bbox`）→ 量不到 380，报 dx≈−2，判过 |
| 新口径（节点框 −4px 起） | dx = −4，判 fail |

即：light-form 有 8 条标签整体左偏 3–4px，旧仪器因为"裁剪起点在 381"看不见。这是真实的版式偏差（容差 2px），不是度量假象。

---

## 4. 测试

| 范围 | 结果 |
|---|---|
| `tests/v2/test_adjudicated_conflicts.py`（新增 4 例） | 4 passed |
| `tests/v2/test_native_text_quality.py`（9 → 12 例，新增 3 例） | 12 passed |
| 受影响 6 个文件（native／adjudicated／acceptance／calibration_strategies／mask_audit／grounding_text） | **65 passed** |
| `tests/v2` 全量 | **1485 passed / 8 failed**（91.8s）；8 个全部是既有的 axure manifest + p5 探针环境失败，与本轮无关 |

新增用例覆盖：family 键文件不再被读取、run 内文件仍生效、`move` 必须 `agreement`、节点框优先于接地框、换行标签算原生、无证据 owner 单列。

---

## 5. 全量对照（2026-11-11 22:44，perception 冻结）

`check_benchmark_families.py --rerun --policy 2.1`，三族全部 PASS：

| 族 | within30 | 旧 within30 | critical | native pass | 旧 native |
|---|---|---|---|---|---|
| dark-card-grid | 94.65% | 94.65% | 27/27 | 1/30 | 1/30 |
| light-form | 92.16% | 92.16% | 24/24 | **23/33** | 30/33 |
| light-table | **95.27%** | 95.17% | 30/30 | **36/59** | 34/59 |

`adjudicated-conflict`：三族均为 `not-needed / no decisions file`，4 条文本回到原位。

> 注：上表 light-form 的 23/33 是**修 `inset` 之前**的读数。定位到左偏根因并修复后（见 §6），最终为 **29/33、within30 92.21%**，三族终值以 §6.3 为准。

**light-table 反而变好（+0.10 within30、+2 native）**：那 4 条金稿坐标不是"没用"，是**用错了**。逐条局部像素差（与参考图比，越低越好）：

| 文本 | 旧（金稿位） | 新（原位） | 判定 |
|---|---|---|---|
| 工时管理 | 10.74% | 9.45% | 金稿位更差 |
| 个人信息 | 33.31% | 32.87% | 金稿位更差 |
| 展开查询 | **48.04%** | **8.33%** | 金稿位差 5.8 倍 |
| 我的工时看板 | 28.55% | 20.60% | 金稿位更差 |

原因：`_gold_positions()` 用 `found.setdefault(text, ...)` 取**该字符串在金稿里的第一次出现**。同页重复文本（`展开查询`、`个人信息`）被搬到另一个实例的位置上，四次全错。

**顺带修正上一份取证的一处说法**：`个人信息` 在旧口径下的 pass 不是"金稿坐标对上参考"，而是**退化的测量**——它的 `styleEvidence.ink_bbox` 与 `source_bbox` 完全相同（`[507,352,67,20]`），于是 position/size 变成盒子和自己比，`dx=dy=0` 恒成立。新口径不再读这个字段，同一 owner 现在报 `cov=0.68 → fail`。

---

## 6. 左偏根因与修复（light-form 的 3–4px）

### 6.1 根因：`_render_ink_bbox(inset=3)` 把字头裁掉了

`calibrate_form_positions_from_render` 用 `_render_ink_bbox(rendered, source_bbox)` 量当前墨迹，而这个函数的默认 `inset=3` 会把裁剪框从 `source_bbox` **往里缩 3px**（本意是避开控件边框）。对没有边框的普通文本标签：

| 量 | 名称 |
|---|---|
| `source_bbox` | [381,145,40,20] |
| 裁剪起点 | 381 + 3 = **384** |
| 渲染实际字头 | **380**（列剖面：ref 从 384 起，exp 从 380 起） |
| 目标 ink（Otsu） | 383 |
| 量到的 current | **恒为 384**（= 裁剪起点） |

于是 `delta = 383 − 384 = −1`，每一轮都往左挪 1px。`form-positions` 与 `form-positions-second` 两轮各自 −1 → 标签累计左移 2–4px，**永不收敛**。三张阶段导出图证实：`figma_form_calibrated` 里字头 382→381→380，一路向左。

### 6.2 修复

`inset = 0 if element.type == "text" else 3`（输入框/按钮保留 3，它们的字确实在边框内）。

回归用例：`test_form_position_calibration_does_not_clip_a_label_glyph`（旧代码得 17，新代码 19）。

### 6.3 效果（light-form 复跑，perception 冻结）

| 指标 | 修前 | 修后 |
|---|---|---|
| native pass | 23/33 | **29/33** |
| within30 | 92.16% | 92.21% |

`名称`/`显示名称`/`备注`/`禁用` 的 dx 收敛到 −1..0、dy=0。
剩余 4 条不是这一类：`自动备份` dy=−3、`刷新` dy=−3（按钮仍用 inset=3，可能同病）、`执行成功` dy=+4/size、`2023年12月16日：` size。

**影响面**：dark 与 light-table 的 `form-positions` 中 `type=text` 调整数为 **0**，本修复不会改变它们的输出。

---

## 7. 还没做

1. **light-form 的 3–4px 左偏**：现在被如实报出来了，但根因（接地框比真实文字起点左 4px？表单内边距？）没查。
2. **门禁阈值未重标定**：2.1 的阈值是在旧口径上定的。新口径语义更干净，但严格说需要按"留一族"重标一次。
3. **position 的语义弱化了**：量框锚在节点自己身上，`position` 现在测的是"框内对齐"，不再是"全局摆放位置"。整块搬走若落点有相似文字，position 不会报警，只能靠 coverage 兜（本次 `个人信息` cov 0.68 就是兜住的）。这是无 token 级真值下的固有限制，要写进门禁说明。
4. 旧产物保留在 `output/_benchmark_families/rerun_pre_fix/`，报告备份 `report_pre_instrument_fix.json`。

---

## 6. 复现

```bash
PY="C:/Users/lzq/.conda/envs/omni/python.exe"
# 同一批产物上重算新口径
$PY scripts/p1_native_text_gate_probe.py \
  --run-dir output/_benchmark_families/rerun/light-form --label light-form --recompute
```
