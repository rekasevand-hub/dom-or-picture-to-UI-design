# R5-EXP-06 · IR 持久化、TTL、迁移与重放

> 状态：`completed-for-current-scope`（2026-10-19），不是 `verified`。  
> 范围：12 个文件级 case、54 个事件；21/21 合同检查通过，32/32 定向负向变异被拒绝；连续 2 次运行得到相同 `content_hash`。  
> 证据：`output/_r5_experiments/r5_exp_06_ir_persistence/result.json`、`runtime_ir.json`、`audit_bundle.json`、`replay_results.json`、`migration.json`、`retention.json`、`events.json`、`store/` 与 5 张结果图。  
> 边界：本实验使用本地文件存储和模拟事件注入；不是生产数据库、WAL、对象存储、权限服务或真实进程崩溃测试，也不连接 Figma。

## 1. 目的与边界

本实验回答 `R5-Q06`：生产 IR 能否分别回答：

- 为什么选这个值；
- 是否写入；
- 是否被验证；
- 是否还能按原证据复现；
- 证据过期、权限撤销或 schema 升级后还能做什么、不能做什么。

本实验验证：

- 写前持久化失败零副作用；
- 发出后崩溃、未落盘结果与 `resume` 对账；
- evidence TTL 失效；
- 临时资产 URL 过期但本地字节仍可用；
- v1 → v2 schema 迁移；
- tombstone、权威链、顺序映射与 unknown 状态保留；
- 未知枚举失败关闭；
- 权限撤销；
- 跨页面引用失效；
- `audit-replay / materialize-replay / recapture-reconcile` 三种语义分离；
- 离线 audit bundle 不被当成 runtime DAG。

本实验不验证：

- 生产数据库事务、WAL、对象存储一致性或分布式锁；
- 真实进程崩溃、网络分区、操作系统掉电或文件系统损坏；
- 真实 TTL 清理服务、权限服务或跨页面引用仓库；
- 真实 Figma 文档、字体环境和像素级 materialize；
- 生产 IR 实现、监控、保留政策审批或法规合规。

## 2. 环境与可复现性

| 项目 | 值 |
|---|---|
| 操作系统 | Windows 11 |
| Python | 3.12.0（`C:\Users\lzq\.conda\envs\omni\python.exe`） |
| 依赖 | 标准库 + `Pillow`、`matplotlib` |
| Figma / bridge | 未连接 |
| case 数 | 12 |
| 事件数 | 54 |
| 合同检查 | 21/21 |
| 负向变异 | 32/32 被拒绝 |
| replay evidence TTL | 30 天 |
| audit metadata TTL | 180 天 |
| 连续运行 | 2 次 |
| 最终 `content_hash` | `127fe5b3f9ee3c3c62c93e918170d033e992fd14ad64904fac008dfa54010b03` |

重跑命令：

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe scripts\r5_exp_06_ir_persistence.py
```

脚本只清理并重建：

```text
output/_r5_experiments/r5_exp_06_ir_persistence/
```

实验使用固定时间 `2026-10-19T00:00:00+00:00`，所以 TTL 与事件顺序可复跑。

## 3. 方法

### 3.1 文件级存储

脚本实际写入：

- runtime IR；
- audit bundle；
- DOM/render evidence JSON；
- PNG 资产字节；
- 每 case 的事件顺序；
- v1/v2 快照；
- replay/migration/retention 结果。

写入使用同目录临时文件、`fsync` 和 `os.replace`。写前失败注入会在 final replace 之前删除临时文件并返回失败，不留下 final snapshot。

### 3.2 Runtime IR 与 Audit Bundle

| 对象 | 外层 schema | 语义 |
|---|---|---|
| Runtime IR | `runtime-ir/1.0` | 可执行依赖 DAG、preconditions、write state、recovery |
| Audit bundle | `audit-bundle/1.0` | `ordered-audit-only`，无 runtime execution graph |

两者共享字段、证据、决策、权威链、tombstone、unknown 与版本字典，但审计顺序不能自动变成运行时依赖。

### 3.3 三种重放语义

| 模式 | 输入 | 输出语义 |
|---|---|---|
| `audit-replay` | 历史决策链与证据可用性 | 证据完整时可重演决策；不完整时只输出摘要 |
| `materialize-replay` | 锁定证据、policy、plan、本地资产字节 | 生成语义输出；不保证环境变化后逐像素一致 |
| `recapture-reconcile` | 重新采集的来源 | 新 capture/revision，不是历史重放 |

发送后崩溃的恢复记录为 `resume`，不是以上三种 replay。

### 3.4 TTL

- 终态 replay evidence：30 天；
- 最小脱敏 audit metadata：180 天；
- 外部临时 URL 与本地资产字节分开；
- 证据过期后保留 hash 与摘要，但不把 hash 当原证据；
- 本地资产仍在且 hash 匹配时，不需要读取过期 URL。

## 4. 结果

### 4.1 Case 结果

| Case | 结果 |
|---|---|
| `preflight-persist-failure` | `blocked-persistence`，side effects 0，无 final runtime snapshot |
| `after-send-crash` | `committed-after-reconcile`，1 个副作用，0 重复创建，未重发 |
| `clean-replay` | audit exact、materialize 成功、recapture 生成新 capture |
| `evidence-ttl-expired` | audit `summary-only` / `evidence-unavailable`，materialize 阻断，recapture 新 revision |
| `asset-url-expired-local-bytes` | URL 已过期，但本地 601-byte 资产仍在；materialize 使用 local bytes，外部请求 0 |
| `schema-upgrade-v1-v2` | v1→v2 迁移完成，原快照保留 |
| `tombstone-migration` | tombstone、pending 删除、unknown、权威链、顺序映射全部保留 |
| `unknown-enum` | 失败关闭，不默认 winner |
| `permission-revoked` | audit 只读摘要；materialize 与 recapture 阻断 |
| `cross-page-reference-invalid` | 失败关闭，未进入 replay |
| `audit-runtime-separation` | audit 无 runtime DAG；runtime 有 execution graph |
| `materialize-environment-changed` | `materialized-revalidation-required`，不保证像素一致 |

### 4.2 关键恢复证据

写前失败：

- final runtime snapshot 不存在；
- `side_effect_count=0`；
- write orchestrator 未发送命令。

发送后崩溃：

- intent 与 IR 已先落盘；
- remote 侧只有 1 个创建；
- resume 读取 remote state 后提交；
- `duplicate_create_count=0`、`resent=false`。

### 4.3 TTL 与资产

TTL 过期证据：

```text
evidence_id = ev-dom
availability = evidence-unavailable
file_exists = false
expires_at = 2026-10-01
```

即使 metadata 中保留 SHA-256，`materialize-replay` 仍为 `blocked-evidence-unavailable`。`audit-replay` 只输出 summary hash，`exact_replay=false`。

资产 URL：

```text
URL expiry = 2026-10-10
local bytes = present
local retention expiry = 2027-01-17
materialize asset_source = local-bytes
external URL fetch count = 0
```

### 4.4 迁移

v1→v2：

```text
source content hash  = 3cb2bd1c1475e7b6f17852c0906b846cca5d1b73e61e01ec8137f91ea105f555
migrated content hash = 2330f75f88d9b4ce79bdca1e0c26cf7100f661ae4bdcc105d7b45cce9e858006
```

以下均保持 exact structural equality：

- fields + observations；
- authority chains；
- order mapping；
- tombstones；
- unknown state；
- evidence metadata。

原文 v1 快照保留，新 v2 是独立副本并记录 migration chain。tombstone 的 scope、authority version、`delete_status=pending` 与 `not_deleted=true` 未改变。

### 4.5 未知枚举与引用

- `field-badge` 的 `future-unknown-enum` 触发未知枚举错误；
- 没有回填默认 winner；
- 必填 `capture-missing` 跨页面引用失败关闭；
- 失败 case 没有进入 audit/materialize/recapture。

### 4.6 Bundle 分层

Audit bundle：

```text
sequence_semantics = ordered-audit-only
execution_graph = null
runtime_dependency_graph = null
```

Runtime IR：

```text
sequence_semantics = runtime-dag
execution_graph = contract -> capture -> fusion -> write -> readback -> acceptance -> publish
```

因此离线 audit bundle 不能直接作为运行时依赖图。

### 4.7 合同检查

21/21 通过，覆盖：

- 12 case 完整；
- 写前持久化失败零副作用；
- 崩溃后 resume 只提交一次；
- audit/materialize/recapture/resume 分开；
- TTL evidence-unavailable、摘要审计与 materialize 阻断；
- hash 不替代缺失字节；
- URL 过期但本地字节可重放；
- migration 保留全部状态；
- tombstone 与 unknown 保留；
- unknown enum 和跨页引用失败关闭；
- permission 撤销失败关闭；
- audit/runtime schema 分离；
- 环境变化要求重新验收；
- 每字段保留观测与决策，不保存 winner-only；
- 临时 URL 不是长期证据；
- 事件顺序单调；
- 基合同和 32 个变异校验一致。

### 4.8 负向变异

32/32 被拒绝，覆盖：

- persistence 失败后仍写或仍 side effect；
- resume 重发、重复创建或冒充 audit replay；
- TTL 证据声称 exact replay 或 materialize 成功；
- hash-only 变体；
- URL 被当作长期证据或实际 fetch；
- recapture 复用旧 capture 或冒充历史重放；
- migration 丢失 tombstone/authority/order/unknown；
- unknown enum 回填 winner；
- permission 撤销后 materialize/recapture；
- 跨页引用静默丢弃；
- audit bundle 加入 runtime DAG；
- runtime DAG 被移除；
- environment change 声称像素一致；
- migration 覆盖原件或丢失 chain。

这些变异只证明当前校验器拒绝列出的错误，不等于生产持久化或迁移已经安全。

## 5. 发现

1. 写前持久化失败必须发生在任何外部副作用之前；final snapshot 不存在与 side effect 为 0 应同时成立。
2. 发送后崩溃只能进入 `resume` 对账，不能伪装成 `audit-replay` 或自动重发。
3. TTL 过期后 hash 仍然有审计价值，但不能替代缺失证据字节；`exact_replay=false`。
4. 临时 URL 过期不等于本地资产失效。只要本地字节存在且 hash 匹配，`materialize-replay` 可以离线复用，不能重新 fetch URL。
5. recapture 必须生成新 capture/revision；把重新采集写成历史重放会破坏证据链。
6. schema 迁移必须生成新副本并保留原件、migration chain、tombstone、权威链、顺序映射和 unknown。
7. 未知枚举和跨页引用必须失败关闭，不能补默认 winner 或静默删除引用。
8. 权限撤销后 audit 只能做允许的摘要，materialize 与 recapture 必须阻断。
9. 离线 audit bundle 与 runtime IR 必须使用不同外层 schema；`ordered-audit-only` 不能成为执行 DAG。
10. 环境变化后 materialize 输出需要重新验收；语义 hash 不等于像素一致。

## 6. 对生产 IR 的门禁建议

1. 首次 Figma 副作用前持久化合同、授权、锁定 IR、证据清单、决策、tombstone、能力、计划、payload hash、intent 与恢复政策。
2. 持久化失败不写；持久化成功后才发送副作用。
3. 每次 command、response、readback、acceptance 追加事件，不允许覆盖历史。
4. TTL 对 replay bytes、audit metadata、外部 URL 与本地资产分别记录。
5. 过期证据保留 hash/摘要，但必须标 `evidence-unavailable`。
6. 迁移使用新副本、migration chain 与前后 hash；未知版本/枚举失败关闭。
7. 跨页引用缺失时阻断，不静默删除。
8. 三种 replay 语义不得混用；resume 单独记录。
9. Runtime DAG 与 audit order 分开 schema；audit bundle 不可执行。
10. 环境变化后 materialize replay 必须重新验收，不保证逐像素一致。

## 7. 限制

1. 本地 JSON/字节文件不是生产数据库或对象存储。
2. 写前失败注入只覆盖 final replace 前失败，不覆盖全部磁盘故障。
3. 崩溃是事件序列模拟，不是实际进程 kill 或网络中断。
4. TTL 使用固定时间和缺失文件，没有真实清理 worker。
5. 只覆盖 v1 → v2 一个迁移路径和一个未知枚举。
6. 权限撤销是 IR 字段，不是身份认证或访问控制实现。
7. 跨页引用验证使用内存 capture 集合，不是生产引用索引。
8. replay hash 证明语义字段与资产身份的一致重算，不证明像素或 Figma 文档完全一致。
9. 没有连接 Figma，也没有运行生产 IR、监控或保留政策。
10. 32 个变异不等于生产持久化、迁移或权限系统已通过安全和故障测试。

## 8. 不得宣称

- 不得写“生产 IR 已 `verified`”。
- 不得写“生产持久化已经具备崩溃一致性”。
- 不得写“hash 可以替代原证据”。
- 不得写“临时 URL 是长期证据”。
- 不得写“recapture 是历史重放”。
- 不得写“offline audit bundle 可以直接作为 runtime DAG”。
- 不得写“materialize replay 保证逐像素一致”。
- 不得把 21/21、32/32、12 case 或本地 migration 写成生产数据库/权限/迁移安全证明。
- 不得把本轮 R5 完成解释为 R5 规则已进入生产默认路径。

## 9. 目视检查

2026-10-19 已人工查看：

- `r5_exp_06_replay_matrix.png`：12 case × audit/materialize/recapture/resume 状态完整；
- `r5_exp_06_lifecycle_timeline.png`：写前失败与发送后崩溃/恢复路径清楚；
- `r5_exp_06_migration_integrity.png`：fields、authority、order、tombstone、unknown、evidence 均显示 preserved；
- `r5_exp_06_retention_timeline.png`：当前时间、证据过期、URL 过期、本地字节与 audit metadata 分线；
- `r5_exp_06_bundle_separation.png`：audit order 与 runtime DAG 明确分开。

目视检查只确认图和事件可读，不替代自动断言或生产验收。

## 10. 证据文件

- `output/_r5_experiments/r5_exp_06_ir_persistence/result.json`：环境、case、事件、replay、迁移、保留、21 项检查、32 项变异和最终哈希。
- `runtime_ir.json`：clean case 的 runtime IR。
- `audit_bundle.json`：clean case 的 ordered audit bundle。
- `replay_results.json`：12 case 的 audit/materialize/recapture/resume 结果。
- `migration.json`：v1→v2 与 tombstone/unknown 保留结果。
- `retention.json`：TTL、URL、本地字节与 audit metadata。
- `events.json`：54 个事件。
- `store/`：每个 case 的 runtime IR、audit bundle、事件、v2 快照、remote state 与公共证据/资产。
- `r5_exp_06_replay_matrix.png`
- `r5_exp_06_lifecycle_timeline.png`
- `r5_exp_06_migration_integrity.png`
- `r5_exp_06_retention_timeline.png`
- `r5_exp_06_bundle_separation.png`
