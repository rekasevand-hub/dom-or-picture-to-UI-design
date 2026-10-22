# P2-P4 Residual Risks

> 更新时间：2026-10-22  
> 状态：`tracked / not-verified`  
> 说明：这些是当前范围完成后仍然存在的可识别风险，不等于已准入 bug，也不允许被其他通过维度抵消。

生产准入处置已在 `R5_PRODUCTION_ADMISSION_DECISION.md` 中逐项复核。当前
决策为 `not-admitted`；RR-004 至 RR-015 仍是阻塞项，RR-001 至 RR-003
只在对应产品承诺进入发布范围时阻塞。

## RR-001 任意 Variable Axis

- **风险**：Figma 当前只暴露命名实例；请求的任意 `wght`、光学尺寸或其他 axis 可能被近似到最近命名实例。
- **当前证据**：`350 -> Semilight Text` 可匹配；`650 -> Semibold Text`，但无法证明 650 axis 精确。
- **影响**：文字内容/可编辑性可保留，字形和度量可能不完全一致。
- **当前处置**：保留 `fontWeightValue`，选择名称最接近的命名实例；任意 axis 标记 unsupported。
- **升级条件**：需要承诺 CSS variable font 精确复现，或 Figma API 暴露可写 variation settings 时。

## RR-002 逐 Glyph Fallback Split

- **风险**：同一段混排文本可能由多个平台字体渲染，当前只能记录平台字体集合，不能证明每个字符对应的最终 face/glyph。
- **当前证据**：Chromium 可观测到 `Arial + Noto Sans SC`，DesignSpec 保持 `ambiguous-platform-font`，Figma generic fallback 为 Inter。
- **影响**：整段文本可保持原生可编辑，但 mixed-script glyph identity 未通过。
- **当前处置**：fail-closed，不将 ambiguous fallback 晋升为单一 face。
- **升级条件**：必须支持逐字符 face 归属，或允许显式 run split + manual/automated verification。

## RR-003 Firefox 字体渲染

- **风险**：Chromium/WebKit 的结果不能外推到 Firefox 的字体选择、fallback、行盒和栅格化。
- **当前证据**：Playwright Firefox 启动失败：`BrowserType.launch: spawn UNKNOWN`。
- **影响**：跨浏览器输出保真未覆盖 Firefox。
- **当前处置**：标记 `environment-blocked`，不用 Chromium/WebKit 结果替代。
- **升级条件**：修复 Firefox 运行环境并建立独立字体/几何基线。

## RR-004 真实站点持续稳定性

- **风险**：受控 canonical holdout 不能保证真实站点在登录态、广告、CDN、动态内容、A/B 实验和不同时间下长期稳定。
- **当前证据**：React/Dushu 在当前 comparison profile 下为 equivalent；Shoelace 为 structure different；W3Schools iframe 为 state-unstable/inconclusive。
- **影响**：不能把单次真实站点 equivalent 当成普遍生产准入。
- **当前处置**：真实站点只做独立外部有效性观测，不进入 P3/P4 生产准入分数。
- **升级条件**：需要冻结 profile、固定采样计划、持续观测周期和失败分类。

## RR-005 Grid 组合空间未闭合

- **风险**：生产 bridge 已支持固定/`FLEX`/`HUG` 轨道、手动/自动流、跨度、对齐和尺寸策略，但真实探针只覆盖固定轨道、手动定位、跨列与 `FILL`。
- **当前证据**：
  - `output/_p3_grid_layout_round2/figma_grid_layout_probe.json` 通过固定 track、手动定位和跨列；
  - `output/_p3_grid_complex_holdout_round1/figma_grid_complex_create.json` 通过嵌套 Grid、长文本、图片、`FIXED/FLEX/HUG` 混合和 `ROW_AUTO_FLOW`；
  - 同一报告目录的 `figma_grid_complex_verify.json` 在插件重载和真实 Figma 标签关闭/最近关闭项重开后均为零差异，最终上下文为 `document-reopen`；
  - 自动 track 超出显式 row count、跨版本回读及更多组合仍未验证。
- **影响**：不能把复杂组合探针和文档重开回读写成 Figma adaptive Grid 全局等价。
- **当前处置**：未覆盖组合保持 unsupported/not-covered；参数非法时在写入前 fail-closed。
- **新增处置**：Grid 维度先写列后写行，未变化维度不重复写入；跨度/对齐更新走 `set_grid_child_overrides`，避免重写父 Frame 尺寸。
- **升级条件**：完成跨版本回读，并为剩余 track/span/自动扩展组合建立独立 holdout。

## RR-006 真实 Figma 故障类别未闭合

- **风险**：真实 Figma Grid 运行时约束错误已能完整回滚，但上传/网络中断、多人协作冲突、Figma 进程终止和 API 版本异常仍未覆盖。
- **当前证据**：
  - `output/_p3_runtime_fault_round1/figma_runtime_fault_probe.json` 通过；
  - 同一事务先改文本，再触发真实 Figma `set_gridColumnSpan` 邻列占用错误；
  - 修复后 `rollback 2/2`、零失败、文本和布局快照一致；
  - 首次真实运行曾返回 `rollback-incomplete`，暴露失败动作未入栈和 Grid anchor 恢复方式错误；两项均已修复。
- **影响**：真实运行时约束错误已闭合；网络中断、协作冲突和版本异常仍可能产生 unknown 或 incomplete recovery。
- **当前处置**：编辑动作应用前入栈快照；失败动作也参与反序恢复；Grid anchor 使用 `setGridChildPosition`；返回逐节点 rollback 明细。
- **升级条件**：需要协作冲突、上传中断、进程终止和 API 版本异常的真实演练。

## RR-007 Bridge 持久 Journal 的单进程与实时对账边界

- **风险**：bridge 已有 JSONL write-ahead journal、本地单实例锁、unknown 事务 readback 和哈希化意图匹配，但没有跨主机 fencing 或并发协作者下的提交归因；readback 只证明当前状态与意图的关系，不证明写入归属。
- **当前证据**：
  - `tests/v2/test_bridge_protocol.py` 35/35 通过（加入写队列满、dispatch 间隔、reconnect 降级、unknown create ownership readback 和 timeout 配置用例后）；
  - 完成幂等响应、payload 冲突和事务终态均可跨 hub 重建恢复；
  - 未闭合 intent 在重启后返回 `REQUEST_OUTCOME_UNKNOWN` 且不重发 plugin；
  - 损坏尾行可忽略，journal 压缩保持有界；
  - 本地 `.lock` 阻止第二个 bridge 实例启动，首个进程停止后可重新获取；
  - unknown `apply_edit_batch` 在插件重连后自动读取目标节点树，readback 写入 journal 并可跨重启查询；
  - 文本/name 期望值以 SHA-256 保存，visibility 使用 boolean；readback 分类为 matches/partial/mismatch/indeterminate。
  - 1000 请求 / 32 并发 soak 零失败、零 pending、journal `180/256`、重启回放 128、traced peak `2.077 MiB`。
  - 两轮各 60 秒真实 Figma readback soak 合计 50,136 请求、0 失败；bridge RSS `81.875 -> 80.707 MiB`，handles `396 -> 388`。
  - 真实写事务：未限速 4 写入器在约 169 次后出现 4 个 timeout/unknown；单写入器 50ms 节流后 347/347 committed。
  - 服务端写闸门已实现：写命令在 intent 前取得有限队列槽位，单写者保持到终态，实际 dispatch 后满足最小间隔；读命令不经过写闸门。
  - 背压拒绝返回 `BRIDGE_WRITE_BACKPRESSURE/not-applied` 和 `retryAfterMs`；已发送写 timeout 后，新写保持拒绝直到插件重连。
  - 320 请求 / 16 worker 无客户端 sleep 的确定性 soak 为 320/320 完成、零 unknown、plugin 写并发恒为 1，content hash `ac1ca01c1cacc6dccd16249667414a5eb04d99b30cbcb36c7422911168c346f2`。
  - R5-P3 ownership marker current scope：创建节点写入 `figma_auto_agent.owner + figma_auto_agent.job_id`，`cleanup_owned_job` 只删除双 marker 精确匹配节点；不同 owner/job 的节点保留。
  - 真实 Figma 会话内 probe 已通过：创建 2 节点、marker 回读 2/2、精确清理 2/2、post-cleanup 0；create/verify/cleanup hash 分别为 `a26236a5…`、`b9f43a2b…`、`e5589b2b…`。
  - development-plugin 重载后 marker 回读仍为 2/2、清理 2/2、post-cleanup 0，create/verify/cleanup hash 为 `c07563cc…`、`8729525d…`、`0f2a8de6…`。
  - 文档保存、关闭、从 Recently closed 重开后 marker 仍为 2/2、清理 2/2、post-cleanup 0，create/verify/cleanup hash 为 `749f35fe…`、`a5fdeea2…`、`66746959…`。
  - 当前已证明开发插件重载和文档重开后的 plugin-data 持久化；多人协作 ownership 仍不能据此闭合。
  - unknown `apply_batch` 的 intent 已保存 ownership job id 与期望创建数；插件重连后自动回读 marker，分类完整/部分/缺失/不可判定，但 transaction 仍保持 unknown，不自动重发。
  - R5-P3 business ledger 已实现 fsync JSONL、duplicate job fail-closed、write-ahead planned/inflight、unknown complete ownership 的 `reconcile-no-resend`、partial/absent manual review 和 cleanup receipt。
  - 确定性 soak：6 jobs、1 committed、1 reconciled、3 manual、0 duplicate side effects、content hash `227076774d5c258d1d9a4ff8bd880b5adf0240a87d041c68739d742f617cbc8d`。
  - 真实 Figma controlled timeout：1 unknown、1 apply_batch intent、marker 1/1、`reconcile-no-resend`、0 duplicate side effects、清理 1/1、post-cleanup 0，content hash `50704b1647c5d266517046526eaa411a9e7ff8c5e53bf23ca728522f60543d29`。
  - ownership namespace 已实现：`r5job:v1:<base64url-client>:<base64url-raw-job>`；coordinator、adapter、BridgeHub 和 business ledger 默认拒绝裸 id，显式 legacy opt-in 才可续作旧状态。
  - BridgeHub 保持 `(clientId, requestId)` 幂等域，canonical job id 作为 transaction key。创建、ledger、resume、cleanup 和 journal replay 均使用 canonical id。
  - 已记录 transaction 换新 request id 重用会在 plugin send 前返回 `TRANSACTION_ID_CONFLICT`；coordinator 对已存在非 planned job 不做第二次 dispatch。
  - transaction payload 现在显式返回 `attribution.status=unavailable`、actor/revision `unknown`；协同者造成相同当前状态时，readback 仍不能证明写入 actor，transaction 不自动晋升或重发。
  - 确定性 namespace soak：7 jobs、2 committed（不同 client 使用同一 raw id）、1 reconciled、3 manual、2 次 bounded plugin write、0 duplicate side effects；content hash `813428fe2c380a104650c1d1ab67d8951adcbb3b8a8cbe1d7ec8ca516a0f190e`，证据在 `output/_r5_p3_namespace_round1/`。
  - R5-P3 当前范围已闭合，但生产准入仍被 authenticated client identity、多人协作归因、权限/限流/用户接管阻塞。
- **影响**：本地单 bridge 崩溃后可阻止盲目重放、重复实例，并判断当前状态是否匹配意图；并发协作者可能造成相同结果，提交归因仍未闭合。
- **当前处置**：写调用必须携带稳定 `clientId + requestId`；intent 在 plugin send 前 `fsync`；日志 replay 前获取独占锁；unknown 保持 unknown，只附 readback 和 intent-match 证据；服务端单写者闸门限制 plugin 队列增长。
- **升级条件**：需要并发协作者归因、image/layout 完整 expected-state 合同、跨主机 fencing、人工解决协议，以及电源/网络文件系统故障测试。

## RR-008 多客户端隔离依赖单插件串行队列

- **风险**：服务端已隔离 client/request 关联并对插件命令串行化，但仍然是单 Figma 文档、单插件连接；多人实时编辑和跨文档并发不在保证内。
- **当前证据**：并发 socket、重复 request id、插件队列和多客户端测试通过；`/command` 可选 Bearer 认证已实现；未做多人协作冲突或跨文档路由。
- **新增证据**：服务端写闸门为进程内全局写队列，所有 `/command` socket 共享；只读命令可在写等待期间旁路执行；背压失败在 plugin send 前发生。
- **namespace 证据**：create batch、ledger、resume、cleanup 与 bridge journal replay 已覆盖同 raw id 的双 client 隔离；默认裸 id 在 dispatch 前失败。
- **影响**：不能把当前隔离写成多租户生产隔离。
- **当前处置**：同请求号按 `clientId` 分域；ownership job id 同样按声明 `clientId` namespace；非法复用、namespace/client mismatch、超限和连接变化 fail-closed；配置 token 后 `/command` 缺失或错误凭据直接拒绝；写请求超限返回可重试的安全拒绝。
- **升级条件**：需要 TLS、`/plugin` 认证、文档租户路由、授权策略和协作冲突策略。

## RR-009 服务端写节流的真实有效性与公平性

- **风险**：服务端写闸门已通过确定性 soak、per-client fairness probe 和 60 秒真实 Figma 四写入器复测，但 60 秒和单进程证据不能外推到 24h/7d、跨主机或 Internet-scale 公平性。
- **当前证据**：
  - 16 worker / 320 请求、无客户端 sleep：320/320 完成，零安全拒绝、零 unknown，plugin 写并发恒为 1，`p50=266.656ms`、`p99=321.405ms`。
  - 4 槽刻意饱和 / 16 worker / 240 请求：240/240 完成，32,218 次 safe rejection 全部以同 request id 重试，零 unknown；`p99=3891.153ms` 足以说明饱和长尾仍明显。
  - 真实 Figma 4 writer / 零客户端 sleep / 60 秒：960/960 committed，零 timeout/unknown，`p50/p95/p99=250.273/262.553/267.832ms`，content hash `6dc0196659991c1e2dc477ce3cd267c82e1621a4bf6f55904b36ecee8e5a724c`。
  - 同一真实运行发生一次 deliberate reconnect 的 keepalive-close 栈跟踪，但该 worker 重连成功，所有命令完成。
  - Windows 事件循环对短 sleep 存在约 15–16ms 的提前唤醒粒度；写闸门已改为条件式循环等待，未再出现低于 `not_before` 的 dispatch。
  - 报告：`output/_p4_write_backpressure_round1/write_backpressure_soak.json`、`output/_p4_write_backpressure_round2/write_backpressure_soak.json`。
  - per-client fairness：一个 client `max_inflight=1` 时第二个请求在 journal intent 前返回 `BRIDGE_CLIENT_RATE_LIMITED`，另一个 client 正常完成；burst 耗尽的 client 等待 refill 时，另一 client 可先 dispatch。content hash `7e06cc0f77028842b9fa3553d2e3ffcdc3d934d59cead73c94525c9525ce3877`。
- **影响**：确定性结果证明超限可变成 not-applied，且单进程内不会被单一 client 永久占满全局队列；仍不能承诺跨进程、跨主机或长时无饥饿。
- **当前处置**：全局最小间隔 50ms、队列 16、等待 5s；per-client 默认 admitted 4、burst 4、仅在有显式 rate 配置时启用 refill interval；背压/限流返回 `retryAfterMs`；已发送写 timeout 后保持 degraded，直到插件重连。
- **升级条件**：加入跨进程/跨主机公平性、长尾指标与 24h/7d 持续写入证据，并关闭或解释 reconnect keepalive 日志噪声。24h/7d 已明确延期到用户云服务器执行，计划与准入门槛记录在 `P4_LONG_SOAK_BACKLOG.md`。

## RR-010 ClientId 可冒充导致 Namespace 冲突

- **风险**：默认未配置 per-client token 时，调用方仍可声明任意 `clientId`，从而与其共享 namespace 和 transaction 域。配置 token 后，错误部署、secret 泄露或缺失轮换仍可破坏身份边界。
- **当前证据**：`figma_bridge.config.json` 的 `server.client_tokens` 可配置 `clientId -> token`；adapter 从 `client` 段读取身份并发送 client id/token header；BridgeHub 在 cache、namespace、写准入和 dispatch 前校验。deterministic probe 覆盖 missing/wrong/mismatch/valid，并确认 secret 不进入 journal；报告 content hash `3289725b55042212dc6c9756db4cda06b6727e8155cc8ceffd337452ba3008e0`。
- **影响**：配置正确时可阻止无 token 的 client-id 冒充，但默认匿名开发模式、明文 transport、`/plugin` 未认证和 token 轮换仍不构成生产安全边界。
- **当前处置**：默认仍为匿名本地开发；生产配置必须显式启用 per-client mapping；token 使用 constant-time comparison；identity 错误均 fail-closed；token 不写入报告或 journal。
- **升级条件**：需要 TLS、secret provisioning/rotation、`/plugin` 认证、默认生产 fail-closed 配置和部署期配置审计。完成前不得宣称默认模式或全局安全 namespace。

## RR-011 Bridge Secret 管理与 Rotation

- **风险**：直接 secret 仍有误提交/误读风险；secret reference 指向的环境或文件也需要权限、轮换和泄露响应。
- **当前证据**：支持 `env:` / `file:` references；`security.require_secret_references` 可禁止直接 literal；`require_secure_file_permissions` 对 config 和 file secret 检查 POSIX mode/Windows `icacls`；atomic rotation script 失败不覆盖旧文件，报告不含 secret。
- **影响**：可以直接使用较安全的引用与原子轮换，但 ACL 解析是保守 best-effort，尚未接外部 secret manager。
- **当前处置**：默认允许 local direct secrets；生产应启用两个 security 选项；不能用 broad Users/Authenticated Users 读权限保存 literal secret。
- **升级条件**：需要 secret manager/KMS、自动 ACL 修复、轮换审计和泄露响应演练。

## RR-012 TLS 证书生命周期与生产信任

- **风险**：TLS 代码路径和本地 handshake 已实现，但生产证书签发、CA 分发、过期/轮换、主机名校验和私钥权限尚未定义；测试自签名证书不能作为生产信任策略。
- **当前证据**：配置支持 server cert/key/CA、client verify/CA/客户端证书；本地 loopback wss handshake 与 round trip 通过；TLS + plugin auth + token rotation + reconnect 联合 probe 通过，报告 `output/_r5_p3_tls_plugin_auth_round2/r5_p3_tls_plugin_auth.json`。
- **影响**：可以安全地做受控本地 TLS 验证，但不能据此宣称默认生产 transport 安全。
- **当前处置**：TLS 默认关闭；启用时严格校验文件存在和 client `wss://`；私钥不进入 probe 报告或 bridge journal。
- **升级条件**：需要证书 provisioning/rotation、系统 trust store、主机名策略、私钥 ACL、吊销/泄露响应，以及在 TLS 上重跑完整 timeout/write-pacing/plugin reconnect 矩阵。

## RR-013 Plugin Token 生命周期与失效恢复

- **风险**：`/plugin` 首帧认证、active-token revocation、UI save/reopen 和 revocation/recovery 已实现，但批量 clientStorage 清理、操作员通知和自动 provisioning 尚未产品化。
- **当前证据**：Python probe 覆盖 missing/wrong/valid、旧 token rotation 后拒绝、新 token 接受，错误认证 close code `4003`；active token 变化/清空时旧连接以 `4004` 关闭；错误新连接不会替换 active plugin；真实 Figma UI 保存/关闭/重开插件后 token 恢复并重连；Node storage test 通过。报告 content hash `86a1859a1f17ca2588f7c27bf789d11fd8dcfab3630dd58a522876df86c80027`。
- **影响**：配置正确时可以阻止未授权替换并撤销存量连接，UI 也会停止旧 token 重试；跨团队轮换通知仍需人工。
- **当前处置**：token 不进入 URL 或 bridge journal；空 token 保留本地开发兼容；错误认证在 socket attach 前关闭；UI 提供 Save and connect。
- **升级条件**：需要 revocation notification、clientStorage 批量清理、自动 rotation 调度与审计；UI 错误恢复和真实 Figma revocation/recovery 已通过 current scope。

## RR-014 多人协作写入归因不可得

- **风险**：Figma Plugin API 不提供可靠的写入 actor/revision；两个协作者产生相同当前状态时，bridge 无法判断原始写入属于谁。
- **当前证据**：transaction payload 通过 `AttributionProvider` 扩展桩显式返回 `attribution.status=unavailable`；默认 provider 永不伪造 actor/revision，异常也 fail-closed；deterministic probe 证明 current-state match 不证明 actor、transaction 仍为 unknown、不会自动重发；双 client namespace 继续隔离。证据 `output/_r5_p3_multiplayer_attribution_round2/r5_p3_multiplayer_attribution.json`。
- **影响**：不能承诺 collaborator-safe commit attribution，也不能把匹配 readback 写成 actor 证明；冲突必须保留人工复核路径。
- **当前处置**：actor/revision 保持 unknown；readback 只作为当前状态证据；unknown 不自动 replay；namespace 和 client token 只隔离应用客户端，不冒称 Figma 协作者身份。
- **升级条件**：需要 Figma 提供权威 actor/revision，或引入外部协作审计源、操作员确认和可验证冲突解决流程；在此之前只能声明 `attribution-unavailable-by-contract`。

## RR-015 Write Job Ledger 保留、压缩与迁移边界

- **风险**：business ledger 已支持 terminal 历史压缩和 legacy 迁移，但 compaction 只有实例内锁；没有跨进程文件锁/fencing。`max_events` 是压缩触发阈值，不是可删除 unknown/nonterminal 的硬上限。迁移工具只处理 business ledger，不重写 Figma plugin-data marker 或 bridge journal。
- **当前证据**：`figma_bridge.config.json` 的严格 `ledger` 段覆盖 path、max events、terminal retention、compact minimum 和 legacy read；`WriteJobLedger.compact()` 只压缩过期 terminal 历史并保留最新 cleanup receipt/fingerprint/resume 字段；注入 `os.replace` 失败时原文件字节不变；migration dry-run/apply、双 client 同 raw id、映射冲突和报告净化均有测试。证据 `output/_r5_p3_ledger_lifecycle_round1/report.json`，content hash `cd6dcef35fab8bde8eef3a74eb8cafab7cc77ff24e428edf8f7f851b5ab86cb3`。
- **影响**：单进程可控运行可以把历史压缩到最新 terminal 快照且不改变 unknown no-resend/cleanup 语义；多进程同时 append/compact、最终数据清除政策、磁盘满、网络文件系统和 marker/journal 历史迁移仍未验证。
- **当前处置**：只允许单 writer 使用 compaction；nonterminal/unknown 永不由自动保留策略删除；迁移默认 dry-run，必须显式 client mapping 和 `--apply`；冲突/非法源文件保持原文件不变。
- **升级条件**：需要跨进程锁或单 writer fencing、长时故障注入、terminal purge 合规决定、备份恢复演练，以及决定 marker/bridge journal 的迁移或保持 legacy read 路径。

## 管理规则

- Residual risk 不得被 visual/structure/edit/asset 任一其他维度的通过所抵消。
- 每次发现新证据时追加记录，不覆盖旧证据。
- 只有形成可测试规则、稳定参数或冻结 policy 后，才将风险提升为正式实现任务。
- 观察型风险与硬门禁风险必须分开报告。
