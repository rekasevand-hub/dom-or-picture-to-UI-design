# P1 执行态、比较结果与 S07 条件候选

> 状态：`implemented-current-scope`，2026-10-20。旧 strict/content 基线冻结；本文件记录两轴合同及后续独立 scope，不把新 profile 结果称为旧 strict 提升，也不是生产验收或 `verified`。

## 1. 冻结旧基线

- round3 原始分母仍为 7：strict `3/7`，content `5/7`，blocked `2/7`。
- 历史矩阵保留在 `output/_p1_dual_sidecars/real_pair_matrix_round3.json`。
- 新 profile 不修改旧 strict gate、不删除失败样本，也不改变旧矩阵。

2026-10-21 导师确认产品转向：

- 主目标改为固定 Chromium canonical 环境下实际 SVG/Figma 输出保真；
- 旧 full-visible strict 保留定义、样本和失败归因；
- 受控旧 strict case 作为硬回归，动态真实站点结果作为持续观测；
- 实时 `3/7` 不再作为产品发布或退步硬门禁；
- 跨浏览器辅助 scope 优先 rendered-frame-boundary，first-party 只作诊断。

详见 `P1_CANONICAL_OUTPUT_FIDELITY.md`。

## 2. 两轴合同

新 profile `p1-capture-outcome/1.0` 分开记录：

| 轴 | 值 | 含义 |
|---|---|---|
| execution | `ready` | 两端都有证据，导航与稳定状态足以比较 |
| execution | `navigation-failed` | 预期非空目标在预算内未完成导航 |
| execution | `state-unstable` | 没有共同稳定参考状态 |
| execution | `capture-failed` | 截图、DOM、sidecar 或执行失败 |
| comparison | `equivalent` | 当前显式 profile 范围内相等；claim 必须带 scope |
| comparison | `different` | 执行 ready，且在范围内观察到差异 |
| comparison | `inconclusive` | 执行未 ready，不能声明不同或相等 |
| comparison | `out-of-scope` | 留给后续显式新 scope |

`different` 不因有合理解释而变成 `equivalent`。opaque frame 的边界证据只支持边界比较，不证明内部内容相等。

## 3. `about:blank`

`about:blank` 本身是 `blank-document`。只有同时满足：

- 合同要求进入非空目标；
- 导航预算耗尽；
- 最终仍为空白文档；

才标为 `browser-navigation-failed`。单次 `domcontentloaded` 重导航仍是采集策略，不是通用解释。

## 4. 轮次接受规则

- 首次满足 execution ready 的成对采样立即接受，无论结果是 equivalent 还是 different。
- 保留此前所有 attempts。
- 不因后续轮次更容易通过而替换首次 ready 结果。
- 两端必须来自同一 attempt，不能分别挑不同轮次的最佳状态。
- 只有 execution 未 ready 时才继续重试。

代码入口：`scripts/p1_dual_browser_capture.py`，schema `p1-dual-browser-capture/1.5`。

## 5. 新 profile 实测

报告：`output/_p1_dual_sidecars/real_pair_matrix_outcome_round1.json`。

| 样本 | execution | comparison | 说明 |
|---|---|---|---|
| S01 | `state-unstable` | `inconclusive` | 4 次均无共同稳定状态；保留动态广告和 frame 差 |
| S02 | `ready` | `equivalent` | 第 1 次 capture-failed，第 2 次 ready |
| S03 | `ready` | `different` | 同源 frame 内容可见范围不同，477/327 文本 |
| S04 | `ready` | `equivalent` | 1415/1415 节点、529/529 文本 |
| S05 | `ready` | `different` | 文本可对齐，但 frame/node/structure 不同 |
| S06 | `navigation-failed` | `inconclusive` | 第 1 轮预算内 WebKit 仍空白，按规则继续到第 4 轮仍未 ready |
| S07 | `ready` | `different` | 两端均登录页；WebKit 缺 4 条登录方式文案 |

新 profile 汇总：equivalent `2`，different `3`，inconclusive `2`。这是在“首次 ready”规则下的独立结果，不能与旧 strict `3/7` 直接比较，也不能写成旧 strict 提升或下降。

后续新增的 `rendered-frame-boundary-strict/1.0` 是另一个独立比较 scope，有自己的 3-sample 分母；它不会改写上面的 7-sample outcome 矩阵。详情见 `P1_RENDERED_FRAME_BOUNDARY.md`。

## 6. S07 条件探针

`scripts/p1_engine_condition_probe.py` 使用 3 次重复 × 4 条件，共 12 个有效会话：

- `chromium-native`
- `webkit-native`
- `chromium-with-webkit-ua`
- `webkit-with-chromium-ua`

结果文件：`output/_p1_engine_conditions/s07_condition_probe.json`。

四个目标文案在 Chromium 两种 UA 条件下均稳定出现，在 WebKit 两种 UA 条件下均稳定缺失。交叉 UA 没有复现切换。

当前归因：`engine-conditioned-candidate`。`confirmed_root_cause=false`。这仍可能是 engine、feature detection、平台分支、站点分组或未记录条件，不能直接写成“浏览器能力差已确认”。

补充观测：

- Chromium 与 WebKit 都报告 `PublicKeyCredential=true` 和 conditional mediation 可用，但 WebKit 没有 passkey 文案。
- WebKit 的 `PasswordCredential=false`，Chromium 为 true；这只是后续 feature-detection 候选。
- language、timezone、cookieEnabled 和 CSS `:has()` 在两端相同。

后续 feature-shim round2/3 分别在并发和单 worker 下重试，均只有 1/21 有效会话，其余被 GitHub 导航失败阻断。因此当时 feature-conditioned 归因仍为 `unresolved`。

2026-10-20 后续 native 导航门恢复后做了 round4 小批复测：

- Chromium/WebKit native 均 HTTP 200、`navigation=ok`；
- round4 1 repeat × 7 条件，7/7 有效；
- Chromium `password-credential-off` 与 `conditional-mediation-off` 四项文案仍存在；
- WebKit `password-credential-on` 四项文案仍缺失；
- `feature_dependency_candidate=false`，继续只保留 `engine-conditioned-candidate`。

文件：`output/_p1_engine_conditions/s07_condition_probe_round4.json`。

### 6.1 S06 导航时间线

S06 使用独立 `scripts/p1_navigation_timeline_probe.py`，不混入 frame scope：

- WebKit 在 `15015ms` 记录 `document-request-failed: Load request cancelled`；
- 最终仍为 `about:blank`，无 document response 或 commit；
- Chromium 未留下可比较 page_state；
- 分类为 `navigation-failure`，不是稳定 DOM 差异；
- 外层 360s 超时后恢复部分 capture/sidecar，报告标记 `diagnostic_incomplete=true`。

报告：`output/_p1_navigation_timeline/s06_timeline_round1.json`。

2026-10-21 补了轻量 `scripts/p1_navigation_only_probe.py`，不生成 DOM/截图/sidecar：

- 2 attempts × Chromium/WebKit，4/4 observation 有效；
- 第 1 attempt 两端 HTTP 200、`navigation=ok`、readyState complete，主分类 `navigation-comparable`；
- 第 2 attempt 两端均为 `browser-navigation-failed/about:blank`；
- Chromium 第 2 attempt 记录 `net::ERR_TIMED_OUT`；
- `later_navigation_failed=true`，但不替换第 1 attempt；
- `dom_difference_evaluated=false`、`stable_dom_difference_claimed=false`。

报告：`output/_p1_navigation_only/s06_round1.json`。

round2 使用同一 2×2 预算：

- primary attempt 是 `capture-failure`：Chromium worker timeout；WebKit navigation timeout；
- 第 2 attempt 两端恢复 HTTP 200、`navigation=ok`；
- `later_navigation_recovered=true`，但主结果不改成 navigation-comparable；
- `dom_difference_evaluated=false`。

报告：`output/_p1_navigation_only/s06_round2.json`。

### 6.2 S01 generation drift 审计

对已有三个 S01 scope 的 9 个 attempts 做只读审计：

- capture failure `3`、execution instability `5`、navigation failure `1`；
- 没有任何双端稳定参考，primary generation-drift `0`；
- boundary scope 三个 attempts 均观测到 generation drift（5/5/4 paths）；
- execution instability 优先，不能把 generation drift 写成已确认根因。

报告：`output/_p1_s01_generation_drift/s01_round1.json`。

## 7. 测试与边界

- 全量 unittest `173/173` 通过。
- 覆盖执行态/比较结果、首次 ready 选择、blank-document 条件分类、无效 worker 不计缺失、导航 context 重试、boundary scope claim/opaque unknown、document generation、部分时间线恢复、authored holdout 与 navigation-only 主 attempt 保留。
- 条件探针每个 worker 独立进程并有硬超时；失败 worker 标 `valid=false`，不会被当成目标文案缺失。
- 该合同轮本身未实现新 scope；后续 `rendered-frame-boundary-strict/1.0` 已作为独立实验补入；生产存储/TTL 与 Figma 写入仍未实现。

## 8. 下一步

1. 以 `P1_CANONICAL_OUTPUT_FIDELITY.md` 为主计划，首轮 SVG 3/3 已建立，继续补 SVG/Figma 四维验收。
2. 视觉阈值必须在独立 canonical 样例上标定，不能沿用合成实验阈值。
3. 旧 strict 拆成受控硬回归与真实站点观测，不再追动态计数。
4. S06/S07/S01 诊断只在 canonical 输出阻塞时继续。

## 9. 不得宣称

- 不得把新 profile 的 equivalent 数写成旧 strict 提升。
- 不得把 `different` 写成 `inconclusive` 或 `navigation-failed`。
- 不得把 `about:blank` 无条件写成导航失败。
- 不得把 engine-conditioned candidate 写成已确认浏览器能力差。
- 不得用 placeholder 或完整 URL 相等证明 opaque frame 内部内容相等。
- 不得把 `rendered-frame-boundary-equivalent` 写成整页等价。
- 不得把 S07 feature-shim 未改变结果写成已确认 feature 或浏览器能力根因。
