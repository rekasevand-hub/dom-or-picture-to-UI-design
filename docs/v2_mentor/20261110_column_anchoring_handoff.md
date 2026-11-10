# Image → Figma 列锚定 · 交接文档（2026-11-10）

**日期：** 2026-11-10
**性质：** 当日工作交接（目标 / 完成 / 归因 / 文件 / 测试 / 遗留 / 下一步 / 禁改项）
**前置文档：**
- `20261109image to Figma-handoff.md`（Phase 0/1/2/4 交接，本文的起点）
- `IMPLEMENTATION_ROADMAP_2026-11-08.md`（路线图，本文执行 Phase 2 列锚定）
**运行环境：** `C:/Users/lzq/.conda/envs/omni/python.exe`；`scripts/run_image_pipeline.sh`；bridge `ws://localhost:8765`

---

## 1. 本次任务的目标

执行路线图 Phase 2 的 x 方向：**列锚定**。解决交接文档 §6-2 的主诉——"表列 x 坐标仍用合成网格，light-table 列错位（dx≈84）"。方法约束：沿用三铁律（常量→规则、三族回归门禁、VLM 提议度量裁决），复用行锚定的全部基建。

## 2. 取证发现（改变实现设计的两个事实）

1. **light-table 的列线检测其实是对的，错的窗口选择**。`detect_table_grid` 在扩窗内返回 13 条候选竖线，其中包含全部真实列线（含右缘 2496）；`_select_contiguous_boundaries` 按等距方差选的连续窗口保留了一条穿过 col6 文本带的假线（1794），丢掉了真右缘（2496），导致后三列所有单元格文本左移 100-240px 渲染。
2. **FlexWeaver 的列错位是同病灶的更重形态**：10 条候选线中，方差窗口选出的 `[286..1137]` 整体**错位一列**（执行结果列完全丢失，`执行时间` 的文本落在 col1 区间外）。此前误判该族"列没问题"，实际 contained 只有 1/7。

grounded 盒质量取证：**盒左缘**是可靠信号（±25px 内跟踪真实文本左缘），盒宽则被右向填充（326-749px）或图像边缘截断；个别盒完全错位（FlexWeaver `启动时间` 表头盒 +402px、`2026-10-31/30` 日期盒 -700px 级离群）。

## 3. 已完成的内容

### `_anchor_table_columns`（inventory.py，+317 行）

行锚定的 x 方向镜像，按取证证据适配：

1. **锚点建立**：每列的表头+单元格文本中，唯一文本（全表出现一次）贡献其**最窄** grounded 实例（紧盒定位文本，宽盒拖入邻区）的左缘；列锚点 = 左缘池的**中位数**（单盒离群不塌锚——实测救回 col3）。
2. **y 过滤**：实例须与表格 y 跨度（行锚定后的边界优先）纵向重叠，排除页面别处的同名文本。
3. **单调拒错**：列锚点必须从左到右严格递增，违者丢弃（FlexWeaver `状态` 1072 < `启动时间` 1321 的错盒即被此规则处理）。
4. **歧义吸收**：已锚列的歧义文本（全表多次出现）在 |左缘-锚点| ≤ 32px 时并入证据池（中位数再抗一次离群）。
5. **DP 子序列选择**：从候选竖线中选 `列数+1` 条边界（**不要求连续**——chrome 线可能夹在真实列线之间），最大化锚点落入各自列区间的数量（ε=8px），平手取内边距一致性；对全排列是精确解，O(n·m²)。
6. **一致性守卫**：仅当 DP 结果的包含数**严格大于**方差窗口时才覆盖；方差窗口已与证据一致 → no-op 并记录证据（dark 无表族、证据弱的表不受影响）。

**明确不做**（V1 范围控制）：
- 无候选线时的边界合成兜底——三族无场景验证，按铁律不上未验证路径；
- FlexWeaver 表格 bbox 过窄的右缘外扩（其 VLM 表 bbox 右缘 1904 vs 检测线 1905——本次 DP 恢复 1887 已覆盖主损失，残余见 §6）。

### 接线

`build_geometry_manifest`：捕获方差选择前的原始候选线；行锚定后调用列锚定；`table_geometry["column_anchor"]` 记录证据（与行锚定的 `anchor` 并列，下游无读者，纯证据透明）；table_bbox / table-column / grid x_boundaries 全部跟随锚定结果。

### 效果（冻结 bundle 验证，同一感知输入的纯代码差异）

| 族 | grid x（旧 → 新） | 列锚定证据 |
|---|---|---|
| light-table | `[470..2376]` → `[470, 663, 897, 1110, 1277, 1467, 1679, 1885, 2170, 2376, 2496]` | contained 10/10，variance 7/10 |
| light-form | `[286..1137]`（错位一列）→ `[308, 388, 577, 717, 857, 1045, 1137, 1887]` | contained 5/7（col4 坏表头盒被 DP 正确排除） |
| dark-card-grid | 无表格 | 不触发 |

### 三族全量 run（2026-11-10，对照实验归因见 §4）

| 族 | within30 | font_ratio | dy_med | critical | 节点数 |
|---|---|---|---|---|---|
| light-table | 93.50 → **94.07**（+0.57pp） | 1.199 → 1.186 | 40.5 → 42.4（slack 内） | 29/29 持平 | 214 → 199（双轨去重） |
| light-form | 91.32 → **92.19**（+0.87pp） | 1.014 → **1.0** | 1.0 持平 | 24/24 持平 | 164 → 149 |
| dark-card-grid | 94.89 → **94.89（逐位不变）** | 0.906 持平 | 4.5 持平 | 25/27 持平 | 74 持平 |

门禁全 PASS 后已 `--register` 刷新三族基线（family.json 含 history 记录）。

## 4. 归因纪律（VLM 方差教训的再现与闭合）

全量 run 时 light-table 的 VLM enrichment 样本与 r7 基线不同（text_candidates 51→36，`.vision_cache` TTL=300s 过期导致）。按 11-09 的对照实验方法闭合归因：

- **旧代码对照 run**：12_design.json 与 r7 **逐位相同**（within30 93.5031 逐位复现，证明管线确定性）；
- **节点级 diff**（新 vs 对照，同日管线）：124 个非表格节点**逐位一致**；62 个变更 + 15 个消失节点**全部是表格相关**——15 个消失节点是 bbox=None 的双轨发射残影（列几何修正后 scene plan 的重叠去重正确生效）；
- 结论：design 层差异 100% 由列锚生造成 → within30 增益归因于列锚定（cell 文本位置修正 + 双轨去重）。
- dark 族逐位不变同时证明：无表格族零影响 + 缓存命中时管线完全可复现。

**过程性发现（影响后续）**：`check_benchmark_families.py --rerun` 的 `--reuse-prepared` 会跳过整个 PreciseAgent（连 10_geometry_manifest 一起冻结），**结构层改动无法被 rerun 门禁感知**——结构层改动的验证路径是"全量 run（缓存命中时逐位可复现）+ 对照实验归因 + 节点级 diff"。这条路径本次已走通，后续结构层改动沿用。

## 5. 已修改的文件

**修改（M）：**
- `src/app/services/structure/fidelity/inventory.py`：新增 `_anchor_table_columns`（+约 300 行）+ `build_geometry_manifest` 接线（raw_x 捕获、列锚定调用、column_anchor 证据、table_bbox 后置重算）。

**新增（A）：**
- `tests/v2/test_table_column_anchoring.py`：10 个单测（窗口覆盖/一致性守卫 no-op/弱证据/无候选/紧盒优先/单调拒错/歧义吸收/内边距平手裁决/无表头单元格锚定/y 过滤）。

**数据（注册）：**
- `tests/fixtures/benchmark_families/*/family.json` ×3：pipeline_run 指向 20261110_colanchor run，baselines 刷新，history 追加。

## 6. 已运行的测试及结果

- 单测：`test_table_column_anchoring.py` 10 passed；`test_grounding_fidelity_contracts.py + test_grounding_fidelity_integration.py + test_inventory_emission_contract.py` 54 passed；`test_grounding_scene_plan.py + test_fixed_canvas_compiler.py + test_grounding_scene_compile.py + test_calibration_strategies.py + test_image_figma_cli_defaults.py + test_image_figma_acceptance.py` 77 passed。
- 冻结 bundle 验证：三族 09_evidence_bundle.json 重建几何清单，列锚定证据与 grid x 如 §3 表。
- 全量 run ×4：三族新代码 + light-table 旧代码对照（exit=2 均为基线同款的 native-gate blocked-fail，非回归）。
- 家族门禁：gate 全 PASS → register 完成。

## 7. 当前仍存在的问题

1. **native gate 绝对值未动**（本次不解决）：light-table native owner pass ~39/70。列锚定改善的是 within30/位置错位，native gate 的剩余阻塞在字号残差与 edgeF1 本质上界（Phase 1/3 范畴）。
2. **light-table dy_med 40.5→42.4**（+1.9px，slack 3.0 内）：对金稿口径的 dy 受列修正后配对变化影响，非 y 方向退化（y 边界未动）。
3. **FlexWeaver 残余**：`启动时间` 表头盒 (+402px) 与 `执行结果` 表头盒靠右对齐导致锚点噪声，DP 靠其他锚点容错；若未来单元格文本证据增多（grounding 枚举变化），锚点质量会更好。
4. **VLM enrichment 缓存 TTL 300s**：全量 run 的样本稳定性依赖 `.vision_cache` 条目存活；跨天 run 必须做对照实验归因（本次方法已建立，建议后续把 `VISION_CACHE_TTL_SECONDS` 纳入基准复现流程文档）。
5. **`--rerun` 门禁对结构层盲区**（§4 过程性发现）：结构层改动需走全量 run + 对照实验。
6. 路线图剩余项不变：Phase 3a 两遍式 grounding（ACCTOKEN 9 条 critical 缺失）、多轮 ink-convergence、Phase 1 字重推断、Phase 5 结构发射。

## 8. 下一步应该从哪里继续

按路线图优先级（交接 §7 顺序不变，列锚定已完成）：
1. **Phase 3a 两遍式 grounding**（建议下一个）：ACCTOKEN 9 条 critical 缺失是 acceptance 硬阻塞。
2. **多轮 ink-convergence 迭代**（小改动）。
3. **Phase 1 字重推断**（dark 族收益大）。
4. **Phase 5 结构发射**（可编辑性主菜）。
5. 每步合入前：结构层改动用"全量 run + 对照实验 + 节点级 diff"，下游改动用 `--rerun` 门禁。

## 9. 哪些内容禁止再次修改

延续 11-09 交接 §8 全部禁改项（truth/黄金稿/金稿 frame、Policy 2.0、已回退的 style_resolver 路线、baseline 语义、fail-closed 纪律、underlay 禁令、门禁度量口径），另加：
1. **`_anchor_table_columns` 的方差守卫语义**：仅严格优于方差窗口才覆盖——这是 FlexWeaver/dark 零回归的保障，不得放宽为"平手也覆盖"。
2. **锚点中位数聚合**：不要回退到 min-left（col3 教训：单盒离群塌锚）或单实例（FlexWeaver `状态` 双实例教训）。
3. **family.json 的 history 链**：pipeline_run 变更必须留 history 记录，保持基线可追溯。
