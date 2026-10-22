# Round 5 · 未决实验与生产落地清单

> 状态：R5 回答已归档（导师回答日期 2026-10-18）。`R5-Q01–Q06` 均为规格建议；`R5-EXP-01–06` 已全部完成当前范围，但均不代表生产能力已验证。  
> 依据：`ROUND_05_ANSWERS_FORMATTED.md`、`ROUND_05_QUESTIONS.md`、`V2_OPTIMIZATION_PLAN.md` 第 14 节。  
> 边界：未执行前保持 `pending / not-evaluated`；不得写成 `verified`。导师明确未独立核验题内 R4、Smoke、13.4 节及所引 R3 实验正文。

## 1. 总表

| ID | 实验 / 实现门禁 | 对应问题 | 阻塞对象 | 当前状态 | 最低通过条件 |
|---|---|---|---|---|---|
| R5-EXP-01 | 冲突字段默认交付与报告一致性 | R5-Q01 | 冲突交付、`Conflicts / Unknowns` 报告 | `completed-for-current-scope`（见 `R5_EXP_01_CONFLICT_DELIVERY.md`） | 5 类字段 × 5 种冲突场景的画面、清单、manifest 一致；未决值不进入正文 |
| R5-EXP-02 | 写入失败注入、对账与补偿 | R5-Q02 | 生产写入、重试、回滚 | `completed-for-current-scope`（见 `R5_EXP_02_WRITE_FAILURE.md`） | 发送前/执行中/成功后丢响应均能对账；重复创建、越权删除、未知结果误报成功零违例 |
| R5-EXP-03 | DOM / 截图字段权威矩阵 | R5-Q03 | 字段权威、OCR 晋升、z-order | `completed-for-current-scope`（见 `R5_EXP_03_AUTHORITY_MATRIX.md`） | 6 类边界场景按字段类型与状态给出权威；截图不接管不可见来源语义 |
| R5-EXP-04 | 部分交付表达与 coverage map | R5-Q04 | PARTIAL 交付、报告、导出 | `completed-for-current-scope`（见 `R5_EXP_04_PARTIAL_COVERAGE.md`） | 四种空缺可区分；遮罩排除后仍保持 PARTIAL；面积/对象/文字/关键项覆盖分开 |
| R5-EXP-05 | 四维验收硬门禁与页面汇总 | R5-Q05 | 发布门禁、验收报告 | `completed-for-current-scope`（见 `R5_EXP_05_ACCEPTANCE_GATE.md`） | 关键项 fail/unknown 阻断；面积不能抵消硬失败；三种发布口径可复算 |
| R5-EXP-06 | IR 持久化、TTL、迁移与重放语义 | R5-Q06 | 生产 IR、证据保留、恢复 | `completed-for-current-scope`（见 `R5_EXP_06_IR_PERSISTENCE.md`） | 写前持久化、崩溃恢复、TTL 过期、schema 迁移与三种重放语义均有证据 |

## 2. 实验明细

### R5-EXP-01 冲突字段默认交付与报告一致性

**目的**

验证 `winner=null / deferred / skipped / authority-required` 在用户可见画面、报告与 manifest 中不会被混成同一个“没写”。

**最低用例**

- 文本冲突但几何已知。
- 颜色未知的新节点。
- 显隐未知节点。
- 价格待权威确认。
- 旧值遇到 tombstone。

**检查**

- 五种字段类型 `text / color / asset / visibility / geometry` 的默认行为。
- 同一节点无冲突字段是否按依赖闭合局部写入。
- 旧值是否被标 `retained-unverified` 或 `carried-forward-not-seen`。
- `Conflicts / Unknowns` 报告是否包含对象、字段、双方观测、权威缺口、当前显示行为、不可做操作和下一步。

**不得宣称**

- 不得把 `deferred / skipped` 改标为成功。
- 不得把旧值保留写成冲突已解决。
- 不得把候选值加小标记后冒充正文或最终价格。

**执行记录（2026-10-19）**

- 离线确定性层：33 个用例 = 25 个冲突矩阵单元 + 5 个权威控制 + 2 个旧值状态 + 1 个 `skipped` 资产；10/10 合同检查通过，15/15 负向变异被拒绝。
- 状态计数：`written` 5、`winner-null` 5、`deferred` 10、`authority-required` 5、`delete-pending` 5、`retained-unverified` 1、`carried-forward-not-seen` 1、`skipped` 1；28 个未决字段对应 28 个报告条目。
- 连续 2 次运行得到相同 `content_hash`，为 `9ed7aba5d2607594a63664dab29373a26e27ae801e3f0f6ad7d96037dc4bc20f`。
- 状态为实验层面的 `completed-for-current-scope`，不是真实 Figma 交付，也不是 `verified`；不证明用户理解、价格正确或生产冲突解决。

### R5-EXP-02 写入失败注入、对账与补偿

**目的**

验证区域级逻辑提交、写前持久化、写后回读与未知结果对账，而不是只验证一次正常顺序重放。

**最低用例**

- 发送前中断。
- 执行中中断。
- 成功后丢响应。
- 保存后恢复。
- 重复与并发运行。
- 节点重命名、父节点删除、用户修改。
- 字体缺失、资产失败、权限拒绝、限流、导出失败、补偿失败。
- 每个确定性用例至少 3 次，并从不同中断点恢复；另做至少 30 次同 job 重放/断线组合。

**通过条件**

- 重复创建、越权删除、未知结果误报成功三项零违例。
- 归属不明时停止并人工确认，不自动重发。
- 清理只针对本 job 明确创建且未被用户接管的节点。
- 写前持久化失败时不产生 Figma 副作用。

**不得宣称**

- 不得把客户端幂等键写成 exactly-once。
- 不得把补偿写成强事务。
- 不得用全局 undo 回退未知并发操作。

**执行记录（2026-10-19）**

- 确定性层：17 个故障用例 × 3 变体 = 51/51 通过；`duplicate_creates / unauthorized_deletes / unknown_reported_success / preflight_side_effects` 均为 0；30 步同 job 重放最终 `committed`；无锁负控制出现 3 次重复创建，本地锁控制为 0。
- 真实 Figma 层：23/23 检查通过，连续 2 次完整运行通过；A/B/C/D/E/F/G/H 与并发探测均已记录；清理后页面无 `R5-EXP-02` 顶层节点。
- 真实层确认的能力缺口：无服务端幂等键、无可靠 ownership marker、无节点级删除、无 visibility/rename；父节点不存在时 bridge 会把子节点静默挂到 `currentPage`。
- 状态为实验层面的 `completed-for-current-scope`，不是生产写入通过，也不是 `verified`。

### R5-EXP-03 DOM / 截图字段权威矩阵

**目的**

验证系统先区分字段类型与状态，再决定权威，而不是整节点一键切换来源。

**最低用例**

- CSS 大小写变换与计数器。
- canvas 叠字。
- 可访问与不可访问 iframe。
- closed shadow root。
- DOM 隐藏旧文案。
- 水合切换。
- 复杂堆叠上下文。

**检查**

- 原始 DOM 文本、可见文本、CSS 声明色、合成像素色是否分开。
- 伪元素、canvas、iframe、shadow DOM、隐藏文本、截图-only 文本和 z-order 冲突是否按场景矩阵处理。
- OCR 晋升是否只提升 `text-content`，不自动提升 `editability / role / asset_source`。
- `external-conflict / unknown / unsupported` 是否分别记录。

**不得宣称**

- 不得写“DOM 永远负责文本”或“截图接管全部字段”。
- 不得从截图顺序恢复全局 z-order。
- 不得把 OCR 晋升写成恢复原语义或原可编辑性。

**执行记录（2026-10-19）**

- 按正文的 8 个最低条目执行 8 个 authored Chromium 场景，没有为对齐总表“6 类”删减；共生成 50 个字段行和 17 类字段。
- 状态计数：`authoritative 31 / observed 4 / candidate 4 / external-conflict 3 / unknown 5 / unsupported 3`；权威计数：`dom 34 / screenshot 7 / dom+screenshot 3 / none 6`。
- 19/19 合同检查通过，22/22 定向负向变异被拒绝；OCR 只提升 `text-content` 候选或由 DOM 源文本共同确认的内容，`role / editability / asset-source` 始终另判。
- 可访问 iframe 保留子文档作用域；sandbox iframe 的页面 DOM 访问为 `unsupported`，closed shadow 的 descendant 语义为 `unknown`；水合 M0/M1 配对为 `external-conflict`。
- 复杂堆叠场景中，后出现的 low-z context 没有盖住先出现的 high-z context；只记录采样点局部遮挡，`global-z-order=unsupported`。
- 连续 2 次运行得到相同 `content_hash`，为 `e954d75a4db5b5b2a8093d1ca000615b3ffc8e3fe41ef47e9a077f3f89a11edf`。
- 状态为实验层面的 `completed-for-current-scope`，不是跨浏览器、跨站点或生产实现验证，也不是 `verified`。

### R5-EXP-04 部分交付表达与 coverage map

**目的**

验证部分交付不能被误认为完整成品，且遮罩排除不能把缺口变成通过。

**最低用例**

- 同一位置分别制造 `intentional-omission / write-failed / observed-absent / not-captured`。
- 检查用户只看摘要和覆盖图能否区分四种空缺。
- 导出局部 diff 后检查页面仍为 PARTIAL，而不是 100% 通过。

**检查**

- PARTIAL 根名、独立报告、图例与不可做操作。
- coverage map 的 `region_id / 坐标系 / 状态 / 原因 / 证据 / 受影响维度 / 对象键`。
- 面积、对象、文字、关键项四类覆盖分开；重叠面积按并集。
- 诊断占位从 diff 排除时分母不缩小。

**不得宣称**

- 不得把锁定写成安全边界或导出门禁。
- 不得用空白代表所有缺口。
- 不得因为遮罩排除错误而宣称全页通过。

**执行记录（2026-10-19）**

- 4 个同坐标变体：`intentional-omission / write-failed / observed-absent / not-captured`，共用 `price-panel` 缺口矩形 `600×290×500×120`。
- 12 个覆盖区域；面积使用并集 `363,200 px`，区域矩形和 `454,250 px`，重叠 `91,050 px`。已覆盖 `303,200 px`（83.48%）、对象 11/12、文字 127/148、关键项 1/2。
- `not-captured` 保持 `unknown`，`observed-absent` 明确 `not_deleted=true`；四种缺口没有折叠成一个 missing。
- raster 固定分母 `912,000 px`，诊断 mask `60,000 px`，raw diff `60,000 px`，有效对比 `852,000 px`，masked diff `0`；发布状态仍为 `partial`，`complete_export_allowed=false`。
- 19/19 合同检查通过，24/24 定向负向变异被拒绝；连续 2 次运行同哈希 `94f843feb23279dc6b090303f36edd00692b52e7b0c642475b2a9aa9b08e7ea2`。
- 真实锁、手动导出阻断、真实 Figma 报告 Frame 与用户理解均未验证；状态为 `completed-for-current-scope`，不是 `verified`。

### R5-EXP-05 四维验收硬门禁与页面汇总

**目的**

验证页面发布使用合同、关键项与依赖闭包的分层门禁，而不是面积加权或简单取最差项。

**最低用例**

- 对 linebreak、pixel、geometry、parent、boundary、native 分别注入故障。
- 加入 `unknown`、`no-ground-truth`、极小但关键的价格错误。
- 加入高面积、低价值背景通过。

**通过条件**

- 关键项 fail/unknown/未允许 partial 时阻断原合同发布。
- 视觉 pass 不能抵消编辑 fail。
- 非关键缺口可隔离时输出 `deliverable-partial`，但缺口保留在原合同分母。
- 只有全部 required 满足且覆盖充分才输出 `deliverable-complete`。

**不得宣称**

- 不得设通用 95% 或 N 样本及格线。
- 不得把 288/288 写成真实页面精度。
- 不得把未支持浏览器默认为通过。

**执行记录（2026-10-19）**

- 19 个 case × 11 条 canonical checks = 209 条记录；六类故障 `linebreak / pixel / geometry / parent / boundary / native` 均单独注入，外加 asset 与内容检查。
- 209 条状态：`pass 186 / fail 9 / partial 2 / unknown 2 / no-ground-truth 1 / not-sampled 2 / not-required 7`。
- Deliverable：`complete 1 / partial 4 / reference-only 1 / blocked 13`；pilot `allowed-provisional 6 / blocked 13`；production 19/19 为 `not-eligible`。
- 视觉 pass、edit fail 的 native case 仍 `blocked-critical`；tiny price 实际 raster diff 仅 481/912,000 px（0.0527%），仍阻断；高面积背景 pass ratio 99.947% 仍不能抵消关键价格错误。
- 非关键可隔离缺口可产生 `deliverable-partial` 且分母不缩小；未允许 partial、unknown critical、no-ground-truth critical、unsupported browser 和 preflight 失败均阻断。
- 22/22 合同检查通过，30/30 定向负向变异被拒绝；连续 2 次运行同哈希 `b5cd12d49937971250973f9acb830386356ccdd82f2031cf8bccdd87067ac6c5`。
- 本轮验证门禁和汇总逻辑，不标定六类检测器，不证明生产发布。状态为 `completed-for-current-scope`，不是 `verified`。

### R5-EXP-06 IR 持久化、TTL、迁移与重放

**目的**

验证生产 IR 能分别回答“为什么选这个值、是否写出、是否验证、是否还能按原证据复现”。

**最低用例**

- 写前持久化失败。
- 发出后崩溃。
- 证据 TTL 失效。
- 资产 URL 过期但本地字节仍在。
- schema 升级回放。
- tombstone 迁移。
- 未知枚举。
- 权限撤销。
- 跨页面引用失效。

**通过条件**

- `audit-replay / materialize-replay / recapture-reconcile` 三种语义分别可复算。
- 历史证据过期时标 `evidence-unavailable`，不声称可精确重放。
- 迁移不丢失 tombstone、权威链、顺序映射与 unknown 状态。
- 离线审计 bundle 不被当成运行时依赖图。

**不得宣称**

- 不得只保存 winner。
- 不得依赖临时 URL 作为长期证据。
- 不得把 hash 当原证据或把重新采集当历史重放。
- 不得把离线顺序当成运行时 DAG。

**执行记录（2026-10-19）**

- 12 个文件级 case、54 个事件；21/21 合同检查通过，32/32 定向负向变异被拒绝。
- 写前持久化失败零副作用；发送后崩溃通过 `resume` 读回 1 个 remote node，重复创建 0、重发 false。
- 30 天 replay evidence TTL 过期后 `audit-replay=summary-only/evidence-unavailable`、`exact_replay=false`，materialize 阻断；180 天 audit metadata 仍保留。
- 资产 URL 已过期但本地 601-byte PNG 与 hash 仍在；materialize 使用 `local-bytes`，外部 URL fetch 0。
- v1→v2 迁移保留 fields/observations、authority chains、order mapping、tombstones、unknown state 与 evidence metadata；tombstone `not_deleted=true`、`delete_status=pending` 未变。
- 未知枚举、权限撤销、无效跨页引用、环境变化与 audit/runtime 混用均有失败关闭证据；离线 audit bundle 为 `ordered-audit-only`，不是 runtime DAG。
- 连续 2 次运行同哈希 `127fe5b3f9ee3c3c62c93e918170d033e992fd14ad64904fac008dfa54010b03`。
- 状态为 `completed-for-current-scope`，不是生产持久化、数据库崩溃一致性、权限服务或 Figma 验证，也不是 `verified`。

## 3. 实现门禁

收口审计：`R5_CURRENT_SCOPE_AUDIT.md`。生产切片：`R5_PRODUCTION_BACKLOG.md`。`P0-CONTRACT-CORE` 已实现当前范围，未接默认路径；`P1-EVIDENCE-ADAPTER` 的 shadow、真实跨浏览器状态签名与 React/Dushu strict 对齐已完成当前范围，成对真实 strict 3/7、content 5/7；S01/S03 节点差、S05/S07 阻断、字符框局部残差与生产对象存储验收仍待完成；P2–P5 仍 blocked。实现记录见 `P0_CONTRACT_CORE.md` 与 `P1_EVIDENCE_ADAPTER.md`。

以下规则在实现前必须先落成可测试合同；未通过前不得写入生产默认路径：

1. 冲突字段默认交付矩阵与 `Conflicts / Unknowns` 报告结构。
2. 区域级逻辑提交、写前持久化、写后回读与失败分类。
3. 字段类型/状态先行的 DOM/截图权威矩阵；已由 `R5-EXP-03` 形成当前范围合同证据，生产采集/融合仍未实现。
4. PARTIAL 根名、coverage map、四种空缺与四维门禁；`R5-EXP-04` 与 `R5-EXP-05` 已形成当前范围合同证据，生产交付、导出与发布实现仍未完成。
5. 生产 IR 分层 schema、版本迁移、TTL 与三种重放语义；`R5-EXP-06` 已形成当前范围文件级合同证据，生产数据库/对象存储/权限实现仍未完成。

## 4. 当前不得宣称

- 不得写 R5 规则已在生产中实现。
- 不得写真实 Figma 写入已具备事务、幂等、回滚或并发安全。
- 不得写 DOM/截图权威边界已跨浏览器、跨站点验证。
- 不得写 partial 表达或四维门禁已在真实交付中通过。
- 不得写生产 IR 已持久化、可迁移或可精确重放。
- 不得把 `R5-EXP-01–06` 的 `completed-for-current-scope` 写成生产路径已经准入。
