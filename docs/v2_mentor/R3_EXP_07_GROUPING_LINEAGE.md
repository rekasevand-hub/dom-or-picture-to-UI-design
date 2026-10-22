# R3-EXP-07 · 截图分组、父关系与 lineage（受控实验）

> 状态：`completed-for-current-scope`（2026-10-18）。
> 范围：单个受控合成页面；验证截图证据下的父关系候选、歧义输出，以及父关系编辑、split/merge 和 undo 的不变量。
> 证据：`output/_r3_experiments/exp07_grouping.json`、`exp07_screenshot.png`、`exp07_contact_sheet.png`。

## 1. 目的与边界

本实验回答四个问题：

1. 有边框的容器是否会自动成为正确的父节点。
2. 共享白底、相邻距离和重复行分别能把分组证据推到什么强度。
3. 无边框的卡片、列表行和筛选行，是否会因为“看起来像一组”而被误判为高置信父关系。
4. 父关系编辑、split/merge、拒绝坏合并和 undo 是否能保持对象身份、lineage 和快照一致性。

本实验**不**验证自动对象发现或图像分割。对象框是分析者预先给出的 seed；实验只验证这些对象之间的父关系判定和编辑不变量。文本与标题语义也没有做 OCR，`role` 是分析者标注。所有结论只适用于这个受控页面。

## 2. 方法

### 2.1 截图与证据来源

- 页面：`output/_r3_experiments/exp07_grouping_site/index.html`，1200×900，DPR 1。
- 浏览器：Playwright 1.62.0 / Chromium `151.0.7922.34`。
- 截图证据只来自 PNG 像素；DOM 不参与父关系判断。
- 页面对象与 ground truth 是同一作者预先编写的，ground truth 只用于评估，不进入候选父关系计算。
- 动画和过渡在截图前关闭，避免时间态污染。

### 2.2 视觉证据

对每个 seed 框计算以下指标：

| 指标 | 含义 |
|---|---|
| `edge_coverage` | 框周界上非白像素比例 |
| `border_contrast` | 周界非白像素的平均亮度差 |
| `content_ratio` | 框内非白像素比例 |
| `anchor_count` | 彩色连通域数量 |
| `band_count` | 水平 ink band 数量；间隔不超过 20px 的墨迹合并为一条 band |
| `rhythm` | band/彩色 anchor 顶部的间距一致性 |
| `left_alignment` | band/anchor 左边缘的众数占比 |
| `white_ratio` | 框内纯白像素比例 |
| `smallest_visual_container` | 包含该框的最小 seed 容器 |
| `candidate_parent` | 最小的“角色允许作为父节点”的 seed 容器 |

父关系状态只有两种可用输出：

| 状态 | 含义 |
|---|---|
| `candidate` | 本受控页里有较强视觉证据，但仍需人工复核 |
| `ambiguous` | 证据冲突或不足，不能自动确认 |

`obj-band` 的 `role_status=ambiguous`：它有边框，但无标题，且是横跨两栏的装饰性外框；它可以有父节点，但不能仅凭边框成为子对象的父节点。

### 2.3 Ledger 不变量

Ledger 记录对象的 `id / rect / role / parent / state / lineage / review_status / history`。本实验验证：

- 父关系编辑记录 `from / to`，对象 id 与像素区域不变。
- 父关系不能形成环；尝试制造环时必须拒绝，且 digest 不变。
- split 后源对象变 `superseded`，新对象 `derived_from` 指向源，子对象重新挂到拆分后的对象。
- merge 后源对象都变 `superseded`，新对象 `derived_from` 记录全部来源，子对象重新挂到合并后的对象。
- 坏 merge 必须保留双方来源和 `review_status=rejected`，并能 undo 恢复原 digest。
- 任意时刻不得有悬空 parent、悬空 lineage 或 parent/lineage 环。

`parent_status` 不会写成 `verified`；本实验没有执行 Figma API 写入，也没有人工逐项复核全部关系。

## 3. 受控页面

页面包含：

- 外层 `band`：1px 边框，横跨主栏与侧栏，无标题。
- 主栏与侧栏：无可见边框，均为白底；两者之间有 40px 纯白 gutter。
- `Section A`：有边框，两个无边框卡片。
- `Section B`：无边框，三行重复列表。
- `Filters`：无边框分组，四行重复筛选行。
- `Promotions`：有边框的 promo 卡片。

| 对象 | rect `[x,y,w,h]` | role | ground-truth parent |
|---|---|---|---|
| `obj-page` | `[0,0,1200,900]` | page | — |
| `obj-band` | `[20,20,1160,860]` | page-frame-or-decoration | `obj-page` |
| `obj-main` | `[40,40,720,840]` | main-column | `obj-page` |
| `obj-sidebar` | `[800,40,360,820]` | sidebar | `obj-page` |
| `obj-sectionA` | `[100,100,640,340]` | section | `obj-main` |
| `obj-sectionB` | `[100,480,640,400]` | section | `obj-main` |
| `obj-cardA1` | `[120,170,288,200]` | card-item | `obj-sectionA` |
| `obj-cardA2` | `[448,170,288,200]` | card-item | `obj-sectionA` |
| `obj-rowB1` | `[120,540,600,100]` | list-row | `obj-sectionB` |
| `obj-rowB2` | `[120,660,600,100]` | list-row | `obj-sectionB` |
| `obj-rowB3` | `[120,780,600,100]` | list-row | `obj-sectionB` |
| `obj-filters` | `[810,48,340,246]` | filter-group | `obj-sidebar` |
| `obj-filter1` | `[820,100,320,36]` | filter-row | `obj-filters` |
| `obj-filter2` | `[820,150,320,36]` | filter-row | `obj-filters` |
| `obj-filter3` | `[820,200,320,36]` | filter-row | `obj-filters` |
| `obj-filter4` | `[820,250,320,36]` | filter-row | `obj-filters` |
| `obj-promo` | `[820,600,320,180]` | promo-item | `obj-sidebar` |

## 4. 结果

### 4.1 状态分布

| 指标 | 值 |
|---|---:|
| 有父对象的 seed | 16 |
| `candidate` | 5 |
| `ambiguous` | 11 |
| 错误 `candidate` | 0 |
| `candidate_parent` 与 ground truth 一致 | 16 / 16 |
| 原始最小容器与 ground truth 一致 | 14 / 16（`0.875`） |

`candidate` 为：`obj-band`、`obj-sectionA`、`obj-sectionB`、`obj-filters`、`obj-promo`。其中 `obj-band` 的 `role_status=ambiguous`，所以“可作为父节点的高置信候选”只有 4 个：`sectionA / sectionB / filters / promo`。

`candidate_parent` 的 16/16 依赖分析者给出的 `role` 标注，用来跳过装饰性 `obj-band`；若只按原始最小容器、不区分角色，则为 14/16。两种口径都在 JSON 中保留。

### 4.2 逐对象结果

| 对象 | 原始最小容器 | 候选父节点 | 父关系状态 | 角色状态 | 结果 |
|---|---|---|---|---|---|
| `obj-band` | `obj-page` | `obj-page` | `candidate` | `ambiguous` | 父关系候选；角色需复核 |
| `obj-main` | `obj-band` | `obj-page` | `ambiguous` | `container` | 边框假父关系冲突 |
| `obj-sidebar` | `obj-band` | `obj-page` | `ambiguous` | `container` | 边框假父关系冲突 |
| `obj-sectionA` | `obj-main` | `obj-main` | `candidate` | `container` | 边框证据 |
| `obj-sectionB` | `obj-main` | `obj-main` | `candidate` | `container` | 重复缩略图节奏 |
| `obj-cardA1` | `obj-sectionA` | `obj-sectionA` | `ambiguous` | `leaf` | 无边框，证据不足 |
| `obj-cardA2` | `obj-sectionA` | `obj-sectionA` | `ambiguous` | `leaf` | 无边框，证据不足 |
| `obj-rowB1` | `obj-sectionB` | `obj-sectionB` | `ambiguous` | `leaf` | 单行只有一个结构 band |
| `obj-rowB2` | `obj-sectionB` | `obj-sectionB` | `ambiguous` | `leaf` | 单行只有一个结构 band |
| `obj-rowB3` | `obj-sectionB` | `obj-sectionB` | `ambiguous` | `leaf` | 单行只有一个结构 band |
| `obj-filters` | `obj-sidebar` | `obj-sidebar` | `candidate` | `container` | 4 条等距 ink band |
| `obj-filter1` | `obj-filters` | `obj-filters` | `ambiguous` | `leaf` | 单行只有一个结构 band |
| `obj-filter2` | `obj-filters` | `obj-filters` | `ambiguous` | `leaf` | 单行只有一个结构 band |
| `obj-filter3` | `obj-filters` | `obj-filters` | `ambiguous` | `leaf` | 单行只有一个结构 band |
| `obj-filter4` | `obj-filters` | `obj-filters` | `ambiguous` | `leaf` | 单行只有一个结构 band |
| `obj-promo` | `obj-sidebar` | `obj-sidebar` | `candidate` | `leaf` | 边框证据 |

### 4.3 基线对照

#### 最小视觉容器

直接取“包含该框的最小 seed 容器”，16 个对象中 14 个与 ground truth 一致，准确率 `0.875`。两个错误都是：

- `obj-main` → `obj-band`（应为 `obj-page`）
- `obj-sidebar` → `obj-band`（应为 `obj-page`）

说明：边框可以证明“某个框在另一个框里面”，不能证明“外层框就是父节点”。

#### 间隙合并

规则：对同一父节点下、互不包含的兄弟对象，若间隙 `<= 40px` 且间隙区域的纯白比例 `>= 0.98`，则合并。

结果为 5 个错误合并组：

| 父节点 | 被合并成员 |
|---|---|
| `obj-page` | `obj-main`, `obj-sidebar` |
| `obj-main` | `obj-sectionA`, `obj-sectionB` |
| `obj-sectionA` | `obj-cardA1`, `obj-cardA2` |
| `obj-sectionB` | `obj-rowB1`, `obj-rowB2`, `obj-rowB3` |
| `obj-filters` | `obj-filter1`, `obj-filter2`, `obj-filter3`, `obj-filter4` |

主栏与侧栏之间的 gutter：

- 宽度：40px
- 纯白比例：`1.0`
- 非白像素：0
- 结果：仍被 gap merge 合并

因此，“距离近 + 中间是白色”不足以证明同组；它只能作为一个弱候选证据。

## 5. 关键行为

1. **边框假父关系**：`obj-band` 同时包含主栏和侧栏，是两者原始最小容器；但它无标题、角色为装饰框。候选算法跳过它，选择 `obj-page`，同时把 `obj-main`、`obj-sidebar` 保持为 `ambiguous`，没有把边框当成父关系证明。
2. **边框证据的强度**：`obj-sectionA` 周界覆盖率 `1.0`、对比度 `48`，被提升为 `candidate`；`obj-promo` 周界覆盖率 `1.0`、对比度 `48`，同样为 `candidate`。
3. **边框被遮挡**：`obj-band` 的底边被主栏白底部分遮挡，周界覆盖率只有 `0.82`。本轮用 `edge_coverage >= 0.8` 且 `border_contrast >= 20` 作为边框候选门槛；这是该受控页的可复现口径，不是通用阈值。
4. **无边框分组**：`obj-sectionB` 依靠 3 个重复缩略图 anchor 的顶部节奏（`rhythm=1.0`）成为 `candidate`；`obj-filters` 依靠 4 条等距 ink band（`rhythm=0.99`）成为 `candidate`。这说明重复结构可以提供比单行更强、但不同于边框的证据。
5. **叶子对象保持歧义**：卡片的 `anchor_count_used` 为 1–2，列表行和筛选行为 1，均不足以独立确认父关系；它们全部保持 `ambiguous`，没有为了匹配 ground truth 而强行提升。
6. **共享白底不是分组证据**：主栏、侧栏、Section A、Section B、卡片行和筛选行之间都存在大面积白底；如果只看白色或距离，会得到 5 个错误合并组。

## 6. Lineage 编辑实验

### 6.1 父关系编辑与 undo

把 `obj-main` 的父节点从 `obj-page` 改为 `obj-band`：

- history 记录 `from=obj-page`、`to=obj-band`。
- 对象 id、rect `[40,40,720,840]` 和边界证据签名保持不变。
- 由于 `obj-band` 的角色是装饰/歧义，关系被标为 `review_status=rejected`。
- undo 后 digest 恢复到编辑前的值。

这条用例证明：父关系编辑可以是“先提出、再拒绝、再撤销”的可审计操作，而不是直接覆盖对象。

### 6.2 环拒绝

尝试把 `obj-page` 的父节点设为 `obj-sectionA`：

- 结果为拒绝，错误为 `parent edit would create a cycle: obj-page -> obj-sectionA`。
- 拒绝后 digest 不变。

### 6.3 Split

把 `obj-sectionB` 拆为：

- `obj-sectionB-upper`：`[100,480,640,180]`
- `obj-sectionB-lower`：`[100,660,640,220]`

结果：

- `obj-sectionB` 状态变为 `superseded`，`superseded_by` 指向两个新对象。
- 两个新对象都 `derived_from=["obj-sectionB"]`，父节点仍为 `obj-main`。
- `obj-rowB1` 重挂到 upper，`obj-rowB2`、`obj-rowB3` 重挂到 lower。
- 校验结果 `ok=true`，无悬空 parent、无 lineage 环、无 active 对象指向 superseded 父节点。

### 6.4 Merge

把 `obj-sectionA` 与 `obj-sectionB` 合并为 `obj-main-content-merged`：

- 两个源对象都变 `superseded`，并各自记录 `superseded_by`。
- 新对象 `derived_from=["obj-sectionA","obj-sectionB"]`，父节点为 `obj-main`。
- `obj-cardA1`、`obj-cardA2`、`obj-rowB1`、`obj-rowB2`、`obj-rowB3` 全部重挂到合并对象。
- 校验结果 `ok=true`。

### 6.5 坏合并与拒绝

把 `obj-main` 与 `obj-sidebar` 合并为 `obj-main-sidebar-merged`：

- 双方都记录在 `sources` 和 `derived_from` 中。
- `review_status=rejected`。
- 40px gutter 证据为 `white_ratio=1.0`、`ink_pixels=0`。
- 子对象 `sectionA / sectionB / filters / promo` 都重挂到合并对象，说明合并操作本身能保持结构。
- 校验结果 `ok=true`，但 review 明确拒绝。
- undo 后 digest 恢复；最终 ledger 与初始 ledger 的 digest 相同。

这条用例的意义是：**结构上可执行的合并，不等于语义上应接受的合并**。白 gutter 和相邻距离只能产生候选，拒绝理由必须与对象一起保存。

### 6.6 最终一致性

| 指标 | 结果 |
|---|---:|
| 初始 digest | `39bfb56a76713c0345aa2f37a13c6906ec8b503bf781b311620e9c56da201310` |
| 最终 digest | `39bfb56a76713c0345aa2f37a13c6906ec8b503bf781b311620e9c56da201310` |
| digest 是否恢复 | 是 |
| 最终对象数 | 17 |
| 最终 active 对象数 | 17 |
| 最终 superseded 对象数 | 0 |
| 悬空 parent | 0 |
| 悬空 lineage | 0 |
| parent 环 | 0 |
| lineage 环 | 0 |

审计记录共 9 条：1 次 `set-parent`、1 次 `reject-cycle`、1 次 `split`、2 次 `merge`、4 次 `undo`。

## 7. 对生产设计的建议

1. 父关系默认输出 `candidate / ambiguous`，不要因为边框、包含关系或距离近就直接写 `verified`。
2. 把“视觉容器”和“可成为父节点的角色”分开记录；外层装饰框可以是视觉容器，但不能自动成为父节点。
3. 边框证据至少同时看周界覆盖率和对比度；被遮挡的边框不能被当成完整边框。
4. 重复结构（等距 band、重复行）可以提升分组的候选强度，但不能自动证明每一行的父节点。
5. 共享白底和接近距离只能作为弱证据；必须与边框、重复节奏、标题/角色等证据组合。
6. 所有父关系编辑都要记录 `from / to / reason / review_status`，并支持 undo 恢复快照。
7. split/merge 必须先建立 lineage 再重挂子对象；源对象不能直接删除，否则历史不可追溯。
8. 坏合并应保留来源、拒绝理由和 gutter 证据；结构可执行不等于语义可接受。

## 8. 限制与未覆盖

- 只有一个 1200×900 的合成页面，不能外推到真实站点或任意 Figma 文件。
- 对象框是分析者 seed；没有验证自动分割、目标检测或 OCR。
- 标题和文本语义没有做 OCR；`role` 是分析者标注，不是从像素自动推断。
- 边框阈值 `0.8` 和对比度阈值 `20` 只在本页校准，不能作为通用阈值。
- 没有测试响应式布局、缩放、DPR 变化、深色模式或字体替换。
- 没有测试多页、滚动中间态、懒加载、动画和遮挡的复杂组合。
- 没有执行 Figma API 写入；ledger 是受控不变量模拟，不是生产编辑链。
- split/merge 的几何切分由分析者指定，没有验证自动切分质量。

## 9. 不得宣称

- 不得写“截图分组已经解决”或“父关系已经验证”；本实验只有 5 个 `candidate`，其余 11 个仍是 `ambiguous`。
- 不得写“有边框就能确定父子关系”；`obj-band` 正是反例。
- 不得写“白色 gutter 可以证明两栏应分开”；naive gap merge 仍然把主栏和侧栏合并。
- 不得写“`0.8 / 20` 是通用边框阈值”。
- 不得写“split/merge 已通过生产 Figma 验证”；本实验只验证 ledger 不变量。
- 不得把本页结论外推到真实站点、自动 CV 分割或 Figma 实际编辑操作。

## 10. 证据文件

| 文件 | 内容 |
|---|---|
| `output/_r3_experiments/exp07_grouping_probe.py` | 可复现实验脚本（截图、证据、基线、ledger、overlay） |
| `output/_r3_experiments/exp07_grouping.json` | 完整结果：逐对象证据、判定、基线、编辑场景和审计记录 |
| `output/_r3_experiments/exp07_grouping_site/index.html` | 受控页面 |
| `output/_r3_experiments/exp07_screenshot.png` | 原始截图 |
| `output/_r3_experiments/exp07_ground_truth.png` | ground truth 关系 overlay（仅评估） |
| `output/_r3_experiments/exp07_candidate_parents.png` | 候选父关系 overlay |
| `output/_r3_experiments/exp07_naive_containment.png` | 最小容器基线 overlay |
| `output/_r3_experiments/exp07_contact_sheet.png` | 四图对照 |

复现命令：

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe output/_r3_experiments/exp07_grouping_probe.py
```
