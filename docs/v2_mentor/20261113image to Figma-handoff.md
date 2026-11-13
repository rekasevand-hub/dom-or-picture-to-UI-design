# Image → Figma · 交接文档（2026-11-13）

承接 `20261112image to Figma-handoff.md` 的第 7 项，并把「证据可复现」补齐。
**一句话**：holdout #4 的 native 从未过门禁的 4/18 推到 14/18，四组全部 `blocked-fail` 但无一回归；
同时把数字从「手抄」变成「脚本生成 + 运行时戳」。

环境事实：

| 项 | 值 |
|---|---|
| 工作树 | `Worktrees/Figma_auto_agent/feature-precise-agent-router-42955d7d` |
| 分支 | `workbuddy/feature-precise-agent-router-42955d7d` |
| HEAD | `2cb6ffd` |
| 领先 `origin/main` | 113 笔（远端已同步，未推送 0） |
| bridge | 本次交付时**已关闭**（8765 无监听） |
| 插件构建 | `2026-11-11-multiline-rotation`，与 `figma_bridge/code.js` 一致 |

> **工作树漂移警告**：`-65c0bdac` 停在 11-12（`67f1fba`），它的 `output/` 不存在；`-ad32e7da`（当前会话默认目录）停在 11-10。**所有产物与代码以下面这份为准。**

---

## 0. 速览

| 组 | within30 | native-only | critical | native | 起点 native |
|---|---|---|---|---|---|
| holdout #4 内容审核 | 94.80 | 94.76（覆盖 0.7%） | 18/18 | **14/18** | 4/18 |
| dark-card-grid | 95.46 | 95.49（0.1%） | 27/27 | **12/30** | 1/30 |
| light-form | 92.21 | **86.24**（51.3%） | 24/24 | 30/33 | 30/33 |
| light-table | 95.60 | 95.63（1.2%） | 30/30 | **49/59** | 36/59 |

四组 `status` 均为 `blocked-fail`——门禁 2.1 是 fail-closed，要求 scope 内 100% 通过。
**这不是回归，是这一天之前就有的状态；本日只做了「让它离可达更近一步」和「让数字可归因」。**

---

## 1. 本次任务的目标

### 1.1 承接自 11-12

11-12 交接把第 7 项（文字定位）定为下一步：holdout 的 8 个 owner「只差 position」，`dx` 分两簇
（左区 −5、右区 +2），预计修好后 native 从 4/18 到 ~12/18。文档当时给的假设是
「元素框含 padding，是 per-container 常量」。

### 1.2 用户明确指定的四步

在完成第 7 项并提交之后，用户指定按以下顺序继续：

| 步 | 内容 |
|---|---|
| 0 | 固化现场：推分支、写一页 `STATE.md`、数字改由脚本生成、版本接进验收报告 |
| 1 | 补缺失仪器：`native-only` 像素指标，让跨族分数可比 |
| 2 | 清掉三条非字族的机械失败 |
| 3 | 只读结构契约审计（`IMPLEMENTATION_ROADMAP_2026-11-08.md` 的 §7.4 第 1 步），回答「离可编辑还差多少」 |

### 1.3 本日真正的隐含目标

不是「再涨几分」，而是**让下一个接手的人能在 5 分钟内判断这些数字能不能信**。
11-12 的 light-table 96.33 用当前代码复现只有 95.35，缺口 0.98 至今无解释——这是手抄的账。
本日所有仪器类改动都服务于这一条。

---

## 2. 已经完成的内容

### 2.1 第 7 项 文字定位 ✅

**取证结论推翻了 11-12 的假设**：元素框左侧 slack 不是 per-container 常量。同一张卡片里
10 个 label 的 slack 分别是 2、4、5、5、6、6、6、6、7、**13**（极差 11）。真正的规律是

```
dx = 渲染端字形留白 bearing(≈1px) − 元素框左侧 slack
```

左区框内有 6px 内边距所以 −5，右区框是紧的（slack 0 或 −1）所以 +2。
**两簇是同一条口径的两端，不是两种毛病。**

另一条关键否证：**不能拿 `styleEvidence.ink_bbox` 当平移目标**。它在 holdout 上是紧的，
但在 light-table 的表头单元格上是整格框（相对元素框偏移 30–95px），照它搬会把整族推歪。
新量具改为直接从参考图在元素框内找最左的字形 run。

| 判据 | 结果 |
|---|---|
| holdout native | 4/18 → **12/18** |
| holdout position 失败 | 12 条 → **1 条** |
| dark native | 1/30 → 10/30 |
| light-table native | 36/59 → 48/59 |
| light-form | 30/33 → 30/33（不动） |

A/B 口径：同一份冻结感知，只 `git stash` 这一条策略前后各跑一次四组。

### 2.2 修掉 `failed-missing-rendered-ink`（2 例，同一根因）✅

`< 1 分钟`（holdout）与 `项目代码`（light-table）的 readback 节点完好——`visible=true`、
`opacity=1`、填充正确、未被裁剪——但导出帧该框内**零墨迹**。

根因：`paint_order` 的深度用元素框算覆盖关系，而文本框常常是整格。

```
< 1 分钟   元素框 [854, 706, 438, 32]      卡片 [829, 647, 270, 114]
```

438px 的框越过 270px 的卡片，于是卡片算 2 层、文本算 1 层，卡片后画把字盖住。
`项目代码` 同理：框的左边 457 越过表头容器左边 470。

修法：新增 `_unbury_text()`，排在 `paint_order` 之后做局部修复。判据是像素真值——一条文本的
**参考墨迹框**被**后绘的不透明元素**完整覆盖才移动，且只挪到最高遮挡者之后，其余元素相对序不变。
四页全扫正好命中 2 条，零误报。

### 2.3 第 0 步 固化现场 ✅

| 事 | 结果 |
|---|---|
| 推分支 | 已推到 `github.com/rekasevand-hub/dom-or-picture-to-UI-design`，中间一次 502，重试后全部同步 |
| `docs/STATE.md` | 一页纸：四组数字、四条瓶颈、四步计划、禁改项、环境陷阱 |
| `scripts/report_state.py` | 数字块从 `acceptance.json` 现算，写进 STATE 的 marker 之间——不再手抄 |
| 版本握手 | `acceptance.json.runtime` 带 `bridgeBuild / expectedBridgeBuild / buildMatches / gitSha / gitBranch / gitDirty / strategies`；插件与源码不一致**直接拒跑** |

`BRIDGE_BUILD` 在此之前只存在于 `code.js` 与 readback，没有任何代码读过它。现在四组全部
`buildMatches = true`。

### 2.4 第 1 步 native-only 像素指标 ✅（结论比预期更狠）

在 `within30` 之外再算一个剔除位图覆盖区域的版本，两个数并列报。门禁仍读 `within30_pct`，
所以**贴图更多不能换来通过**。

| 页面 | within30 | native-only | 位图覆盖 |
|---|---|---|---|
| holdout #4 | 94.80 | 94.76 | 0.7% |
| dark | 95.46 | 95.49 | 0.1% |
| light-form | 92.21 | **86.24** | **51.3%** |
| light-table | 95.60 | 95.63 | 1.2% |

**light-form 有一半画布是贴上去的裁剪图。** 它的 92.21 不是画得好，是贴得多——那 51% 的像素
根本没参与竞争。**今后跨族比较必须用 native-only 那列。**

### 2.5 第 2 步 三条机械项 ✅

| 项 | 根因 | 修法 | 效果 |
|---|---|---|---|
| `系统正在对当前内容…` 四维全过仍 fail | owner 状态用整串精确匹配，门禁的 `nativeText` 早已改成去空白比较——同一判据两种写法 | 统一为门禁那一条 | holdout **13 → 14/18**，其余三页不动（140 个 owner 里只有 1 个） |
| 宽度死区写死 4% | 门禁容差是 `max(3px, 3%)`，校准比门禁松 1 个百分点 | run ≥ 4em 用 3%，短 run 仍 4%（25px 的 run 上 3% 只有 1px） | 四页共 4 条元素落在缝里 |
| `REQ-OIBFZVUES` 的 size 反复不过 | width→fontSize 不是闭式，是不动点：19pt 量 140px，放大到参考 172，渲染器回 **178**（23.25pt） | 新增 `ink-convergence-second`，按剩余 size 残差门控再量一次 | dark **10 → 12/30** |

**第一次实现踩了一个坑并已修正**：第二遍收敛最初对控件也生效，但按钮的字号不走 `style.fontSize`，
第一遍的修改没到画布，第二遍在**没动的帧**上又乘了一次 1.099（双重校正）——
light-table `展开查询` 19.75 → 21.75、宽度 −20px，丢掉一个 owner。限制成只对 `type == "text"`
后 light-table 回到 49/59。

### 2.6 第 3 步 结构契约审计（只读）✅

四页结果完全一致：

| 指标 | 值 |
|---|---|
| 树深 | **1** |
| FRAME（含根） | **1** |
| Auto Layout 节点 | **0** |
| 孤立顶层叶子 | 41 / 69 / 144 / 164 |
| 单根 Frame | ✅ 四页都是 |
| 真实溢出 | holdout 右栏段落越右边界 3px；dark `Kimi K3` 越下边界 10px |

所以「可编辑」的准确说法是：**不是差四个点，是零，外加两处溢出。**
L1 四项里三项已满足（单根 Frame、原生文字、回读一致），缺的是容器语义。

### 2.7 交接协议 `docs/HANDOFF.md` ✅

三层文档分工：`STATE.md`（现在是什么，每次重新生成）/ `HANDOFF.md`（怎么接力，基本不变）/
`v2_mentor/*.md`（为什么这么判断，只增不改）。含 5 分钟接手清单、三条工作纪律、
20 分钟交付清单、可信度四查。

### 2.8 第 5 族原图入库（**未登记**）✅

`tests/fixtures/holdout5_pending/atomgit-home.jpg`，1920×1008，
sha256 `8a1f4961d204e402049f3e04550d1f58260dfb974f5ad129000e300e83aeb610`。
README 写清登记还缺什么。**登记之前它不参与任何门禁，也不要拿它调参。**

---

## 3. 已修改的文件

### 新增（14）

**源码（1）**
- `src/app/services/rendering/bridge_build.py`

**脚本（4）**
- `scripts/p1_text_position_probe.py`
- `scripts/report_state.py`
- `scripts/audit_structure.py`

**测试（4）**
- `tests/v2/test_text_position_calibration.py`
- `tests/v2/test_buried_text_paint_order.py`
- `tests/v2/test_bridge_build_runtime.py`
- `tests/v2/test_native_only_visual.py`

**文档与夹具（5）**
- `docs/STATE.md`
- `docs/HANDOFF.md`
- `docs/v2_mentor/20261113_text_position_handoff.md`
- `docs/v2_mentor/20261113_instruments_and_mechanics.md`
- `tests/fixtures/holdout5_pending/README.md` + `atomgit-home.jpg`

### 修改（7）

- `src/app/services/structure/fidelity/text_calibration.py`
- `src/app/services/structure/fidelity/calibration_strategies.py`
- `src/app/services/rendering/adapter_base.py`
- `src/app/services/evidence/native_text_quality.py`
- `src/app/services/evidence/image_figma_acceptance.py`
- `scripts/image_figma_mvp.py`
- `tests/v2/test_native_text_quality.py`

---

## 4. 每个文件修改了什么

### `text_calibration.py`

1. **`_text_run_box()`（新）**：由 `_text_run_width()` 重构而来（后者改为取它的 `[2]`，
   **宽度语义逐位不变**）。窗口、阈值 60、去贯穿细带、只取最左一段全部沿用；
   新增纵向只在**该 run 自己的列范围**内取，邻居压不进来。
2. **`calibrate_text_positions_from_render()`（新）**：只对 `type == "text"`，四条守卫——
   run 宽 ≥ 0.6em、墨高差 ≤ max(3, 0.3em)、位移 ≤ 0.75em、两侧都要有墨迹。每条跳过都记原因。
3. **宽度死区分档**：`abs(width_ratio - 1) > 0.04` 改为「run ≥ 4em 用 0.03，否则 0.04」，
   与门禁的 `max(3px, 3%)` 对齐。
4. **`calibrate_ink_convergence_from_render()` 增加 `types` 参数**：第二遍收敛只处理 `text`，
   避开控件的双重校正。

### `calibration_strategies.py`

1. 新分组 **`text-positions`**，排在 `font-tone` **之后**（字号和字重都会移动墨迹框，
   先量到的平移会过期），`residuals=("position",)` 门控，无调整不渲染。
2. 新策略 **`ink-convergence-second`**（独立组，`render_suffix="figma_ink_converged_2"`），
   `residuals=("size",)` 门控。
3. `_ink_convergence()` 支持 `types=("text",)` 过滤。

### `adapter_base.py`

1. **`_unbury_text()`（新）**：`paint_order` 排序后做局部修复，只把「参考墨迹框被后绘不透明元素
   完整覆盖」的文本挪到最高遮挡者之后；空跑返回原列表，所以没有埋字的页面字节不变。
2. **`_is_opaque_fill()`（新）**：判定填充是否真的遮挡（透明填充不算）。
3. `paint_order()` 末尾接上 `_unbury_text()`。

### `native_text_quality.py`

owner 的 `status` 判据与门禁的 `nativeText` 统一为同一个表达式（去空白比较），
删掉原来的整串精确匹配分支。**一个 owner 只能有一个答案。**

### `image_figma_acceptance.py`

1. **`bitmap_regions()`（新）**：从 readback 收集所有 `IMAGE` 填充节点的框。
2. **`native_only_visual_metrics()`（新）**：把位图区域从分子分母同时剔除后重算 within30。
3. 接进报告的 `visual.native_only`；`within30_pct` 与门禁判据**完全不动**。

### `bridge_build.py`（新）

读 `figma_bridge/code.js` 的 `BRIDGE_BUILD` 常量，与本次运行的 readback 比对，
产出 `runtime` 段。`buildMatches` 要求两侧都存在且相等——**未知不等于匹配，也不等于不匹配**
（缺 `code.js` 只告警，不失败）。

### `image_figma_mvp.py`

1. 首次写入后读取 readback 的 build，与源码比对；不一致则在**继续跑 4 轮校准之前**停下，
   报 `blocked-environment`。
2. `report["runtime"] = {...}` 写进 `acceptance.json`。

### `scripts/p1_text_position_probe.py`（新）

只读探针，回答 11-12 交接 §7 的三个问题：元素框左侧 slack、发射位移、同一容器内的差值是否恒定，
并给出逐条预计平移。**不写任何东西。**

### `scripts/report_state.py`（新）

从 `acceptance.json`（holdout）+ 三族 `acceptance.json` 现算数字表，
`--write` 时替换 `docs/STATE.md` 两个 marker 之间的内容。数字只有一个来源。

### `scripts/audit_structure.py`（新）

只读结构审计：树深、FRAME 数、Auto Layout 数、孤立叶子、单根校验、
父 bbox 包含关系、溢出示例、原生文字比、静默丢失数。

### 测试（4 新 + 1 改）

| 文件 | 例数 | 覆盖 |
|---|---|---|
| `test_text_position_calibration.py` | 11 | run 框、四条守卫、跳过原因、幂等 |
| `test_buried_text_paint_order.py` | 7 | 宽框上浮、已在上面的不动、无墨迹证据不动、透明填充不算遮挡、部分重叠不算埋、空跑幂等、其余元素相对序不变 |
| `test_bridge_build_runtime.py` | 8 | 匹配/不匹配/未知、拒跑时机、runtime 字段完整性 |
| `test_native_only_visual.py` | 5 | 无位图时两数相等、全位图时为 null、分母不为零、覆盖比例 |
| `test_native_text_quality.py`（改） | — | 补一条断言：`nativeText=true` 且四维全过时 `status` 必须是 `pass` |

---

## 5. 已运行的测试及结果

### 5.1 全量

```
tests/v2  1542 passed, 8 failed in 88.14s
```

**8 个失败与 11-12 完全同一批，均为既有环境项，与本轮无关：**

| 文件 | 性质 |
|---|---|
| `test_axure_holdout_manifest.py` | 冻结输入哈希 |
| `test_axure_holdout_v2_manifest.py` | 同上 |
| `test_axure_holdout_v3_manifest.py` | 同上 |
| `test_axure_holdout_v4_manifest.py` | 同上 |
| `test_p5_collaboration_race_probe.py` | p5 协作探针（`'failed' != 'completed-for-current-scope'`） |
| `test_p5_partial_release_probe.py` | 同上 |
| `test_p5_permission_takeover_probe.py` | 同上 |
| `test_p5_region_compensation_probe.py` | 同上 |

基线对照：11-12 为 1509 passed / 8 failed / 1 skipped；本日净增 **32 例**（4 个新文件）+ 1 例既有断言收紧。

### 5.2 本轮新增的四个测试文件

```
tests/v2/test_text_position_calibration.py
tests/v2/test_buried_text_paint_order.py
tests/v2/test_bridge_build_runtime.py
tests/v2/test_native_only_visual.py
→ 32 passed in 2.93s
```

### 5.3 静态检查

`ruff check` 与 `ruff format --check` 对全部改动文件干净。
（`native_text_quality.py` 与 `image_figma_acceptance.py` 存在**改动前就有**的格式差异，未整体重排，
避免把 diff 冲成噪音。）

### 5.4 端到端（四组，`--acceptance-policy 2.1`，`--reuse-prepared`）

| 组 | within30 | critical | native | status | buildMatches |
|---|---|---|---|---|---|
| holdout #4（`output/_p25_mech2`） | 94.80 | 18/18 | 14/18 | `blocked-fail` | true |
| dark-card-grid | 95.46 | 27/27 | 12/30 | `blocked-fail` | true |
| light-form | 92.21 | 24/24 | 30/33 | `blocked-fail` | true |
| light-table | 95.60 | 30/30 | 49/59 | `blocked-fail` | true |

三族报告：`output/_benchmark_families/report_p25.json`、`report_p25b.json`（受第二遍收敛影响的两族复跑）。

---

## 6. 当前仍存在的问题

### 6.1 门禁仍然全红（结构性）

四组都是 `blocked-fail`。门禁 2.1 是 fail-closed：scope 内**任一** owner 不过即 blocked。
产品从上线到现在没有过一次绿灯。**这是判据构成的问题，不是缺陷没修完**——
「字族差异」和「渲染缺陷」被塞进同一个 100%。

### 6.2 holdout 剩 4 条（`critical-gate` 14/18）

| owner | 差什么 | 归属 | 可行性判断 |
|---|---|---|---|
| `检查状态` | coverage 0.59 | **字族** | 700 已是 Noto Sans SC 能给的最近档位，CJK advance 不变、面积只多 8–10%，补不上 0.16。**换族才能修** |
| `内容正在审核中` | edgeF1 0.24 | **字族** | 96pt 大标题，尺寸位置都对 |
| `REQ-OIBFZVUES` | size | 拉丁加粗改 advance（§14.4 已知） | 需要字重→宽度联动，第二遍收敛在 holdout 上是 0 调整，没吃到 |
| `系统运行正常` | position + size | **量具** | 参考侧是「绿点 + 文字」同框，窗口把点裁到边，`referenceInkBBox` 两边贴边 → dx=0 是假象。修它要改「跳过不足一字宽的前导 run」，会连带移动 light-form 的 11 条坐标，**为 1 个 owner 动 11 条，尚未做** |

另有 1 条 `diagnostic-only` scope 的失败，不进 critical 门禁。

### 6.3 三族剩余

| 组 | 剩 | 主体 |
|---|---|---|
| dark | 18/30 | 以 coverage 为主（深底浅字的掩码/笔画量具尚未标定） |
| light-table | 10/59 | coverage / edgeF1 为主 |
| light-form | 3/33 | size 1、edgeF1+position 1、position 1 |

### 6.4 结构为零（产品侧最大缺口）

depth 1 / FRAME 1（只有根）/ Auto Layout 0 / 41–164 个孤立顶层叶子。
**每加一条逐元素校准，元素就更散一分，结构发射更难**——这是本日新增的债。

### 6.5 仪器与复现的遗留

1. **`silentDrops` 非零**：设计里有、回读里没有的元素——holdout 1、dark 10、light-form 13、light-table 13。
   尚未取证是「同坐标合并」还是「真丢失」。
2. **`_p25_mech2` 的 `runtime.gitDirty = true`**：该轮跑在 `ba6e752` 但工作区含未提交改动。
   严格说这批数字对应「`ba6e752` + 当时工作区」，不是任何一个干净提交。**这是本日最后一次带 dirty 的运行，之后应以 `gitDirty=false` 为验收前提。**
3. **11-12 文档的 light-table 96.33 / 38-59 用当前代码复现不出**（95.35 / 36-59），缺口 0.98 仍未定位。
   已确认与本日改动无关，只记账。
4. **渲染次数口径**：holdout 实测 **4 次校准渲染 + 1 次初始写入**（`figma` / `figma_font_calibrated` /
   `figma_ink_converged` / `figma_font_tone` / `figma_positioned`），其余组零调整被跳过。
   外部评审说的「13 次」是别的页面（flexweaver 9 次写盘 / 136s）的数据，不要混用。
5. **pytest 临时目录陷阱**：`--basetemp` 指到工作区之外时，teardown 会被沙箱的删除防护拦住并报
   `SystemExit: 1`。统一用 `--basetemp=output/_pytest_tmp`。

### 6.6 未开工

- 校准组的 `reads / invalidates` 依赖声明——`刘治强` 0.96→0.68 这类事故的根因，见 §7.2
- 参考侧测量窗口与节点框解耦（`native_text_quality.py:735` 两侧共用 `measure_box`）
- 笔画比的 em 归一化——`2·面积/周长` 是像素量，成对比较时把字号误差乘进了字重比，见 §7.2
- `container` 拆成「透明 frame + 同级 rect」（`parentId` 管道已通，属语义拆分不属能力建设）
- **设计 IR 的字段注册表**：加一个字段（如 `measuredLines`）要穿 7 个模块 20 处白名单。
  光加 `TypedDict` 不解决——那是运行时转发，静态类型碰不到
- 参考图的单一加载器（当前 **24 个模块各自 `Image.open`**）。注意：合并加载器只省 IO，
  **不修任何测量 bug**——独立性靠窗口，不靠加载次数
- 第 5 族的 `truth.json` 与 `family.json`

---

## 7. 下一步应该从哪里继续

### 7.1 顺序（前三步都不碰门禁阈值，也不碰 holdout #4）

| 序 | 事项 | 为什么排在这 | 验收 |
|---|---|---|---|
| 1 | **第 5 族登记**（truth + family + 冻结感知） | 图已入库但未登记；**继续在 holdout #4 上调参等于自证** | 它能独立跑出四维数字，且不进任何调参回路 |
| 2 | **参考窗口解耦** | 唯一能立刻解释现存假象（`系统运行正常` dx=0）的一项 | 该 owner 的 dx 从「假 0」变成可解释值；三族 native 不回退 |
| 3 | **组依赖声明 `reads/invalidates`** | 先有依赖图，才能安全地减少渲染次数；否则只是把串行换成不可解释的批 | 产出依赖图 + 四组 A/B，within30 降幅 ≤ 0.2 |
| 4 | **笔画比 em 归一化** | 联合求解的唯一前提 | 同帧量字号与字重不再互相污染（可用现有 5 个元素验收） |
| 5 | **`container` 拆 frame + rect（只做第一步）** | Phase 5 唯一一天能落地的入口，且像素不变 | depth ≥ 2、孤立叶子下降、within30 不低于基线 −0.3 |

**第 5 项之所以是「一天」而不是「重构」**：`parentId` 管道早就通了——
`figma_adapter._with_parent()` → `code.js appendToParent()` → 找不到父级抛 `PARENT_NOT_FOUND`。
缺的是语义，不是能力。

**但做第 5 项之前必须先解这个**：~~`code.js` 的 `applyGeometry()` 在 `appendToParent()` **之后**写
`node.x = params.x`（绝对坐标）。父级原点非 0 时这会二次偏移。~~ **以上三条均已实测推翻，
见下方更正块。**

> **11-13 下午更正（勿再按旧文行事）**
> 1. **顺序相反**：`createFrame` / `createRectangle` 都是 `applyGeometry()` 先、`appendToParent()`
>    后（`code.js:340/346`、`480/499`、`513/515`）。
> 2. **spec 的 `x/y` 本来就是父级局部**：根帧建在 `x=22000`，`banner` 的 `x=129` 只有按局部
>    解释才落在画布内。
> 3. **按旧假设给插件加换算的实测结果**：`banner` 被推到 **−21871**（`129 − 22000`），
>    within30 反而 **+0.253**（95.051 vs 94.798）、native 14 → 12，已 revert。
>
> **结论：`code.js` 不需要改。** 真要动是调用方把子项坐标减去容器原点——`_offset_spec()` 已经在做
> （`adapter_base.py:647`）。同时记住：**裸 `_send` 探针不能推断整条流水线的语义**，判据是跑一页
> 比 owner 数，不是探针读数漂亮。

### 7.2 两份外部架构评审：采信什么、改什么、否什么

本日收到两份外部评审（AI Agent 视角 / 视觉 AI 视角）。它们的框图与代码一一对应，是本项目收到的
质量最高的一批外部意见；但数字与处方各有偏差。**下一步 5 件事里有 4 件来自它们**，所以取舍必须留档。

| 提案 | 判定 | 依据 |
|---|---|---|
| 组声明 `reads / invalidates` | **采信**（第 3 步） | `刘治强` 0.96→0.68 不是调错，是影响面没声明。且可**零行为变更**落地：只加声明不改调度，先拿到依赖图再动 |
| 参考侧窗口不随节点走 | **采信，但换构造** | 它提的 `source_bbox ∪ node_box` 在本语料上会吞邻居（表头 `ink_bbox` 是整格，偏移 30–95px）。改成 0.75em 固定 padding（§7.3） |
| 笔画比 em 归一化 | **采信**（第 4 步） | `_stroke_width` 返回 `2.0 * area / perimeter`（4321 行）是**像素量**；成对比较是 `reference_stroke / rendered_stroke`（4680 行），字号误差被乘进字重比；4671 行 `abs(height_ratio - 1) > 0.15` 就跳过是 workaround，不是解耦 |
| `container` 拆 frame + rect | **采信**（第 5 步） | `adapter_base.py:350` 把 `container` 与 `rectangle` 并在一支送进 `create_rectangle`；但 `parentId` 管道已通 → 是语义未分，不是能力缺失 |
| `fontSize` 闭式解 | **否掉** | `REQ-OIBFZVUES` 19pt 量 140px → 按参考 172 放大 → 渲染器回 **178**（23.25pt）。width→fontSize 是不动点，不是公式 |
| 「13 次全帧写入」 | **否掉该口径** | holdout 实测 **4 次校准 + 1 次初始**；而且 `CalibrationGroup` 本身就是批（组内任一策略 `adjusted_count > 0` 才渲染一次）→ 第 3 步不是「建批处理」，是「把手调的组换成按依赖推导的组」，ROI 比它估的低 |
| `TypedDict` 作为 IR | **只采一半** | 它诊断的病灶（一个字段穿 7 模块 20 处）是**运行时白名单**，`TypedDict` 是静态类型，救不了。要塌缩需要字段注册表 |
| 联合求解 | **推迟** | 前提是窗口与 em 都干净。且必须有 `max_iterations` + 回滚槽——`grep rollback\|best_design\|max_iterations` 在 `fidelity/` 下**零命中**，`inset=3` 的「每轮稳定左移 1px」就是没有上界的震荡 |
| 门禁分层（机械 / 字族） | **采信方向，修正预期** | 分层只能合法化 2 条（`内容正在审核中` edgeF1、`检查状态` coverage）；另 2 条（`REQ` size、`系统运行正常` 量具）仍要各自修。**它不是收尾项** |

**两份共同的正确判断，值得单列**：不要为「更像 Agent」引入自主循环。这条流水线的确定性部分是
几何/像素求解，VLM 只该待在感知入口和只读裁判。加「自己判断像不像、自己决定改哪儿」的循环，
等于把可解释的回归换成不可复现的抖动。

**两份共同的盲点**：都假设「做完架构改造，门禁会变绿」。实际不会——`blocked-fail` 是判据构成
问题（字族项混在 100% 里），改造只让内部更干净。**架构改造和门禁分层是两件事，别指望前者顺带
解决后者。**

### 7.3 第 2 步的具体做法（对应 §7.1 第 2 项）

**不要**用 `source_bbox ∪ node_box`——light-table 表头单元格的 ink 框是整格（30–95px 偏移），
并集只会更宽。正确构造是：以元素框中心为基准，向两侧各扩 **0.75em 的固定 padding**，
在该窗口内取最左 run。这样窗口不随节点框收缩，也不会把邻居吞进来。

### 7.4 明确不做

- **不做闭式解**（`fontSize` 闭式一次求解）：已被 `REQ` 反例打掉——19pt 量 140 → 目标 172 → 渲染回 178。
  width→fontSize 是不动点，不是公式。
- **不为字族项调参数**：`检查状态` 的 coverage 0.59 是字族上限，调字号只会更差。
- **不动 `blocked-fail` 的阈值**：要改的是判据构成（机械层 vs 字族层），不是阈值。

---

## 8. 禁止再次修改

### 8.1 本日新增的禁改项

| 禁改项 | 原因（都是实测） |
|---|---|
| **不要用元素框判断「文本是否被背景盖住」** | `< 1 分钟` 的框比它所在卡片宽 168px；用它算深度必然把字埋掉 |
| **不要把绘制深度整体改成按墨迹框算** | 实测四页顺序变化 23 / 53 / 104 / 130 条，文本一次跳 10–20 名，还会把标签抬到网格线上 |
| **不要在 `_unbury_text` 里对没有 `ink_bbox` 的文本猜框** | 没有像素证据就没有判据，猜错等于凭空改绘制序 |
| **不要让第二遍收敛碰控件** | 按钮字号不走 `style.fontSize`，第二遍会在没动的帧上再乘一次 → 双重校正，light-table 掉到 48/59 |
| **不要对短 run 用 3% 的宽度死区** | 25px 的 run 上 3% 只有 1px，会把噪声当残差 |
| **不要把 owner 的 `status` 和门禁的 `nativeText` 写成两个表达式** | 一天的 blocker 就来自这一处——同一 owner 一个 true 一个 fail，怎么渲染都过不去 |
| **不要用 `within30` 跨族比较** | light-form 51.3% 画布是贴图，92.21 与 dark 的 95.46 不可比；用 `native-only` |
| **不要手抄任何数字进文档** | 11-12 的 0.98 缺口、本日 STATE 里 13 vs 14 的自相矛盾，都是手抄的账。用 `scripts/report_state.py` |
| **不要用 SVG 去对门禁** | 门禁读 `export.png`（Figma 真帧）。SVG 只能做秒级预览，两者能力不同 |
| **不要接受 `gitDirty = true` 的运行作为基线** | `_p25_mech2` 就是这种情况，它对应的不是任何一个可复现的提交 |
| **组依赖声明上线时，不要拆掉 `sequential` 对照臂** | 组本来就是「看着上一组的结果调」的；批渲染必然改变数值结果。没有对照臂，就分不清「变好」还是「换了条路」 |
| **不要为 Phase 5 顺手开 Auto Layout** | 金稿 55 个 FRAME 全是 `NONE`，几何已 100% 对齐。强行布局是拿像素稳定性换字段好看 |

### 8.2 沿用 11-12 及更早的禁改项（仍然有效）

| 禁改项 | 来源 |
|---|---|
| 不为任何单族加 `if family == ...` 或手写常量 | 11-12，`grep` 至今零命中，继续守住 |
| 不放宽门禁阈值换通过 | 11-12 |
| 不重新引入金稿旁路（`gold_tree.json` 偷坐标） | 11-12，曾制造 3 个假高分来源 |
| 不拿 `styleEvidence.ink_bbox` 当平移目标 | 本日实测：light-table 表头是整格框（30–95px） |
| 不做「整体右移 5px」这类全局平移 | 会把右区 +2 变成 −3，两簇全 fail |
| 不用元素框当字形框 | 这个教训今天出现第四次：位置（§2.1）、绘制序（§2.2）、字号宽度通道（11-12） |
| 不在 holdout #4 上继续调参 | 感知、装饰、调色板、字号、字重、定位、埋字，七轮都在这张图上 |
| 感知类改动必须固定在冻结产物上做 A/B（`--reuse-prepared`） | 全量跑会重新采样 VLM，方差能盖过被测改动 |
| 一次只动一件事，四组全跑 | 单看一族的好转，八成是另一族在出血（§2.5 第二遍收敛就是实例） |

---

## 9. 补记（03:12）：把 native-only 表也变成生成的

§2.4 那张表当时是手抄的，第二天核对时 dark 写着 95.51、产物是 95.49 —— 0.02，正是 §1.3 想消灭的那类账。表已并入 `report_state.py` 的生成块，并加两条守卫：**块必须等于现算**、**表头只能出现一次**。顺带校正了 STATE 正文三处停在旧结论上的段落（瓶颈 #4 已修、第 1/2/3 项已收口、`FRAME 0 → 1`）。

- 改：`scripts/report_state.py`（`_page` 收 `visual.native_only`；新增 `_native_only_lines()`，覆盖 ≥10% 加粗）、`docs/STATE.md`
- 增：`tests/v2/test_report_state_native_only.py`（8 例）
- 测试：`tests/v2` **1550 passed / 8 failed**（同既有 8 项）
- 提交：`5ebb8d0` 正文校正、`001d606` 表并入、`a16bebf` 删手抄表
- 论证与新增禁改项：`20261113_instruments_and_mechanics.md` §6

**行为变化**：跑完新验收不刷新 STATE，`test_the_committed_block_is_what_the_script_would_generate` 会红，报错里带修复命令。这是故意的。

