# R4-EXP-06 · 重复元素自动配对与歧义标定

> 状态：`completed-for-current-scope`（2026-10-18），不是 `verified`。  
> 范围：12 个受控场景、24 次真实 Chromium 捕获、109 个真实 DOM 观测；验证一对一配对、重复歧义、局部采集与节点 ID 隔离。  
> 证据：`output/_r4_experiments/r4_pairing_calibration.json`、`output/_r4_experiments/r4_pairing_artifacts/`，以及 `r4_pairing_matrix.png`、`r4_pairing_thresholds.png`、`r4_pairing_cases.png`。  
> 边界：页面与卡片内容由作者构造，但 DOM 观测、截图和 8×8 图像签名均来自真实 Chromium 渲染；未修改 `src/`、`figma_bridge/`，未执行 Figma 写入。

## 1. 目的与边界

本实验回答 `R4-O04`：在没有稳定身份、节点 ID 可复用、重复卡片无法区分的情况下，能否用内容与上下文特征做一对一配对，并在无法区分时稳定输出 `ambiguous`，而不是按位置、遍历顺序或节点 ID 强行配对。

本实验验证的是**配对规则与状态输出**，不验证：

- 真实站点上的配对准确率、商品理解或跨语言语义；
- OCR/CV 能否检测到正确元素；
- 感知哈希、CLIP 嵌入或真实资产下载；
- 多页面、无限滚动、持续虚拟复用或网络失败；
- `0.20 / 0.04 / 0.30` 是生产通用阈值。

## 2. 环境与可复现性

| 项目 | 值 |
|---|---|
| 操作系统 | Windows 11（`10.0.26300`） |
| Python | 3.12.0（`C:\Users\lzq\.conda\envs\omni\python.exe`） |
| Playwright / Chromium | 1.62.0 / 151.0.7922.34（headless） |
| Pillow / NumPy / SciPy | 12.2.0 / 1.26.4 / 1.17.1 |
| DPR | 1.0 |
| 场景 | 12（7 calibration + 5 validation） |
| 捕获 | 24（每场景 old/new 各 1 次） |
| 观测 | 109 个真实 DOM 卡片观测 |
| 预期配对 | 46 |

重跑命令：

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe output/_r4_experiments/r4_pairing_calibration.py
```

脚本会重建受控页面、24 张截图、观测 JSON、三张图和主结果 JSON。`content_hash` 在写盘后重新读取并排除自身字段校验；每次重跑因 `generated_at` 改变而得到不同哈希。

## 3. 方法

### 3.1 真实页面与状态

页面包含 12 个场景的稳定/插入/跨栏/近似重复/复制交换/局部采集/缺特征/重排/虚拟复用/近似但不同/多对一/一对多状态。每个场景分别渲染 old 与 new 两版，使用真实 Chromium 的 `getBoundingClientRect()`、`getComputedStyle()`、DOM 文本与截图。

跨栏场景使用两个真实列容器（`left / right`）；其余场景使用真实 CSS Grid。局部采集场景的 old 是全页采集，new 是 `1000×360` 视口、滚动到 `y=210` 的采集。

### 3.2 特征

| 特征 | 计算 | 权重 |
|---|---|---:|
| `text` | 标题与价格拼接后的归一化 Levenshtein 相似度 | 0.40 |
| `image` | 真实截图缩略图裁片的 8×8 RGB 均值签名平均绝对差 | 0.26 |
| `geometry` | 中心距离指数衰减 0.55 + 宽 0.225 + 高 0.225 | 0.09 |
| `role` | 完全相同为 1，否则为 0 | 0.06 |
| `style` | 字号相似 0.45 + 颜色距离 0.55 | 0.04 |
| `order` | 观测序差归一化 | 0.02 |
| `parent` | 父容器相同为 1，否则为 0 | 0.05 |
| `neighbor` | 相邻文本集合 Jaccard | 0.08 |

配对成本：

```text
coverage = 可用特征权重之和
cost = 1 - sum(weight_i * similarity_i) / coverage
```

特征缺失时按可用权重重新归一化，并记录 `coverage`；不把缺失特征当作 0 分。文本相似度 `< 0.35` 时，成本强制不低于 `0.70`，防止几何位置把内容错误项救回来。

图像签名只从真实截图缩略图裁片计算，不读取原始资产，也不是感知哈希或视觉嵌入。

### 3.3 一对一与歧义

- 用 Hungarian 分配保证一对一；一个旧项不能同时占用多个新项。
- 完全相同副本先过 `primary-content-tie`：文本、图像、角色、样式、父容器都近似一致且至少两个候选时，直接输出 `ambiguous`。
- 平局检测发生在位置、顺序和邻接上下文之前；节点 ID、坐标、遍历顺序不能打破身份平局。
- 候选成本差小于 `gap=0.04` 时保持 `ambiguous`。
- 可用覆盖率低于 `0.30` 时输出 `ambiguous / insufficient-coverage`。
- 采集范围外的旧项输出 `not-seen`，不输出 `deleted`。

### 3.4 输出状态

旧项只输出 `proposed-match / ambiguous / not-seen`；新项输出 `matched / ambiguous / unmatched-new`。本实验不产生 `deleted`。

## 4. 场景与结果

| 场景 | 分流 | 预期配对 | 实际 | 结果 |
|---|---|---:|---|---|
| `cal_stable` | calibration | 6 | 6 `proposed-match` | 通过 |
| `cal_insertion` | calibration | 6 | 6 `proposed-match` + 1 `unmatched-new` | 通过 |
| `cal_cross_column` | calibration | 4 | 4 `proposed-match` | 通过 |
| `cal_near_duplicate` | calibration | 4 | 4 `proposed-match` | 通过 |
| `cal_duplicate_swap` | calibration | 2 | 2 `proposed-match` + 2 `ambiguous` | 通过 |
| `cal_partial_capture` | calibration | 4 | 4 `proposed-match` + 4 `not-seen` | 通过 |
| `cal_missing_features` | calibration | 5 | 5 `proposed-match`（1 项 `coverage=0.30`） | 通过 |
| `val_reorder` | validation | 6 | 6 `proposed-match` | 通过 |
| `val_virtual_reuse` | validation | 3 | 3 `proposed-match` + 1 `not-seen` + 1 `unmatched-new` | 通过 |
| `val_similar_but_different` | validation | 3 | 3 `proposed-match` + 1 `not-seen` + 1 `unmatched-new` | 通过 |
| `val_multi_to_one` | validation | 2 | 2 `proposed-match` + 1 `ambiguous` | 通过 |
| `val_one_to_many` | validation | 1 | 1 `proposed-match` + 1 `ambiguous` + 2 个新项 `ambiguous` | 通过 |

合计：46 个预期配对全部提出；4 个旧项 `ambiguous`、6 个旧项 `not-seen`、4 个新项 `ambiguous`、3 个新项 `unmatched-new`。**错误配对 0，漏配对 0，非预期歧义 0。**

## 5. 关键行为

### 5.1 完全相同副本交换

两张完全相同的卡片交换位置后，`dup-a` 与 `dup-b` 的最佳成本都是 `0.0`，候选差为 `0.083009`；由于 `primary-content-tie` 优先于位置和顺序，两侧都保持 `ambiguous`。两张唯一卡片仍以成本 `0.0` 匹配。

### 5.2 跨栏同标题

左右两列各有同标题、同图片的卡片；仅靠文本和图像无法区分。父容器与几何使 4 个配对都以成本 `0.0`、候选差 `0.100001` 通过。仅内容基线在这个场景漏掉 4 项，说明内容特征不能独立承担跨栏身份。

### 5.3 近似重复

同图片、标题 `Blue shirt` 与 `Blue shirt sale` 的两张卡片交换顺序后仍全部匹配。最紧的真实匹配是 `near-1`，成本 `0.083009`、候选差 `0.061233`；当 `gap` 提高到 `0.08` 时，它会被推成 `ambiguous`，因此 `0.04` 保留了约 `0.021233` 的余量。

### 5.4 局部采集

旧状态有 8 张卡片，新状态只采集中间 4 张。4 张被观测到的卡片全部匹配，另外 4 张保持 `not-seen`。没有任何旧项被写成 `deleted`。

### 5.5 缺特征

一张新卡片没有标题、价格与图片；它仍以 `coverage=0.30`、成本 `0.0`、候选差 `0.263115` 匹配，依赖几何、角色、顺序、父容器和邻接上下文。该覆盖率正好落在 `0.30` 门限上，说明缺特征场景的余量很小。

### 5.6 重排

6 张唯一卡片完全重排后全部匹配；最差成本为 `reorder-5` 的 `0.143236`，仍低于 `0.20`。这验证内容特征在顺序和几何大幅变化时仍占主导。

### 5.7 虚拟复用

同一节点 ID 与位置被换成完全不同的商品：旧项最佳成本 `0.315638`，保持 `not-seen`；新内容 `unmatched-new`。节点 ID 基线会错误地把这两项配成一对。

### 5.8 近似但不同与多对一

- `Aurora Lamp` 在同一位置被替换成 `Aurora Lamp XL` 和完全不同的深色资产；成本 `0.268759`，保持 `not-seen`。把 `accept` 提到 `0.30` 会产生 1 个错误配对。
- 两个旧候选竞争一个新卡片时，`multi-b` 以成本 `0.086343` 获得唯一分配；`multi-a` 保持 `ambiguous / best-candidate-taken`，没有重复占用。

### 5.9 一对多

一个旧卡片对应两个完全相同的新副本时，旧项候选差仅 `0.006343`，命中 `primary-content-tie`；两个新副本都保持 `ambiguous`。

## 6. 阈值扫描

固定 `coverage>=0.30`，扫描 `accept ∈ {0.10,0.15,0.20,0.25,0.30,0.35}` 与 `gap ∈ {0.02,0.03,0.04,0.06,0.08}`：

| 范围 | 零错误单元 | `accept` 平台 | `gap` 平台 |
|---|---:|---|---|
| calibration | 24 / 30 | 0.10–0.35 | 0.02–0.06 |
| validation | 10 / 30 | 0.20–0.25 | 0.02–0.08 |

两个分支共同的零错误矩形是 `accept 0.20–0.25 × gap 0.02–0.06`。推荐值取其中的内部点 `accept=0.20, gap=0.04`：

- `accept=0.15` 会让 `multi-a`（成本 `0.170909`）从 `ambiguous` 变成 `not-seen`，validation 出现 1 个歧义错误。
- `accept=0.30` 会让近似但不同项（成本 `0.268759`）过门，validation 出现 1 个错误配对。
- `gap=0.08` 会让 `near-1`（候选差 `0.061233`）变成 `ambiguous`，calibration 出现 1 个漏配对。
- 选用 `0.20 / 0.04` 时，距离最近错误配对成本约 `0.068759`，距离最近真实匹配的 gap 失败边界约 `0.021233`。

这只是本次 12 个场景上的弱标定；平台很宽，不能据此宣称精确阈值或通用阈值。

## 7. 不变量检查

26/26 检查通过，覆盖：

- 12 个场景、24 次捕获、109 个观测与 PNG 哈希/尺寸；
- 所有观测 bbox 为正、只有作者构造的缺图卡片没有图像签名；
- Hungarian 一对一、`proposed-match` 必须是已分配的最佳候选；
- 0 错误配对、0 漏配对、0 非预期歧义；
- 预期 `not-seen`、`unmatched-new`、旧/新 `ambiguous` 全部正确；
- 复制交换与一对多两侧歧义、局部采集 4 匹配 + 4 未采集；
- 6 个固定随机种子、72 次输入顺序置换，结果状态与提出配对完全一致；
- 随机化所有节点 ID 后结果完全一致，且 `node_id` 不在特征列表中；
- 缺特征覆盖率 `0.30`、同图签名相似度 `1.0`、替换图相似度 `0.186091`；
- 所选阈值在两个分支都为 0 错误；
- 输出中不存在 `deleted`；
- 写盘后 `content_hash` 可复算。

## 8. 基线对照

### 8.1 直接用节点 ID

| 指标 | 值 |
|---|---:|
| 错误配对 | 3 |
| 错误记录 | 8 |
| 漏配对 | 0 |
| 提出配对 | 49 |
| 预期旧项歧义错误 | 4 |
| 新项状态错误 | 4 |

失败集中在：

- `cal_duplicate_swap`：2 个错误配对；节点 ID 跟随对象，但身份已经交换。
- `val_virtual_reuse`：1 个错误配对；同一节点 ID 被复用为完全不同的内容。

结论：**可复用的节点 ID 不能作为身份真值**。

### 8.2 只用文本 + 图像

| 指标 | 值 |
|---|---:|
| 错误配对 | 0 |
| 漏配对 | 5 |
| 非预期歧义 | 4 |
| 非预期 `not-seen` | 1 |
| 提出配对 | 41 |

失败集中在：

- `cal_cross_column`：4 项漏配对；跨栏同标题同图片无法仅靠内容区分。
- `cal_missing_features`：1 项漏配对；缺标题和图片时内容覆盖率为 0。

内容基线不会误配，但会因过度歧义而漏配；上下文特征承担了必要的区分作用，但也会在重复副本上被正确抑制。

## 9. 对生产匹配器的建议

1. 默认输出 `proposed-match / ambiguous / not-seen` 与 `matched / ambiguous / unmatched-new`；不要输出 `deleted`。
2. 始终用一对一分配；不允许一个旧项占用多个新项，也不允许重复提出。
3. 文本与真实裁片签名是主特征；几何、顺序、父容器和邻接只作上下文，不应压过内容。
4. 完全相同副本的平局检测必须先于位置、顺序、节点 ID 和 Hungarian 分配；同级同内容副本必须保持 `ambiguous`。
5. 节点 ID 只可作为调试字段，不得进入特征或身份真值。
6. 采集范围必须显式记录；范围外旧项是 `not-seen`，不是删除。
7. 每个结果记录 `cost / candidate_gap / coverage / features / identity_ties / reason`，便于复核。
8. 缺特征时按可用权重重归一化；覆盖率低于门限时降级为 `ambiguous / insufficient-coverage`。
9. `0.20 / 0.04 / coverage 0.30` 只是本次数据的弱标定，换数据集必须重标。

## 10. 限制与未覆盖

- 页面与卡片是作者构造的受控合成页面，不是真实站点分布；只覆盖 Chromium 与 DPR 1。
- 图像签名是真实截图裁片的 8×8 RGB 均值，不是感知哈希、OCR、CLIP 或通用视觉嵌入。
- 只有 12 个场景、46 个预期配对；没有大规模重复列表、跨语言文本、价格/规格变体或真实商品语义。
- 未覆盖跨页面、无限滚动、持续虚拟复用、图片加载失败动画、网络抖动和多轮更新。
- `partial capture` 的旧状态是全页采集、新状态是视口采集；它验证采集范围语义，不等价于真实多瓦片采集。
- 未覆盖旋转、缩放、遮挡、懒加载中间态与动画相位；这些必须继续由 R4-EXP-03 的状态门隔离。
- 未修改 `src/`、`figma_bridge/`，未执行 Figma 写入；配对器仍是实验脚本，不是生产匹配 API。

## 11. 不得宣称

- 不得写“配对器已在真实站点验证”；本实验是受控页面。
- 不得写“`0.20 / 0.04` 或 `coverage 0.30` 是通用阈值”。
- 不得写“节点 ID 可以作为稳定身份”。
- 不得写“`not-seen` 等于 `deleted`”。
- 不得写“8×8 图像签名等于原始资产、感知哈希或 OCR/CV 检测”。
- 不得把 46/46 写成真实商品配对准确率或生产接受率。
- 不得写“配对器已接入 `src/`、`figma_bridge/` 或已驱动 Figma 写入”。

## 12. 证据文件

| 文件 | 内容 |
|---|---|
| `output/_r4_experiments/r4_pairing_calibration.py` | 可复现实验脚本（页面、捕获、特征、配对、基线、阈值扫描、绘图） |
| `output/_r4_experiments/r4_pairing_calibration.json` | 12 个场景的期望、观测、成本矩阵、结果、基线、扫描与 26 项检查 |
| `output/_r4_experiments/r4_pairing_artifacts/site/index.html` | 真实渲染页面 |
| `output/_r4_experiments/r4_pairing_artifacts/captures/` | 24 张真实 Chromium 截图 |
| `output/_r4_experiments/r4_pairing_artifacts/observations.json` | DOM/截图观测与场景结果 |
| `output/_r4_experiments/r4_pairing_matrix.png` | 跨栏场景成本矩阵 |
| `output/_r4_experiments/r4_pairing_thresholds.png` | accept/gap 阈值扫描 |
| `output/_r4_experiments/r4_pairing_cases.png` | 复制交换、局部采集、虚拟复用、一对多案例 |
