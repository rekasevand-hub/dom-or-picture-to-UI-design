# R5-EXP-02 · 写入失败注入、对账与补偿

> 状态：`completed-for-current-scope`（2026-10-19），不是 `verified`。  
> 范围：确定性模型 17 个故障用例 × 3 个变体 = 51 次运行，另加 2 个并发探测与 1 组 30 步同 job 重放；真实 Figma 子集 23/23 项检查，最终脚本连续 2 次完整运行均通过。  
> 证据：`output/_r5_experiments/r5_exp_02_failure_injection/result.json`、同名目录下的 `ledger.json`、`readback_tree.json`、`events.json`、`deterministic/`、`r5_exp_02_region_a.png`、`r5_exp_02_matrix.png`、`r5_exp_02_timeline.png`、`r5_exp_02_deterministic_timeline.png`。  
> 边界：确定性层是实验控制器/账本模型，不是生产事务管理器；真实层只覆盖当前 WebSocket bridge 可执行的动作。两者都不能证明 exactly-once、强事务、全量回滚、全局 undo 或生产并发安全。

## 1. 目的与边界

本实验回答 `R5-Q02`：当写入在发送前、执行中、响应后或账本落盘前后中断时，系统能否区分“未发送、明确失败、已写成功但结果未知、已写成功但 ID 未落盘”，并在不重复创建、不越权删除、不把未知结果误报成功的前提下恢复。

本实验验证：

- 写前持久化、意图键、区域级逻辑提交与写后回读；
- 发送前中断、发送后响应丢失、响应后账本未落盘、账本落盘后中断、回读超时、保存恢复、重复运行；
- 节点重命名、父节点删除、用户修改、字体缺失、资产失败、权限拒绝、限流、导出失败、补偿失败；
- 同一 job 的 30 步重放/断线组合；
- 真实 Figma 中的 frame/text/rectangle 写入、回读、导出、缺字体失败关闭、区域补偿、唯一名称对账、父节点删除回退、非法图片 payload、导出失败保留已写节点、job 作用域清理与双客户端并发探测。

本实验不验证：

- 服务端幂等键、exactly-once、强事务或全页原子提交；
- 全局 undo 作为回滚；
- 真实权限拒绝、真实限流、用户真实重命名/修改/接管、补偿失败的真实注入；
- 节点级删除、节点级 visible/rename 能力；
- 生产并发写入、跨版本、跨平台、长时间 soak；
- 像素级验收或真实站点端到端交付。

## 2. 环境与可复现性

| 项目 | 值 |
|---|---|
| 操作系统 | Windows 11 |
| Python | 3.12.0（`C:\Users\lzq\.conda\envs\omni\python.exe`） |
| bridge | `ws://localhost:8765` |
| Figma 插件 | 已连接；页面为 `Page 1` |
| 页面基线 | 4 个顶层子节点：`Screen 1440×900 · 34/42 (100%)`、`SmokeB Root`、`R4-EXP-09 Artboard`、`SmokeD Root`；无 `R5-EXP-02` 节点 |
| 最终 job | `JOB-20261018171831` |
| 确定性检查 | 51/51 运行通过；4 项安全不变量全部为 0 |
| 真实检查 | 23/23 通过；连续 2 次完整运行均通过 |
| 最终 `content_hash` | `73a70b5af34456952abc4ef85937b9d3e00c7d383abe508e8ee3fba7d82b6b71` |

最终重跑命令：

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe scripts\r5_exp_02_write_failures.py
```

只跑确定性层：

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe scripts\r5_exp_02_write_failures.py --skip-real
```

脚本每次真实运行前会删除并重建 `output/_r5_experiments/r5_exp_02_failure_injection/ledger.json`，避免不同 job 的账本跨运行混合；运行结束后独立只读检查页面顶层节点，确认无 `R5-EXP-02` 残留。

## 3. 方法

### 3.1 确定性控制器与账本

每个操作由 `intent_key = sha256(canonical(job, revision, logical_key, action, payload_hash))` 标识。账本在发送任何命令前持久化，记录：

- `planned / prepared / acknowledged / verified`；
- `unknown-outcome / unknown-absent / ambiguous-multiple / ambiguous-renamed / ambiguous-user-modified / ambiguous-payload`；
- `blocked-font / blocked-asset / blocked-access / paused`；
- `compensated-removed / compensation-failed`；
- `recovered-unique-name` 与 `inferred-unique-name-only`。

控制器按区域执行逻辑提交：区域内的操作按依赖顺序发送，成功后回读并验证；区域提交后才把该区域标为 `committed`。故障注入点是：

- `preflight_persist`：写前持久化失败；
- `before_send`：发送前中断；
- `after_send_before_response`：已发送但未收到响应；
- `after_response_before_ledger_commit`：已收到响应但账本未落盘；
- `after_ledger_commit`：账本已落盘后中断；
- 回读超时、节点重命名、用户修改、父节点删除等回调。

对归属不明的结果，控制器停止并保留 `unknown / ambiguous` 状态，不自动重发。并发探测使用本地 advisory lock；另做无锁负控制，确认没有锁时确实会产生重复创建。

### 3.2 真实 Figma 子集

真实层只使用当前 bridge 已存在的动作，不伪造能力：

| 区域 | 动作 | 观察 |
|---|---|---|
| A | `create_frame` + `create_text` + `create_rectangle` | 返回 ID；`get_node_tree` 回读类型、父子、文本、字体、颜色与几何；`export_frame` 产出 PNG |
| B | frame + rect 已写，`create_text` 使用不存在的字体族并带 `fontPolicy=strict` | 严格失败，未创建文本节点；随后按精确顶层名称补偿 B frame，A 保持 |
| C | 用独立原始 WebSocket 发送 `create_frame` 后立即关闭，不读取响应 | 节点实际出现在页面；1.5 秒后按唯一稳定名称找到；仅 1 个节点，几何匹配 |
| D | bridge 返回了 ID，但故意不把 ID 写入账本 | 按唯一稳定名称恢复；仅 1 个节点 |
| E | 创建父 frame 与子 text，删除父 frame 后再用旧 `parentId` 创建子节点 | bridge 未报错，把子节点静默挂到 `currentPage`；实验将其识别为顶层孤儿并删除 |
| F | 在 frame 内发送非法 base64 图片 | bridge 报 `atob` 错误，frame 内无 image 子节点 |
| G | 写入 frame + text 后，对不存在的节点 ID 导出 | 导出报错；已写 text 保留；账本标 `written-verification-pending`；不重建 |
| H | 创建不属于本 job 账本的 user-owned 节点 | 该节点在 job 前缀之外；job 作用域清理后仍存在；随后手工删除 |
| 并发 | 两个独立客户端同时创建两个不同名称 | 两个名称各出现 1 次；返回 ID 与回读节点匹配 |
| 清理 | 先按 job 前缀删除，再按实验前缀收尾 | 当前 job 节点为 0；用户节点在 job 清理后仍存在；最终无 `R5-EXP-02` 残留 |

### 3.3 名称与归属

稳定名称只用于定位，不是所有权凭证。真实层中：

- C/D 的恢复标记为 `inferred-unique-name-only`；
- A/B 的归属来自 bridge 返回 ID，仍不是服务端幂等键；
- 用户节点只证明“不在 job 账本且在 job 前缀之外”这一谓词；bridge 本身没有节点级 ownership 检查；
- 最终清理按 `R5-EXP-02 {job}` 名称前缀执行，而不是按账本 ID 逐节点删除，因为 bridge 没有节点级删除动作。

## 4. 结果

### 4.1 确定性层

51/51 次运行通过。17 个故障用例各 3 个变体：

| 用例 | 观察状态 | 3 次结果 |
|---|---|---:|
| `preflight-persistence-failure` | `blocked-persistence` | 3/3 |
| `before-send` | `committed` | 3/3 |
| `after-send-before-response` | `committed` | 3/3 |
| `after-response-before-ledger-commit` | `committed` | 3/3 |
| `after-ledger-commit` | `committed` | 3/3 |
| `readback-timeout` | `committed` | 3/3 |
| `save-resume` | `committed` | 3/3 |
| `duplicate-rerun` | `committed` | 3/3 |
| `node-renamed` | `ambiguous-renamed` | 3/3 |
| `parent-deleted` | `conflict-missing` | 3/3 |
| `user-modified` | `ambiguous-user-modified` | 3/3 |
| `font-missing` | `blocked-font` | 3/3 |
| `asset-failure` | `blocked-asset` | 3/3 |
| `permission-denied` | `blocked-access` | 3/3 |
| `rate-limited` | 2 × `committed`，1 × `paused` | 3/3 |
| `export-failure` | 2 × `committed`，1 × `written-verification-pending` | 3/3 |
| `compensation-failure` | `compensation-failed`，保留 residue | 3/3 |

安全不变量合计：

| 不变量 | 次数 |
|---|---:|
| `duplicate_creates` | 0 |
| `unauthorized_deletes` | 0 |
| `unknown_reported_success` | 0 |
| `preflight_side_effects` | 0 |

并发探测：

- 无锁负控制：`duplicate-created`，观察到 3 次重复创建；这证明负控制有效，不是通过结果。
- 本地锁控制：`committed`，`locked_concurrent_duplicate_creates = 0`。

30 步同 job 重放/断线组合：

- 30 个区域依次在 `clean / before-send / after-send / after-response / after-ledger` 之间轮换中断；
- 每次中断后恢复；
- 最终 `committed`，重复创建 0，越权删除 0。

### 4.2 真实 Figma 层

23/23 项检查通过。关键观察：

- A：frame/text/rect 均返回 ID；回读文本 `R5-EXP-02 A`、字体 `Inter / Semi Bold`、字号 18、颜色 `#0f172a`；矩形 120×48、圆角 8、颜色 `#1d4ed8`；导出 PNG 2938 bytes，SHA-256 `419fa37e3cc410e6ae3dcbdc1516952804cc3156135ea47cba8ea8499b6e1bea`。
- B：缺字体返回 `FONT_NOT_AVAILABLE: R5-EXP-02 Missing Font Family`；frame 内只有 rect，没有 text；补偿删除 1 个 B frame；A 仍存在。
- C：原始 WebSocket 发送后立即关闭，未读取响应；页面出现 1 个 C frame，按唯一名称恢复成功，几何 360×220 匹配；没有创建第二个节点。
- D：bridge 返回 `3:...` ID 但账本未落盘；按唯一名称恢复成功，且只有 1 个节点。
- E：删除父 frame 后，使用旧 `parentId` 的 `create_text` 无错误返回，子节点出现在页面顶层；实验判定为 orphan 并删除。这是 bridge 的真实缺陷，不是成功语义。
- F：非法 base64 图片报 `Failed to execute 'atob' ...`；frame 内 0 个子节点。
- G：导出不存在的 `999:999` 报错；已写 text 仍在；账本区域 G 为 `written-verification-pending`，没有重建。
- H：user-owned 节点存在、且不在 job 账本；job 作用域清理删除 3 个 job 节点后，该用户节点仍存在；随后手工删除。
- 并发：两个独立客户端创建 `CONCURRENT-A` / `CONCURRENT-B`，各 1 次；返回 ID 与回读节点匹配。
- 清理：job 前缀剩余 0；最终实验前缀剩余 0；独立页面检查确认无 `R5-EXP-02` 顶层节点。

真实 job 账本终态为 `partial-blocked-font`，因为区域 B 的缺字体被严格阻断并补偿；A/C/D 已提交或恢复，G 仍为 `written-verification-pending`。这不是整页成功。

## 5. 发现与能力缺口

1. bridge 没有服务端幂等键。客户端 `intent_key` 只能在账本内去重；“创建成功但 ID 尚未落盘”的窗口仍存在。C/D 只能按唯一名称推断归属。
2. bridge 没有可靠的 ownership marker。名称、返回 ID 和账本记录都不能单独证明节点归本 job 所有；唯一名称恢复标为 `inferred-unique-name-only`。
3. bridge 没有节点级删除，只能按顶层名称或名称前缀删除；补偿的粒度是顶层 staging frame。
4. bridge 没有 visibility、rename、节点级修改动作；无法在真实层注入用户重命名、隐藏或节点级修改。
5. 真实权限拒绝、限流、用户修改、补偿失败无法通过当前 bridge 稳定注入；这些行为只由确定性模型覆盖。
6. 父节点不存在时，bridge 不拒绝子节点创建，而是把子节点挂到 `currentPage`。生产写入必须先预检父节点，或要求 bridge 修复为失败关闭。
7. 并发探测只覆盖两个独立客户端、两个不同名称；它不证明同名并发幂等、同一请求流水线关联或服务端并发安全。
8. 清理前预检使用实验前缀 `R5-EXP-02`，会删除本实验遗留的所有顶层节点；最终清理使用 job 前缀。名称前缀不是所有权证明；生产清理必须使用节点 ID + 归属标记 + 当前状态核对。
9. 真实层的 G/E/F/用户/并发探测是直接发送，不经过完整写前账本；它们只验证各自边界，不应被当作完整 job 提交证据。
10. 当前 job 账本最终是 `partial-blocked-font`，说明“实验检查通过”不等于“交付完整”。

## 6. 对生产写入的门禁建议

1. 在 bridge 或服务端增加幂等键，至少覆盖 `job_id / revision / logical_object_key / operation_type / payload_hash`；明确它不是 exactly-once。
2. 任何副作用前先持久化 write-ahead ledger；持久化失败则零写入。
3. 以依赖闭合的区域/小子树做逻辑提交；提交前回读类型、父子、文本、字体、颜色、几何、资产哈希与裁剪。
4. 已发送但结果未知时先对账：按服务端幂等键或节点级归属标记查找；多候选、重命名、用户修改一律转人工冲突，不自动重发。
5. 为每个节点写入 job ID、revision、op ID 与状态标记；清理只针对本 job 创建且未被用户接管/修改的节点。
6. 父节点不存在必须失败关闭；禁止静默挂到 `currentPage`。
7. 字体与资产在写入前预检；缺字体、非法资产、权限拒绝、限流按失败类型处理，未知结果不重试。
8. 导出失败只标 `verification-pending`，不得重新创建已写节点。
9. 区域补偿成功后，账本必须把对应操作标为 `compensated-removed`；补偿失败保留 residue 并阻断后续自动清理。
10. 在生产准入前，必须补做真实权限/限流/用户接管/补偿失败注入，以及同 job 同 revision 的并发恢复测试。

## 7. 限制

1. 确定性控制器是实验模型，不是生产事务管理器；它的“零违例”只对本模型和注入点成立。
2. 51 次确定性运行、2 个并发探测和 30 步重放不能外推为生产负载、网络分区或跨进程故障覆盖率。
3. 真实层只覆盖当前 bridge 可执行的动作；没有服务端幂等、ownership marker、节点级删除、visibility/rename。
4. 真实层没有注入权限拒绝、限流、用户真实修改、用户接管或补偿失败；这些只在确定性模型中覆盖。
5. C 的“丢响应”是原始 WebSocket 发送后立即关闭连接、未读取响应；它证明“写成功但确认丢失”的真实窗口，不等于任意网络分区、代理超时或服务端崩溃。
6. D 的“ID 未落盘”是通过实验代码故意不保存 ID 模拟的，不是进程崩溃注入。
7. E 的父节点删除是真实 bridge 行为，但只覆盖 text 子节点与顶层 frame 父节点。
8. 并发探测是两个独立连接、两个不同名称；没有覆盖同名并发、同 job 并发恢复、请求流水线或响应乱序。
9. 真实层的 G/E/F/用户/并发节点是直接发送，不完全经过写前账本；清理按名称前缀执行，不是按节点 ID 和 ownership 标记执行。
10. 没有做像素级验收、字体渲染比对、跨版本/跨平台、长时间 soak、真实站点或生产权限环境测试。

## 8. 不得宣称

- 不得写“已实现 exactly-once 写入”。
- 不得写“已具备强事务、全有或全无提交或完整回滚”。
- 不得写“全局 undo 可作为回滚”。
- 不得写“bridge 已具备服务端幂等键或可靠 ownership marker”。
- 不得写“生产并发写入安全”。
- 不得写“真实权限拒绝、限流、用户接管与补偿失败已验证”。
- 不得写“缺字体、资产失败、父节点删除等所有失败在真实 Figma 中都已覆盖”。
- 不得把唯一名称恢复写成确定归属。
- 不得把 job 作用域名称前缀清理写成生产 ownership 安全边界。
- 不得把 23/23、51/51 或 30/30 写成生产成功率、页面还原度或跨环境稳定性。

## 9. 证据文件

- `output/_r5_experiments/r5_exp_02_failure_injection/result.json`：确定性/真实层摘要、检查、发现、限制与最终哈希。
- `output/_r5_experiments/r5_exp_02_failure_injection/ledger.json`：最终真实 job 账本（`partial-blocked-font`；A 已提交，B 已补偿，C/D 唯一名称恢复，G 待验证）。
- `output/_r5_experiments/r5_exp_02_failure_injection/readback_tree.json`：基线、区域 A/B、丢响应、父节点回退、资产失败、导出失败、并发与清理后的回读树。
- `output/_r5_experiments/r5_exp_02_failure_injection/events.json`：真实层事件序列。
- `output/_r5_experiments/r5_exp_02_failure_injection/deterministic/`：17 个用例 × 3 变体的 `run.json` / `ledger.json`，以及 `replay-stress/` 与并发结果。
- `output/_r5_experiments/r5_exp_02_failure_injection/r5_exp_02_region_a.png`：真实区域 A 导出图。
- `output/_r5_experiments/r5_exp_02_failure_injection/r5_exp_02_matrix.png`：确定性用例矩阵。
- `output/_r5_experiments/r5_exp_02_failure_injection/r5_exp_02_timeline.png`：真实层时间线。
- `output/_r5_experiments/r5_exp_02_failure_injection/r5_exp_02_deterministic_timeline.png`：确定性层时间线。
