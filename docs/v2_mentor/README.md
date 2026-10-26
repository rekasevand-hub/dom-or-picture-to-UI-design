# v2 导师问答闭环

- 全局总计划与交接基线：`GLOBAL_OPTIMIZATION_MASTER_PLAN_2026-10-25.md`。

- Image → Figma MVP 当前范围验收：`IMAGE_FIGMA_MVP_ACCEPTANCE_2026-10-25.md`。

- Image → Figma MVP 任务与证据 ledger：`IMAGE_FIGMA_MVP_LEDGER_2026-10-25.md`。

- Axure 共享 IR 边界：`AXURE_SHARED_IR_BOUNDARY_2026-10-25.md`。

- Axure 路线 ledger：`AXURE_ROUTE_LEDGER_2026-10-25.md`。

- Axure 额外 Rect 归因：`AXURE_EXTRA_RECT_ATTRIBUTION_2026-10-25.md`。

- Axure fresh holdout A-008：`AXURE_FRESH_HOLDOUT_A008_2026-10-25.md`。

- Axure rendered-region repair A-009：`AXURE_A009_RENDERED_REGION_REPAIR_2026-10-25.md`。

- Axure fresh holdout A-010：`AXURE_FRESH_HOLDOUT_A010_2026-10-25.md`。

- Axure current-scope exit review A-011：`AXURE_CURRENT_SCOPE_EXIT_REVIEW_2026-10-25.md`。

- 当前 P1 Figma 交接：项目根目录 `HANDOFF_2026-10-21_p1_figma_acceptance.md`。

- 最近一次项目交接：项目根目录 `HANDOFF_2026-10-21_p3_p4.md`；当前实际进度以本文“当前进度”为准。

## 文档分工

- `ROUND_01_FIG_INVENTORY.md`：对导师 `.fig` 的只读事实盘点，回答“文件里实际有什么”。
- `ROUND_01_QUESTIONS.md`：第一轮问题与回答位，回答“为什么这样做、边界在哪、建议怎么做”。
- `ROUND_01_ANSWERS_RAW.txt`：导师第一轮纯文本回答的原始归档，保留逐字来源。
- `ROUND_01_ANSWERS_FORMATTED.md`：导师纯文本回答的格式化归档；只重建结构，不改写判断。
- `ROUND_01_REFLECTION.md`：第一轮回答后的思考与证据归纳，含 V1.1.0 代码对照。
- `ROUND_02_QUESTIONS.md`：第二轮 DOM → Figma 追问，预留回答位。
- `ROUND_02_ANSWERS_RAW.txt`：第二轮导师纯文本回答的逐字归档。
- `ROUND_02_ANSWERS_FORMATTED.md`：第二轮回答的格式化归档，保留原文行号与未决状态。
- `ROUND_03_DOM_QUESTIONS.md`：第三轮 DOM 并行轨，承接 R2 六项遗留问题。
- `ROUND_03_QUESTIONS.md`：第三轮“截图 → Figma”主线问题，保留原始提问与空白回答位。
- `ROUND_03_ANSWERS_RAW.txt`：第三轮两轨导师纯文本回答的逐字合并归档。
- `ROUND_03_DOM_ANSWERS_FORMATTED.md`：第三轮 DOM 并行轨回答的格式化归档。
- `ROUND_03_ANSWERS_FORMATTED.md`：第三轮截图主线回答的格式化归档。
- `ROUND_05_ANSWERS_RAW.txt`：第五轮生产交付、写入失败与权威边界回答的逐字归档。
- `ROUND_05_ANSWERS_FORMATTED.md`：第五轮 `R5-Q01–Q06` 的格式化归档；只重建结构，不改写导师判断。
- `ROUND_05_OPEN_ITEMS.md`：R5 建议实验与生产落地门禁；`R5-EXP-01–06` 已全部完成当前范围，生产落地仍未准入。
- `R5_EXP_01_CONFLICT_DELIVERY.md`：冲突字段默认交付与报告一致性；离线 33 用例、10/10 检查、15/15 变异拒绝；不连接 Figma。
- `R5_EXP_02_WRITE_FAILURE.md`：写入失败注入、对账与补偿；确定性 51/51、真实 Figma 23/23、30 步重放；记录 bridge 能力缺口与生产门禁。
- `R5_EXP_03_AUTHORITY_MATRIX.md`：DOM / 截图字段权威矩阵；8 个 authored Chromium 场景、50 字段行、19/19 检查、22/22 变异拒绝；只记录局部遮挡，不恢复全局 z-order。
- `R5_EXP_04_PARTIAL_COVERAGE.md`：部分交付表达与 coverage map；4 个同坐标变体、12 个区域、19/19 检查、24/24 变异拒绝；masked diff 为 0 仍保持 PARTIAL。
- `R5_EXP_05_ACCEPTANCE_GATE.md`：四维验收硬门禁与页面汇总；19 case × 11 条记录、22/22 检查、30/30 变异拒绝；关键项和依赖闭包阻断，面积不参与发布分数。
- `R5_EXP_06_IR_PERSISTENCE.md`：IR 持久化、TTL、迁移与重放；12 case、54 事件、21/21 检查、32/32 变异拒绝；audit/materialize/recapture/resume 分离。
- `R5_CURRENT_SCOPE_AUDIT.md`：六项 R5 产物、哈希、检查与 production gap 的只读收口审计；合计 118/118 检查、123/123 结构化变异拒绝、0 verified。
- `R5_PRODUCTION_BACKLOG.md`：R5 生产实现切片；P0 current scope，P3 ownership marker 已解除部分 blocker，P2/P4/P5 与真实 Figma resume 仍未准入。
- `R5_PRODUCTION_REASSESSMENT_2026-10-22.md`：R5-P3 当前范围完成；ownership marker、插件重载/文档重开、business ledger、确定性 resume 和真实 controlled-timeout resume 均通过，生产准入仍受全局 namespace、多人协作与权限/限流限制。
- `R5_P3_EXECUTION_PLAN.md`：R5-P3 ownership、business ledger、resume、补偿、确定性故障注入与真实 Figma 验证的分阶段实施计划。
- `R5_P5_PRODUCTION_ROADMAP_2026-10-22.md`：从当前 current-scope 状态到 P5 pilot、生产验证和 admission review 的分阶段计划；明确 pilot gate 与 production gate 分离。
- `P0_CONTRACT_CORE.md`：P0 纯合同/schema/validator 实现记录；20/20 单测、未接默认路径、不是生产或 verified。
- `P1_EVIDENCE_ADAPTER.md`：P1 样本范围、registry、30/180 天本地证据保留策略与 shadow adapter；全量 180/180 单测；受控 strict/content 7/7；旧 round3 strict 3/7、content 5/7 冻结；已补 6 样例 canonical output、5 样例视觉 holdout、data URI/受控远程资产 identity 与 crop mapping；当前 visual holdout 5/5；字符框位置仍未通过验收。
- `P1_OUTCOME_CONTRACT.md`：P1 执行态/比较结果两轴合同、首次 ready 接受规则、blank-document 条件分类与 S07 条件候选；旧 round3 基线冻结，新 profile equivalent 2 / different 3 / inconclusive 2；S06 已分离为 navigation-failure，S07 round4 7/7 有效但仍只保留 engine-conditioned candidate。
- `P1_FRAME_BARRIER_EXPERIMENT.md`：有限 frame barrier A/B；S03 文本差 28→0、覆盖 75.11%→100%，但仍 different，耗时 +25.25s；S01 未受益；实验能力默认关闭，不接生产路径。
- `P1_FIRST_PARTY_SCOPE.md`：显式中断跨源 frame document 的独立 scope A/B；S03 节点差 690→31、文本差 477→1，但仍 different；S05 基本不变；S07 round4 在 native 导航恢复后 7/7 有效，feature shim 未改变文案。
- `P1_RENDERED_FRAME_BOUNDARY.md`：拓扑优先、URL 仅作观测、opaque 内部保持 unknown 的独立 boundary scope；S01/S03/S05 固定预算为 different 2 / inconclusive 1 / equivalent 0，false equivalence 0；authored holdout 9/9，含混合可访问/opaque 与 sandbox token 顺序；S01 generation drift 仅作 execution-instability 下的伴随候选。
- `P1_CANONICAL_OUTPUT_FIDELITY.md`：产品主目标转向固定 Chromium canonical 环境下的实际 SVG/Figma 输出保真；旧 strict 保留为受控回归与真实站点诊断；calibration SVG 为 `5 pass + 1 partial`，独立视觉 holdout 为 5/5；Figma 已完成真实写入/回读/PNG 导出与独立验收链。
- `P1_FIGMA_ACCEPTANCE.md`：Figma 独立内容、几何、字体、原生文本编辑、Auto Layout 父级传播、资产替换和视觉验收；单行文本显式 `line-height` 已落地；canonical Figma holdout 达到 `5 pass / 0 blocked`；canonical assets 达到 3/3 IMAGE fill、3/3 payload SHA-256；Chromium platform font provenance 将 `sans-serif` 解析为 Microsoft YaHei。
- `P2_EXPANSION.md`：DPR 2、移动视口、非白画布背景、missing font、mixed-font run、nested iframe、transparent crop 与 partial asset 扩面；P2 11 个独立 Figma holdout 为 `10 pass + 1 partial + 0 blocked`。
- `P2_EXTENDED_CLOSURE.md`：italic/bold italic、variable named instances、ambiguous platform fallback、320–430 移动矩阵与两个真实站点观测；P2 independent Figma holdout 更新为 `10 pass + 1 partial + 0 blocked`。
- `P3_EDIT_CAPABILITIES.md`：Grid/Wrap、component instance、多级 Auto Layout 传播与编辑事务回滚；五个真实 Figma 探针均通过。
- `P4_BRIDGE_PRODUCTION.md`：request id、响应关联、`clientId + requestId` 幂等、unknown outcome 防重放、事务回滚、多客户端隔离、插件串行队列、持久 journal 与资源限制。
- `P4_WRITE_BACKPRESSURE.md`：服务端单写者闸门、有限写队列、`retryAfterMs`、timeout 后降级和确定性/真实 Figma 写入证据。
- `P4_PRODUCTION_GAP_ASSESSMENT.md`：TLS、`/plugin` 认证、unknown readback 归因、跨主机 fencing 与 24h/7d soak 的未准入判断。
- `P4_LONG_SOAK_BACKLOG.md`：24h/7d 长时 soak 的延期状态、云服务器前置条件、checkpoint、证据与准入门槛。
- `REAL_SITE_OBSERVATION.md`：`RS-LONG-01` 独立长期观测任务；冻结 profile、失败分类、运行节奏与门禁隔离，不进入生产准入分数。
- `RESIDUAL_RISKS.md`：RR-001–RR-009，区分字体/glyph/Firefox/真实站点与 P3/P4 仍未闭合的 Grid、故障注入、持久事务、多客户端和真实长时写入风险。
- `p1_sample_registry.json`：P1 的 7 类场景、14 个真实/受控样本槽与预期页面状态；批量 runner 为 `scripts/p1_sample_runner.py`，结构信号统计为 `scripts/p1_sample_signal_audit.py`。
- `ROUND_03_OPEN_ITEMS.md`：R3 仍需实验、标定或人工复核的项目清单。
- `R3_EXP_01_ONLINE_GRID.md`：`1:101` 在线图书目录 21 个槽位的网格核对结果。
- `R3_EXP_02_GRID_PROBE.md`：grid/wrap 静态能力与真机阻塞报告。
- `R3_EXP_03_EFFECT_MATRIX.md`：SVG、滤镜、mask 与混合效果矩阵，区分直接导入与重建策略。
- `R3_EXP_04_IDENTITY_MATCHING.md`：无稳定 ID 的匹配成本、歧义输出与阈值标定。
- `R3_EXP_05_FULLPAGE_CAPTURE.md`：full-page 拼接、sticky/fixed 与扩展视口对比。
- `R3_EXP_06_TEXT_METRICS.md`：行盒、基线、混排与同环境文本度量。
- `R3_EXP_07_GROUPING_LINEAGE.md`：截图分组、父关系候选、共享白底/间隙过合并与 lineage 不变量。
- `R3_EXP_08_TEXT_ACCEPTANCE.md`：OCR、低清、压缩、模糊、遮挡与文字阈值；内容/断行/框/字形分项结论。
- `R3_EXP_09_ASSET_CONTRACT.md`：裁片来源、四项能力分离、同源候选、共享整页 vs 独立裁片成本与矩形替换碰撞。
- `R3_EXP_10_FLOW_PERTURBATION.md`：截图 flow 的 L1/L2/L3 扰动、固定坐标回退与 DOM 冲突隔离。
- `R3_EXP_11_ACCEPTANCE_CALIBRATION.md`：四项验收样例集、阈值冻结、留出验证、`partial` 有效/无效区域与评分分母。
- `R3_EXP_12_REFERENCE_STATES.md`：多状态参考、状态守卫、拼接覆盖、显式权威链与外部冲突隔离。
- `R4_EXP_01_FUSION_CONTRACT.md`：逐字段融合合同、DOM/截图权威分工、状态门与未决审计。
- `R4_EXP_02_OCR_CANDIDATES.md`：真实 Tesseract/EasyOCR/OpenCV 候选接入、双引擎 exact 门、遮挡优先与升级精度。
- `R4_EXP_03_STATE_GATE.md`：真实滚动、IntersectionObserver 懒加载与动画相位的状态签名、瞬态拒绝与朴素比较假差异。
- `R4_EXP_04_PROVENANCE_IR.md`：把前三阶段回放为只读、版本化的字段级 provenance IR。
- `R4_EXP_05_BBOX_CALIBRATION.md`：跨 DPR、CSS 缩放与字体的 bbox 量化误差标定。
- `R4_EXP_06_PAIRING_CALIBRATION.md`：无稳定身份下的一对一配对、重复歧义、局部采集与节点 ID 隔离。
- `R4_EXP_07_ASSET_RESOLUTION.md`：原图下载验证、跨域/懒加载、DPR 候选、原生来源与光栅降级链。
- `R4_EXP_08_AUTHORITY_CHAIN.md`：显式 supersedes、字段权威、多轮增量、删除墓碑、跨来源冲突与非法变异。
- `R4_EXP_09_FIGMA_WRITE_CONTRACT.md`：混合来源字段的写入决策、bridge 命令形状、遮挡/z-order 与离线 mock 执行。
- `R4_EXP_10_END_TO_END_INTEGRATION.md`：九个 R4 产物的统一 stage envelope、确定性 bundle、元数据缺口与非法组合拒绝。
- `R4_SMOKE_D_AUTOLAYOUT_FONT_OCCLUSION.md`：真实 Figma 的 Auto Layout 流式重排、缺字体默认回退与严格失败、部分遮挡与 `clipsContent` 导出差异。
- `ROUND_04_OPEN_ITEMS.md`：R4 仍需真实感知、真实站点、生产 IR 与写入验证的项目清单。
- `ROUND_05_QUESTIONS.md`：R5 生产交付、真实 Figma 写入失败与 DOM/截图权威边界；已回答，见 `ROUND_05_ANSWERS_FORMATTED.md`。
- `V2_OPTIMIZATION_PLAN.md`：已收敛决策与待验证项；未过决策门的内容不写入。
- 当未知项变多时，再拆出 `EVIDENCE_LOG.md` 和 `UNKNOWNS.md`。

## 当前进度

| 轮次 | 主题 | 状态 |
|---|---|---|
| R1 | 三块画板的结构、布局、资产、命名 | 已回答并格式化；思考已落盘 |
| R2 | DOM → Figma 的 true flow 边界与证据契约 | 已回答并格式化；五类容器为 `candidate`；`R2-EXP-01` 已完成 authored DOM 扰动（42/42），原站仍待验收 |
| R3-D | DOM 并行轨：六项遗留问题 | 已回答并格式化；R3-EXP-01–06 均已完成当前范围；截图主线见 `R3-Q` |
| R3-Q | 截图主线：输入、分组与可编辑性 | 已回答并格式化；R3-EXP-07–15 均已完成当前范围 |
| R4 | 两条路线融合 | `R4-EXP-01`–`R4-EXP-10` 均已完成当前范围；生产接入与真实 Figma 未验证 |
| R5 | 生产交付、写入失败与权威边界 | 已回答；`R5-Q01–Q06` 均为规格建议；`R5-EXP-01–06` 已全部完成当前范围，收口审计 118/118 检查、0 verified；P0 纯合同已实现当前范围；P1 完成采集诊断、canonical SVG 输出基线与 Figma 独立验收链；5 个 canonical Figma holdout 均为四维 pass，Auto Layout 父级传播通过 probe；旧 strict 只作诊断与受控回归；R5 收口时 P3–P5 blocked，后续 P3/P4 已另行完成 current scope；见 `P1_CANONICAL_OUTPUT_FIDELITY.md`、`P1_FIGMA_ACCEPTANCE.md`、`P1_EVIDENCE_ADAPTER.md`、`P1_OUTCOME_CONTRACT.md`、`R5_PRODUCTION_BACKLOG.md` 与 `ROUND_05_OPEN_ITEMS.md` |
| P2 | DPR、移动、字体、frame 与资产边界 | 扩展当前范围完成；DPR2、mobile matrix、italic、variable named instances、ambiguous fallback、nested srcdoc、transparent crop、partial asset 均有独立证据；11 个 Figma holdout 为 `10 pass + 1 partial + 0 blocked`；真实站点 React/Dushu equivalent、Shoelace different、W3Schools inconclusive；Firefox environment-blocked；见 `P2_EXPANSION.md`、`P2_EXTENDED_CLOSURE.md` 与 `HANDOFF_2026-10-21_p2_expansion.md` |
| P3 | 编辑能力 | current scope 完成；Grid/Wrap、component instance、两级 Auto Layout、文档重开、预检拒绝、编辑/布局事务回滚和真实 Figma Grid 运行时故障注入均通过；协作冲突与网络中断仍为 RR-006；见 `P3_EDIT_CAPABILITIES.md`、`P3_GRID_COMPLEX_HOLDOUT.md` 与 `P3_RUNTIME_FAULT_RECOVERY.md` |
| P4 | Bridge 生产化 | current scope 完成；request id、响应关联、幂等、unknown 防重放、事务回滚、多客户端隔离、JSONL write-ahead journal、重启恢复、压缩、本地独占锁、unknown 自动 readback、哈希化意图匹配、可选 Bearer 认证、1000 请求 journal soak、两轮 60 秒真实 Figma readback soak 与限速写事务 soak 均通过；TLS、`/plugin` 认证、跨主机 fencing、并发提交归因、写 backpressure policy、24h/7d soak 与多租户仍未覆盖；见 `P4_BRIDGE_PRODUCTION.md`、`P4_PERSISTENT_JOURNAL.md`、`P4_JOURNAL_SOAK.md`、`P4_REAL_FIGMA_SOAK.md` 与 `P4_COMMAND_AUTH.md` |
| RS-LONG-01 | 真实站点长期观测 | 独立运行，与 P3/P4 并行；当前 profile 下 React/Dushu equivalent、Shoelace different、W3Schools inconclusive、Firefox environment-blocked；不进入生产准入分数；见 `REAL_SITE_OBSERVATION.md` |

> R3 分成两条并行轨：`R3-D` 6 题、`R3-Q` 7 题。两轨各自控制在 5–8 题内，但必须分开回答、分开归档、分开写结论。

> R3 回答只形成 2.0 规格，没有修改实现。所有未标定项见 `ROUND_03_OPEN_ITEMS.md`；在线目录推导值、截图布局候选等均不得写成 `verified`。

> 2026-10-18：用户已确认 5 项默认产品策略（默认忠实、缺字体不自动替换、四维验收、部分交付须标范围、截图轨默认不引入 DOM），详见 `V2_OPTIMIZATION_PLAN.md` 第 13.4 节。

## 变更记录
- 2026-10-25：A-011 Axure current-scope exit review 返回 `pass-current-scope`。受控 `DOM -> Axure` 由 A-010 fresh holdout 控制，命名 image 样本由 A-003/A-006 控制；独立验收、确定性 `.rp` 和 open/reopen publish 均有证据。A-006/A-008 历史失败及 A-007/A-009 remediation 分开保留；image route 未用 A-009 region gate 重跑，作为覆盖限制保留。任意泛化、Auto Layout、runtime replacement、clip、原生字距、交互、save-back 和生产准入仍未声明。下一步需用户选择能力扩展或生产准入。见 `AXURE_CURRENT_SCOPE_EXIT_REVIEW_2026-10-25.md`。
- 2026-10-25：A-010 fresh Axure holdout 返回 `pass-unseen-holdout`。全新冻结的 assets、transparent-crop 和 nested-iframe 三样本均通过 object mapping、critical text、资产哈希、critical regions、within-30、参考图审查、确定性和发布/重开门禁；六次发布均为 `RESULT=OK`。该结论只覆盖冻结三样本，不升级为任意 DOM 或生产可用。A-011 进行 current-scope exit review。见 `AXURE_FRESH_HOLDOUT_A010_2026-10-25.md`。
- 2026-10-25：A-009 完成当前范围。iframe 失败被归因为 A-008 使用历史 DesignSpec：当前采集器已把 `Accessible iframe content` 放在 `(18,133)`，历史输入仍为 `(16,37)`。A-009 重新生成输入，并为 Axure 发布验收新增 `critical_regions` ink 门禁；旧 A-008 渲染现在会以 `critical-region-missing` 失败，repaired iframe 在 `(14,120,286,40)` 的 reference/render ink 均为 `7.01923%`。Partial-asset 契约更正为 2 个声明/显示资产，同时保留 1 个缺失原图 provenance。两套 repaired 产物均确定性、conformance、发布/重开和验收通过；A-008 仍失败，A-010 需新的 untouched holdout。见 `AXURE_A009_RENDERED_REGION_REPAIR_2026-10-25.md`。
- 2026-10-25：A-008 fresh Axure holdout 返回 `fail-unseen-holdout`。三份新冻结样本均确定性生成、conformance 通过并完成两轮 `RESULT=OK` 发布；320px mobile 全门通过。iframe 的自动化 label-only critical text 通过，但参考图审查发现可访问 iframe 正文没有可见呈现且标题重叠；上游 DesignSpec 已把内容 Text 放在 `(16,37)`。partial-asset 输出与参考图 100% 一致且 2/2 图片哈希匹配，但冻结 manifest 只预期 1 个资产，形成评估契约冲突。A-009 需修复 iframe 子坐标、可见 critical region 验收和资产计数语义。见 `AXURE_FRESH_HOLDOUT_A008_2026-10-25.md`。
- 2026-10-25：A-007 完成当前范围。AX6-DOM-TEXTFLOW 的空 `360x96` Rect 被归因为样式 native Text 的派生背景层，不是幽灵对象；比较器仅允许一对一匹配已 matched Text 的源外框，并输出 `auxiliary_widgets` 来源映射。重新生成的 `.rp` 与 A-006 字节哈希完全一致，因此没有视觉或发布变化，A-006 仍保持 `fail-unseen-holdout`。全量 `tests/v2` 为 `722 passed`，A-008 需使用全新 untouched holdout。见 `AXURE_EXTRA_RECT_ATTRIBUTION_2026-10-25.md`。
- 2026-10-25：A-006 untouched Axure holdout 返回 `fail-unseen-holdout`。全新 AX6-DOM-FONTFALLBACK、AX6-IMG-OVERLAY 通过对象图与发布验收；AX6-DOM-TEXTFLOW 的 critical/assets/visual 通过，但 `.rp` 多出一个未投影的空 `360x96` Rect，page/object mapping 不满足 100%。按 A-006 规则未在观测后修复，A-007 另行归因该对象。见 `AXURE_HOLDOUT_V2_ACCEPTANCE_2026-10-25.md`。
- 2026-10-25：A-005 Axure frozen holdout 执行完成，结论 `partial-post-holdout-tuning`。冻结 DQ-R01、DQ-R03、AX-IMG-H01 后，首轮暴露 IR/asset 绑定、DQ-R03 视觉 `89.69745%`、image OCR `1/3` 与 asset `1/3`。TDD 修复后三样本在阈值不变下最终为 `93.7288%`、`90.2025%`、`97.2427%`，critical/assets 均 100%，且 reopen page HTML 一致。由于同一 holdout 驱动了修复，不宣称干净泛化；A-006 需新 untouched holdout。见 `AXURE_HOLDOUT_ACCEPTANCE_2026-10-25.md`。
- 2026-10-25：A-003/A-004 完成当前范围。`image -> Axure` 复用既有 image MVP 与共享 IR，在 Axure RP 8.0.0.3400 生成真实 page `A003 IMG-MVP-01 Image Axure`、确定性 `.rp`、open/reopen publish 和独立 HTML 验收；22 widgets、14/14 critical text、1/1 reference-only 图片载荷、within-30 `96.571979%`。runtime replacement 明确降级为 `creation-only-image-box`。TDD 同时关闭 flat-image 单行标题/双位统计被 Axure 重折行的真实布局缺陷。A-004 对 DQ-R02 与 IMG-MVP-01 两条受控路径均完成；见 `AXURE_IMAGE_ACCEPTANCE_2026-10-25.md`。
- 2026-10-25：A-002 完成 DOM → Axure 当前范围。DQ-R02 生成 647,034 字节确定性 `.rp`，Axure page 为 `A002 DQ-R02 DOM Axure`，469 widgets、54 个创建时图片载荷、3/3 critical text、30/30 published asset hashes、within-30 `99.377184%`；Axure open/reopen publish 与独立验收通过。见 `AXURE_DOM_ACCEPTANCE_2026-10-25.md`。
- 2026-10-25：A-001 Axure 共享 IR 边界完成当前范围。`design-ir/2.0` 仅包装现有 DesignSpec，不重写输入理解链；新增 `design-ir/2.0` projection、fail-closed validation 与 Figma/Axure capability/degradation matrix。`IMG-MVP-01`（21 nodes / 1 asset）与 DQ-R02（440 nodes / 54 assets）均 0 IR 校验错误；Axure 分别明确报告 runtime image replacement 与 letter-spacing 不支持。尚无 `.rp` 输出或 Axure acceptance，A-002 为下一步。
- 2026-10-25：Image → Figma MVP 当前范围通过。Grounding 默认，owned 截图 `IMG-MVP-01` 在真实 Figma frame `77:4851` 完成写入/回读/导出；critical text 14/14、原生文本编辑恢复和 reference-only 图片显示替换恢复通过，导出 within-30 `96.533125%`。原图身份、字体、DPR/viewport、hidden regions 与 adaptive flow 均为显式 non-claims；见 `IMAGE_FIGMA_MVP_ACCEPTANCE_2026-10-25.md`。
- 2026-10-22：启动 R5 生产化重评估并完成首个 `R5-P3` 切片。`apply_batch` 创建节点写入 owner/job plugin data，`ownership_report` 只读回读，`cleanup_owned_job` 只删除双标记精确匹配节点；返回 ownership receipt，marker 失败时创建事务回滚。真实 Figma 同一会话完成 2 节点回读/清理闭环，零 unknown；插件重载/文档重开回读、business ledger、resume 与区域补偿仍开放。
- 2026-10-22：BridgeHub 为 unknown `apply_batch` 持久化 ownership job id、期望创建数和 marker readback 分类；插件重连后自动调用 `ownership_report`，但 transaction 保持 unknown，不自动重发或晋升 committed。development-plugin 重载与文档关闭/重开后 marker 均为 2/2、清理 2/2；协议测试 33/33。
- 2026-10-22：实现 R5-P3 business ledger、write-ahead coordinator、unknown resume 决策、job-scoped cleanup receipt 和确定性故障注入；6 job soak 为 1 committed、1 reconcile-no-resend、3 manual review、0 duplicate side effects，全量 338/338。
- 2026-10-22：R5-P3 真实 Figma controlled-timeout resume 通过。短 timeout 产生 1 个 unknown，正常重启后 marker 回读 1/1，resume 为 `reconcile-no-resend`，journal 只有 1 个 apply_batch intent，cleanup 1/1、post-cleanup 0、duplicate side effects 0；全量 342/342。
- 2026-10-21：按用户决定暂停本地 24h/7d soak，新增 `P4_LONG_SOAK_BACKLOG.md` 记录云服务器执行前置条件、分阶段 checkpoint、证据包和准入标准；RR-009 保持开放，当前不启动长时任务。
- 2026-10-21：P4 增加服务端持续写背压。写命令在 intent 前取得有限队列槽位，单写者闸门保持到终态，实际 dispatch 后满足最小间隔；超限返回 `BRIDGE_WRITE_BACKPRESSURE/not-applied` 与 `retryAfterMs`。16 worker / 320 无客户端 sleep 的确定性写入 320/320 完成、零 unknown。协议测试 31/31，全量 312/312。
- 2026-10-21：P4 新写闸门下真实 Figma 4 writer / 零客户端 sleep / 60 秒完成 960/960 committed，零 timeout/unknown，p99 `267.832ms`，超过上轮 672 次提交与 4 个 unknown 的触发规模。保留一次 reconnect keepalive 日志噪声，24h/7d 仍开放。
- 2026-10-21：新增 `P4_PRODUCTION_GAP_ASSESSMENT.md`，明确 TLS、`/plugin` 认证、unknown readback 并发归因、跨主机 fencing 与 24h/7d soak 均未准入；当前 bridge 仍限定本地单主机、单插件、单文档开发链路。
- 2026-10-21：P3 完成真实 Figma 运行时故障注入。同一编辑事务先改文本，再触发 Grid 邻列 span 约束错误；首次运行暴露 `rollback-incomplete`，修复失败动作未入 rollback 栈和 Grid anchor setter 问题后达到 `rollback 2/2`、零失败。协作冲突与网络中断仍开放。
- 2026-10-21：P4 增加 unknown 事务自动 readback。持久 intent 记录目标 node id；插件重连后自动读取节点树并写入 journal，`bridge_transaction_status` 可查询状态与证据；readback 不自动晋升为 committed。协议测试 18/18。
- 2026-10-21：P4 增加可选 `/command` Bearer token。缺失或错误凭据 fail-closed，adapter 自动发送认证 header；token 使用常量时间比较且不写入 journal。`/plugin`、TLS 与多租户授权仍开放。
- 2026-10-21：P4 unknown readback 增加哈希化意图匹配。文本/name 不落明文，readback 分类为 `matches-intended / partial-match / does-not-match-intended / indeterminate`；分类不升级为 committed。协议测试 23/23。
- 2026-10-21：P4 完成 1000 请求 / 32 并发 journal soak。1000/1000 成功，pending/scope 为 0，cache 128、journal 180/256，重启回放 128，533.919 req/s，traced peak 2.077 MiB；24h/7d 真实 Figma soak 仍开放。
- 2026-10-21：P4 完成两轮各 60 秒真实 Figma readback soak。合计 50,136 请求、0 失败，约 415–420 req/s；第二轮 bridge RSS 与 handles 未增长；journal 压缩至 1,978 事件。24h/7d 与插件 renderer 泄漏仍未覆盖。
- 2026-10-21：P4 完成真实写事务 soak。未限速 4 写入器在约 169 次后触发 plugin 队列延迟和 4 个 unknown；单写入器 50ms 节流后 347/347 committed，约 17.3 写事务/s。高频写需要显式 backpressure/节流策略。
- 2026-10-21：P4 增加单实例 JSONL write-ahead journal 与独占锁。完成结果、payload 冲突和事务终态可跨 hub 重建恢复；未闭合 intent 恢复为 `REQUEST_OUTCOME_UNKNOWN`，损坏尾行可忽略，journal 压缩有界；第二个 bridge 进程会在监听端口前 fail-closed。协议测试 17/17；跨主机 fencing 与 Figma 文档自动对账仍开放。
- 2026-10-21：P3/P4 current scope 完成。生产 bridge 接入 Grid/Wrap 与 layout transaction；真实 Figma 的 Grid、Wrap、component instance、两级 Auto Layout 和编辑事务探针 5/5 pass。Bridge 完成 request/client 关联、幂等冲突、unknown outcome、事务回滚、多客户端 socket 隔离、插件串行队列、inflight/消息大小/参数深度/缓存上限，并新增真实 loopback WebSocket 测试。真实站点另立 `RS-LONG-01`，不进入生产准入分数；RR-005–RR-008 继续开放。
- 2026-10-21：完成 Figma 单行文本显式 `line-height` 落地，修复默认行盒造成的字形整体偏上；remote-asset `bad_pixel_count=14520 -> 12769`，无需调整冻结阈值即通过。5 个 Figma canonical holdout 现为 `5 pass / 0 blocked`，五样例四维全部通过；text 首次热重载后出现过一次 `212 -> 242` 宽度瞬态，独立重复已稳定为 `242` 并保留失败归档。全量 226/226。
- 2026-10-21：P2 扩展当前范围完成。补齐 italic/bold italic、variable named instances、ambiguous platform fallback、320–430 移动矩阵与四个真实站点观测；11 个独立 Figma holdout 为 `10 pass + 1 partial + 0 blocked`。全量 253/253；任意 variable axis、ambiguous glyph identity、Firefox 与真实站点普遍等价仍未证明。
- 2026-10-21：扩展 boundary holdout 到 `9/9`，新增混合可访问/opaque 层级与 sandbox opaque；S06 navigation-only round2 primary 为 capture-failure；完成 S01 generation drift 审计，9 attempts 中 5 unstable、3 capture、1 navigation failure，generation drift 不升级为根因。全量 145/145；旧 strict 3/7、content 5/7 不变。
- 2026-10-20：完成 `rendered-frame-boundary-strict/1.0` 独立 scope、S06 导航时间线与 S07 导航恢复小批复测：S01/S03/S05 boundary 为 different 2 / inconclusive 1、equivalent 0，false equivalence 0，排除 frame 130 次、不可观测 opaque frame 9 个；S06 为 navigation-failure；S07 round4 7/7 有效但 feature shim 未改变四项文案。全量 135/135；旧 strict 3/7、content 5/7 不变。
- 2026-10-20：完成 first-party frame scope 与 S07 feature-shim 轮次：新增显式跨源 frame document 阻断、profile 隔离和固定预算 A/B；S03 节点差 690→31、文本差 477→1，但仍 different；S05 基本不变；S07 round2/3 仅 1/21 有效，feature 结论保持 unresolved；全量 113/113。默认采集未改变。
- 2026-10-20：完成有限 frame barrier A/B：新增 frame-tree 会合、超时与 divergence 分类，区分 `frame-barrier-mismatch` 和 `frame-barrier-divergence`；固定 3 attempts 下 S03 文本差 28→0、覆盖 75.11%→100%，但 final 仍 different，S01 仍 inconclusive，false equivalence 0；全量 106/106。barrier 仅保留为实验参数，不接默认路径。
- 2026-10-20：按导师回复完成 P1 outcome 合同修正：旧 strict 3/7、content 5/7 冻结；新增 `execution_status` 与 `comparison_result` 两轴，首次 execution-ready 成对结果直接接受，不再挑选后续更容易通过的轮次；`about:blank` 改为条件性导航失败；S07 做 3×4 条件探针，UA swap 未改变文案，仅记 engine-conditioned candidate。全量 93/93；新 profile equivalent 2 / different 3 / inconclusive 2。未新增 scope、frame barrier、生产存储或 Figma 写入。
- 2026-10-20：完成 P1 真实 strict 扩面的 frame/导航轮次：新增 frame inventory（URL/尺寸/sandbox/同源/可访问/opaque）、同源子文档递归、可渲染 frame-tree 状态签名、不可渲染 tracker 证据隔离、frame 导航变化检测；空白文档归为 `browser-navigation-failed` 并做一次有界 `domcontentloaded` 重导航，成对重试使用 250–2000ms 封顶退避；动态 `❯` 只归因不伪造通过。全量 78/78；round3 真实 strict 仍 3/7（目标未提升），content 5/7；S01/S07 保留 blocked 证据，S03/S05 仅 content。未接默认路径、未写 Figma。
- 2026-10-20：完成 P1 严格真实页面状态对齐当前范围：修复 WebKit `<clipPath><rect>` 伪可见节点，React 恢复 1415/1415 且 strict 通过；新增字体/可见状态稳定签名、语义结构哈希、瞬时探针重试与成对最佳轮次选择，Dushu 第 2 轮进入同轮播相位后 strict 通过；全量 64/64 单测；成对真实 strict 3/7、content 5/7，S01/S03 仅 content，S05/S07 blocked；未接默认路径、未写 Figma。
- 2026-10-19：实现 P1 evidence shadow 当前范围：新增 sidecar adapter、WebKit capture、M0/M1、资产/OCR/materialize、双层状态门与 text-tag 对齐；14/14 adapter + 8/8 OCR + 4/4 下载 + 1/1 materialize + 5/5 browser-engine 单测；受控 strict/content 7/7，真实 strict 1/7、content 5/7；字符框位置仍未通过验收；未接默认路径、未接 OCR 正文、未写 Figma。
- 2026-10-19：实现 `P0-CONTRACT-CORE` 当前范围：新增纯确定性 `src/app/services/contracts/` 与 20 个标准库单测；覆盖字段权威、coverage、四维门禁、runtime/audit 分层、迁移与 replay；`PreciseAgent`/`FigmaBridgeAdapter` 可导入，默认路径未接入，非生产、非 verified。
- 2026-10-19：完成 R5 收口审计：6/6 实验 current-scope、118/118 合同检查、123/123 结构化变异拒绝、0 verified；审计 14/14、8/8 元变异拒绝；生成 `R5_CURRENT_SCOPE_AUDIT.md` 与 `R5_PRODUCTION_BACKLOG.md`。唯一 ready 切片为 `P0-CONTRACT-CORE`，真实 Figma 写入/生产存储未准入。审计哈希 `83079c2e...`。
- 2026-10-19：完成 `R5-EXP-06` 当前范围：12 个文件级 case、54 事件；写前持久化失败零副作用，发送后崩溃 resume 一次提交；TTL 过期只做摘要审计、本地资产字节可 materialize、v1→v2 保留 tombstone/权威链/顺序/unknown；未知枚举、权限撤销、跨页引用和环境变化失败关闭；21/21 检查、32/32 定向变异拒绝；连续 2 次同哈希 `127fe5b3...`。R5 六项实验全部达到 current-scope，不代表生产准入或 `verified`。
- 2026-10-19：完成 `R5-EXP-05` 当前范围：19 个 case × 11 条 canonical checks = 209 条记录；六类故障、critical partial/not-sampled、unknown/no-ground-truth、tiny price、高面积背景、reference-only 与 preflight 均覆盖；Deliverable `complete 1 / partial 4 / reference-only 1 / blocked 13`，production 19/19 not eligible；22/22 检查、30/30 定向变异拒绝；连续 2 次同哈希 `b5cd12d4...`。检查状态是注入输入，不证明检测器标定或生产发布。
- 2026-10-19：完成 `R5-EXP-04` 当前范围：4 个同坐标缺口变体、12 个覆盖区域；四种空缺在根名、报告、manifest 与 coverage map 中分开，面积使用并集，固定 raster 分母 `912,000 px`，诊断 mask `60,000 px`，masked diff `0` 仍保持 PARTIAL；19/19 检查、24/24 定向变异拒绝。连续 2 次同哈希 `94f843fe...`。真实锁、手动导出阻断、Figma 报告 Frame 与用户理解仍未验证。
- 2026-10-19：完成 `R5-EXP-03` 当前范围：8 个 authored Chromium 场景、50 个字段行、17 类字段；状态计数 `authoritative 31 / observed 4 / candidate 4 / external-conflict 3 / unknown 5 / unsupported 3`；19/19 合同检查、22/22 定向变异拒绝。验证 CSS counter/text-transform、canvas、可访问/不可访问 iframe、closed shadow、隐藏旧文案、水合切换与复杂堆叠上下文的字段级处理；OCR 只提升文本候选，局部位图叠放不恢复全局 z-order。连续 2 次同哈希 `e954d75a...`。只覆盖单一 Chromium authored fixture，不是跨浏览器、真实站点或生产实现验证。
- 2026-10-19：新增项目交接 `HANDOFF_2026-10-19_v2_r5.md`，记录 R1–R4 与 R5-EXP-01/02 当前状态、证据路径、环境、bridge 缺口、工作树安全规则与 R5-EXP-03 的启动清单；同时补入 `R5_EXP_01_CONFLICT_DELIVERY.md` 索引。
- 2026-10-19：完成 `R5-EXP-01` 当前范围：33 个离线确定性用例（25 个冲突矩阵单元 + 5 个权威控制 + 2 个旧值状态 + 1 个 skipped），10/10 合同检查、15/15 负向变异拒绝；5 个 written、28 个未决、28 个报告条目；连续 2 次运行同哈希。只证明离线交付合同，不证明真实 Figma 交付、用户理解或价格正确。
- 2026-10-19：完成 `R5-EXP-02` 当前范围：确定性 17 用例 × 3 变体 = 51/51，安全不变量 0/0/0/0，30 步同 job 重放 `committed`；真实 Figma 23/23，连续 2 次通过并清理无残留。确认 bridge 无服务端幂等键、可靠 ownership marker、节点级删除与 visibility/rename；父节点缺失会静默挂到 `currentPage`。状态为 `completed-for-current-scope`，不是生产通过。
- 2026-10-19：归档并格式化第五轮导师回答 `R5-Q01–Q06`，覆盖冲突字段默认交付、真实 Figma 部分写入失败的事务/回滚、DOM/截图权威边界、部分交付表达、四维验收门禁与生产 IR 最小契约。已写入 `V2_OPTIMIZATION_PLAN.md` 的 D39–D44 与第 14 节规格，并建立 `ROUND_05_OPEN_ITEMS.md` 的 `R5-EXP-01–06` 待验证清单。导师明确本轮只回答规格、未独立核验题内实验；所有内容仍是待实施、待验证的生产合同。
- 2026-10-19：完成真实 Figma Smoke D。纵向 HUG 列与横向 `layoutGrow` 行由 Figma 引擎真实重排；严格字体探针与严格 `create_text` 在缺族时失败关闭且不留节点；子节点顺序形成部分遮挡，`clipsContent=true/false` 的导出分别为 240×160 与 280×160。26/26 检查通过，`content_hash=fa904922230649a5`。发现默认 `create_text` 缺族仍静默回退到 `Inter / Regular`，已记为 `high` 差异；Auto Layout 走实验动作 `set_layout_flow`，不代表生产 `set_autolayout`。见 `R4_SMOKE_D_AUTOLAYOUT_FONT_OCCLUSION.md`。
- 2026-10-19：整理 R5 导师问题，覆盖冲突字段默认交付、真实 Figma 部分写入失败的事务/回滚、DOM/截图权威边界、部分交付表达、四维验收门禁与生产 IR 最小契约。见 `ROUND_05_QUESTIONS.md`；当时状态为待回答，后续已收到回答。
- 2026-10-19：完成真实 Figma Smoke C。把 `R4-EXP-09` 实际发出的 1 条画板命令 + 8 条写入命令重放到真实 Figma，回读 16/16：命令 ID、子节点顺序、延迟节点缺席、字体解析、资产哈希、文本/颜色/几何与 PNG 导出均通过；导出 13604 字节，`content_hash=186af6e44a5eecbc`。仍只覆盖已发出的命令，不覆盖 19 个字段决策、遮挡/权威链、事务与回滚。见 `R4_SMOKE_C_WRITE_CONTRACT.md`。
- 2026-10-18：完成真实 Figma 冒烟。Smoke A 将 34 元素夹具写入真实画板并导出；Smoke B 新增 `get_node_tree` 回读，frame/text/rectangle/image 四类节点 12/12 检查通过。两者均为 `completed-for-current-scope`，不是生产写入或事务验证。见 `R4_SMOKE_B_READBACK.md`。
- 2026-10-18：完成 `R4-EXP-10` 当前范围：将 `R4-EXP-01`–`R4-EXP-09` 聚合为 9 阶段确定性离线 bundle；9/9 状态正确、227/227 阶段检查通过、9/9 显式哈希复算一致、9/9 派生 digest、13/13 集成检查、9/9 非法变异拦截，120 次顺序置换同 `bundle_hash`。`boundary 9/9`、`limitations 9/9`、`envelope_gaps={}`；`sequence_semantics=ordered-audit-only`，未重跑感知/浏览器/写入，未连接 Figma。状态为 `completed-for-current-scope`，不是 `verified`。
- 2026-10-18：完成 R4 envelope 元数据补齐：EXP-01–06 补 boundary、EXP-08 补 limitations、EXP-01–04 补显式 `content_hash`；幂等复跑 `changed=0`、7/7 检查。见 `output/_r4_experiments/r4_metadata_supplement.py`。
- 2026-10-18：完成 R3 envelope 元数据补齐：EXP-01–12 补 `status / boundary / limitations / content_hash`；幂等复跑 `changed=0`、8/8 检查；EXP-02 另生成只读清单。见 `output/_r3_supplements/r3_metadata_supplement.py`。
- 2026-10-18：完成 `R3-EXP-15` 当前范围：四个失败 SVG 特性的离线平铺栅格回退；4/4 生成、PNG 逐像素无损、JPEG q90 最大 MAE `1.121845`、9/9 合同检查；真实 Figma 导入/回读未执行。
- 2026-10-18：完成 `R3-EXP-14` 当前范围：已知字体/字号下从静态截图估计 alphabetic baseline；28 次测量、最大误差 `0.5px`、平均 `0.018px`、6/6 检查；未知字体/字号仍为 `not-evaluated`。
- 2026-10-18：完成 `R3-EXP-13` 当前范围：Chromium + WebKit 跨渲染器文本度量；72 次测量、换行数差 0/12、基线最大差 `0.5px`、8/8 检查；Firefox 启动失败（`spawn UNKNOWN`），未覆盖。
- 2026-10-18：完成 `R2-EXP-01` 当前范围：五个 authored DOM 容器的 24 个内容/尺寸变体与 42/42 合同检查；不证明原站 DOM、原站响应式或 Figma Auto Layout。
- 2026-10-18：完成 `R1-EXP-02` 当前范围：content/soft_block/hard_login 三态回归 3/3、soft-block 降级 `screenshot_only`、hard-login 终止提示、10/10 检查。
- 2026-10-18：完成 `R4-EXP-09` 当前范围：19 个受控混合来源字段用例、11 个节点、10 个 bridge 动作；8 `written` / 7 `deferred` / 4 `skipped`，9 条命令（1 `create_frame` + 5 `create_text` + 1 `create_rectangle` + 2 `create_image`）；文本只写 DOM 或双引擎 exact 晋升值，颜色只写 DOM 选中来源，原图与 `flat-raster-crop` 保留 claim，完全遮挡跳过、遮挡未知延迟，命令按截图 `z_order` 升序；38/38 检查与 8/8 非法变异通过。所有命令只进入内存 mock executor，`real_figma_connected=false`、`figma_write=false`、`source_mutation=false`；状态为 `completed-for-current-scope`，不是 `verified`。
- 2026-10-18：完成 `R4-EXP-08` 当前范围：15 个真实 Chromium 页面修订 / 4 轮 / 2 scope / 10 字段；6 条显式 supersedes、5 个有效权威、6 个被淘汰、1 个内容等价镜像；`title` 与 `rating` 外部冲突、`price` 由 inventory 保持 1399、`description` 墓碑删除、`stock/battery/weight` 继承、`discount` 15%；24 次置换同哈希、4 种非法变异失败、朴素基线 5 错，35/35 检查；状态为 `completed-for-current-scope`，不是 `verified`。
- 2026-10-18：完成 `R4-EXP-07` 当前范围：资产来源解析与降级链。受控页面含 20 个资产用例，经 2 个 loopback HTTP 服务与真实 Chromium 在 DPR 1/2 下验证；10 个 HTTP 原图通过状态/MIME/解码/尺寸门，6 个光栅降级与 4 个原生/本地来源按预期分流，20/20 状态、来源与原因匹配，39/39 检查通过。404、超时、MIME 欺骗与截断分别保留 `http-404 / timeout / mime-body-mismatch / decode-failed`；`srcset`/`image-set` 在 DPR 2 请求 2x 候选；跨域图片页面 `fetch` 被 CORS 阻断但请求上下文可下载；懒加载滚动前请求 0、滚动后 1。原图 17972 字节、降级 14305 字节，20 次元素截图 P50 约 64.05 ms，为本实验主要固定成本。未修改 `src/`、`figma_bridge/`，未执行 Figma 写入；状态为 `completed-for-current-scope`，不是 `verified`。
- 2026-10-18：完成 `R4-EXP-06` 当前范围：无稳定身份的一对一配对与歧义标定。12 个受控场景、24 次真实 Chromium 捕获、109 个 DOM 观测、46 个预期配对；输出 46 个 `proposed-match`、4 个旧项与 4 个新项的重复歧义、6 个 `not-seen`、3 个 `unmatched-new`，错误配对、漏配与非预期歧义均为 0，26/26 检查通过。完全相同副本的 `primary-content-tie` 先于位置、顺序、节点 ID 与 Hungarian 分配；节点 ID 不进入特征，随机替换后结果不变。节点 ID 基线 3 个错误配对 / 8 条错误记录；纯文本+图像基线 0 误配 / 5 漏配。`accept=0.20 / gap=0.04 / coverage>=0.30` 在两分支均为 0 错误，零错误交集为 `accept 0.20–0.25 × gap 0.02–0.06`，仅属弱标定。72 次输入顺序置换无结果变化；未修改 `src/`、`figma_bridge/`，未执行 Figma 写入；状态为 `completed-for-current-scope`，不是 `verified`。
- 2026-10-18：完成 `R4-EXP-05` 当前范围：跨 DPR、CSS 缩放与字体的 bbox 容差标定。1 个受控页面、4 个 DPR（1/1.25/1.5/2）、5 个缩放（0.5–1.5）、4 组字体与 2 个小尺寸压力样本，共 20 次真实 Chromium 截图、200 个 bbox 样本。固定 `2.0 px` 门限下 200/200 通过，常规样本 160/160、小尺寸压力样本 40/40；P50 0.5000 px、P95 0.8333 px、P99 1.0375 px、最大 1.1000 px，最小余量 0.9 px。最坏点在 DPR 1.25 / zoom 1.0；+2.5 px 正向平移诊断全部被拒绝。22/22 完整性检查通过；截图 bbox 是纯色背景连通域的渲染量化口径，不是 OCR/CV 检测器基准。未修改 `src/`、`figma_bridge/`，未执行 Figma 写入；状态为 `completed-for-current-scope`，不是 `verified`。
- 2026-10-18：完成 `R4-EXP-04` 当前范围：把 `R4-EXP-01/02/03` 回放为只读、版本化的字段级 provenance IR。34 个节点、77 个字段、181 条证据、103 条来源决策；每字段记录权威、状态、选中值/显式 `null`、选择来源、理由、provenance 与保留观测。冲突保持双侧观测且 winner 为 `null`，`unknown` 只保留 absent observation；OCR 只提升 `text-content`，O06/O11 各由双引擎证据支撑，`editability / role / asset_source` 永不升级；4 个同态重复对零字段/像素差，32 个异态对与 19 个瞬态对不携带 `field_result`。22/22 检查通过，11/11 非法变异被拒绝。IR 未接入 `src/`、`figma_bridge/`，未执行 Figma 写入；状态为 `completed-for-current-scope`，不是 `verified`。
- 2026-10-18：完成 `R4-EXP-03` 当前范围：1 个合成页面、11 次真实浏览器捕获、7 个状态签名、55 个捕获对与 18 项检查。4 对同态重复的字段差异 0、缩略图像素差 0；32 对 `state-mismatch`、19 对 `transient-state` 全部在字段比较前阻断，假可比与假阻断均为 0。真实滚动到 900/1400/1950 px，IntersectionObserver 提交三代懒加载（探针 23 → 26 → 29 → 32，文档高度 3112 → 3032），sticky 头部视口位置不变而文档位置 0 → 900，动画 700 ms 相位改变宽度/背景/opacity/transform；pending 与滚动中捕获保持 transient。跳过状态门会在 51 个被阻断对上产生 2172 个朴素字段假差异。状态为 `completed-for-current-scope`，不是 `verified`；只覆盖单个合成页面，动画为暂停相位，未修改 `src/`、`figma_bridge/`，未执行 Figma 写入。
- 2026-10-18：完成 `R4-EXP-02` 当前范围：1 个合成页面、12 个单行用例 + 1 个重复块、5 个 CV 目标；Tesseract `chi_sim+eng` / EasyOCR `ch_sim+en` / OpenCV 轮廓共产生 25 条 OCR 候选与 32 条 CV 候选。13 用例状态为 `promoted-text-content=2`、`screenshot-candidate=4`、`ambiguous=6`、`occluded=1`、`unknown=0`；2/2 升级正确，朴素最高置信度基线 8 次升级、2 次误升级（O08、O10）。CV 命中 4/5 目标，B02/B03 保留歧义，1 px 分隔线未命中。13/13 检查通过，重复过门哈希一致。OCR 只在给定框内运行，阈值 `0.85 / 0.50 / 0.30` 为实验合同值，`unknown` 分支未触发；未修改 `src/`、`figma_bridge/`，未执行 Figma 写入。状态为 `completed-for-current-scope`，不是 `verified`。
- 2026-10-18：用户同意开启 R4；完成 `R4-EXP-01` 当前范围：1 个合成页面、4 个状态签名、24 个逐字段合同用例、20 个裁片。DOM 负责 `text / font / color / role / editability / asset_source`，截图负责 `visible_state / occlusion / z_order / rendered_effect`；状态门先于字段比较，bbox 绝对容差 `2.0 px` 且不平均。13 已裁决 / 5 有范围证据 / 6 未决；字段政策错误 `0`、静默覆盖 `0`、14/14 合同检查通过；朴素等值比较在 18/24 用例上给出错误状态。截图观测值为真实截图上的夹具输入，未运行 OCR/CV，未修改 `src/`、`figma_bridge/`。状态为 `completed-for-current-scope`，不是 `verified`。
- 2026-10-18：完成 `R3-EXP-12` 当前范围：11 个合成参考、6 个状态签名、7 个 scope-state 组、8 个参考比较对与 4 个拼接场景。同态重复像素 MAE `0.0`、最小几何 IoU `1.0`；轮播帧、滚动、缩放、遮挡和过渡保持独立状态，守卫后几何错误 `0`（避免 2 个 naive 假差异）。同态全重叠拼接为 `composite-verified`，缺口/混合帧/v1+v2 混拼为 `composite-unknown`；v2 显式 `supersedes` v1，v3 与外部 A/B 保持未决，外部冲突 winner 为 `null`。16/16 合同检查通过；`composite-conflict`、真实轮播时序、真实外部来源与截图自动状态识别仍未验证。状态为 `completed-for-current-scope`，不是 `verified`。
- 2026-10-18：完成 `R3-EXP-11` 当前范围：24 个合成基础样例（标定集 12 + 验收集 12；6 类 × 2 难度）× 6 变体 = 144 张截图。标定集与验收集均为 288/288 四维状态匹配、故障目标命中 60/60、跨维误报 0/180、baseline 假报警 0/12。错字只在 visual `fail`；遮挡只在 visual `partial`，被遮挡正文内容/断行/字形为 `unknown`；烘焙合成资产只在 asset `fail` 而视觉 `pass`；不传播高度只在 edit `fail`；结构角色错误只在 structure `fail`。冻结 14 个阈值；`linebreak/pixel/geometry/parent/boundary/native` 无对应故障变体，只作合同值或干净噪声边界。`partial` 有效区域 89.99%–95.82%、未知区域 4.18%–10.01%；维度级 `unknown` 未触发；编辑只探测 12/20 段，资产每页一个槽。状态为 `completed-for-current-scope`，不是 `verified`。
- 2026-10-18：完成 `R3-EXP-10` 当前范围并并入 `R2-EXP-01` 扰动类型：7 个合成输出合同场景为 4 `pass`、1 `partial-fallback`、1 `partial-fixed-width`、1 `fallback-fixed`，0 失败检查。页面纵向 stack 在 `+40`、插入/删除与宽度 `+10%` 下传播正确；卡片信息 `237→281→299`；页脚第 2 行 `44→84`、页脚 `222→262`；绝对分隔线 `y 43→83`。宽度缩小导致固定卡片溢出 68.4 时回退整个区域为固定坐标；主栏/侧栏溢出 19 时保留静态宽度；复杂叠放保持 `layoutMode=NONE`。DOM 合成夹具只记 `external-conflict`，在线目录 `dom_order` 仍为 `unknown`。通过项仅写 `verified_for=output-contract`、`source_behavior=inferred`，不是 `verified`。
- 2026-10-18：完成 `R3-EXP-09` 当前范围并并入 `R2-EXP-02`：9 个受控资产的观测类别 `independent=5 / reference-only=2 / constrained=2`，与 ground truth 数量一致；标签 9/9、原因 8/9（`flat_badge` 为标签巧合）。36 个有序配对中 6 个同源预期对全部命中，0 FP / 0 FN；精确重复 `cover_full_a == cover_full_b`。1x/2x、PNG/JPEG 的共享、独立、去重与混合成本已测，但无单调优势；9 次替换碰撞独立资产 0–0.0005、合成/受限资产 0.0264–0.6649。`missing` 仅定义并实现，未实例化。状态为 `completed-for-current-scope`，不是 `verified`。
- 2026-10-18：完成 `R3-EXP-08` 当前范围：受控页面 13 用例 × 27 条件标签 × 2 OCR 引擎共 702 条记录；严格 exact 81/702，核心字符 230/702，行数匹配 677/702。对抗字符 324 条 exact 为 0；普通 32px 核心 exact 为 Tesseract 5/7、EasyOCR 3/7，16px 各 4/7，12px 为 1/7 与 2/7，8px 均为 0/7。证据字段仅 Tesseract 有效 32px 通过 1/2；EasyOCR 清晰 32px 仍把 `¥` 识别为 `半`。JPEG/模糊非单调；行数、IoU 与 OCR 置信度均不能单独通过；遮挡保持 `unknown`，补文 `user-supplied-unverified`，基线 `not-evaluated`。
- 2026-10-18：完成 `R3-EXP-07` 当前范围：单个受控页 16 个 seed，5 `candidate` / 11 `ambiguous` / 0 错误候选；`obj-band` 复现“边框包含不等于父关系”，主栏/侧栏 40px 纯白 gutter（`white_ratio=1.0`）仍被 naive gap merge 合并；父关系编辑、环拒绝、split/merge 和坏合并 undo 均保持 lineage 与快照一致。自动分割、OCR、真实站点与 Figma API 写入未验证。
- 2026-10-18：完成 `R3-EXP-03` 当前范围：20 个 SVG + 12 个原生用例；渐变/clip/mask/blur 可直接导入，`feDropShadow`、filter 链、`foreignObject`、`pattern`、远程图片直接导入失败；mask+effect 包装层把均值差从 10.2087 降到 1.2351；raster-fallback 仍未验证。
- 2026-10-18：完成 `R3-EXP-04` 当前范围：14 场景 / 37 配对；`0.20 / 0.06` 下校准与验证均为 0 错误记录、0 漏配；节点 ID 基线 10 条错误记录；仅内容特征漏 6 条；阈值属弱标定。
- 2026-10-18：完成 `R3-EXP-02` 当前范围：基础 27/27 步、补充 32/32 步、隔离复测 13/13 步。补充覆盖跨度+`FILL`、`MIN/CENTER/MAX`、`FLEX` 比例、HUG 列/父帧，以及三节点保存重开逐字段回读；嵌套 grid、HUG+FILL、自动/混合轨道与生产 bridge 集成仍未覆盖。
 - 2026-10-18：完成 `R3-EXP-05` 受控实验：8 段原视口拼接、保持原视口的整页文档捕获、扩展视口捕获三模式对比；8 段 M0/M1 全部稳定，覆盖 100%；屏蔽 sticky/fixed 区域后有效像素差为 0；扩展视口改变 `100vh`/媒体条件并只覆盖新文档的 54.44%。该实验只覆盖本地受控页，真实站点与跨浏览器扩展待做。
- 2026-10-18：完成 `R3-EXP-06` 受控实验：12 个文本用例的行盒、行进、混排 run、基线探针、平台字体、缺字与 emoji；Arial 实际行进 32、YaHei/混排 33；混排 run 顶部差 3px 但基线一致；3 次重复与 DPR 1/2 CSS 度量一致。`R3-EXP-13` 已补 Chromium + WebKit，Firefox 与通用跨平台阈值仍为 `not-evaluated`。
- 2026-10-18：执行 `R3-EXP-02` 静态能力核对与桥接探测；类型定义有 `GRID/WRAP`，但当前 bridge 未实现且 Figma 插件未连接，记录为 `blocked-environment`。
- 2026-10-18：完成 `R3-EXP-01`：`1:101` 的 21 个槽位全部核对为 152×237，3×7 网格、步长/间隙/padding 与聚类稳定性均有可复跑产物；只覆盖该节点，`dom_order` 仍为 `unknown`。
- 2026-10-18：用户确认 5 项默认产品策略；写入 D34–D38 与 `V2_OPTIMIZATION_PLAN.md` 第 13.4 节。
- 2026-10-18：归档导师 R3 两轨原始回答（SHA-256 `5237385D78BDBC08E9C653CBCC63B946E7A9E4439979552E2085850B6151EA16`），生成 DOM 轨与截图轨格式化版；写入 D21–D33 与 `V2_OPTIMIZATION_PLAN.md` 第 13 节；建立 `ROUND_03_OPEN_ITEMS.md`。
- 2026-10-18：归档导师 R2 原始回答并生成格式化版；写入 D12–D20 与 `V2_OPTIMIZATION_PLAN.md` 第 12 节；将五类 DOM 容器保持为 `candidate`，六项遗留问题转第三轮 DOM 并行轨 `R3-D01–D06`，截图主线为 `R3-Q01–Q07`。
- 2026-10-18：复核 R2-Q01，移除误用的 URL 版节点（1:619、1:485、1:685），改为 DOM 版 1:211、1:243、1:244、1:213、1:312 的实测几何；补充“DOM 顺序与视觉顺序相反”“首个排行项没有容器”“分隔线非居中”等事实。同期校正 R2-Q06 的 DOM 字体统计（Noto Sans SC 153 个、Arimo Italic 13 个）。

## 规则

1. **Artifact-first**：能从 `.fig` 直接测量的事实，不重复问导师。
2. **问题 ID 稳定**：使用 `R1-Q01` 这种编号；追问写成 `R1-Q01.1`，回答只追加、不覆盖。
3. **每轮 5–8 题**：每轮只围绕一个主题；回答中产生的新问题先进入 parking lot，不打断当前轮次。
4. **回答模板固定**：本次实际做法 / 通用建议 / 依据或可复现证据 / 不确定项 / 失败或放弃的方案。
5. **证据分层**：`[FIG]` 文件事实、`[MENTOR]` 导师判断、`[OUR-CODE]` 我们代码现状、`[EXPERIMENT]` 我们自己的实验。
6. **决策门**：只有能落成可测试规则、参数或验收标准的结论，才进入优化实现方案；否则留在未知项。
7. **冻结与变更**：已采纳的决策不反复重开；如要改变，必须记录新证据和变更原因。
8. **导师回答不覆盖**：问题文档保留原始提问与空白回答位；导师回答单独归档为 `ROUND_XX_ANSWERS_FORMATTED.md`，便于追溯。
