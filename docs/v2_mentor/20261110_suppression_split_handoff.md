# Phase 3a 感知收尾 · 交接文档（2026-11-10 下午）

**日期：** 2026-11-10
**性质：** 当日工作交接（目标 / 取证 / 设计调整 / 实现 / 验证 / 遗留 / truth 勘误建议 / 禁改项）
**前置文档：**
- `20261110_column_anchoring_handoff.md`（同日上午，Phase 2 列锚定）
- `IMPLEMENTATION_ROADMAP_2026-11-08.md`（路线图 §5a 两遍式 grounding）
**当日提交：** 见文末（worktree 与主仓库同步提交）

---

## 1. 本次任务的目标

执行路线图 Phase 3a"两遍式 grounding"，考场是 ACCTOKEN 的 critical 缺失（路线图写作时为 18/27，目标 ≥24/27）。

## 2. 取证（改变了执行形态的三个事实）

1. **考卷已缩小**：9 条缺失已被 short-unit 合并等措施消化到 25/27，剩 2 条。
2. **`查看详情` 是 truth 转录瑕疵**：参考图上两个按钮的实际文字是 **`看详情 →` / `看详情`**（第一个字就是"看"，双按钮裁图确认），EasyOCR 观测正确、readback 渲染正确（`看详情`、`看详情 →`）。truth.json 里的 `查看详情` 在图上不存在，该 critical **永不可能合法命中**。按禁改项，truth 勘误需显式审批（建议见 §8）。
3. **`本期好价` 是抑制丢文本**（真实管线缺陷）：VLM 把区块标题+副标题输出为两个重叠元素——合并盒 `本期好价 折扣都按官方价实时算`（OCR 行合并产物，authority=ocr）与副标题独立盒 `折扣都按官方价实时算`（grounding）。`suppression_allowed` 的 OCR 噪声变体分支按相似度 **0.833 ≥ 0.80** 放行了抑制（"包含"被误判为"噪声变体"），scene plan 抑制合并盒时标题文本蒸发。与 light-table 双轨发射是同一病灶的两面：不重叠→冗余发射，重叠+包含→丢内容。

**结论**：路线图原设计（改第一遍 prompt 加版式草稿遍）在当前证据下无对症目标——dark 的感知召回已足够（两条缺失一条在 truth、一条在结构层），改 prompt 反而使三族全部拿新 VLM 样本（回归风险），违反"不做无证据修复"纪律。Phase 3a 以**发射契约强化**（抑制拆分保留）形态落地。

## 3. 已完成的内容

### 抑制拆分保留（scene_plan.py + emission_contract.py）

- `_suppressed_leftover_text`：被抑制文本规范化后**包含**替代文本且剩余 ≥2 字符 → 剩余是可见内容（优先原始文本剥离，规范化回退）；等价/噪声变体/无关文本返回空。
- `_split_remaining_bbox`：剩余文本的 bbox 估计——替代盒相对被抑制盒的主偏移轴（水平/垂直中心偏移比）决定切分方向，取未被覆盖的带。dark 实测：估计 [90,486,231,72] vs 真实墨迹 [90,486,218,72]，误差 13px。
- `_suppress_overlapping_text_owners` 抑制分支：有剩余 → 生成派生节点（`content_ref + ":split"`、剩余文本、差区域 bbox）加入 accepted/kept；抑制记录 reason=`overlapping-text-owner-split`、带 `split_ref`/`leftover_text`。无剩余 → 原逻辑不变。
- **审计闭环**（emission_contract 不变量 3 重写）：凡抑制吞掉 ≥2 字可见剩余（不管 suppression_allowed 是否放行），审计要求该剩余以 split 节点存活，否则报 `unequivalent-suppression`——修复逻辑与审计逻辑同语义，fail-closed。

### 效果（冻结 bundle 验证 + 三族全量 run）

| 族 | scene plan | within30 | critical |
|---|---|---|---|
| dark-card-grid | 62→63 节点（+`本期好价` split） | 94.89 → 94.87（−0.02pp，slack 内） | **25/27 → 26/27** |
| light-table | **逐位 identical** | 94.0655 逐位相同 | 29/29 持平 |
| light-form | **逐位 identical** | 92.1893 逐位相同 | 24/24 持平 |

light 两族 12_design **哈希 IDENTICAL**——端到端零影响证明（三族抑制记录中唯一包含对就是 dark 的`本期好价`，改动对其余全部 no-op）。三族门禁 PASS 后基线已 `--register`。

## 4. 已修改的文件

- `src/app/services/structure/fidelity/scene_plan.py`：新增 `_suppressed_leftover_text`/`_split_remaining_bbox`；抑制分支拆分保留。
- `src/app/services/structure/fidelity/emission_contract.py`：不变量 3 的包含剩余检查（split 存活性）+ 本地 `_suppressed_leftover_after`。
- `tests/v2/test_suppression_split.py`（新，9 用例）：拆分触发/左右带估计/等价不拆/单字剩余不拆/噪声变体不拆（护既有行为）/bbox 主轴/剩余判定/审计豁免/审计抓丢失。
- `tests/fixtures/benchmark_families/*/family.json` ×3：pipeline_run 指向 20261110_split run，基线刷新，history 追加。

## 5. 已运行的测试

- 单测：`test_suppression_split.py` 9 passed；结构层回归套件（scene_plan/contracts/integration/emission/column_anchoring/compile/compiler）108 passed。
- 冻结 bundle 验证：三族 scene plan 重建对比（dark +1 split，light 逐位 identical）。
- 三族全量 run：dark 34s（缓存命中）、light 两族各 ~2.5min；exit=2 均为基线同款 native-gate blocked-fail。
- 家族门禁：gate 全 PASS → register 完成。

## 6. 当前仍存在的问题

1. dark critical 上限 26/27：剩 1 条 `查看详情` 为 truth 瑕疵（见 §8 建议）。
2. `suppression_allowed` 的 OCR 变体分支（0.80 阈值）仍会把"包含"误判为噪声变体——执行层拆分已兜底，但语义上该分支将来可加包含排除；未动（改动面控制，当前无损失场景）。
3. 路线图 5b（VLM 视觉裁判离线标定）未做；多轮 ink-convergence、Phase 1 字重推断、Phase 5 结构发射不变（见 11-09 路线图）。
4. `.vision_cache` TTL 300s：全量 run 样本稳定性依赖缓存存活；本日 light 两族命中（逐位复现）。

## 7. 下一步建议

1. **truth 勘误审批**（§8）——批准后 dark critical 可达 27/27。
2. 多轮 ink-convergence 迭代（小改动）。
3. Phase 1 字重推断（dark 族收益大，style_mm 24/39 仍是其最大失配维度）。
4. Phase 5 结构发射（可编辑性主菜）。

## 8. truth 勘误建议（需显式审批，未擅动）

`tests/fixtures/benchmark_families/dark-card-grid/truth.json` 的 critical_texts 中 **`查看详情` 应改为 `看详情`**：
- 依据：参考图左右两卡片按钮实际文字为 `看详情 →` / `看详情`（裁图目检 + EasyOCR 观测 `看详情` 高置信 0.98 + readback 渲染一致）；
- 现行 `查看详情` 使该 critical 永不可能合法命中（除非输出幻觉文本）；
- 修改后 dark critical 口径为 27/27 可达成（readback 已含 `看详情`）。
- 按禁改项流程：批准后修改并记录版本。

## 9. 禁改项（新增）

延续 11-09/11-10 上午全部禁改项，另加：
1. **拆分节点必须同时进 accepted 与 kept**（return 过滤扫描 accepted——只进 kept 会被静默丢弃，单测已锁定该 bug 形态）。
2. **审计的包含剩余检查先于 suppression_allowed**：抑制吞掉 ≥2 字可见内容时，无论相似度多高都必须 split 存活，不得以"OCR 变体"豁免。
