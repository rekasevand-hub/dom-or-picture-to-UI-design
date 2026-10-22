# R4-EXP-08 · 多页面、多轮更新的权威链

> 状态：`completed-for-current-scope`（2026-10-18），不是 `verified`。  
> 范围：15 个真实 Chromium 页面修订、4 个轮次、2 个 scope、10 个字段；验证显式 `supersedes`、字段权威、删除墓碑、跨来源冲突与轮次增量解析。  
> 证据：`output/_r4_experiments/r4_authority_chain.json`、`output/_r4_experiments/r4_authority_artifacts/`，以及 `r4_authority_chain.png`、`r4_authority_matrix.png`、`r4_authority_conflicts.png`。  
> 边界：页面与权威声明由作者构造，DOM、页面渲染和字段观测来自真实 Chromium；未修改 `src/`、`figma_bridge/`，未执行 Figma 写入。

## 1. 目的与边界

本实验回答 `R4-O07`：当同一产品跨多个页面、多个轮次持续更新时，解析器能否只让合法的权威声明生效，按显式 `supersedes` 淘汰旧修订，并把删除、未见到、外部冲突和需要权威的候选分开处理。

本实验验证的是**权威图与字段级增量解析规则**，不验证：

- 真实站点、登录态、CMS、发布系统或多租户权限；
- 自动发现页面之间的 `supersedes` 关系；
- 真实商品目录的规模、更新频率或并发写入；
- 生产 IR 持久化、回滚、审计存储或跨进程一致性；
- Figma 文本、颜色、资产或遮挡字段写入；
- 任意来源类型、任意 scope 模型或通用冲突阈值。

## 2. 环境与可复现性

| 项目 | 值 |
|---|---|
| 操作系统 | Windows 11（`10.0.26300`） |
| Python | 3.12.0（`C:\Users\lzq\.conda\envs\omni\python.exe`） |
| Playwright / Chromium | 1.62.0 / 151.0.7922.34（headless） |
| Matplotlib | 3.11.0 |
| 页面服务 | loopback HTTP |
| 页面修订 | 15 |
| 轮次 | 4（product scope 到 r4，campaign scope 到 r2） |
| 字段 / scope | 10 / 2 |
| 检查 | 35/35 通过 |

重跑命令：

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe output/_r4_experiments/r4_authority_chain.py
```

脚本会重建 15 个 HTML 页面、启动 loopback HTTP、用 Chromium 逐页捕获 DOM、生成四轮快照、执行 24 次输入置换和 4 种非法变异，并重绘三张分析图。`content_hash` 覆盖包含 `generated_at` 与随机端口在内的完整结果，因此每次重跑的哈希会变化；写盘后可排除 `content_hash` 字段重新计算并核对。

## 3. 方法与合同

### 3.1 页面修订模型

每个页面修订记录：

- `page_id` 与页面家族（去掉 `@rN` 后缀）；
- `round`、`scope`、`source_kind`；
- `authority` 与 `granted_by`；
- `authority_claims`；
- `supersedes` 目标；
- `deleted_fields`；
- 字段值与内容哈希。

轮次只作审计元数据，不自动产生权威，也不自动产生删除。只有显式权威声明、显式 `supersedes` 和显式墓碑可以改变字段状态。

### 3.2 两个独立 scope

- `product:aurora-x1`：`title / price / color / description / stock / battery / weight / promo_code / rating`
- `campaign:aurora-x1`：`discount`

scope 独立解析；campaign 字段不会因为同页出现而泄漏到 product 字段。

### 3.3 字段权威期望

| 字段 | scope | 期望权威 |
|---|---|---|
| `title` | product | `detail` |
| `price` | product | `inventory` |
| `color` | product | `detail` |
| `description` | product | `detail` |
| `stock` | product | `inventory` |
| `battery` | product | `spec` |
| `weight` | product | `spec` |
| `promo_code` | product | 无，必须有来源授权 |
| `rating` | product | 无，必须有来源授权 |
| `discount` | campaign | `promo` |

来源自称为 `authoritative` 不足以生效：还必须存在 `granted_by`、合法页面家族、合法轮次方向和未被 `supersedes` 淘汰。与期望权威页不一致的声明保留在 `authority_mismatches`，不会被静默丢弃。

### 3.4 解析顺序

1. 先验证 `supersedes` 的结构：目标存在、来源有授权、同页面家族、轮次严格递增。
2. 在同一结构图上检测环；存在环时整条链 `chain_valid=false`，所有字段输出 `invalid-authority-chain`。
3. 仅让未被淘汰的有效权威进入字段解析。
4. 权威值唯一时解析；外部候选不同则降为 `authority-required`，保留权威值但要求确认。
5. 多个有效权威值不同则输出 `external-conflict`，`winner=null`。
6. 显式墓碑输出 `deleted`，不可被未授权来源“复活”。
7. 权威声明字段但未给值且无墓碑时，向前继承并输出 `carried-forward-not-seen` 或 `not-seen`。
8. 没有权威、只有单一外部候选时输出 `authority-required`；多个不同候选输出 `external-conflict`。

### 3.5 状态集合

`resolved / resolved-consensus / authority-required / external-conflict / deleted / carried-forward-not-seen / not-seen / unknown / invalid-authority-chain`

## 4. 场景与轮次结果

### 4.1 页面修订

| 页面修订 | 轮次 | 来源 | 权威 | 声明 | supersedes | 墓碑 |
|---|---|---:|---|---|---|---|
| `detail@r1` | 1 | product | authoritative | title, description, color | — | — |
| `spec@r1` | 1 | product | authoritative | battery, weight | — | — |
| `inventory@r1` | 1 | product | authoritative | price, stock | — | — |
| `promo@r1` | 1 | campaign | authoritative | discount | — | — |
| `detail@r2` | 2 | product | authoritative | title, description, color | `detail@r1` | — |
| `spec@r2` | 2 | product | authoritative | battery, weight | `spec@r1` | — |
| `inventory@r2` | 2 | product | authoritative | price, stock | `inventory@r1` | — |
| `promo@r2` | 2 | campaign | authoritative | discount | `promo@r1` | — |
| `legacy-mirror@r2` | 2 | mirror | unattested | — | — | — |
| `partner-feed@r2` | 2 | external | external-unattested | — | — | — |
| `detail@r3` | 3 | product | authoritative | title, description, color | `detail@r2` | description |
| `marketplace@r3` | 3 | external | external-unattested | — | — | — |
| `archive-snippet@r3` | 3 | archive | unattested | — | — | — |
| `detail@r4` | 4 | product | authoritative | title, description, color | `detail@r3` | description |
| `rogue-detail@r4` | 4 | rogue | authoritative | title | — | — |

共 6 条合法 `supersedes` 边、5 个有效权威页、6 个被淘汰修订、1 个内容等价历史镜像、2 个外部候选和 1 个影子候选。

### 4.2 轮次快照

| 轮次 | 状态计数 |
|---|---|
| r1 | `resolved=8`, `unknown=2` |
| r2 | `authority-required=4`, `resolved=6` |
| r3 | `authority-required=3`, `carried-forward-not-seen=3`, `deleted=1`, `external-conflict=1`, `resolved=2` |
| r4 | `authority-required=2`, `carried-forward-not-seen=3`, `deleted=1`, `external-conflict=2`, `resolved=2` |

r1 只有 product/campaign 基础页，`promo_code` 与 `rating` 没有任何证据，保持 `unknown`。r2 引入 partner-feed 后，`title / price / promo_code / rating` 需要权威。r3 的 detail 页显式删除 `description`，inventory/spec 未再出现，三个未更新字段进入 `carried-forward-not-seen`。r4 的 rogue 页面与合法 detail 页同时声明 `title`，因此成为两个有效权威的冲突。

### 4.3 最终字段

| 字段 | 状态 | 选中值 | 来源 | 说明 |
|---|---|---|---|---|
| `title` | `external-conflict` | `null` | — | `detail@r4` 与 `rogue-detail@r4` 两个有效权威冲突 |
| `price` | `authority-required` | `1399` | `inventory@r2` | detail/外部页的 `1349 / 1299 / 1199` 只作候选 |
| `color` | `resolved` | `Midnight` | `detail@r4` | 合法 r4 detail 修订胜出 |
| `description` | `deleted` | `null` | `detail@r4` | 显式墓碑；archive 候选不得复活 |
| `stock` | `carried-forward-not-seen` | `low-stock` | `inventory@r2` | r3/r4 未再见到 inventory |
| `battery` | `carried-forward-not-seen` | `36h` | `spec@r2` | r3/r4 未再见到 spec |
| `weight` | `carried-forward-not-seen` | `245g` | `spec@r2` | r3/r4 未再见到 spec |
| `promo_code` | `authority-required` | `null` | — | 只有 partner-feed 的单一外部候选 |
| `rating` | `external-conflict` | `null` | — | partner-feed `4.6` 与 marketplace `4.8` 冲突 |
| `discount` | `resolved` | `15%` | `promo@r2` | campaign scope 独立解析 |

## 5. 基线对比

“取最高轮次且包含该字段的观测”基线在 10 个字段中正确 5 个、错误 5 个：

| 字段 | 基线来源 | 基线值 | 期望值 | 结果 |
|---|---|---|---|---|
| `title` | `rogue-detail@r4` | `Aurora X1 Ultra` | `null` | 错误，自声明权威按 recency 胜出 |
| `price` | `detail@r4` | `1349` | `1399` | 错误，忽略 inventory 权威 |
| `color` | `detail@r4` | `Midnight` | `Midnight` | 正确 |
| `description` | `archive-snippet@r3` | 已删除文本 | `null` | 错误，复活显式删除 |
| `stock` | `inventory@r2` | `low-stock` | `low-stock` | 正确 |
| `battery` | `spec@r2` | `36h` | `36h` | 正确 |
| `weight` | `spec@r2` | `245g` | `245g` | 正确 |
| `promo_code` | `partner-feed@r2` | `AURORA15` | `null` | 错误，无授权候选被采用 |
| `rating` | `marketplace@r3` | `4.8` | `null` | 错误，外部冲突被消解为单值 |
| `discount` | `promo@r2` | `15%` | `15%` | 正确 |

基线错误集中在权威、删除和外部冲突三类，而不是“旧值是否更新”。

## 6. 非法变异

| 变异 | 预期失败方式 | 实际结果 |
|---|---|---|
| 移除 `detail@r4 -> detail@r3` 隐式依赖 | 不按 recency 自动继承 | `color` 变为 `external-conflict`，r3 与 r4 同时有效 |
| 反向增加 `detail@r2 -> detail@r4` | 形成环并整体 fail closed | 检出 `detail@r2/detail@r3/detail@r4` 环，10 个字段均为 `invalid-authority-chain` |
| 让 partner-feed 声明 `supersedes detail@r4` | 非权威边被忽略 | 边进入 `ignored_edges`，`detail@r4` 仍有效 |
| 去掉 `detail@r4` 的 description 墓碑 | 缺字段只表示未见到 | `description` 变为 `not-seen`，继承 r2 文本，不变成 `deleted` |

环检测在轮次单调性之前基于结构边构图；非单调边同时记录为非法。这样“反向 supersedes”不会被简化为普通非法边而漏掉环。

## 7. 检查

35/35 检查通过，覆盖：

- 15 个页面修订唯一，且真实 DOM 与作者声明一致；
- 6 条合法边、无非法边、无环；
- 5 个有效权威、6 个被淘汰修订、1 个内容等价镜像；
- 四轮状态计数与字段级预期；
- `title` 双权威冲突、`price` inventory 权威、`color` r4 解析；
- `description` 墓碑与 archive 候选隔离；
- `stock / battery / weight` 继承；
- `rating` 双外部候选冲突与 `promo_code` 单候选待授权；
- `discount` campaign scope 隔离；
- 24 次输入置换同哈希、重复解析与四轮重放稳定；
- 4 种非法变异均按预期失败；
- 新旧基线 5 正确 / 5 错误；
- 冲突字段保留权威与候选观测；
- `content_hash` 写盘后重新计算一致；
- 只读边界：`source_mutation=false`、`figma_write=false`。

## 8. 对生产权威链的建议

1. 轮次只能用于审计和单调性校验，不能替代显式权威与 `supersedes`。
2. 权威声明必须绑定来源、授权者、scope 与页面家族；自声明权威进入 `authority_mismatches`，不得静默生效。
3. `supersedes` 必须在同一页面家族内、轮次严格递增；结构图和轮次校验应分开记录，先构图检环，再判断单调性。
4. 删除必须使用显式墓碑；缺字段只能表示未见到，并从最近的合法权威值继承。
5. 权威值与外部候选不同时，保留权威值但输出 `authority-required`，不要静默覆盖或平均。
6. 两个有效权威值不同必须输出 `external-conflict` 且 `winner=null`，同时保留双方观测。
7. scope 必须独立解析；campaign 字段不得因页面共现进入 product 结果。
8. 内容等价的镜像应标为历史副本，不进入候选；内容哈希需要覆盖 scope、字段和删除集合。
9. 每次更新应输出可重放的字段级 provenance，至少包含权威、轮次、边、候选、墓碑和选择理由。

## 9. 限制与未覆盖

- 页面、来源和权威声明均为作者构造的受控 loopback 内容，不是真实站点或 CMS。
- 只覆盖 Chromium；未覆盖跨浏览器、移动端、登录态、权限系统和发布延迟。
- `supersedes` 为显式声明；未实现从 URL、标题、时间戳或内容相似度自动发现页面关系。
- 只覆盖 15 个修订、10 个字段和 2 个 scope；未覆盖大规模目录、分页、无限滚动或并发更新。
- 未覆盖真实网络失败、部分页面缺失、乱序到达、重复修订、时钟偏差或多写者冲突。
- 未覆盖生产 IR 持久化、事务、回滚、审计日志或跨进程一致。
- 未执行 Figma 文本、颜色、资产或遮挡字段写入。

## 10. 不得宣称

- 不得写“多页面权威链已在真实站点验证”；本实验是受控 loopback 页面。
- 不得把 35/35 写成真实站点解析准确率、覆盖率或生产接受率。
- 不得写“轮次更新可以自动推导权威”；本实验明确拒绝隐式 recency。
- 不得把 `carried-forward-not-seen` 写成 `deleted`，也不得把 `not-seen` 写成删除。
- 不得把 `authority-required` 写成已解决；它表示仍需来源授权或人工确认。
- 不得把 `external-conflict` 的平均值、最高分或最新值写成 winner。
- 不得把本实验写成已接入 `src/`、`figma_bridge/` 或已驱动 Figma 写入。

## 11. 证据文件

| 文件 | 内容 |
|---|---|
| `output/_r4_experiments/r4_authority_chain.py` | 可复现实验脚本（页面、HTTP、捕获、权威图、四轮解析、变异、绘图） |
| `output/_r4_experiments/r4_authority_chain.json` | 15 个观测、四轮快照、最终字段、基线、变异与 35 项检查 |
| `output/_r4_experiments/r4_authority_artifacts/site/index.html` | 15 个页面修订索引 |
| `output/_r4_experiments/r4_authority_artifacts/site/pages/` | 15 个真实渲染页面 |
| `output/_r4_experiments/r4_authority_artifacts/dom_observations.json` | Chromium DOM 捕获与哈希 |
| `output/_r4_experiments/r4_authority_artifacts/round_snapshots.json` | 四轮字段快照 |
| `output/_r4_experiments/r4_authority_artifacts/mutations.json` | 4 种非法变异的解析结果 |
| `output/_r4_experiments/r4_authority_artifacts/index.png` | 页面索引截图 |
| `output/_r4_experiments/r4_authority_chain.png` | 页面修订与显式 supersedes 图 |
| `output/_r4_experiments/r4_authority_matrix.png` | 10 个字段的四轮状态矩阵 |
| `output/_r4_experiments/r4_authority_conflicts.png` | 最终候选与冲突分布 |
