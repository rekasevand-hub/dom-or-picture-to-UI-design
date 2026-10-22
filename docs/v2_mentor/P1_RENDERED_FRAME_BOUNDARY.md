# P1 rendered-frame-boundary-strict/1.0 实验

> 状态：`completed-for-current-scope`，2026-10-20。显式实验 profile，不替换旧 `rendered-frame-state-strict/1.0`，不接默认渲染路径，也不是整页等价或生产验收。

## 1. Profile 合同

Profile：`rendered-frame-boundary-strict/1.0`。

身份与拓扑：

- 以 `scope_path` 的可见 frame 位置作为主键；
- 比较 `parent_chain`、`visible_index`、`depth`；
- 不把 URL、`src`、placeholder 或内容 hash 当作唯一身份；
- 同一 URL 出现在不同可见位置时，不自动视为同一 frame。

观测字段：

- 宿主几何：四舍五入后的 CSS `x / y / width / height`，严格相等；
- 可见性：`display / visibility / opacity`；
- sandbox：是否存在、按排序后的 token 集合比较；
- opaque 边界：`same_origin / accessible / opaque_frame / opaque_reason`；
- 文档代次：采集会话内经 `framenavigated` 观测到的零基 commit ordinal；
- 导航阶段：`committed / blank / failed / opaque-boundary / unknown`；
- URL 与 `src`：作为观测属性比较，不作为 frame 主键。

`rendered=false` 的 tracker/隐藏 frame 不进入 boundary 相等分母，但保留在排除项。opaque frame 只比较宿主边界和外部可见属性；其内部 DOM、占位内容与内部状态保持 `unknown/not-observable`，不能由边界相等推断内部相等。

必需观测缺失时失败关闭：

- 文档代次或导航阶段不可见时，本轮不是 `different`，而是 execution `state-unstable` / comparison `inconclusive`；
- `rendered-frame-boundary-strict/1.0` 的唯一相等 claim 是 `rendered-frame-boundary-equivalent`；
- 不得输出整页 equivalent 或 `opaque-frame-content-equivalent`。

## 2. 实现

- `src/app/services/structure/frame_boundary.py`：拓扑优先的 frame boundary snapshot 与字段比较；
- `src/app/services/structure/navigation_timeline.py`：有界文档请求、失败、response、document commit 与 frame generation 证据；
- `scripts/p1_dual_browser_capture.py --rendered-frame-boundary-profile`：显式选择新比较 profile；
- `scripts/p1_rendered_frame_boundary_experiment.py`：full-visible、first-party 与新 boundary scope 的固定预算 A/B；
- `scripts/p1_navigation_timeline_probe.py`：S06 独立导航时间线诊断与部分 sidecar 恢复。
- `scripts/p1_frame_boundary_holdout.py`：确定性 authored holdout，不做网络采集；
- `scripts/p1_navigation_only_probe.py`：不生成 DOM/截图/sidecar 的轻量 navigation-only probe。
- `scripts/p1_s01_generation_drift_audit.py`：只读审计现有 S01 attempts 的稳定性、failure 优先级和 frame generation 差异。

时间线每个 engine/attempt 最多保留 128 个 document 事件，超出后设置 `truncated=true`；只记录 document resource，不记录普通静态资源。

## 3. 固定预算 A/B

S01/S03/S05 使用同一预算：

- 最多 3 次 attempts；
- 页面导航预算 15000ms；
- 截图预算 10000ms；
- 首次 execution-ready 成对结果接受，不挑选后续更容易通过的轮次；
- 三个条件独立分母，均为 3 个样本。

报告：`output/_p1_rendered_frame_boundary/experiment_round1.json`。

| 样本 | 旧 full-visible strict | first-party | rendered-frame-boundary |
|---|---|---|---|
| S01 | `state-unstable/inconclusive` | `state-unstable/inconclusive` | `state-unstable/inconclusive` |
| S03 | `capture-failed/inconclusive` | `ready/different` | `ready/different` |
| S05 | `ready/different` | `ready/different` | `ready/different` |

汇总：

| scope | equivalent | different | inconclusive | 总耗时 |
|---|---:|---:|---:|---:|
| full-visible | 0 | 1 | 2 | 341.501s |
| first-party | 0 | 2 | 1 | 208.453s |
| rendered-frame-boundary | 0 | 2 | 1 | 253.938s |

- first-party 显式阻断 frame document 89 次；
- boundary scope 排除不可渲染 frame 130 次；
- boundary scope 记录不可观测 opaque frame 9 个；
- false equivalence：0；
- whole-page equivalence claim：false。

本表是新实验自己的 3-sample 分母，不是冻结 7-sample round3 的升降。旧 round3 strict `3/7`、content `5/7` 保持不变。

## 4. 样本差异

S01：

- boundary inventory 两端均为 8 个可见 frame，8 个拓扑身份匹配；
- 但 full/first-party/boundary 都没有形成共同稳定 execution 状态；
- 观测到 host geometry、sandbox/opaque boundary、document generation、navigation phase 与 URL 差异；
- 因 execution 未 ready，本轮只能 `inconclusive`，不能写成 three-way `different`。

S03：

- boundary 左/右为 4/2 个可见 frame，共同身份 2 个；
- 差异包含 topology、geometry、sandbox/opaque boundary、document generation、navigation phase 与 URL；
- 仍是 `different`，没有因文本差缩小或 boundary 字段更细而变成 equivalent。

full-visible S03 本轮没有 ready 对：

- attempt 1：两端截图均超时，`capture-failed`；
- attempt 2：WebKit `browser-navigation-failed`；
- attempt 3：WebKit 截图超时，仍 `capture-failed`；
- 按首次可用规则保留 attempt 1 为 audit primary，不拿后续局部成功的状态替换。

S05：

- boundary 左/右均为 4 个可见 frame，共同身份 4 个；
- 拓扑数量相同，但 host geometry、sandbox/opaque boundary、document generation、navigation phase 与 URL 仍不同；
- 第 2 个 attempt 才 execution ready，按规则接受该首次 ready 轮次；
- 结果仍 `different`，并保留动态 glyph 归因。

## 5. S06 导航时间线

报告：`output/_p1_navigation_timeline/s06_timeline_round1.json`。

本轮请求最多 2 个 attempts/Navigation budget 15000ms；外层有界诊断在 360s 超时，未写完整 pair summary。诊断从 attempt 1 的 capture/sidecar 部分产物恢复：

- WebKit：
  - `document-request` 2 次；
  - `document-request-failed` 1 次；
  - failure=`Load request cancelled`；
  - request 在 `15015ms` 失败；
  - final URL=`about:blank`；
  - 无 document response、无 document commit、无 frame generation。
- Chromium：未留下可比较 `00_page_state.json`，不能与 WebKit 构件稳定 DOM 差异对。

归因：`navigation-failure`。本轮没有证明 S06 的稳定 DOM 差异，也不新增全局重试。报告明确标记 `diagnostic_incomplete=true` 和 `recovered_from_partial_sidecars=true`。

## 6. S07 feature-shim 小批复测

先做串行 native 导航门，两个会话均有效：

- Chromium：HTTP 200，`navigation=ok`，valid；
- WebKit：HTTP 200，`navigation=ok`，valid。

随后只做 1 次 repeat × 7 条件的小批 round4：

- 7/7 observation 有效，0 个导航失败；
- Chromium `password-credential-off`：四项文案仍全部存在；
- WebKit `password-credential-on`：四项文案仍全部缺失；
- Chromium `conditional-mediation-off`：四项文案仍全部存在；
- UA swap 仍不改变四项结果。

当前目标归因继续是 `engine-conditioned-candidate`：

- `confirmed_root_cause=false`；
- `feature_dependency_candidate=false`；
- `ua_dependency_candidate=false`；
- 不能把本轮写成已确认浏览器能力差或已确认 feature 根因。

文件：

- `output/_p1_engine_conditions/s07_navigation_recovery_round1/`
- `output/_p1_engine_conditions/s07_condition_probe_round4.json`

## 7. Authored holdout 与 navigation-only（2026-10-21）

### 7.1 Boundary authored holdout

固定 fixture：`tests/fixtures/p1/frame_boundary_holdout.json`。

9 个 case 全部通过：

| case | 预期 | 实际 |
|---|---|---|
| 同 URL 换位 | 不得按 URL 重新配对，URL/src 只作观测差异 | reason 仅 URL/src observation，identity match 仍按路径 |
| 同边界换内容 | boundary 可等价，但 claim 只限 boundary | boundary equivalent，内容 state 不参与比较 |
| opaque placeholder 不同 | 外部边界相同即可做 boundary 比较，内部不可观测 | boundary equivalent，`opaque_contents_observable=false` |
| document generation 漂移 | 不能 boundary equivalent | `frame-document-generation-difference` |
| navigation phase 漂移 | 不能 boundary equivalent | `frame-navigation-phase-difference` |
| 父子双层漂移 | 子 frame 换父级后不能按 URL/局部几何合并 | `frame-topology-difference` |
| sandbox token 顺序 | token 集合相同应 boundary equivalent | boundary equivalent，无 sandbox 差异 |
| 可访问父级 + opaque 子级 | 父级可比较，子级只保留外部边界 | boundary equivalent，opaque 子级不可观测 |
| sandbox opaque 相同 token | opaque 外部边界相同可比较，内部仍不可观测 | boundary equivalent，不比较 placeholder |

汇总：

- case `9/9`；
- content changed 且 boundary equivalent `4`；
- false equivalence `0`；
- page equivalence claim `false`；
- result SHA-256：`61fa3ab334ab322ce9a4d24ac7f5cc3e95668d3944bcb7de8b1553505bc2e8d1`。

报告：`output/_p1_frame_boundary_holdout/result.json`。

该 holdout 只验证 comparator 合同。opaque placeholder 不同时 boundary equivalent 不表示内部内容相等；它只表示被声明的外部边界和观测属性相同。

### 7.2 轻量 S06 navigation-only

`scripts/p1_navigation_only_probe.py` 使用 2 attempts、2 engines、每 engine/attempt 独立 worker、15s navigation budget、800ms settle；不生成 DOM、截图或 sidecar。

本轮 4/4 observation 有效：

| attempt | Chromium | WebKit |
|---|---|---|
| 1 | HTTP 200、`ok`、readyState complete、body text length 1173 | HTTP 200、`ok`、readyState complete、body text length 1153 |
| 2 | `browser-navigation-failed`、`about:blank`；`net::ERR_TIMED_OUT` | `browser-navigation-failed`、`about:blank` |

主分类保留第 1 attempt：

- `classification=navigation-comparable`；
- `later_navigation_failed=true`；
- `dom_difference_evaluated=false`；
- `stable_dom_difference_claimed=false`；
- response `2`、document commit `2`；
- body text length 的 1173/1153 不构成 DOM 差异结论，因为该 probe 不采 DOM。

报告：`output/_p1_navigation_only/s06_round1.json`。

round2 使用完全相同的预算：

- primary attempt 没有 ready 对：
  - Chromium worker timeout，`valid=false`；
  - WebKit navigation timeout，最终 `about:blank`；
- 第 2 attempt 两端恢复为 HTTP 200、`navigation=ok`；
- `later_navigation_recovered=true`，但不替换 primary；
- 主分类仍是 `capture-failure`，不是 navigation-comparable 或 DOM 差异。

报告：`output/_p1_navigation_only/s06_round2.json`。

### 7.3 S01 generation drift 只读审计

来源：`output/_p1_rendered_frame_boundary/experiment_round1.json` 中的三个 S01 scope。

共 9 个 attempts：

- capture failure `3`；
- execution instability `5`；
- navigation failure `1`；
- stable comparable `0`；
- primary frame-generation-drift `0`。

| scope | primary | attempts | 观测 |
|---|---|---|---|
| full-visible | execution-instability | 2 capture + 1 unstable | attempt 1 有 4 条 generation drift path；timeline 两端均 128 events/truncated |
| first-party | execution-instability | 1 capture + 1 unstable + 1 navigation-failure | 没有 matched generation drift path；WebKit attempt 3 未提交 |
| rendered-frame-boundary | execution-instability | 3 unstable | 三个 attempts 分别有 5/5/4 条 generation drift path；timeline 全部 truncated |

full-visible attempt 1 的 generation drift paths：`root/v0/v1`、`root/v0/v2`、`root/v1`、`root/v3`。

关键判断：

- execution instability 优先于 generation drift，5 个不稳定 attempts 不能写成 generation root cause；
- 没有双端共同稳定参考，不能声明 S01 boundary 或 DOM `different`；
- generation 漂移在 boundary scope 的 3/3 attempts 中重复出现，可作为后续因果候选；
- timeline 大量 commit 且多数 full/boundary attempts 达到 128-event 上限，不支持继续扩大全局 retry。

报告：`output/_p1_s01_generation_drift/s01_round1.json`。

## 8. 测试与边界

全量 unittest `173/173` 通过。新增覆盖：

- URL 不作为 frame 主键；
- 可见位置、父链、几何、可见性、sandbox/opaque boundary、代次与阶段比较；
- opaque 内部 state 不参与相等；
- 缺少代次时失败关闭；
- 128-event 有界时间线；
- S06 部分 capture/sidecar 恢复；
- 三 scope 独立分母、profile mismatch 与 false-equivalence 保护。
- authored holdout 九类 scope trap，含父子双层、sandbox token 顺序、混合可访问层级与 sandbox opaque；
- navigation-only 首次 attempt 保留、后续失败/恢复、worker timeout 与复用 observation 重汇。
- S01 failure 优先级、selected attempt 保留与 generation drift path 提取。

仍不做：

- 不接默认渲染路径；
- 不替换或提升旧 strict；
- 不实现生产对象存储/TTL；
- 不写 Figma；
- 不把 boundary equivalent 写成整页 equivalent；
- 不把 opaque 边界相同写成内部内容相同。

## 9. 下一步

1. S01 已确认 execution instability 优先，generation drift 是重复伴随候选；下一步做显式 per-frame generation quiet-window 小实验，不增加全局重试。
2. boundary holdout 已覆盖混合可访问层级与 sandbox opaque；后续增加同一路径的安全边界切换 case。
3. S06 navigation-only 两轮主结果分别为 comparable / capture-failure；不用 later recovery 重选，后续只做小量重复。
4. S07 只有在 native navigation gate 再次双端有效时，才扩大 feature repeat；否则保持 unresolved。
