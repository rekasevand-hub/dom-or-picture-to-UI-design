# R4-EXP-03 · 真实滚动、懒加载与动画相位的状态门（受控实验）

> 状态：`completed-for-current-scope`（2026-10-18），不是 `verified`。  
> 范围：1 个合成页面、11 次真实浏览器捕获、7 个状态签名、55 个捕获对、18 项检查；视口 1200×900、DPR 1。  
> 证据：`output/_r4_experiments/r4_state_gate.json`、`output/_r4_experiments/r4_state_artifacts/captures.json`、`state_pairs.json`、`gate_results.json`、`captures/` 11 张真实截图，以及 `r4_state_matrix.png`、`r4_state_pair_matrix.png`、`r4_naive_vs_gate.png`、`r4_state_gallery.png`。  
> 边界：只有一个实验者编写的合成页面；状态签名、探针集合和懒加载位置均由实验者定义。动画通过 Web Animations API 暂停到显式相位，不是实时采样。不覆盖轮播、视频、网络失败、无限滚动或生产状态识别；未修改 `src/`、`figma_bridge/`，未执行 Figma 写入。

## 1. 目的与边界

本实验回答五个问题：

1. 浏览器真实滚动位置能否作为状态签名的一部分，在字段比较前稳定区分状态。
2. IntersectionObserver 驱动的懒加载代次、占位符替换和文档高度变化，能否被识别为状态迁移而不是内容缺陷。
3. 只改变动画相位的两次捕获，能否在字段与像素比较前被阻断。
4. pending 懒加载和滚动进行中的捕获，能否保持 transient，不进入比较。
5. 如果跳过状态门直接逐字段比较，是否会把状态差异报告成大量假缺陷。

实验验证的是**状态门顺序、状态签名覆盖和瞬态拒绝**，不是通用状态识别器，也不是真实站点分布或生产验收器。

## 2. 环境与可复现性

| 项目 | 值 |
|---|---|
| 操作系统 | Windows 11（`10.0.26300`） |
| Python | 3.12.0（`C:\Users\lzq\.conda\envs\omni\python.exe`） |
| Chromium | 151.0.7922.34（Playwright headless） |
| Pillow | 12.2.0 |
| NumPy | 1.26.4 |
| 视口 / DPR | 1200×900 CSS px / 1 |
| 合成页面 | `output/_r4_experiments/r4_state_artifacts/site/index.html` |

重跑命令：

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe output/_r4_experiments/r4_state_gate.py
```

脚本会重建页面、11 张截图、四份 JSON 与四张图；本次完整重跑约 5.8 秒。

## 3. 方法

### 3.1 夹具

- 页面包含 sticky 头部、带动画的 hero、4 张静态卡片、3 个懒加载区块和页脚。
- 初始有 23 个 `data-probe` 元素；每次懒加载提交把 1 个占位符替换为 4 张卡片，净增 3 个探针，探针数依次为 23 → 26 → 29 → 32。
- 懒加载 1/2/3 由各自的 `IntersectionObserver` sentinel 触发；提交后分别出现 `L1–L4`、`M1–M4`、`K1–K4`，并把 `lazy_generation` 推进到 1/2/3。
- 懒加载 2 的占位符高度从 440 px 变为 360 px 的网格，因此代次 2 提交时文档高度从 3112 px 变为 3032 px。
- `__holdLazy(3)` 让代次 3 的 observer 回调停在 pending；`__releaseLazy(3)` 再真实提交。`S04_pending_gen3` 即在此窗口捕获。
- `__setAnimationPhase(ms)` 暂停页面动画并把 `currentTime` 设为显式毫秒值；`S03_anim700` 为 700 ms 相位。
- `__startScrollTo(1500, 1800)` 用 `requestAnimationFrame` 做 1800 ms 的真实滚动；`S06_scroll_transient` 在约 260 ms 时捕获。

### 3.2 捕获协议

每次捕获按固定顺序执行：

1. 读取截图前状态签名 `state_before`。
2. 读取 23–32 个探针的文本、视口/文档 bbox、可见比例、opacity、背景色与 transform。
3. 执行真实 Playwright 截图。
4. 再次读取状态签名 `state_after`。

`stable_during_capture` 定义为 `state_before == state_after`。`transient_state` 为真当且仅当截图前存在 `lazy_pending`、滚动动画标记，或截图期间状态不稳定。该标记只进入状态门，不读取任何探针值。

### 3.3 状态签名与门顺序

状态签名包含：

| 字段 | 含义 |
|---|---|
| `scroll_y` | 浏览器实际滚动位置 |
| `viewport` | 视口矩形 |
| `doc_height` | 文档高度 |
| `lazy_generation` | 已提交的懒加载代次 |
| `lazy_pending` | 已触发但尚未提交的代次 |
| `animation_time_ms` | 探针 A1 的动画当前时间 |
| `animation_play_state` | 动画播放状态 |
| `scroll_animating` | 程序化滚动是否仍在进行 |

状态哈希是上述字段规范化 JSON 的 SHA-256；`mutation_epoch` 只用于记录截图期间是否发生 DOM 变更，不进入状态键。

门顺序固定为：

1. `capture-stability`
2. `transient-flag`
3. `scroll`
4. `content-generation`
5. `layout`
6. `animation-phase`
7. `viewport`

实现中前两项先合并为一次 early return：任一捕获为 transient 时返回 `transient-state`，原因记录为 `capture-unstable`、`lazy-pending`、`scroll-animating` 或兜底的 `transient-capture`。非瞬态对随后依次检查滚动差、懒加载代次、文档高度、动画相位与视口；任一不满足即返回 `state-mismatch`，全部满足才返回 `comparable`。

全部 55 对的门输入字段都只有 `state_key / stable_during_capture / transient_state`，`gate_used_probe_values=false`。实验者的期望状态只在门后用于评估误判，不参与门控。

### 3.4 字段比较与像素比较

门通过后才比较 8 类字段：

| 字段 | 比较方式 |
|---|---|
| `element_set` | 两侧探针 ID 对称差的大小 |
| `bbox_viewport` | 任一坐标差 > 1.0 px 记 1 |
| `bbox_document` | 任一坐标差 > 1.0 px 记 1 |
| `visibility` | 可见比例差 > 0.05 记 1 |
| `opacity` | 差 > 0.02 记 1 |
| `background` | 背景色字符串不同记 1 |
| `transform` | transform 字符串不同记 1 |
| `text` | 共享探针的文本不同记 1 |

像素差在两图缩放到 240×180 后计算：任一通道差 > 2 的像素占比，允许误差为 `0.00005`。

实验合同容差：滚动 1.0 px、文档高度 1.0 px、动画相位 16 ms、bbox 1.0 px、可见比例 0.05、opacity 0.02。它们都是实验合同值，不是通用阈值。

## 4. 结果

### 4.1 总览

| 指标 | 结果 |
|---|---|
| 捕获 | 11 |
| 唯一状态签名 | 7 |
| 捕获对 | 55 |
| 门结果 | `comparable=4`、`state-mismatch=32`、`transient-state=19` |
| 同态重复对 | 4 |
| 同态字段差异 | 0 |
| 同态最大像素差 | 0.000000 |
| 异态/瞬态对朴素字段差异 | 2172 |
| 假可比 / 假阻断 | 0 / 0 |
| 瞬态捕获 | 2 |
| 检查 | 18/18 通过 |

### 4.2 捕获状态

| 捕获 | scrollY | docH | gen | pending | 动画 | stable | transient |
|---|---:|---:|---:|---:|---:|---|---|
| `S00_top` | 0 | 3112 | 0 | - | 0 ms | yes | no |
| `S00_top_repeat` | 0 | 3112 | 0 | - | 0 ms | yes | no |
| `S03_anim700` | 0 | 3112 | 0 | - | 700 ms | yes | no |
| `S01_scroll900` | 900 | 3112 | 1 | - | 0 ms | yes | no |
| `S01_scroll900_repeat` | 900 | 3112 | 1 | - | 0 ms | yes | no |
| `S02_scroll1400` | 1400 | 3032 | 2 | - | 0 ms | yes | no |
| `S02_scroll1400_repeat` | 1400 | 3032 | 2 | - | 0 ms | yes | no |
| `S04_pending_gen3` | 1950 | 3032 | 2 | 3 | 0 ms | yes | yes |
| `S05_scroll1950` | 1950 | 3032 | 3 | - | 0 ms | yes | no |
| `S05_scroll1950_repeat` | 1950 | 3032 | 3 | - | 0 ms | yes | no |
| `S06_scroll_transient` | ~1886 | 3032 | 3 | - | 0 ms | no | yes |

7 个唯一签名来自 4 组同态重复（`S00`、`S01`、`S02`、`S05`）加上 `S03`、`S04`、`S06`。

### 4.3 同态重复

| 左 | 右 | 字段差异 | 像素差 | 状态哈希 |
|---|---|---:|---:|---|
| `S00_top` | `S00_top_repeat` | 0 | 0.000000 | 一致 |
| `S01_scroll900` | `S01_scroll900_repeat` | 0 | 0.000000 | 一致 |
| `S02_scroll1400` | `S02_scroll1400_repeat` | 0 | 0.000000 | 一致 |
| `S05_scroll1950` | `S05_scroll1950_repeat` | 0 | 0.000000 | 一致 |

4 对同态重复在捕获期间均稳定；门全部返回 `comparable`，没有出现误阻断。

### 4.4 异态与瞬态的阻断

32 个 `state-mismatch` 的原因分布：

| 原因组合 | 对数 |
|---|---:|
| `scroll + content-generation + layout` | 16 |
| `scroll + content-generation` | 8 |
| `scroll + content-generation + layout + animation-phase` | 4 |
| `scroll + content-generation + animation-phase` | 2 |
| `animation-phase` | 2 |

19 个 `transient-state` 的原因分布：

| 原因组合 | 对数 |
|---|---:|
| `lazy-pending` | 10 |
| `capture-unstable + scroll-animating` | 8 |
| `capture-unstable + lazy-pending + scroll-animating` | 1 |

`animation-running`、`viewport` 与兜底 `transient-capture` 分支未被单独触发：所有捕获的动画状态均为 `paused`，视口均为 1200×900，且两个瞬态捕获都有具体原因。

`S04_pending_gen3` 与其余 10 次捕获组成 10 对，全部因 `lazy-pending` 阻断。`S06_scroll_transient` 与其余 10 次捕获组成 10 对，全部因捕获不稳定或滚动动画阻断。两者之间的一对同时命中三个原因。

### 4.5 朴素逐字段比较的假差异

如果跳过状态门，对 51 个异态/瞬态对直接做同样的字段比较：

| 字段 | 假差异数 |
|---|---:|
| `element_set` | 390 |
| `bbox_viewport` | 882 |
| `bbox_document` | 330 |
| `visibility` | 540 |
| `opacity` | 10 |
| `background` | 10 |
| `transform` | 10 |
| `text` | 0 |
| 合计 | 2172 |

这表明在本夹具上，绝大多数“差异”来自滚动、懒加载代次、布局位移和动画相位，而不是内容缺陷。门的作用是抑制比较，不是修复、平均或忽略这些差异。

### 4.6 目标现象

**真实滚动。** 目标位置分别为 900、1400、1950、1950；实际 `scrollY` 与目标一致（容差 2 px）。`S06` 在滚动进行中捕获；本次重跑记录约 1886 px，位置会随采样时刻略有变化，不能作为固定断言。

**真实懒加载。** `S01` 出现 `L1–L4`，`S02` 出现 `M1–M4`，`S05` 出现 `K1–K4`；探针数 23 → 26 → 29 → 32。`S04` 保持代次 2、`lazy_pending=3`，没有提前写入代次 3 的内容。

**懒加载布局变化。** 代次 2 提交时文档高度 3112 → 3032（-80 px），对应懒加载 2 占位符 440 → 360 px。该对被 `content-generation + layout` 阻断。

**sticky 元素。** 头部 `H1` 在顶部与 900 px 滚动两态的视口框均为 `[0, 0, 1200, 64]`，但文档框顶部从 0 变为 900。只比较视口坐标会漏掉 sticky 位移；跨状态比较必须先由状态门阻断，或改用文档坐标解释。

**动画相位。** `S00_top` 与 `S03_anim700` 只差动画相位。A1 宽度 56.0 → 369.6 px，背景 `rgb(37, 99, 235)` → `rgb(185, 110, 86)`；A2 opacity 0.35 → 0.8782，transform `scale(0.8)` → `scale(1.12504)`。该对的唯一门原因是 `animation-phase`。

**pending 与滚动中捕获。** `S04` 与 `S06` 分别代表“事件已触发但内容未提交”和“视口正在移动”。两者都被标为 transient；相关 19 个唯一捕获对（`S04` 10 对、`S06` 10 对，其中一对重叠）没有任何一对进入字段比较。

### 4.7 检查项

18/18 通过：

1. `real-scroll`：浏览器实际滚动到目标位置。
2. `real-lazy-load`：IntersectionObserver 真实提交三代懒加载。
3. `real-animation`：动画相位真实改变宽度、背景与 opacity/transform。
4. `state-signature-distinct`：11 次捕获得到 7 个签名。
5. `same-state-hash`：4 对同态重复共享状态哈希。
6. `same-state-stable`：同态重复期间稳定且像素一致。
7. `same-state-fields`：同态重复字段差异为 0。
8. `scroll-blocked`：不同滚动与懒加载代次在字段比较前阻断。
9. `sticky-document-shift`：sticky 视口位置不变、文档位置改变。
10. `lazy-layout-shift`：懒加载代次与文档高度变化被记录。
11. `animation-phase-blocked`：仅动画相位不同也被阻断。
12. `pending-transient`：未提交的懒加载保持 transient。
13. `scroll-transient`：滚动中的捕获保持 transient。
14. `no-false-comparable`：异态/瞬态对误判为可比较 0 对。
15. `no-false-blocked`：同态对误阻断 0 对。
16. `naive-defects-positive`：朴素比较产生 2172 个假差异。
17. `gate-field-independent`：55 对的门输入均不含探针值。
18. `deterministic-gate`：重复过门结果一致，门投影 SHA-256 `fa7cf39de5ccd760…`。

## 5. 解释与边界

### 5.1 可以支持的判断

1. 状态门必须先于字段和像素比较。本实验直接测量了字段层面：跳过门会在 51 个被阻断对产生 2172 个假差异；像素层面只用于同态一致性，不构成本实验的异态假差异统计。
2. 状态签名应包含滚动位置、内容代次、文档高度、动画相位、pending/滚动中标记，并记录视口；这些字段共同把 11 次捕获分成 7 个签名。本实验未做逐字段消融，不能声称每一项都是最小必要集合。
3. sticky 元素不能只按视口坐标解释；视口位置不变不代表文档位置不变。
4. 懒加载会同时改变元素集合、文档高度和可见性，这三类变化不能当作内容缺陷。
5. 同一动画的不同相位不能做字段或像素回归；即使内容完全相同也必须阻断。
6. pending 懒加载与滚动中的捕获必须保持 transient；它们不是“稍微不同”的稳定状态。
7. 状态门只应读取状态签名、稳定标记和 transient 标记，不得读取它要保护的字段值。

### 5.2 不能支持的判断

- 不能宣称已实现通用状态识别器；签名字段和探针集合都是实验者编写的。
- 不能把结果外推到真实站点、轮播、视频、无限滚动、网络失败、媒体查询、zoom 或拖拽。
- 不能把动画相位实验写成实时动画采样、帧率稳定性或掉帧分析；动画是被暂停到显式相位的。
- 不能把 `1.0 px / 16 ms / 0.05 / 0.02 / 0.00005` 写成通用几何、动画或视觉回归阈值。
- 不能宣称状态门已覆盖真实页面的全部状态维度，也不能宣称已验证生产验收器或 Figma 写入。

### 5.3 限制

- 只有一个合成页面，样本量小，且页面结构为实验目的而设计。
- 懒加载由本地 IntersectionObserver 和同步提交驱动，没有网络延迟、失败重试或无限滚动。
- 动画通过 Web Animations API 暂停，不是连续录屏；真实动画的抖动、掉帧和异步合成未覆盖。
- 像素比较在 240×180 缩略图上进行，只用于确认同态重复一致，不是通用视觉回归指标。
- 状态签名没有覆盖轮播、视频、媒体查询、zoom、拖拽、网络状态和多页面导航。
- 没有对状态签名字段做逐项消融，无法判断最小必要集合或各字段的独立贡献。
- 未修改 `src/`、`figma_bridge/`，未执行 Figma 写入；没有生产状态识别或生产验收能力。

## 6. 可写入 2.0 规格的结论

可以写入：

1. 状态门必须先于字段比较和像素比较；异态对不比较、不平均、不修补。
2. 状态签名至少包含滚动位置、内容代次、文档高度、动画相位、pending 标记与滚动进行中标记；签名还应记录视口。
3. 截图前后状态不一致，或存在 pending 懒加载、滚动进行中标记时，捕获必须标为 transient。
4. 同态重复才允许进入字段比较；同态重复应共享状态哈希，并在稳定捕获上得到零字段差异。
5. sticky 元素至少同时记录视口 bbox 与文档 bbox；跨滚动状态不得用视口 bbox 代替文档 bbox。
6. 懒加载代次和文档高度变化属于状态迁移，不是缺陷；必须与元素集合变化一起记录。
7. 动画相位不同即不可比较；内容相同不能覆盖相位差异。
8. 状态门输入不得包含被比较的探针字段，期望状态只能在门后用于评估。

仍不能写入：

- 通用状态识别器或自动状态发现算法；
- 真实站点、轮播、视频、无限滚动、网络失败和跨浏览器规则；
- 通用滚动、动画、可见性、opacity 或像素阈值；
- 生产 IR、生产验收器或 Figma 写入策略。

## 7. 下一步候选

以下仅为候选，本实验不自动开启：

- `R4-EXP-04`：设计生产 IR 的字段级 provenance，并做只读回放验证。
- `R4-EXP-05`：多引擎/多语言矩阵与跨 DPR bbox 可比性标定。
- 后续可单独验证真实站点的轮播、视频与无限滚动状态，以及网络失败下的 pending/transient 语义。

## 8. 产物清单

| 产物 | 路径 |
|---|---|
| 脚本 | `output/_r4_experiments/r4_state_gate.py` |
| 总 JSON | `output/_r4_experiments/r4_state_gate.json` |
| 捕获记录 | `output/_r4_experiments/r4_state_artifacts/captures.json` |
| 捕获对记录 | `output/_r4_experiments/r4_state_artifacts/state_pairs.json` |
| 门结果 | `output/_r4_experiments/r4_state_artifacts/gate_results.json` |
| 截图 | `output/_r4_experiments/r4_state_artifacts/captures/`（11 张） |
| 合成页面 | `output/_r4_experiments/r4_state_artifacts/site/index.html` |
| 状态矩阵 | `output/_r4_experiments/r4_state_matrix.png` |
| 捕获对矩阵 | `output/_r4_experiments/r4_state_pair_matrix.png` |
| 朴素比较对照 | `output/_r4_experiments/r4_naive_vs_gate.png` |
| 捕获画廊 | `output/_r4_experiments/r4_state_gallery.png` |
