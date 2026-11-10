# Image → Figma · 交接文档（2026-11-10）

**日期：** 2026-11-10
**性质：** 当日工作交接（目标 / 完成 / 文件 / 修改明细 / 测试 / 遗留 / 下一步 / 禁改项）
**前置文档：**
- `20261109image to Figma-handoff.md`（Phase 0/1/2/4 交接，本文起点）
- `IMPLEMENTATION_ROADMAP_2026-11-08.md`（路线图）
- `20261110_column_anchoring_handoff.md` / `20261110_suppression_split_handoff.md`（当日两份详细交接）
**当日提交：**
- `941cf5c` feat: anchor table column boundaries to grounded text evidence（列锚定）
- `679a1eb` feat: keep a suppressed owner's leftover text via split（抑制拆分）
- `50f912f` fix(truth): correct dark-card-grid critical 查看详情 -> 看详情（truth 勘误，已批准）
（worktree `workbuddy/feature-precise-agent-router-ab3a4770` 有内容相同的三笔：`d2b4607` / `2c6d7dd` / `0085dd4`）
**运行环境：** `C:/Users/lzq/.conda/envs/omni/python.exe`；`scripts/run_image_pipeline.sh`；bridge `python -m src.app.services.bridge_server`（ws://localhost:8765，插件自动重连）

---

## 1. 本次任务的目标

执行路线图 Phase 2 剩余项与 Phase 3a：

1. **Phase 2 列锚定**：把行锚定的同法扩展到 x 方向，解决"表列 x 坐标仍用合成网格"的主诉（light-table 列错位 dx≈84）。
2. **Phase 3a 感知收尾**：路线图目标为 ACCTOKEN critical ≥24/27（写作时基线 18/27）。

核心方法论（三铁律）继续全程遵守：常量→规则、三族回归门禁、VLM 提议度量裁决。

## 2. 已经完成的内容

### ① Phase 2 列锚定 ✅（核心）

**取证**：竖线检测其实找到了真实列线，错在 `_select_contiguous_boundaries` 的等距方差窗口——light-table 保留了穿过 col6 文本带的假线（1794）、丢掉真右缘（2496），后三列文本左移 100-240px；**FlexWeaver 更重**：整体错位一列（执行结果列丢失，此前误判该族"列没问题"）。grounded 盒质量规律：盒左缘可靠（±25px），盒宽右向填充、个别完全错位。

**实现**（`_anchor_table_columns`，行锚定的 x 镜像 + 取证适配）：
- 每列锚点 = 唯一文本**最窄实例左缘的中位数**（多实例投票，单盒离群不塌锚——实测救回 col3：两个日期盒错位 -700px 被 9 张好票否决）；
- y 跨度过滤排除页面别处同名文本；单调拒错；歧义文本 ≤32px 吸收入池；
- **DP 从候选竖线选最优子序列**（不要求连续，chrome 线可夹在真列线间），最大化锚点落入各自列区间的数量（ε=8px），平手取内边距一致性；
- 一致性守卫：仅严格优于方差窗口才覆盖，已一致的表 no-op。

**效果**：light-table grid x 修正（contained 10/10）；FlexWeaver 错位一列修正（contained 5/7）；within30 light-table +0.57pp、light-form +0.87pp（font_ratio 1.014→**1.0**）；light-form 双轨去重生效（节点 164→149）。

### ② Phase 3a 感知收尾 ✅（形态按取证调整）

**取证改变了执行形态**：路线图的"两遍式 grounding（版式草稿遍）"无对症目标——9 条缺失已被消化到 25/27，剩 2 条的根因分别是：
- `查看详情` = **truth 转录瑕疵**（图上按钮实际是`看详情 →`/`看详情`，裁图+OCR+readback 三方一致，该 critical 永不可能合法命中）；
- `本期好价` = **抑制丢文本**（OCR 行合并产生的包含文本，0.833 相似度骑过 `suppression_allowed` 的 OCR 变体分支 0.80 阈值，"包含"被误判为噪声变体，抑制时标题蒸发）。

**实现**（发射契约强化，未改第一遍 prompt——避免三族全部换新 VLM 样本）：
- `scene_plan.py`：抑制一个 owner 时，若其文本包含替代文本且剩余 ≥2 字符，剩余作为派生节点存活（`:split` 后缀、差区域 bbox——替代盒主偏移轴决定切分方向，dark 实测误差 13px）；
- `emission_contract.py`：审计不变量 3 重写——凡抑制吞掉 ≥2 字可见内容，**无论相似度多高**都强制要求 split 存活，否则报 `unequivalent-suppression`（修复与审计同语义，fail-closed）。

### ③ truth 勘误 ✅（用户批准）

`查看详情` → `看详情`，`corrections[]` 记录审批与证据链。dark critical 达 **27/27**。

### 当日三族终态（门禁全 PASS，基线已注册）

| 族 | within30 | font_ratio | dy_med | critical | 节点 |
|---|---|---|---|---|---|
| light-form | 91.32 → **92.19** | 1.014 → **1.0** | 1.0 | **24/24** | 164→149 |
| light-table | 93.50 → **94.07** | 1.199 → 1.186 | 40.5 → 42.4（slack 内） | **29/29** | 214→199 |
| dark-card-grid | 94.89（−0.02） | 0.906 | 4.5 | 25/27 → **27/27** | 74→75 |

**三族 critical 全部满分**。归因纪律：列锚定经"旧代码对照 run（12_design 与 r7 逐位相同）+ 节点级 diff（差异 100% 表格相关）"闭合；拆分改动经"light 两族 12_design 哈希 IDENTICAL、within30 逐位相同"证明端到端零影响。

## 3. 已修改的文件

**修改（M）：**
- `src/app/services/structure/fidelity/inventory.py`
- `src/app/services/structure/fidelity/scene_plan.py`
- `src/app/services/structure/fidelity/emission_contract.py`
- `tests/fixtures/benchmark_families/light-table/family.json`
- `tests/fixtures/benchmark_families/light-form/family.json`
- `tests/fixtures/benchmark_families/dark-card-grid/family.json`
- `tests/fixtures/benchmark_families/dark-card-grid/truth.json`（勘误，已批准）

**新增（A）：**
- `tests/v2/test_table_column_anchoring.py`
- `tests/v2/test_suppression_split.py`
- `docs/v2_mentor/20261110_column_anchoring_handoff.md`
- `docs/v2_mentor/20261110_suppression_split_handoff.md`
- 本文档

## 4. 每个文件修改了什么

| 文件 | 修改内容 |
|---|---|
| `inventory.py` | ① 新增 `_anchor_table_columns`（约 +300 行）：grounded 列锚点建立（唯一文本→最窄实例左缘→列内中位数；y 过滤、单调拒错、歧义吸收）+ DP 候选线子序列选择（包含度最大化、内边距平手、方差守卫）。② `build_geometry_manifest` 接线：方差选择前捕获原始候选线 `raw_x_boundaries`；行锚定后调用列锚定；`table_geometry["column_anchor"]` 记录证据；table_bbox 计算后移至两个锚定之后。 |
| `scene_plan.py` | ① 新增 `_suppressed_leftover_text`（被抑制文本包含替代文本且剩余 ≥2 字 → 返回剩余，原始剥离优先/规范化回退）与 `_split_remaining_bbox`（替代盒主偏移轴决定差区域带）。② `_suppress_overlapping_text_owners` 抑制分支：有剩余 → 派生 split 节点（同时进 accepted 与 kept——只进 kept 会被 return 过滤静默丢弃）+ 抑制记录带 `split_ref`/`leftover_text`；无剩余 → 原逻辑不变。 |
| `emission_contract.py` | `audit_emission` 不变量 3 重写：抑制吞掉 ≥2 字可见剩余（`_suppressed_leftover_after` 判定）时，无论 `suppression_allowed` 是否放行，审计强制要求 split 节点存活（文本等价于剩余），否则报 `unequivalent-suppression`（detail 注明被吞内容）。 |
| `truth.json`（dark） | critical `查看详情` → `看详情`；新增 `corrections[]` 记录日期/字段/依据/审批/证据链接。 |
| `family.json` ×3 | `pipeline_run` 指向当日新 run（`*_20261110_colanchor` → `*_20261110_split`，dark 最终 `*_20261110_split_r2`）；`baselines` 三次刷新（列锚定、拆分、勘误各一次）；`history[]` 追加变更链。 |
| `test_table_column_anchoring.py`（新） | 10 用例：证据子序列覆盖方差窗口/一致性守卫 no-op/弱证据/无候选/y 过滤/紧盒优先/单调拒错/歧义吸收/内边距平手裁决/无表头单元格锚定。 |
| `test_suppression_split.py`（新） | 9 用例：拆分触发（dark 形态）/右带估计/等价不拆（duplicate-text-owner 路径）/单字剩余不拆/噪声变体不拆（护既有行为）/bbox 主轴/剩余判定/审计豁免/审计抓 split 丢失。 |
| 两份详细 handoff | 列锚定与拆分的完整取证、设计决策、归因过程、禁改项。 |

## 5. 已运行的测试及结果

**单元测试（omni python + `-p no:cacheprovider`，全部通过）：**

| 测试文件 | 结果 |
|---|---|
| `tests/v2/test_table_column_anchoring.py`（新） | 10 passed |
| `tests/v2/test_suppression_split.py`（新） | 9 passed |
| `test_grounding_fidelity_contracts.py` + `test_grounding_fidelity_integration.py` + `test_inventory_emission_contract.py` + 列锚定 | 54 passed |
| `test_grounding_scene_plan.py` + `test_grounding_scene_compile.py` + `test_fixed_canvas_compiler.py` + `test_table_column_anchoring.py` + contracts + integration + emission | 108 passed |
| `test_calibration_strategies.py` + `test_image_figma_cli_defaults.py` + `test_image_figma_acceptance.py`（列锚定时） | 77 passed |

**端到端（全量管线 run，VLM 缓存命中）：**

| run | 说明 | 结果 |
|---|---|---|
| 三族 `*_20261110_colanchor` | 列锚定 | within30 +0.87/+0.57/逐位不变；critical 全持平 |
| light-table `*_20261110_control_oldcode` | 旧代码对照（归因） | 12_design 与 r7 **逐位相同** |
| 三族 `*_20261110_split` | 抑制拆分 | dark critical 26/27；light 两族 12_design **哈希 IDENTICAL** |
| dark `*_20261110_split_r2` | truth 勘误后 | **critical 27/27**，within30 94.87 |

（exit=2 均为基线同款 native-gate blocked-fail，非回归。）

**门禁：** `check_benchmark_families.py` 三次全 PASS → `--register` 三次完成（列锚定、拆分、勘误）。

**冻结 bundle 验证：** 三族 `09_evidence_bundle.json` 重建几何清单/scene plan——dark grid x 修正（contained 10/10）+ split 节点出现；light 两族逐位 identical。

## 6. 当前仍存在的问题

1. **native gate 绝对值未动**：当日改动改善的是列位置与内容存活，native gate 的剩余阻塞在字号残差与 edgeF1 本质上界（Phase 1/3b 范畴）。
2. **light-table dy_med 40.5→42.4**（+1.9px，slack 3.0 内）：对金稿口径的配对变化，非 y 方向退化。
3. **dark style_mm 24/39**：字重系统性欠发射仍是其最大失配维度（Phase 1 字重推断未做）。
4. **FlexWeaver 列锚定残余**：`启动时间` 表头盒（+402px）与`执行结果`右对齐表头盒是锚点噪声，DP 靠其余锚点容错；未来单元格证据增多会更好。
5. **`suppression_allowed` 的 OCR 变体分支**（0.80 阈值）仍会把"包含"误判为噪声变体——执行层拆分已兜底，语义修正未做（无损失场景，改动面控制）。
6. **`--rerun` 门禁对结构层改动盲区**：`--reuse-prepared` 连 `10_geometry_manifest` 一起冻结；结构层改动验证路径 = 全量 run + 对照实验 + 节点级 diff（当日已走通，后续沿用）。
7. **`.vision_cache` TTL 300s**：全量 run 样本稳定性依赖缓存存活；跨天 run 必须做对照实验归因。
8. **路线图剩余**：多轮 ink-convergence、Phase 1 字重推断、Phase 3b VLM 视觉裁判、Phase 5 结构发射（输出仍扁平 1 层 vs 金稿 5-8 层，可编辑性主菜）。

## 7. 下一步应该从哪里继续

按路线图优先级（critical 已全满分，重心转向保真与可编辑性）：
1. **多轮 ink-convergence 迭代**（小改动）：几何收敛设计支持 2-3 轮，再压一档字号残差。
2. **Phase 1 字重推断**：笔画密度证据 → Bold/Medium/Mono（dark 族 style_mm 24/39 收益最大）。
3. **Phase 5 结构发射**：parents→FRAME、重复组→auto-layout、位图判据收紧——对标金稿 5-8 层。
4. 每步合入前：结构层改动用"全量 run + 对照实验 + 节点级 diff"，下游改动用 `check_benchmark_families.py --rerun [--policy 2.1]`（跑前先清 `output/_benchmark_families/rerun/`，环境批量删除护栏会拦脚本的 shutil.rmtree）。

## 8. 哪些内容禁止再次修改

延续 11-09 交接 §8 全部禁改项（truth/黄金稿/金稿 frame、Policy 2.0、已回退的 style_resolver 路线、baseline 语义、fail-closed 纪律、`visible_full_screenshot_underlay: blocked`、门禁度量口径），另加当日新增：

1. **dark truth 勘误的既成事实**：`查看详情`→`看详情` 已批准生效（corrections[] 有记录），不得回改。
2. **`_anchor_table_columns` 的方差守卫语义**：仅严格优于方差窗口才覆盖——dark/light 零回归的保障，不得放宽为"平手也覆盖"。
3. **列锚点的中位数聚合**：不得回退 min-left（col3 单盒离群塌锚教训）或单实例（FlexWeaver 状态双实例教训）。
4. **split 节点必须同时进 accepted 与 kept**：return 过滤扫描 accepted，只进 kept 会被静默丢弃（单测已锁定该 bug 形态）。
5. **审计的包含剩余检查先于 suppression_allowed**：抑制吞掉 ≥2 字可见内容时，无论相似度多高都必须 split 存活，不得以"OCR 变体"豁免。
6. **family.json 的 history 链**：pipeline_run 变更必须留 history 记录，保持基线可追溯。
