# R5 生产实现切片与后备清单

> 状态：`P0-CONTRACT-CORE` 与 `P3-WRITE-LEDGER-RESUME` 已实现当前范围，P3 增加 ledger retention/compaction/legacy migration current scope；P1 canonical output 继续生产加固；P2/P4/P5 仍未准入，P3 也不是生产准入或 `verified`。  
> 审计依据：`R5_CURRENT_SCOPE_AUDIT.md`、`output/_r5_closeout/result.json`。  
> 原则：先做纯合同核心；真实 Figma 写入、生产存储和检测器校准都不作为第一步。

门禁与验证词汇以 `R5_GATE_MATRIX.md` 为唯一清单。本文中的
`implemented-current-scope`、`completed-for-current-scope` 等切片状态只描述
当前实现或实验，不自动产生 `pilot-verified`、`verified-for:<scope>` 或
`production-admitted` 结论。

## 1. 切片总表

| Slice | 内容 | 状态 | 依赖 |
|---|---|---|---|
| `P0-CONTRACT-CORE` | 纯合同/schema/validator | `implemented-current-scope` | 无 |
| `P1-EVIDENCE-ADAPTER` | 采集证据侧车、字段观测与 canonical 输出保真 | `diagnostics-current-scope; canonical-output-svg-3of3-initial-scope; visual-not-gated; figma-not-evaluated; legacy-live-strict-diagnostic-only` | P0 |
| `P2-PARTIAL-DELIVERY` | PARTIAL 报告、coverage map、验收门禁 | `blocked-by-detector-status` | P0、P1 |
| `P3-WRITE-LEDGER-RESUME` | 写前账本、resume、ownership namespace、client identity、文件配置、client fairness、TLS、plugin auth/revocation、secret lifecycle、TLS+auth reconnect、attribution boundary、ledger retention/compaction/migration、区域补偿 | `completed-for-current-scope; real-timeout-resume-pass; namespace-slice-pass; client-identity-slice-pass; file-config-slice-pass; client-fairness-slice-pass; tls-slice-pass; plugin-auth-slice-pass; revocation-reconnect-slice-pass; secret-lifecycle-pass; attribution-boundary-pass; ledger-lifecycle-pass; production-not-admitted` | P0、P1 |
| `P4-PERSISTENCE-OPERATIONS` | 生产 IR 存储、TTL、权限、迁移 | `blocked-by-storage-policy` | P0 |
| `P5-PILOT-E2E` | 受限真实 Figma 试点 | `blocked-by-p0-p4` | P0–P4 |

> 2026-10-20 的 P1 真实状态对齐更新了本表 P1 行；`R5_CURRENT_SCOPE_AUDIT.md` 与 `output/_r5_closeout/result.json` 保留 R5 收口时点，因此仍记录当时的 `blocked-by-sample-scope`，不回写历史审计。

## 2. P0-CONTRACT-CORE

### 目标

把 D39–D44 中已经收敛的字段、状态、coverage、验收、IR 与 replay 合同落成纯确定性库。它不连接 Figma、不读写生产页面、不改变默认行为。

### 建议模块

```text
src/app/services/contracts/
  __init__.py
  ir.py
  authority.py
  coverage.py
  acceptance.py
  migration.py
  replay.py
  validation.py
```

路径是候选，需按实际包边界调整；不得直接塞进 `figma_adapter.py`。

### 最小 API

- `FieldDecision` / `FieldAuthority`；
- `CoverageRegion` / `PageCoverage` / `PartialReport`；
- `AcceptanceRecord` / `PageAcceptance` / `ReleaseDecision`；
- `RuntimeIR` / `AuditBundle`；
- `validate_runtime_ir()` / `validate_audit_bundle()`；
- `evaluate_release()` / `compute_coverage()`；
- `migrate_ir_v1_to_v2()`；
- `audit_replay()` / `materialize_replay()` / `recapture_reconcile()`。

### 必须保留的语义

- unknown、deleted、not-applicable 不能用同一个 `null`；
- 未决字段保留双方观测，`winner=null`；
- OCR 只提升 `text-content`；
- partial/coverage 分母不能因 mask 缩小；
- area 不参与 release score；
- critical fail/unknown/不允许 partial 阻断；
- audit bundle 与 runtime DAG 分开；
- TTL 后 `evidence-unavailable`，hash 不替代字节；
- recapture 生成新 revision；
- unknown enum 与缺失引用失败关闭。

### 验收

1. 全部模块为纯 Python、确定性、无网络与 Figma。
2. Golden valid examples 覆盖 D39–D44。
3. 负向用例覆盖：候选值入正文、critical 放行、遮罩缩分母、TTL exact replay、迁移丢 tombstone、audit 当 DAG。
4. 所有枚举与 schema 失败关闭。
5. `py_compile` 与单元测试通过。
6. 默认 `PreciseAgent` 行为、`RenderingController` 与 bridge 命令字节不变。

### 明确不做

- 不接生产写入；
- 不改 `figma_bridge/code.js`；
- 不接真实数据库；
- 不声称真实检测器已标定；
- 不创建真实 Figma 报告 Frame。

### 实现记录（2026-10-19）

已新增：

```text
src/app/services/contracts/
  __init__.py
  acceptance.py
  authority.py
  coverage.py
  enums.py
  ir.py
  migration.py
  models.py
  replay.py
  schema.py
  validation.py
tests/v2/test_r5_contracts.py
```

当前范围结果：

- 20/20 unittest 通过；
- runtime IR / audit bundle JSON schema 通过 golden example 校验；
- unknown enum、OCR 语义越权、critical fail、edit fail、mask 分母、migration、replay、DAG cycle 均有负向用例；
- `PreciseAgent` 与 `FigmaBridgeAdapter` 可正常导入；
- 未接入默认渲染、`PreciseAgent` 或 bridge，未改生产路径字节。

状态：`implemented-current-scope`，不是生产接入或 `verified`。

## 3. P1-EVIDENCE-ADAPTER

目标：把 `capture_page_with_fallback` 的截图、DOM、page_state 和资产转成证据侧车。

前置：P0。

已完成的 shadow 当前范围（2026-10-19）：

- 新增 `src/app/services/evidence/`，提供 `adapt_capture()` 与 `write_evidence_sidecar()`。
- 定义 `p1-sample-scope/1.0`：7 类场景、每类至少 2 次 capture、至少 1 个真实页面。
- 定义 `p1-evidence-store/1.0`：本地 sidecar、replay evidence 30 天、audit metadata 180 天、外部 URL 不持久化。
- 生成 P0 `RuntimeIR` 与 `audit_bundle`；DOM 字段只标 `OBSERVED / release_eligible=false`。
- 对 shadow/soft-block/hard-login/缺 DOM 保留 unknown，不从截图猜内容。
- 受控 `_fixture_final` 生成 96 字段、4 unknown，公开 `dushu.com` 基线生成 1256 字段、1 unknown；两份 RuntimeIR/audit 校验均为 0 issue；14/14 单测通过；registry 的 Chromium 首轮 14/14 page-state 与声明 marker 通过并生成 sidecar。
- 结构信号审计：`scripts/p1_sample_signal_audit.py` 写 `output/_p1_evidence_shadow/sample_signal_summary.json`；声明 marker 14/14 通过，并记录受控 M0/M1 与 closed-shadow truth；OCR 字符框位置审计显示 Chromium 41/57、WebKit 37/57 在 2px 内，剔除可疑合并框后最大残差 8px，仍未通过。
- WebKit 受控对比：`scripts/p1_cross_browser_compare.py` 写 `output/_p1_evidence_shadow_webkit/cross_browser_summary.json`；7/7 节点数、文本序列、结构计数和几何最大差 ≤1px 均通过；S02 初始 host 高度差已定位为 fixture display 问题并修复。
- 资产证据：受控 2 个 data URI 资产写入 `evidence/assets/` 并得到一致 SHA-256；Dushu 45 个远程图片记录为 `reference-only`，未下载。
- 早期状态与 ground truth：受控动态样本在 Chromium/WebKit 记录 M0→M1 文本变化；shadow fixture 的 closed root 由 `shadow_dom.truth.json` 声明为不可观察。
- OCR 文本探针：受控 canvas 在 Chromium/WebKit 均 2/2 命中，真实 W3Schools canvas 1/1 命中 `Hello World`；受控样本输出 2 行 bbox/confidence，真实样本 confidence 0.98；OCR 仍只产生 candidate evidence。
- 远程资产探针：httpbin PNG 经 scheme/私网/大小/MIME/魔数门禁后下载 8090 bytes，本地 SHA-256 与报告一致；结果在 `asset_downloads.json`，未改写 RuntimeIR。
- 资产 materialize：`scripts/p1_asset_materialize.py` 生成新的 sidecar 副本，更新 RuntimeIR assets、`asset-bytes-materialized` / `asset-download-report` evidence、audit 顺序与 manifest；原 sidecar 不变。
- 2026-10-20 真实状态对齐：WebKit 对 `<clipPath><rect>` 的伪非零 bbox 已从 DOM 与状态签名排除，React 从 1415/1419 恢复为 1415/1415，strict 通过；快照前增加有界字体等待、600ms 可见状态稳定窗口、瞬时探针重试与语义结构哈希。
- 并发双浏览器：React 首次 strict 通过，322/322 文本节点覆盖 100%、最大 2px；Dushu 第 1 轮轮播相位被拒绝，第 2 轮 484/484 节点、165/165 文本、相同结构哈希后 strict 通过。
- round2 成对真实矩阵：strict 3/7（S02、S04、S06），text-only content 5/7（另含 S01、S03），blocked 2/7（S05 文本数量 363/364 不一致；S07 WebKit about:blank）。S01/S03 的 strict 阻断为 iframe 计数 `5 vs 1` / `4 vs 1`。这是历史结果，见 `output/_p1_dual_sidecars/real_pair_matrix_round2.json`。
- round3 frame/导航扩面：strict 仍 3/7，content 5/7（S03、S05 为 content），blocked 2/7。frame inventory 覆盖 URL、尺寸、sandbox、同源/跨源、可访问性和 opaque 原因；同源可访问 frame 递归采集，坐标与 `framePath` 合并，跨源/sandbox opaque frame 只保留边界证据；不可渲染 tracker 不合并 DOM。见 `output/_p1_dual_sidecars/real_pair_matrix_round3.json`。
- S01 四轮尝试仍被动态广告 frame、同源子文档变化和 state-unstable 阻断；S03 最终 716/683 节点、477/477 文本，node/structure/frame scope 仍不同；S05 第 3 轮出现 `❯` 并归因 `dynamic-glyph`，第 4 轮文本 365/365、覆盖 100%，strict 仍被 frame/node/structure 差阻断；S07 经空白文档单次重导航后两端均到 GitHub login，WebKit 少 4 条登录方式文案，归因真实 DOM 状态差。
- outcome profile 单独记录 `execution_status` 与 `comparison_result`；首次 execution-ready 成对结果直接接受，不挑选后续更容易通过的轮次。S01 为 `state-unstable/inconclusive`，S06 为 `navigation-failed/inconclusive`，S07 为 `ready/different`；旧 strict/content 基线不变。见 `P1_OUTCOME_CONTRACT.md` 与 `output/_p1_dual_sidecars/real_pair_matrix_outcome_round1.json`。
- S07 条件探针使用 3 次重复 × native/交叉 UA 共 12 个有效会话。四项文案随 engine 稳定出现/缺失，交叉 UA 未改变结果，当前只记 `engine-conditioned-candidate`，`confirmed_root_cause=false`。见 `output/_p1_engine_conditions/s07_condition_probe.json`。
- 有限 frame barrier A/B：S03 文本差 `28 -> 0`、覆盖 `75.11% -> 100%`，但仍 different，node/frame 结构差仍在，耗时 `88.69s -> 113.94s`；S01 未受益。barrier 只作为显式实验参数，默认关闭，不继续泛化。见 `P1_FRAME_BARRIER_EXPERIMENT.md` 与 `output/_p1_frame_barrier/experiment_round1.json`。
- first-party frame profile：S03 节点差 `690 -> 31`、文本差 `477 -> 1`，证明跨源广告 frame 是主要噪声源；但仍为 different，equivalent 0；S05 基本不变；S01 未形成 ready 对。见 `P1_FIRST_PARTY_SCOPE.md` 与 `output/_p1_first_party_scope/experiment_round1.json`。
- S07 feature-shim round2/3 均只有 1/21 有效会话，其他被导航失败阻断；无效会话不计缺失，feature-conditioned 仍 unresolved，不能增加根因强度。见 `output/_p1_engine_conditions/s07_condition_probe_round2.json`、`s07_condition_probe_round3.json`。
- `rendered-frame-boundary-strict/1.0` 独立 A/B：S01/S03/S05 为 different `2` / inconclusive `1` / equivalent `0`，false equivalence `0`；boundary 排除不可渲染 frame 130 次、记录 opaque 不可观测项 9 个。S01 因 execution state-unstable 保持 inconclusive，S03/S05 均 different。见 `P1_RENDERED_FRAME_BOUNDARY.md` 与 `output/_p1_rendered_frame_boundary/experiment_round1.json`。
- S06 时间线：WebKit 在 `15015ms` 报 `document-request-failed: Load request cancelled`，最终 `about:blank`，无 response/commit；外层 360s 超时后从部分 capture/sidecar 恢复，分类 navigation-failure，不冒充稳定 DOM 差异。见 `output/_p1_navigation_timeline/s06_timeline_round1.json`。
- boundary authored holdout `9/9`：新增混合可访问/opaque 层级与 sandbox opaque；content changed 且 boundary equivalent `4`，false equivalence `0`，page equivalence claim `false`。见 `output/_p1_frame_boundary_holdout/result.json`。
- S06 navigation-only 2 attempts × 2 engines，4/4 observation 有效；第 1 attempt 两端主文档提交、HTTP 200，第 2 attempt 两端 `about:blank` 导航失败；primary 保留第 1 attempt，后续失败单列，不做 DOM 差异判断。见 `output/_p1_navigation_only/s06_round1.json`。
- S06 navigation-only round2 primary 为 capture-failure：Chromium worker timeout、WebKit navigation timeout；第 2 attempt 双端恢复但不替换 primary。见 `output/_p1_navigation_only/s06_round2.json`。
- S01 只读审计：9 attempts 为 capture failure `3` / execution instability `5` / navigation failure `1` / stable comparable `0`；boundary scope 3/3 attempts 有 generation drift，但 execution instability 优先，不能写成根因。见 `output/_p1_s01_generation_drift/s01_round1.json`。
- canonical 输出主目标已建立：固定 Chromium `151.0.7922.34`、Windows 11、900×700、DPR1；6 样例 SVG `5 pass + 1 partial`，视觉 holdout 5/5；Figma 已完成真实写入、节点树回读和 PNG 导出烟测。新增 data URI/受控远程资产 content hash、natural size、object-fit source rect。见 `P1_CANONICAL_OUTPUT_FIDELITY.md`、`output/_p1_canonical_output_fidelity_round16/round1.json` 与 `output/_p1_figma_canonical_frame_round1/`。
- 实际修复：tracking frame 抢用 iframe host 导致子文档偏移；flow 文本忽略 padding 且重复 paint。iframe `ink_mean 66.60→64.43`；text-flow `mean 3.14→2.86`、`ink_mean 73.98→69.29`、bad px `16582→15537`。
- 视觉 policy 先冻结后扩到 5 例独立 holdout：SVG 5/5，visual 5/5；iframe bevel、content-box offset 与 srcdoc 默认字体已修复，frame 仅保留 12 个非遮蔽差异像素。见 `output/_p1_canonical_visual_holdout_round14/round1.json`。
- data URI 与受控 loopback 远程资产均验证 content SHA-256、natural size、object-fit source rect；任意生产远程站点字节身份与 Figma 替换仍未验证。
- S07 native 导航门双端有效后，round4 小批 `7/7` 有效；feature shim 未改变四项文案，`feature_dependency_candidate=false`，继续只保留 engine-conditioned candidate。见 `output/_p1_engine_conditions/s07_condition_probe_round4.json`。
- 独立真实重采：page-state 7/7，strict 1/7、content 3/7；说明独立采集时刻仍会引入内容/字体/懒加载漂移，不能替代成对状态门。
- 文本节点对齐：S02/S04/S06 在 strict 轮次均 100% 覆盖，文本节点几何最大差分别为 2/2/1px；Dushu index-aligned 整页几何仍有 13px 最大差，不能写成整页几何等价。
- 字符框位置仍未通过验收；生产对象存储/TTL、真实 M0/M1、动态广告 frame 同步与 WebKit 登录页能力差仍待完成。

仍需补：

- 补 canonical 字体缺失、资产失败、透明叠放、图片裁剪、partial delivery 与独立视觉 holdout；
- 继续处理 text-flow 自动换行差异，并标定视觉阈值；
- Figma 已完成真实写入、回读、PNG 导出；四维验收、字体严格失败、资产替换和编辑传播仍需完成；
- 将文件级 materialize 接入生产对象存储、权限与 TTL worker。

## 4. P2-PARTIAL-DELIVERY

目标：从 P0/P1 结果生成 PARTIAL 报告、coverage map 和页面 release decision，再接入现有设计/渲染链。

仍需补：

- 真实 detector 状态，不能只注入；
- 真实报告渲染目标；
- 用户对 PARTIAL、unknown 与 blocked actions 的理解；
- 导出 gate 的真实能力边界。

## 5. P3-WRITE-LEDGER-RESUME

目标：把 D40/D44 接到 Figma bridge 与 `FigmaBridgeAdapter`。

当前能力：

- 服务端幂等键、持久 journal 和 unknown outcome：已实现 current scope；
- visibility / rename：已实现；
- 节点级删除：已有宽度按名称删除与 job-scoped marker cleanup；
- 父节点缺失：已 fail-closed；
- ownership marker：已在 `apply_batch` 创建节点上写
  `figma_auto_agent.owner + figma_auto_agent.job_id`，并由
  `ownership_report` 只读回读、`cleanup_owned_job` 精确清理。
- 真实 Figma 会话内 probe：创建 2 节点、marker 回读 2/2、清理 2/2、清理后回读 0。
- Figma development-plugin 重载后 marker 仍为 2/2，精确清理 2/2；见 `output/_r5_ownership_marker_reload_round1/`。
- 文档保存、关闭、从 Recently closed 重开后 marker 仍为 2/2，精确清理 2/2；见 `output/_r5_ownership_marker_document_reopen_round1/`。
- unknown `apply_batch` 在 BridgeHub 中保存 ownership job id/期望创建数，插件重连后自动回读 marker 并写入 journal；不自动晋升 committed。
- business ledger 已实现 JSONL planned/inflight/terminal、duplicate-job fail-closed、unknown resume 和 cleanup receipt；确定性 resume soak 为零 duplicate side effects。
- 真实 Figma controlled timeout：短 timeout 产生 1 个 unknown，正常 bridge 重启后 marker 1/1、`reconcile-no-resend`、仅 1 个 apply_batch intent、0 duplicate side effects、精确清理 1/1。
- ownership job id 已改为
  `r5job:v1:<base64url-client>:<base64url-raw-job>`；格式可解析、客户端绑定、默认拒绝裸 id。
- coordinator 在 ledger append 与 plugin dispatch 前生成 canonical id；BridgeHub 仍以
  `clientId + requestId` 做协议幂等，canonical id 作为全局 transaction key。
- business ledger 升级到 schema v2，保存 `raw_job_id` 与 `namespace_version`，并继续读取 v1 事件；
  旧 bridge/adapter/ledger 仅可通过显式 `allow_legacy_job_ids=True` 续作。
- 确定性 namespace soak：7 jobs，两个 client 使用同一 `shared-raw` 生成两个不同 job，
  2 次 bounded plugin write、0 duplicate side effects；报告在
  `output/_r5_p3_namespace_round1/r5_p3_resume_soak.json`。
- journal replay 测试证明同 raw、不同 client 的 transaction 在 bridge 重启后仍分别可查；
  adapter/coordinator resume 与 cleanup 使用 canonical id，未回退到裸 id。
- BridgeHub 对已记录的 canonical transaction 使用新 request id 的再次写入返回
  `TRANSACTION_ID_CONFLICT`，不做第二次 plugin dispatch。
- 可配置 per-client token binding：bridge 读取
  `FIGMA_BRIDGE_CLIENT_TOKENS` JSON 映射，adapter 使用
  `X-Figma-Client-Id + X-Figma-Client-Token`；身份校验发生在 cache、namespace、
  写准入和 plugin dispatch 之前。
- 配置 client tokens 时，缺失、错 token、header/payload client id mismatch 分别为
  `CLIENT_IDENTITY_REQUIRED`、`CLIENT_IDENTITY_INVALID`、
  `CLIENT_IDENTITY_MISMATCH`；token 不进入 journal。
- deterministic client identity probe 通过，证据在
  `output/_r5_p3_client_identity_round1/r5_p3_client_identity.json`。
- bridge server 与默认 adapter 配置已集中到根目录
  `figma_bridge.config.json`；host/port、timeout、journal、边界、认证、legacy、
  写节流和 client 设置均由文件提供。
- 配置 schema 为 `figma-bridge-config/1.0`，未知字段/非法类型/非法端口/空 token
  等启动失败关闭；journal 相对路径按配置文件目录解析。
- `allow_env_overrides` 默认 `false`，因此不再需要 `FIGMA_BRIDGE_*` 启动环境变量；
  只有显式开启时才保留环境覆盖兼容路径。
- per-client admission：`client_write_defaults` / `client_write_limits` 配置
  `max_inflight`、`burst`、`min_interval_ms`，按已验证 `clientId` 隔离。
- 单 client 超限返回 `BRIDGE_CLIENT_RATE_LIMITED/not-applied`，拒绝发生在 journal
  intent 与 plugin dispatch 之前；token refill 等待不持有全局 dispatch lock。
- token bucket fairness 测试证明一个 client burst 耗尽时，另一个 client 可先行
  dispatch；报告在 `output/_r5_p3_client_fairness_round1/r5_p3_client_fairness.json`。
- `figma_bridge.config.json` 支持 server/client TLS：证书/私钥、CA、客户端证书、
  verify 和 `wss://` URL；默认关闭。
- server 使用真实 `SSLContext`，adapter 使用 `sslopt`；本地 loopback wss
  handshake + round trip 通过，证据在 `output/_r5_p3_tls_round1/r5_p3_tls_probe.json`。
- `/plugin` 支持首帧 token handshake；`server.plugin_token` 为空时保持本地可选认证，
  配置后缺失/错误 token 在 attach 前关闭，close code `4003`。
- Figma UI 通过 `figma.clientStorage` 保存 bridge URL 与 plugin token；token 不进入 URL。
- plugin token provider 在新连接时读取最新统一配置文件；旧 token 在 rotation 后拒绝，
  新 token 接受；错误新连接不会替换当前 active plugin。
- deterministic plugin auth probe 通过，证据在
  `output/_r5_p3_plugin_auth_round2/r5_p3_plugin_auth.json`。
- active plugin token 变化/清空时以 `4004` 撤销；错误新连接不能驱逐当前插件，
  正确新 token 可以接管。
- 真实 Figma plugin UI：token 经 clientStorage 保存，关闭插件后 quick actions
  重开，token 自动恢复并重连成功，证据在 `output/_r5_p3_real_plugin_ui_round1/`。
- 本地真实 wss + first-frame auth + command round trip + old token revoke +
  new token reconnect 全部通过，证据在
  `output/_r5_p3_tls_plugin_auth_round2/r5_p3_tls_plugin_auth.json`。
- transaction payload 显式标记多人 attribution `unavailable/unknown`；
  current-state match 不提升 actor/revision，也不自动 resend，证据在
  `output/_r5_p3_multiplayer_attribution_round2/`。
- `AttributionProvider` 已留扩展桩；默认 `UnavailableAttributionProvider` 只返回
  unavailable，provider 异常也 fail-closed，不伪造 actor/revision。
- `env:` / `file:` secret references 已实现；`security` 可要求引用和私密文件权限，
  Windows 使用保守 `icacls` 检查，无法确认时 fail-closed。
- `scripts/rotate_figma_bridge_config.py` 提供同目录临时文件、完整校验、fsync、
  `os.replace` 原子 rotation；报告不含 secret。
- 真实 Figma UI 已验证 4004 revocation 提示、旧 token 停止重试、新 token 恢复；
  测试 token 已从 config/clientStorage 清空，证据在
  `output/_r5_p3_real_plugin_revocation_round2/`。
- 统一配置新增严格 `ledger` 段：`path`、`max_events`、
  `terminal_retention_days`、`compact_min_events`、`allow_legacy_read`；
  unknown/missing 字段、非法边界和 `compact_min_events > max_events` 均 fail-closed。
- `WriteJobLedger.from_bridge_config()` 使用同一配置；相对 ledger path 按配置目录解析。
- terminal（`committed/rejected/rolled-back`）超过保留期后只压缩历史，保留最新
  fingerprint、ownership、resume decision、node ids 和 cleanup receipt；
  `planned/inflight/unknown/resume-required/rollback-incomplete` 永不自动删除。
- compaction 使用同目录临时文件、`fsync`、完整候选解析/状态校验和
  `os.replace`；注入 replace 失败时旧 ledger 字节不变。torn tail 忽略，
  interior corruption fail-closed。
- `scripts/migrate_write_job_ledger.py` 提供 legacy business ledger 迁移：
  默认 dry-run、显式 legacy client id -> target client id mapping、冲突检测、
  atomic apply。同 raw id 的不同 legacy client 生成不同 namespace。
- 迁移报告只包含字段名、计数和 source/candidate/report hashes，不包含 action
  payload、text、secret、raw id 或 source client id。
- deterministic evidence：8 source events、6 migrated jobs、compaction 8 -> 7、
  5 protected jobs、cleanup receipt/fingerprint conflict 保持；报告在
  `output/_r5_p3_ledger_lifecycle_round1/report.json`，content hash
  `cd6dcef35fab8bde8eef3a74eb8cafab7cc77ff24e428edf8f7f851b5ab86cb3`。

生产准入仍阻塞：

- 默认无 token 配置仍为匿名开发模式；生产部署必须显式启用 per-client mapping。
- 自动 certificate provisioning、系统 trust store 和跨团队 token 撤销通知仍未完成。
- 真实权限、限流、用户接管与同名并发。
- 真实两名 Figma collaborator 的 actor/revision 归因仍不可得，需人工复核策略。
- 跨进程 ledger compaction fencing、terminal purge 策略，以及旧 Figma
  marker/bridge journal 是否需要独立迁移。
- 配置文件包含真实 secret 时的文件权限、secret manager 与轮换流程。

当前范围已完成，但不得把 R5-EXP-02 写成生产事务或并发安全。

重新评估：`R5_PRODUCTION_REASSESSMENT_2026-10-22.md`。

## 6. P4-PERSISTENCE-OPERATIONS

目标：将文件级 IR 实验替换为生产存储、权限、TTL worker、迁移与监控。

需要决策：

- 数据库/对象存储后端；
- evidence TTL 与 audit metadata TTL 的组织政策；
- tombstone/compaction；
- 权限模型与审计访问；
- 备份、恢复、监控和迁移版本矩阵。

P0 的纯 schema 可以先做，但生产存储不能在没有这些决策时开工。

## 7. P5-PILOT-E2E

目标：在受控真实页面上完成：

```text
采集 -> 字段裁决 -> PARTIAL/coverage -> materialize -> 真实 Figma 写入
-> readback -> 四维验收 -> limited pilot release
```

只允许 `pilot-allowed-provisional`，不能升级生产；失败、unknown、partial 必须保留。必须有操作员、人工复核和恢复脚本。

## 8. 推荐执行顺序

1. P0 contract core；
2. P1 evidence adapter；
3. P2 partial delivery + P4 storage contract can start after P0, but not as default path;
4. P3 ownership/ledger/resume integration；
5. P5 bounded pilot.

## 9. 不得宣称

- 不得把 `ready-to-implement` 写成已实现。
- 不得因为 P0 是纯合同就绕过生产权限/存储/导出评审。
- 不得先改真实 Figma 写入再补合同。
- 不得用面积、平均分或 masked diff 替代 four-dimensional gate。
- 不得把 R5 实验通过写成生产准入。
- 不得遗漏 `R5_GATE_MATRIX.md` 中的 conditional 项；只有对应产品承诺进入
  发布范围时才升级为阻塞项。
- 不得把当前范围状态写成项目级布尔验证结论。
