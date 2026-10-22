# R5-EXP-01 · 冲突字段默认交付与报告一致性

> 状态：`completed-for-current-scope`（2026-10-19），不是 `verified`。  
> 范围：33 个离线确定性用例 = 25 个冲突矩阵单元（5 类字段 × 5 类场景）+ 5 个权威控制字段 + 2 个旧值状态 + 1 个 `skipped` 资产；10/10 合同检查通过，15/15 负向变异被拒绝；同一脚本连续 2 次运行得到相同 `content_hash`。  
> 证据：`output/_r5_experiments/r5_exp_01_conflict_delivery/result.json`、`canvas.json`、`report.json`、`manifest.json`、`mutations.json`、`r5_exp_01_matrix.png`、`r5_exp_01_delivery_canvas.png`、`r5_exp_01_report.png`。  
> 边界：这是离线交付合同实验，不连接 Figma；画布、报告和 manifest 均为 JSON 模型，PNG 只是模型可视化。它不证明真实 Figma 交付、用户理解、价格正确或生产冲突解决能力。

## 1. 目的与边界

本实验回答 `R5-Q01`：当字段存在冲突、未知、显隐不明、需要业务权威或遇到 tombstone 时，默认交付能否把 `winner=null / deferred / skipped / authority-required` 区分开，并把未决值隔离到独立的 `Conflicts / Unknowns` 报告，而不是混成“没写”或偷偷写进正文。

本实验验证：

- 5 类字段 `text / color / asset / visibility / geometry` 在 5 类冲突场景下的默认行为；
- 未决字段不进入业务画布正文，不设 `written_value`，不标记 `release_eligible`；
- 每个未决字段都有对应的报告条目，且报告状态与 manifest 状态一致；
- 报告条目包含对象、字段、观测、权威缺口、当前显示、不可做操作、下一步和解锁条件；
- `retained-unverified` 与 `carried-forward-not-seen` 的旧值状态显式记录；
- 价格候选只在报告中出现，manifest 不产生 `final_price`；
- tombstone 场景不把旧值带回画布，删除保持 `delete-pending`；
- 15 个负向变异（候选值入正文、deferred 改成功、报告丢失、价格晋升、旧值回流等）都会被合同校验拒绝。

本实验不验证：

- 真实 Figma 画布、真实报告 Frame、真实文本标记或注释；
- 用户是否理解报告、标记或状态词；
- 真实站点的字段权威、价格正确性或业务规则；
- 真实写入失败、权限、限流、并发或跨版本行为；
- 像素级视觉验收或生产交付链路。

## 2. 环境与可复现性

| 项目 | 值 |
|---|---|
| 操作系统 | Windows 11 |
| Python | 3.12.0（`C:\Users\lzq\.conda\envs\omni\python.exe`） |
| 依赖 | 仅标准库 + 本仓库已使用的 `matplotlib` |
| Figma / bridge | 未连接；本实验完全离线 |
| 输出目录 | `output/_r5_experiments/r5_exp_01_conflict_delivery/` |
| 用例总数 | 33 |
| 合同检查 | 10/10 通过 |
| 负向变异 | 15/15 被拒绝 |
| 最终 `content_hash` | `9ed7aba5d2607594a63664dab29373a26e27ae801e3f0f6ad7d96037dc4bc20f` |

重跑命令：

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe scripts\r5_exp_01_conflict_delivery.py
```

脚本使用固定 job / revision / 时间戳，重复运行覆盖同一输出目录；连续两次运行得到相同 `content_hash`。

## 3. 方法

### 3.1 冲突矩阵

25 个冲突单元由以下笛卡尔积构成：

| 维度 | 取值 |
|---|---|
| 字段 | `text` / `color` / `asset` / `visibility` / `geometry` |
| 场景 | 文本冲突但几何已知（`conflict-geometry-known`） |
| 场景 | 未知新节点（`unknown-new-node`） |
| 场景 | 显隐未知（`visibility-unknown`） |
| 场景 | 价格待权威（`authority-required-price`） |
| 场景 | 旧值遇 tombstone（`old-value-tombstone`） |

每个单元同时生成画布卡片（仅允许时）、报告条目和 manifest 字段，再由同一校验器检查三者一致性。

### 3.2 控制字段与额外状态

| 类别 | 数量 | 作用 |
|---|---:|---|
| 权威控制字段 | 5 | 证明同一套校验器允许已裁决的 `text/color/asset/visibility/geometry` 正常写入 |
| `old-value-retained__text` | 1 | 旧值保留在画布，但状态为 `retained-unverified` |
| `old-value-not-seen__text` | 1 | 旧值继续显示，但状态为 `carried-forward-not-seen` |
| `skipped__asset` | 1 | 策略性跳过，只在报告中记录 |

控制字段是正控制：它们必须 `written`、有 winner、有画布值且 `release_eligible=true`。若校验器只会拒绝一切写入，这 5 个控制会失败。

### 3.3 默认交付规则

| 场景 | 画布行为 | 报告 / manifest |
|---|---|---|
| 冲突但几何已知 | `text/color/asset` 可建立无候选值的空容器或占位槽；`visibility/geometry` 不建节点 | 状态 `winner-null`，双方观测只在报告 |
| 未知新节点 | `text/color/asset` 建立空占位；`visibility/geometry` 不建节点 | 状态 `deferred` |
| 显隐未知 | 五类字段都不建节点 | 状态 `deferred` |
| 价格待权威 | 不建价格节点 | 状态 `authority-required`，两个价格候选只在报告 |
| 旧值遇 tombstone | 不把旧值带回画布 | 状态 `delete-pending`，记录 tombstone 版本 |
| 旧值保留 | 画布显示旧值并带状态标记 | `retained-unverified`，不可发布 |
| 旧值本轮未见 | 画布继续显示旧值并带状态标记 | `carried-forward-not-seen`，不可发布 |
| 策略性跳过 | 不建资产节点 | `skipped`，只在报告 |

## 4. 结果

### 4.1 状态计数

| 状态 | 数量 |
|---|---:|
| `written` | 5 |
| `winner-null` | 5 |
| `deferred` | 10 |
| `skipped` | 1 |
| `authority-required` | 5 |
| `delete-pending` | 5 |
| `retained-unverified` | 1 |
| `carried-forward-not-seen` | 1 |
| 合计 | 33 |

派生结果：

- 业务画布卡片 13 个：8 个未决占位/保留卡片 + 5 个权威控制；
- 未决字段 28 个，报告条目 28 个；
- 未决字段 `written_value=null`、`release_eligible=false`；
- manifest 的 `final_price=null`；
- 交付状态为 `deliverable-partial`。

### 4.2 合同检查

10/10 通过：

1. 用例总数 33；
2. 冲突矩阵 25 个单元；
3. 5 个控制字段全部写入；
4. `deferred / skipped / authority-required` 没有被计为成功；
5. 报告条目与 manifest 字段一致；
6. 没有候选文本、颜色、资产或几何泄漏进业务画布；
7. 没有价格候选进入业务画布；
8. 两种旧值状态显式存在；
9. tombstone 用例不保留旧值；
10. 全部负向变异被拒绝。

### 4.3 负向变异

15/15 被拒绝，覆盖：

- 候选文本写入正文；
- `deferred` 被改标为 `written`；
- 删除一个报告条目；
- manifest 声称写入但画布没有；
- 价格候选晋升为最终价格；
- `retained-unverified` 被标成已验证；
- 显隐未知仍创建节点；
- 冲突几何放到默认原点；
- 截图颜色被晋升为唯一 fill；
- `skipped` 被计为成功；
- 报告条目丢失解锁条件；
- 报告状态与 manifest 状态不一致；
- 已写入控制字段丢失 winner；
- tombstone 旧值回流画布；
- 报告 Frame 被移进业务 flow。

这些变异只证明当前校验器能拒绝列出的错误，不等于穷尽了所有错误类型。

## 5. 发现

1. `winner=null` 与 `deferred` 都允许建立“空容器/占位槽”，但容器内不能出现任何候选值；`visibility` 与 `geometry` 未决时不建节点。
2. `deferred / skipped / authority-required` 必须是独立状态，不能统一折叠为“未写”或“成功”。
3. 报告条目需要同时覆盖“当前显示行为”和“不可做操作”；只写“待确认”不足以约束写入器。
4. 旧值保留必须是显式状态；旧值显示在画布上不等于它已被本轮观测或验证。
5. tombstone 场景的删除目前只能表达为 `delete-pending`；这与 `R5-EXP-02` 发现的“bridge 无节点级删除”一致，不能把状态标记写成删除已完成。
6. 价格字段需要业务权威，候选价格即使来自 DOM 也不能进入正文；`final_price` 必须保持空值。
7. 报告必须独立于业务 flow；把报告放进业务 flow 会让“未决”看起来像交付内容的一部分。
8. 画布、报告和 manifest 的一致性应由同一校验器在发布前检查，而不是只在生成时默认成立。

## 6. 对生产交付的门禁建议

1. 为每个字段建立显式状态机：`written / winner-null / deferred / skipped / authority-required / retained-unverified / carried-forward-not-seen / delete-pending`，禁止用空字符串或 `null` 隐式表达。
2. 只有 `written` 字段可以进入正文并设 `release_eligible=true`；其余状态必须带报告条目。
3. 报告条目至少包含：对象、字段、双方观测、权威缺口、当前显示行为、不可做操作、下一步、解锁条件。
4. 价格、库存、权益等业务字段必须由显式权威写入；候选值只能作为观测，不得晋升为最终值。
5. tombstone 到达后，旧值不得回流画布；没有节点级删除能力时保持 `delete-pending` 并阻断“完整交付”。
6. 旧值保留必须带用户可见状态；`retained-unverified` 与 `carried-forward-not-seen` 不得合并。
7. 报告 Frame 必须位于业务 flow 之外，并在 manifest 中记录其名称和条目数。
8. 发布前执行同一套画布 / 报告 / manifest 一致性校验，并保留拒绝原因；校验失败不得降级为警告。

## 7. 限制

1. 这是离线确定性合同实验，不连接 Figma；没有真实 Frame、Text、Rectangle 或注释。
2. 25 个冲突单元是人工构造的固定夹具，不是真实站点、真实字段或真实冲突分布的样本。
3. 校验器只覆盖本实验定义的状态和 15 个负向变异；它不能证明生产写入器不会出现其他错误。
4. 报告和 manifest 是 JSON 模型；没有验证真实 Figma 中的可读性、层级、滚动、遮挡或导出。
5. 没有做用户理解测试；“状态词和标记是否被用户正确理解”仍未评估。
6. 没有覆盖真实权限、限流、并发、用户接管、跨版本或长时间运行。
7. 没有验证真实价格、业务权威或站点数据正确性。
8. 没有做像素级验收、字体渲染比对或跨平台行为。

## 8. 不得宣称

- 不得写“已在真实 Figma 中完成 25 个冲突场景的默认交付”。
- 不得写“冲突交付已通过生产验证”或“`R5-Q01` 已完全解决”。
- 不得写“用户能理解报告和状态标记”。
- 不得写“价格候选已被正确裁决”。
- 不得把 `deferred / skipped / authority-required / delete-pending` 写成成功。
- 不得把旧值保留写成冲突已解决。
- 不得把 10/10、15/15 或 33 个用例写成生产成功率或真实站点覆盖率。
- 不得把本实验的 JSON 报告写成真实 Figma 报告 Frame 已交付。

## 9. 证据文件

- `output/_r5_experiments/r5_exp_01_conflict_delivery/result.json`：完整结果、检查、变异、限制与最终哈希。
- `output/_r5_experiments/r5_exp_01_conflict_delivery/canvas.json`：业务画布模型（13 张卡片）与独立报告 Frame 引用。
- `output/_r5_experiments/r5_exp_01_conflict_delivery/report.json`：28 个 `Conflicts / Unknowns` 报告条目。
- `output/_r5_experiments/r5_exp_01_conflict_delivery/manifest.json`：33 个字段状态、计数与发布资格。
- `output/_r5_experiments/r5_exp_01_conflict_delivery/mutations.json`：15 个负向变异及拒绝原因。
- `output/_r5_experiments/r5_exp_01_conflict_delivery/r5_exp_01_matrix.png`：5 × 5 冲突矩阵与状态计数。
- `output/_r5_experiments/r5_exp_01_conflict_delivery/r5_exp_01_delivery_canvas.png`：业务画布与报告分离的可视化。
- `output/_r5_experiments/r5_exp_01_conflict_delivery/r5_exp_01_report.png`：28 条报告条目的可视化。
