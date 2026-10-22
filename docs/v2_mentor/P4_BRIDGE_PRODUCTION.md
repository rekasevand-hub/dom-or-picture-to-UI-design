# P4 Bridge 生产化边界

> 状态：`p4-current-scope-write-paced`，2026-10-21。  
> 范围：request id、响应关联、幂等、事务、回滚、多客户端隔离、持久 journal。  
> 结论：当前单 bridge 实例、单插件、单文档链路、崩溃后 fail-closed 恢复、本地 journal 独占锁与可选 `/command` Bearer 认证已闭合；TLS、`/plugin` 认证、跨主机 fencing 与多租户生产隔离仍未准入。

## 1. 请求协议

客户端命令：

```json
{
  "action": "apply_edit_batch",
  "params": {},
  "clientId": "stable-client-scope",
  "requestId": "stable-request-id"
}
```

规则：

- 缺省 `requestId` 由服务端生成；
- 缺省 `clientId` 进入 `default` 域；
- plugin 回包必须携带服务端 wire request id；
- 返回客户端前恢复为用户请求 id；
- client/request 关联失败、未知响应和过期响应均丢弃。

## 2. 幂等

- 幂等域为 `(clientId, requestId)`；
- 缓存保存 action/params 的规范 SHA-256 fingerprint；
- 同 key、同 payload 在 TTL 内返回原响应，不再发往 plugin；
- 同 key、不同 payload 返回 `IDEMPOTENCY_KEY_CONFLICT`；
- 同 key 已 in-flight 返回 `REQUEST_IN_FLIGHT`；
- timeout、插件断连等无法判断提交状态的结果写入 `outcome=unknown`，TTL 内禁止盲目重试；
- 默认 TTL 60 秒，缓存条目有数量上限与过期清理；
- `(clientId, requestId)`、fingerprint、intent 和 terminal 响应写入 JSONL write-ahead journal；
- 发往 plugin 前先 `fsync` intent；
- 重启后完成结果可直接重放，未闭合 intent 恢复为 `REQUEST_OUTCOME_UNKNOWN`。
- 只有读命令绕过写闸门；其他命令保守按写命令处理。
- 写命令先取得有限队列槽位，再写 intent 和发送 plugin；槽位不足或等待超限返回
  `BRIDGE_WRITE_BACKPRESSURE/not-applied`，不产生已发送 intent。
- 同一 bridge 一次只允许一个写命令在 plugin 侧执行，并在实际发送后满足最小间隔。

## 3. 事务与回滚

创建事务：

- `apply_batch` 只接受 create actions；
- 中途失败按反序删除已创建节点；
- 返回 created rollback 明细。

编辑事务：

- `apply_edit_batch` 在首次写入前完成全量 preflight；
- 对文本、图片 fill、name、visibility 和 layout flow 建快照；
- 中途失败反向恢复；
- 返回 `committed / rejected / rolled-back / rollback-incomplete`；
- rollback 失败逐节点报告。

布局快照包括：

- frame 的 layoutMode、wrap、spacing、padding、size policy；
- Grid count/gap/track/positioning/autoTracks；
- 子项 anchor、span、alignment、sizing、最小/最大宽度与几何。

## 4. 多客户端隔离

- bridge 接受多个并发 `/command` socket；
- 每个 socket 只收到自己 command coroutine 的响应；
- 同 request id 可由不同 `clientId` 独立使用；
- wire request id 在跨客户端时加入 client 域，避免 pending 冲突；
- Figma plugin 使用 promise 队列串行执行异步 action，防止两个事务在节点级交错；
- plugin 替换会关闭旧 socket；plugin 断开会使所有 pending 命令失败关闭。

## 5. 资源与失败边界

默认限制：

- `max_inflight=64`；
- `max_message_bytes=1 MiB`；
- `max_params_depth=16`；
- `max_cache_entries=1024`；
- `max_journal_events=4096`；
- idempotency TTL 60 秒。
- `write_min_interval=50ms`；
- `write_queue_timeout=5s`；
- `max_write_queue=16`。

失败码包括：

- `REQUEST_TOO_LARGE`；
- `PARAMS_TOO_DEEP`；
- `BRIDGE_BACKPRESSURE`；
- `BRIDGE_WRITE_BACKPRESSURE`；
- `IDEMPOTENCY_KEY_CONFLICT`；
- `REQUEST_IN_FLIGHT`；
- `PLUGIN_TIMEOUT`；
- `PLUGIN_DISCONNECTED`；
- `PLUGIN_CONNECTION_CHANGED`；
- `REQUEST_OUTCOME_UNKNOWN`。

## 6. 验证

- `tests/v2/test_bridge_protocol.py`：35 个协议用例，含真实 loopback WebSocket round trip；
- 并发客户端响应关联；
- 跨 client 同 request id；
- 幂等重放与 payload 冲突；
- timeout unknown 防重放；
- 并发上限、消息大小、缓存上限；
- 插件断连 fail-closed；
- journal 跨 hub 重放、重启 unknown、payload 冲突、事务终态恢复、损坏尾行和压缩边界；
- journal 独占锁、释放后重新获取，以及第二个 bridge 进程启动 fail-closed；
- unknown 事务的目标节点自动 readback、`bridge_transaction_status` 查询与跨重启持久化；
- 文本/name 哈希期望检查、visibility 期望值、intent-match 分类及敏感值不落明文；
- 1000 请求 / 32 并发 journal soak：零 pending、cache 128、journal 180/256、重启回放 128；
- 两轮各 60 秒真实 Figma readback soak：合计 50,136 请求、0 失败；第二轮 RSS/handles 未增长；
- 真实写事务 soak：未限速 4 写入器触发延迟超时与 unknown；单写入器 50ms 节流后 347/347 committed；
- 服务端写闸门：16 worker / 320 无客户端 sleep 写入全部完成、零 unknown、plugin 写并发恒为 1；
- 新写闸门下真实 Figma 4 writer / 零客户端 sleep / 60 秒：960/960 committed，零 timeout/unknown，p99 `267.832ms`，content hash `6dc0196659991c1e2dc477ce3cd267c82e1621a4bf6f55904b36ecee8e5a724c`。
- 刻意四槽饱和：240/240 完成，32,218 次安全拒绝全部按同 request id 重试，零 unknown；
- 背压响应携带 `retryAfterMs`，`FigmaBridgeError` 暴露 `code/outcome/retry_after_ms`；
- 缺失、错误和正确 Bearer token，以及 adapter 认证 header；
- `tests/v2/test_figma_bridge_text_metrics.py`：plugin action 串行、编辑/布局回滚、Grid/Wrap、request id echo 等行为测试；
- 真实 Figma 探针连续调用新 bridge 与重载后的插件并通过。

真实幂等 smoke：

- `clientId=p4-smoke-client`；
- `requestId=p4-idempotency-smoke`；
- 两次 `font_report` 返回完全一致；
- 第二次本地耗时 `0.0ms`；
- bridge 日志只出现一次对应 wire request id，证明第二次未再次发往 plugin。

跨 bridge 重启幂等 smoke：

- `clientId=p4-journal-smoke-client`；
- `requestId=p4-journal-restart-20261021-2242`；
- 首次真实 Figma `font_report` 用时 `46.042ms`；
- bridge 停止并重启后，同请求本地命中 `0.680ms`；
- 重启后的 bridge 日志出现 Python command，但没有第二次 plugin 响应；
- 生产 journal 对应一条 intent 与一条 terminal。

## 7. 持久 Journal

- 默认路径 `output/_bridge_state/bridge-journal.jsonl`；
- `FIGMA_BRIDGE_JOURNAL` 可覆盖路径，`off/memory/none/disabled` 可关闭；
- intent/terminal 事件只保存 key、fingerprint、action、transaction id 和响应，不保存 params；
- 事务状态恢复为 `committed / rejected / rolled-back / rollback-incomplete / unknown`；
- journal 达到事件阈值后原子压缩。
- 生产入口在 journal replay 前获取 `.lock`，同一 journal 只允许一个 bridge 实例。
- `apply_edit_batch` intent 保存目标 node id；unknown 事务在插件重连后自动读取 `get_node_tree` 并写入 readback 事件。
- `apply_batch` intent 保存 ownership job id 与期望创建数；unknown 事务在插件重连后自动调用 `ownership_report`，分类完整/部分/缺失/不可判定。
- `bridge_transaction_status` 可读取事务状态、目标节点、readback 和 intent-match 分类；readback 不自动晋升为 committed。
- `set_text / set_name` 期望值只保存 SHA-256，visibility 保存 boolean；分类为 `matches-intended / partial-match / does-not-match-intended / indeterminate`。
- 写命令由服务端单写者闸门和最小 dispatch 间隔节流；饱和时返回安全背压，
  不再依赖每个客户端自行 sleep。某次已发送写 timeout 后，新的写会保持拒绝直到
  插件重连。

## 8. 可选命令认证

- 配置 `FIGMA_BRIDGE_TOKEN` 后，`/command` 必须携带 `Authorization: Bearer <token>`；
- 缺失或错误 token 返回 `UNAUTHORIZED`，不会发往 plugin；
- `FigmaBridgeAdapter` 自动从环境变量或显式参数读取 token；
- token 使用常量时间比较，不写入 journal；
- `/plugin` 保持本地 development plugin 兼容，不受该 token 保护。
- 真实 smoke：缺失/错误 token 均为 `UNAUTHORIZED`；正确 token 的 `font_report` 成功，plugin 只收到正确凭据请求。

详细合同见 `P4_PERSISTENT_JOURNAL.md`、`P4_JOURNAL_SOAK.md`、`P4_REAL_FIGMA_SOAK.md`、
`P4_WRITE_BACKPRESSURE.md`、`P4_PRODUCTION_GAP_ASSESSMENT.md` 与 `P4_COMMAND_AUTH.md`。

## 9. 仍未覆盖

- TLS、`/plugin` 认证和网络暴露策略；
- 跨主机 fencing、网络文件系统的锁语义与多实例高可用；
- 并发协作者存在时的提交归因和人工决策协议；
- 多 Figma 文档/多租户路由；
- 多人协作冲突、节点锁和撤销/重做；
- 请求取消协议；
- 24h/7d 真实 Figma soak、插件 renderer RSS 与长时连接泄漏观测。

不得把当前结果写成“bridge 已达到无条件生产可用”。
