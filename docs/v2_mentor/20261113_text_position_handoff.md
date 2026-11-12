# 第 7 项：文字定位（2026-11-13）

**性质：** 行为变更（新增一条校准策略），已端到端验证。
**承接：** `20261112image to Figma-handoff.md` §7「下一步：文字定位（dx 两簇）」。
**环境：** `C:/Users/lzq/.conda/envs/omni/python.exe`；bridge `ws://localhost:8765`（本轮运行期间在线）。
**本轮没有改门禁阈值、没有为任何一族加常量、没有重新引入金稿旁路。**

---

## 0. 速览

四组都在**同一份冻结感知**上做了 A/B：`before` 是把 `text-positions` 策略临时摘掉（`git stash` 该文件）重跑的结果，`after` 是带上策略的结果。除这一条策略外两侧代码完全相同。

| 组 | within30 | Δ | critical | native | Δ |
|---|---|---|---|---|---|
| dark-card-grid | 94.73 → **95.49** | +0.76 | 27/27 | 1/30 → **10/30** | **+9** |
| light-form | 92.20 → **92.21** | +0.01 | 24/24 | 30/33 → 30/33 | 0 |
| light-table | 95.35 → **95.60** | +0.25 | 30/30 | 36/59 → **48/59** | **+12** |
| **holdout #4** | 94.46 → **94.80** | +0.34 | 18/18 | 4/18 → **12/18** | **+8** |

四组全部上升，没有一组回归。holdout 的 native 从 4/18 到 **12/18**，与 §7 的预估一致。三族门禁 PASS；holdout 仍是 `blocked-fail`（native 要求 100%，剩 6 条不是定位问题）。

---

## 1. 取证：三个问题，答案推翻了文档里的假设

新增只读探针 `scripts/p1_text_position_probe.py`，在同一份冻结帧上量三件事（`--run-dir` 即可复现）：

| 问题 | 结论 |
|---|---|
| ① 元素框左侧 padding（`reference run x − element x`） | **不是 per-container 常量**：同一张卡（`reference-panel`）里 10 个 label 分别是 2、4、5、5、6、6、6、6、7、**13**，极差 11；`aside` 里是 −1、−1、1、4 |
| ② 渲染节点到墨迹左沿（Figma 行内留白） | 基本恒定 **≈1 px**（96pt 标题是 8，属字形边距） |
| ③ 同容器内是否恒定 | **否**。所以 §7 设想的「一个 per-container 常量」不成立，必须逐元素 |

holdout 的两簇其实是同一件事的两端：

| 元素 | element.x | 参考墨迹 x | 渲染墨迹 x | slack | bearing | dx |
|---|---|---|---|---|---|---|
| `请求编号` | 267 | 273 | 268 | 6 | 1 | **−5** |
| `处理进度` | 238 | 244 | 239 | 6 | 1 | **−5** |
| `内容完整性检查` | 1298 | 1298 | 1300 | 0 | 2 | **+2** |
| `访问环境验证` | 1298 | 1297 | 1299 | −1 | 1 | **+2** |

`dx = bearing − slack`。左区框里带 6px 左内边距，右区框是紧的，而发射端一律把文本放在框原点，于是左边偏 −5、右边偏 +2。

**为什么不能用 `styleEvidence.ink_bbox` 当目标**：它在 holdout 上是紧的（与门禁 `referenceInkBBox` 差 ≤1px），但在 light-table 的表头单元格上，它与元素框的偏移是 30–95px、dy 23–29px（那是整格框）。照它平移会把整族推歪。所以新量具**直接从参考图在元素框内找最左的字形 run**，不读 `ink_bbox`。

---

## 2. 实现

### 2.1 量具：`_text_run_box()`

由 `_text_run_width()` 重构而来（后者现在只是取 `[2]`，宽度语义逐位不变，`test_ink_convergence_band` 全过）。窗口、阈值 60、去掉贯穿细带、只取最左一段，全部沿用 §13.3 的三道闸；新增的是：**纵向只在那一 run 自己的列范围内取**，邻居压不进来。

同一把尺子量两侧（参考图与导出帧），窗口都是元素框，所以差值是纯平移，不是两套仪器的差。

### 2.2 校准：`calibrate_text_positions_from_render()`

只对 `type == "text"`；四条守卫，任一不过就记原因跳过：

| 守卫 | 挡的是什么 | 现场命中 |
|---|---|---|
| run 宽 ≥ 0.6 em（两侧都要） | 笔画残片、表格线 | `系统运行正常`（参考 run 只有 7px，低对比） |
| 两侧墨高差 ≤ max(3, 0.3 em) | 量的不是同一 run | 本轮 0 |
| \|dx\|,\|dy\| ≤ 0.75 em | 窗口抓到了邻居/图标/另一行 | 本轮 0 |
| 两侧都要有墨迹 | 渲染侧丢字 | `< 1 分钟`（渲染无一像素） |

### 2.3 接线：策略 + 分组

| 位置 | 改动 |
|---|---|
| `calibration_strategies.py` | 新增 `_text_positions` runner；新增分组 `text-positions`（`render_suffix=figma_positioned`），排在 **`font-tone` 之后** |
| 门控 | `residuals=("position",)`，不设 region 门（`regions=()`）：position 残差为 0 的页面整组跳过，不额外渲染 |

排在最后是因为字号和字重都会移动墨迹框，先量到的平移会过期。无调整时组不渲染——四组各只多付一次渲染。

---

## 3. 结果

### 3.1 holdout #4（同图同缓存）

17 条被平移，2 条被守卫拒绝：

```
CONTENT REVIEW CENTER (+5,-2)   内容完整性检查 (-1,+2)   请求编号 (+4,0)
内容正在审核中 (+5,-1)          风险特征识别 (-2,-3)     REQ-OIBFZVUES (+5,0)
系统正在对当前内容… (+4,-1)      访问环境验证 (-2,-6)     处理进度 (+5,+1)
© 2026 内容安全协议 (+5,0)       90% (+4,-2)              44 (+2,-3)
```

12 条 native 翻过：

| 指标 | 修前 | 修后 |
|---|---|---|
| within30 | 94.46 | **94.80** |
| critical | 18/18 | 18/18 |
| native | 4/18 | **12/18** |
| position 失败 | 12 | **1** |

剩下 6 条，**没有一条是定位口径问题**：

| owner | 还差什么 |
|---|---|
| `系统运行正常` | position+size，dy=−6。参考侧低对比，run 只有 7px，被守卫拒绝（宁可不修，不瞎修） |
| `内容正在审核中` | 只剩 edgeF1（96pt 大标题，字族差异，§6.3 已知） |
| `检查状态` | 只剩 coverage 0.59（Noto Sans SC 字形不如参考饱满，§6.3 已知） |
| `REQ-OIBFZVUES` | 只剩 size（拉丁加粗变宽，§14.4 已知） |
| `系统正在对当前内容…` | 四个维度全过，owner 仍判 fail（段落类 owner 的 status 汇总口径，待查） |
| `< 1 分钟` | `failed-missing-rendered-ink`：渲染帧里该框内一个墨迹像素都没有，是发射/遮挡问题 |

### 3.2 三族（同一套代码、冻结感知，A/B 见 §0）

| 族 | within30 | Δ | native | 平移条数 |
|---|---|---|---|---|
| dark-card-grid | **95.49** | +0.76 | 10/30（+9） | 30 |
| light-form | **92.21** | +0.01 | 30/33（0） | 23 |
| light-table | **95.60** | +0.25 | 48/59（+12） | 56 |

三族 gate 全 PASS，critical 全满。dark 与 light-table 的 native 各涨 9–12 条，说明这两族此前那批 position 失败确实是同一口径问题（dark 的 37 条 position 失败降下来了）。

一处要记账的诊断量：light-table 的 `dy_med` 从 5.9 升到 **6.2**。该族表格正文有 56 条在 y 上被 −2 拉齐（参考图的表格行普遍比渲染高 2px），逐元素对齐后文字本身更准（within30 +0.25），但「整块行距」与参考的关系变差了一点。这不是回归，是把「逐元素对齐」与「整表原点」两笔账混在一个数里——见 §6 第 1 条。

**顺带发现一处对不上的旧账**：11-12 文档记 light-table 终态 96.33 / 38-59，但用当前代码（不带本策略）重跑只有 **95.35 / 36-59**。差 0.98 不是本项造成的，应该是那之后某次 revert（`fb769ca`）或未留存的运行目录留下的。此项不改，只记录。

---

## 4. 测试

| 范围 | 结果 |
|---|---|
| `tests/v2/test_text_position_calibration.py`（新，12 例） | 12 passed |
| 受重构影响的 4 个文件（ink band / grounding text / weight / compiler） | 65 passed |
| `tests/v2` 全量 | **1522 passed / 8 failed**（基线 1510+8，净增 12，失败项与基线相同） |
| ruff check + format | 4 个改动/新增文件干净 |

新增用例覆盖：双轴平移、对齐不动、run 过短、墨高不符、位移超 3/4 em、渲染无墨、非 text 类型不碰、`_text_run_width` 与新量具宽度一致、右侧邻居不干扰、缺图要报错而不是静默通过。

---

## 5. 复现

```bash
PY="C:/Users/lzq/.conda/envs/omni/python.exe"

# 只读取证（三件事 + 逐条预计平移）
$PY scripts/p1_text_position_probe.py \
  --run-dir output/_p22_position --label holdout4

# holdout 端到端（冻结感知，需 bridge + Figma 插件在线）
$PY scripts/image_figma_mvp.py \
  --image output/_holdout_review/reference.png \
  --truth output/_holdout_review/truth.json \
  --out output/_p22_position \
  --acceptance-policy 2.1 --reuse-prepared

# 三族
$PY scripts/check_benchmark_families.py --rerun --policy 2.1 \
  --out output/_benchmark_families/report_p22.json
```

产物：`output/_p22_position/`（holdout after）、`output/_p22_position_before/`（holdout before）、
`output/_benchmark_families/rerun/`（三族 after）、`output/_benchmark_families/_rerun_ab_before_20261113/`（三族 before）、
`output/_benchmark_families/report_p22.json` / `report_ab_before.json`、
`output/_p1_text_position/light-table.json`（探针中间产物）。

> `_rerun_pre_p22_20261113/` 与 `_rerun_pre_p22_stale_95_27/` 是 A/B 之前的两份同名快照（95.27 / 36-59，内容相同），
> 与本次结论无关，可手动删除。

### 5.1 A/B 是怎么做的

```bash
# before：只摘掉策略文件，其余代码不动
git stash push -- src/app/services/structure/fidelity/calibration_strategies.py
$PY scripts/check_benchmark_families.py --rerun --policy 2.1 --out output/_benchmark_families/report_ab_before.json
# holdout 同理：复制冻结 pipeline 到新目录后 --reuse-prepared
git stash pop
```

两侧用的是同一批 `family.json → pipeline_run` 冻结感知目录，所以差异只来自这一条策略。

---

## 6. 遗留 / 下一步

1. **表格的「整块原点」与「逐元素对齐」是两笔账**：light-table 56 条平移里多数是正文 y −2，文字本身更准（within30 +0.25），但 `dy_med` 5.9→6.2。若同一张表所有行都差同一个 dy，那是表格原点的口径差，应移动表格容器而不是每一行——下一轮先量这个。
2. **`系统运行正常`**：参考侧低对比导致 run 只有 7px。可以先放大窗口或降低阈值到 40 再试，但要先证明不会把那条浅灰分隔线吃进来。
3. **`< 1 分钟`**：渲染帧该框内零墨迹，是发射/遮挡问题，不是定位。
4. **段落 owner 的 status 汇总**：`系统正在对当前内容…` 四维全过仍判 fail，口径待查。
5. Phase 5 结构发射仍是扁平 1 层，未动。

---

## 7. 禁改项（本轮新增）

| 禁改项 | 原因 |
|---|---|
| **不要用 `styleEvidence.ink_bbox` 当平移目标** | 它在表头单元格上是整格框（偏移 30–95px），在 holdout 上却是紧的。用它等于给不同族上不同尺子 |
| **不要给 `text-positions` 加 region 门或 per-family 常量** | 它就是「逐元素对齐」，加 region 门就退回 §7 被否掉的 per-container 假设 |
| **不要把 run 宽 0.6 em、墨高 max(3, 0.3em)、位移 0.75 em 这三条守卫放宽** | 分别挡的是笔画残片、错 run、邻居；本轮 4 条守卫各命中过至少一次 |
| **不要把这组挪到 `ink-convergence` 之前** | 字号/字重都会移动墨迹框，先量的平移会过期 |
| **不要用整体平移 N px 修这一类** | 左区 −5 与右区 +2 会一起坏 |
