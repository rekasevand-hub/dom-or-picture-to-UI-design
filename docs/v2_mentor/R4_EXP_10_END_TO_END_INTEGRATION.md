# R4-EXP-10 · 九阶段离线集成与 envelope 审计

> 状态：`completed-for-current-scope`（2026-10-18），不是 `verified`。  
> 范围：把 `R4-EXP-01` 至 `R4-EXP-09` 的 9 个 JSON 产物组合成一个确定性离线 stage bundle；审计状态、检查项、边界声明和内容哈希，并用 9 个非法变异验证组合合同。  
> 边界：不重跑 OCR/CV、浏览器采集、配对或权威解析；不连接 Figma，不修改 `src/` 或 `figma_bridge/`；`sequence_semantics=ordered-audit-only`，实验顺序不是运行时数据依赖证明。

## 1. 目的

前九个实验分别证明了局部合同，但没有验证它们能否作为一个统一的离线产物被枚举、复算和拒绝非法组合。本实验回答一个实现前问题：

> 九个 R4 阶段是否都具备可组合的最小 envelope，并且不会在聚合时静默丢失状态、边界或哈希？

本实验不把不同实验的受控夹具伪装成同一条运行时数据流；它只验证**产物级合同**。

## 2. 输入与 envelope

每个阶段被归一化为以下 envelope：

- `experiment / title / status / scope_sha256 / summary_sha256`；
- `checks_passed / checks_total / check_ids`；
- `boundary` 是否存在，以及是否出现 `source_mutation / figma_write / real_figma_connected / src_modified / figma_bridge_modified`；
- `limitations` 是否存在；
- 原始文件 `artifact_sha256`；
- 显式 `content_hash`（如有）与按当前 JSON 复算的 `computed_content_hash`；
- `gaps`：缺失的边界、limitations 或显式哈希。

缺少显式元数据不会被静默补成“已验证”；它会被写入 `gaps`，并在覆盖率中单独计数。

## 3. 结果

### 3.1 总览

| 项目 | 结果 |
|---|---:|
| 阶段数 | 9 |
| 阶段检查合计 | 227/227 通过 |
| 状态为 `completed-for-current-scope` | 9/9 |
| 阶段检查全部通过 | 9/9 |
| 显式 `content_hash` | 9/9 |
| 显式哈希复算一致 | 9/9 |
| 派生 canonical digest | 9/9 |
| 显式 `boundary` | 9/9 |
| 显式 `limitations` | 9/9 |
| 非法边界标志 | 0 |
| 集成检查 | 13/13 通过 |
| 非法变异 | 9/9 被预期问题拦截 |
| 120 次阶段输入顺序置换 | 1 个 bundle hash |

`bundle_hash`：

```text
486a200d057dbb5d5f4acfaeb2931a6aa8463fa4fbf167f0452f906ab9a54dbb
```

结果 JSON 的 `content_hash`：

```text
9e171aa32e29b421260f158f6277afe82f7129378e20a5c3341015b99805c706
```

### 3.2 envelope 缺口

| 缺口 | 数量 | 阶段 |
|---|---:|---|
| `boundary-not-declared` | 0 | — |
| `limitations-not-declared` | 0 | — |
| `stored-content-hash-not-declared` | 0 | — |

`envelope_gaps={}`。历史缺口已由 `r4_metadata_supplement.py` 幂等补齐：EXP-01–06 的 boundary、EXP-08 的 limitations、EXP-01–04 的显式 `content_hash`；补跑审计为 `changed=0`、7/7 检查通过。显式哈希现在是写盘 attestation，派生 digest 仅作为交叉核对保留。

### 3.3 非法变异

| 变异 | 预期问题 | 实际结果 |
|---|---|---|
| 状态提升为 `verified` | `invalid-status` | 拦截 |
| 阶段检查强制失败 | `failed-stage-check` | 拦截 |
| 显式哈希被篡改 | `stored-hash-mismatch` | 拦截 |
| 实验 ID 被改名 | `experiment-id-mismatch` | 拦截 |
| 写入边界被标为真实 Figma 连接 | `unsafe-boundary` | 拦截 |
| 删除 summary | `missing-summary` | 拦截 |
| 删除 checks | `no-checks` | 拦截 |
| 删除 title | `missing-title` | 拦截 |
| 重复阶段 | `duplicate-stage` | 拦截 |

## 4. 结论

1. 九个阶段的**最小 envelope 可以稳定组合**：9/9 状态正确、227/227 阶段检查通过、9/9 显式哈希复算一致、9/9 可计算 digest。
2. 组合合同可以拒绝状态提升、哈希篡改、边界越权、缺字段和重复阶段；当前 9/9 变异均按预期被拦截。
3. 组合顺序对 bundle 哈希没有影响；阶段按固定 ID/index 归一化，120 次输入顺序置换只产生 1 个哈希。
4. 这不是生产 end-to-end 管线。它只说明现有实验产物可以被统一封装和审计，不能说明真实运行时链路已经打通。
5. 九个阶段的 boundary、limitations 与显式 `content_hash` 已全部就位；接入 `src/` 仍缺运行时数据依赖、生产 envelope/持久化与真实 Figma 回读。

## 5. 重跑

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe output/_r4_experiments/r4_end_to_end_integration.py
```

脚本读取九份既有 R4 JSON，生成 stage bundle、envelope 清单、变异结果和三张图；写盘后会复算结果 JSON 的 `content_hash`。若只补 envelope 元数据，先运行：

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe output/_r4_experiments/r4_metadata_supplement.py
```

## 6. 不得宣称

- 不得写“R4 端到端生产管线已验证”；本实验只做产物级离线组合。
- 不得把 227/227 写成生产链路成功率、真实站点覆盖率或 Figma 写入成功率。
- 不得把 `sequence_semantics=ordered-audit-only` 写成阶段之间的真实运行时依赖。
- 不得把派生 digest 写成实验写盘时的原始 attestation。
- 不得把 envelope 齐全写成“生产边界已证明”；它只说明每份产物的元数据字段存在且可审计。
- 不得把 9/9 变异拦截写成生产 fuzz 测试、安全认证或并发事务验证。
- 不得把本实验写成已连接 Figma、已修改 `src/` 或已接入生产 IR。

## 7. 证据文件

- `output/_r4_experiments/r4_end_to_end_integration.json`：完整 envelope、bundle、检查、变异与哈希。
- `output/_r4_experiments/r4_end_to_end_artifacts/stage_bundle.json`：九阶段确定性 bundle。
- `output/_r4_experiments/r4_end_to_end_artifacts/stage_envelopes.json`：逐阶段归一化 envelope。
- `output/_r4_experiments/r4_end_to_end_artifacts/mutations.json`：9 个非法变异及观测问题。
- `output/_r4_experiments/r4_end_to_end_stages.png`：阶段状态、检查、哈希、边界和限制矩阵。
- `output/_r4_experiments/r4_end_to_end_evidence.png`：阶段证据链与显式元数据覆盖率。
- `output/_r4_experiments/r4_end_to_end_mutations.png`：非法变异审计。
