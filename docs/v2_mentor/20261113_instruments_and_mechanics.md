# 仪器、机械项与结构审计（2026-11-13 后半段）

**性质：** 第 0–3 步（现场固化 / 新仪器 / 三条机械项 / 结构审计）。前两项已完成并验证，第 4 步（第 5 族）只把图存进仓库。
**承接：** `20261113_text_position_handoff.md`（第 7 项 + 埋字修复）。

---

## 0. 现场固化

| 做了什么 | 结果 |
|---|---|
| 推分支 | `workbuddy/feature-precise-agent-router-42955d7d` → `origin`，之前 103 个 commit 只在本机 |
| `docs/STATE.md` | 一页纸：四个数字 + 四条瓶颈 + 四步计划 + 禁改项 + 环境陷阱 |
| `scripts/report_state.py` | 数字块由脚本从 `acceptance.json` 生成，写进 STATE 的 marker 之间，**不再手抄** |
| 版本握手 | `acceptance.json` 新增 `runtime`：`bridgeBuild` / `expectedBridgeBuild` / `buildMatches` / `gitSha` / `gitBranch` / `gitDirty` / `strategies` |

**版本握手为什么值得单独做**：`BRIDGE_BUILD` 一直在 `code.js` 和 readback 里，但没有任何代码读过它。插件加载的是另一个 checkout（`D:/LLM-Data/Figma_auto_agent`），所以「盘上的代码」和「实际渲染的代码」是两件事。现在插件版本与源码不一致会**直接以 `blocked-environment` 拒跑**——在第一次写入之后、五次校准渲染之前，代价是 1 帧而不是 6 帧。

`buildMatches` 的语义：两边都存在且相等才算 true。缺一边是「未验证」，不是「通过」，也不是「不一致」——不会误杀。

---

## 1. native-only 像素指标

`within30` 把「重画的矩形」和「贴上去的裁剪图」算成同一件事，于是贴图多的页面天然占便宜。新指标把位图覆盖区域从分子分母同时剔除（`visual.native_only`，**只读诊断，不进任何门**）。

同一批产物重算，结论比预期更狠：

| 页面 | within30 | native-only | 位图覆盖 |
|---|---|---|---|
| holdout #4 | 94.80 | 94.76 | 0.7% |
| dark-card-grid | 95.46 | 95.51 | 0.1% |
| light-form | 92.21 | **86.24** | **51.3%** |
| light-table | 95.60 | 95.63 | 1.2% |

**light-form 有一半画布是贴图**。它的 92.21 不是"画得好"，是"贴得多"；跨族比较必须用后一列。这也解释了它为什么长期稳稳落在 92 分附近而改动几乎不影响——那 51% 的像素根本没参与竞争。

---

## 2. 三条机械项

### 2.1 `系统正在对当前内容…`：同一个判据，两个写法 ✅

owner 的 `checks` 四维全过、`nativeText=true`，`status` 却是 fail。原因是 `status` 还在用**整串精确匹配**，而门禁的 `nativeText` 早已改用 `_compact_gate_text`（去空白）。段落被发射端折行成 `…更新\n处理状态。`，于是两处给出两个答案。

改成同一个表达式后：holdout native **13 → 14/18**。

### 2.2 `REQ-OIBFZVUES`：宽度死区与门禁容差不一致 ✅（部分）

门禁的 size 容差是 `max(3px, 3%)`，而 `ink-convergence` 的宽度通道死区写死 4%——两者表达的是同一件事。收窄规则：**run ≥ 4 em 时用 3%，短 run 仍用 4%**（短 run 上 3% 只有 1px，是噪声）。

四页扫描，只有 4 条元素落在这条 1% 的缝里（holdout 的 `REQ`、dark 的 `谷时…`、light-form 的两条）。

### 2.3 第二遍收敛 ✅

宽度→字号不是公式而是不动点：`REQ` 在 19px 时量到 140px，按 172 放大到 23.25，渲染器却给出 178。一遍必然留几像素在桌上。

新增 `ink-convergence-second`（`residuals=("size",)` 门控、无残差不渲染）。它带来两个结果：

- dark native **10 → 12/30**（第二遍又调了 7 条文字）；
- light-table **第一次掉到 48/59**——`展开查询` 被二次放大到 21.75，宽度 −20px。

**掉分的原因值得记**：那是个 button。它的字号写在控件自己的字段里，第一遍写进 `style.fontSize` 根本没到画布，于是第二遍在同尺寸的帧上又乘了一次 1.099。这是**双重校正**，不是收敛。

修法：第二遍只处理 `type == "text"`（`types=("text",)` 参数）。控件不参与——它拿不到第二遍的好处，却会吃到双重校正的亏。修完 light-table 回到 **49/59**。

### 2.4 四组结果

| 组 | within30 | native | 变化 |
|---|---|---|---|
| holdout #4 | 94.80 | 14/18 | +1（2.1） |
| dark-card-grid | 95.46 | 12/30 | +2（2.3），within30 −0.03 |
| light-form | 92.21 | 30/33 | 不变 |
| light-table | 95.60 | 49/59 | 不变（2.3 先 −1 再修回） |

**没做的一条**：`系统运行正常`。它看起来是量具问题，实测是**状态点 + 文字同一个框**：参考侧左边有个绿点，门禁的测量窗（节点框 +4）从点上开始，`referenceInkBBox` 两边都被窗口裁到边，dx=0 是假象；而 `text-positions` 的 run 守卫正确地拒绝了把文字吸附到 7px 的圆点上。

要修得让量具跳过"不是一个字宽"的前导 run——但那会让 light-form 的 11 条（首段 1–3px 抗锯齿碎点）一起改变吸附位置。为了 1 个 owner 动 11 条的坐标，不划算。**它现在的位置错误是真的（文字压在绿点上），但修它的代价大于收益，先记账。**

---

## 3. 结构审计（Phase 5 第 1 步，只读）

新脚本 `scripts/audit_structure.py`，量化路线图 §7.5 的指标，不改任何发射逻辑。

四页一致：

```
depth 1    FRAME 0（不含根）    Auto Layout 0    孤立顶层叶子 = 全部节点
```

L1 四项（结构底线）：

| 项 | 状态 |
|---|---|
| 单一根 Frame | ✅ 四页都是 |
| 原生文字 | ✅ TEXT 节点数 ≈ 设计文本元素数 |
| 回读一致 | ✅ 无静默丢弃（节点数 ≥ 设计元素数） |
| 无父子溢出 | ❌ **两处真违规**：holdout 右栏段落越出画布右边 3px；dark 的 `Kimi K3` 越出下边 10px |

「可编辑性」的准确表述现在是：**结构 0，溢出 2 处，其余 L1 已满足。** 这不是"差 4 个点"，是"还没开始"——和 within30 是两条正交的线。

---

## 4. 复现

```bash
PY="C:/Users/lzq/.conda/envs/omni/python.exe"
$PY scripts/image_figma_mvp.py --image output/_holdout_review/reference.png \
  --truth output/_holdout_review/truth.json --out output/_p25_mech2 \
  --acceptance-policy 2.1 --reuse-prepared
$PY scripts/check_benchmark_families.py --rerun --policy 2.1
$PY scripts/report_state.py --write docs/STATE.md
$PY scripts/audit_structure.py --run-dir output/_p25_mech2 \
  --run-dir output/_benchmark_families/rerun/dark-card-grid --json out.json
```

## 5. 新增禁改项

| 禁改项 | 原因 |
|---|---|
| **不要用 `text in native_characters` 判 owner 状态** | 它和门禁的 `nativeText` 是同一判据的两种写法；折行段落会在两处得到两个答案（§2.1） |
| **不要让第二遍收敛碰控件** | 控件的字号不走 `style.fontSize`，第二遍会在没动的帧上再乘一次（light-table −1） |
| **不要用 within30 跨族比较** | 位图覆盖 0.1% 与 51.3% 的两个数不可比，用 `native_only` |

---

## 6. 补记（03:12）：STATE 的数字表不止一张

**被推翻的假设**：「`report_state.py` 上了以后，STATE 里的数字就都是生成的」——不是。它只生成主表，native-only 那张表还留在 prose 里手抄，dark 写着 95.51，产物是 95.49，漂了 0.02。数额小，但和 11-12 的 0.98 缺口是同一类账：没人会去查一个看起来合理的数。

**踩过的坑**：生成块刷新了，正文却停在旧结论上——瓶颈 #4 还在说「口径待查」（§2.1 已修），下一步表还把第 1/2/3 项标成未完成；结构审计那行更典型，STATE 写 `FRAME 0`（工具按**不含根**计）、本交接写 `FRAME 1`（**含根**），同一事实两个数，谁都没标口径，读起来像打架。两层文档矛盾时，读的人会先信 prose，因为它更像人写的。

**处置**：

| 事 | 结果 |
|---|---|
| native-only 表并进生成块 | `_native_only_lines()`；位图覆盖 ≥10% 加粗（`NATIVE_ONLY_BOLD_RATIO`），提示跨族不可比；缺字段降级 `—` |
| 守卫一 | `docs/STATE.md` 的块必须逐行等于 `render_block(collect())`（只忽略时间戳行） |
| 守卫二 | native-only 表头只能出现一次，且在 marker 内——防止手抄表回来 |
| 正文校正 | 瓶颈按 4 个 owner 重写；下一步换成主交接 §7.1 的五步；`FRAME 0 → 1` 并标口径（含根）；L1 补「单根 Frame」 |
| 测试 | `tests/v2` **1550 passed / 8 failed**（新增 8 例，8 个失败仍是既有 axure + p5 环境项） |

代价要说清楚：**跑完新验收不刷新 STATE，守卫一就会红。** 这是故意的——它把「数字过期」从要靠人发现的问题，变成会响的测试，报错信息里直接带修复命令。

**本日第二批新增禁改项**（03:12）：

| 禁改项 | 原因 |
|---|---|
| **不要在 STATE 的 prose 里再放数字表** | 生成块外的表没有守卫，本次就是它漂了 0.02 |
| **不要手改生成块** | 守卫一逐行比对现算结果，手改必红 |

提交：`5ebb8d0` 正文校正、`001d606` 表并入生成块、`a16bebf` 删手抄表。

