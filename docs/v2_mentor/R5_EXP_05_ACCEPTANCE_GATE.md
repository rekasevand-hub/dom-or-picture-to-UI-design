# R5-EXP-05 · 四维验收硬门禁与页面汇总

> 状态：`completed-for-current-scope`（2026-10-19），不是 `verified`。  
> 范围：19 个受控 case × 11 条验收记录 = 209 条检查记录；22/22 合同检查通过，30/30 定向负向变异被拒绝；连续 2 次运行得到相同 `content_hash`。  
> 证据：`output/_r5_experiments/r5_exp_05_acceptance_gate/result.json`、`contracts.json`、`checks.json`、`page_summaries.json`、`release_ledger.json`、`mutations.json`、`artifacts/` 与 5 张结果图。  
> 边界：检查状态是注入的合同输入；本实验验证门禁和页面汇总逻辑，不重新标定 linebreak/pixel/geometry/parent/boundary/native 检测器，不连接 Figma，也不证明生产发布安全。

## 1. 目的与边界

本实验回答 `R5-Q05`：页面发布能否按合同、关键项和依赖闭包分层判断，而不是用面积、平均分或单维度最差值代替所有验收。

本实验验证：

- 视觉、结构、编辑、资产四维分别给出 `pass / partial / fail / unknown`；
- 六类故障 `linebreak / pixel / geometry / parent / boundary / native` 分别注入；
- `unknown / no-ground-truth / not-sampled` 不进入 PASS 分子；
- 极小但关键的价格错误阻断发布；
- 大面积背景通过不能抵消关键项失败；
- 视觉通过不能抵消编辑失败；
- 非关键缺口只有可隔离且用户允许时才产生 `deliverable-partial`，分母不缩小；
- 只有全部 required 满足且覆盖充分才产生 `deliverable-complete`；
- pilot、deliverable、production 三种口径分别计算；
- 不使用通用 95% 或最少 N 样本阈值。

本实验不验证：

- 检测器能否真实识别上述六类故障；
- R3-EXP-11 合同阈值在真实页面上的判别能力；
- 真实 Figma 交付、真实浏览器、真实资产或真实编辑能力；
- 生产故障恢复、幂等、权限、并发、持久化、迁移、监控与部署；
- 用户是否理解状态词、报告或发布限制。

## 2. 环境与可复现性

| 项目 | 值 |
|---|---|
| 操作系统 | Windows 11 |
| Python | 3.12.0（`C:\Users\lzq\.conda\envs\omni\python.exe`） |
| 依赖 | 标准库 + `numpy`、`Pillow`、`matplotlib` |
| Figma / bridge | 未连接 |
| case 数 | 19 |
| 每 case 检查记录 | 11 |
| 检查记录总数 | 209 |
| 合同检查 | 22/22 |
| 负向变异 | 30/30 被拒绝 |
| tiny price raster diff | 481 / 912,000 px |
| 连续运行 | 2 次 |
| 最终 `content_hash` | `b5cd12d49937971250973f9acb830386356ccdd82f2031cf8bccdd87067ac6c5` |

重跑命令：

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe scripts\r5_exp_05_acceptance_gate.py
```

脚本只清理并重建：

```text
output/_r5_experiments/r5_exp_05_acceptance_gate/
```

不修改 `src/`、`figma_bridge/` 或其他用户产物。

## 3. 方法

### 3.1 合同输入

每个 case 都声明：

- 交付范围与 `faithful / reference-only` profile；
- required dimensions；
- 关键项 `price-panel / cta / price-value`；
- 关键项依赖闭包，例如 `price-value` 依赖 `V-CONTENT-PRICE / E-NATIVE-PRICE`；
- 用户是否允许 partial、非关键缺口是否可隔离；
- 授权、目标状态、IR 完整性、输出归属四个前置门；
- coverage policy，明确 `generic_pass_ratio=null`、`minimum_sample_count=null`；
- 生产运行前置项，全部固定为未提供。

### 3.2 检查记录

11 条 canonical checks：

| ID | 类型 | 维度 | 关键 |
|---|---|---|---|
| `V-LINEBREAK-HERO` | linebreak | visual | 否 |
| `V-PIXEL-BG` | pixel | visual | 否 |
| `V-PIXEL-PRODUCT` | pixel | visual | 否 |
| `V-CONTENT-PRICE` | content | visual | 是 |
| `S-GEOMETRY-PRICE` | geometry | structure | 是 |
| `S-PARENT-CTA` | parent | structure | 是 |
| `S-BOUNDARY-CTA` | boundary | structure | 是 |
| `E-NATIVE-PRICE` | native | edit | 是 |
| `E-NATIVE-CTA` | native | edit | 是 |
| `A-ORIGIN-IMAGE` | asset | asset | 否 |
| `A-ORIGIN-BADGE` | asset | asset | 否 |

这些阈值来自 R3-EXP-11 的合同值，`detector_calibration=not-evaluated`。本轮只注入状态，不把合同值写成已标定检测准确率。

### 3.3 页面汇总

汇总顺序：

1. 前置门禁；
2. 逐维度汇总 required checks；
3. 关键项与依赖闭包阻断；
4. 覆盖充分性；
5. `deliverable` 状态；
6. `pilot / production / reference-only` 口径。

维度状态规则：

- 任一 required check `fail` → 维度 `fail`；
- 存在 `unknown / no-ground-truth / not-sampled` → 维度 `unknown`；
- 存在 `partial` 且无更高严重状态 → 维度 `partial`；
- 仅全部 `pass` → 维度 `pass`；
- 非 required → `not-required`，不伪装成 pass。

关键项 `fail / unknown / no-ground-truth / not-sampled / 未允许 partial` 阻断原合同发布。

### 3.4 三种发布口径

- `pilot`：只对 preflight 通过且未被关键项阻断的 complete/partial/reference-only 输出 `pilot-allowed-provisional`，始终要求限定范围、人工复核和可见缺口；
- `deliverable`：使用页面 release 状态，只有 all-pass + coverage complete 才为 `deliverable-complete`；
- `production`：除效果验收外还必须满足故障恢复、幂等、权限、持久化、环境与监控；本实验全部缺失，因此所有 case 都是 `production-not-eligible`；
- `reference-only`：只在 reference-only 合同中成立，不能升级成 complete。

## 4. 结果

### 4.1 发布计数

| Deliverable 状态 | case 数 |
|---|---:|
| `deliverable-complete` | 1 |
| `deliverable-partial` | 4 |
| `reference-only` | 1 |
| blocked | 13 |

Pilot：`pilot-allowed-provisional=6`，`pilot-blocked=13`。  
Production：`production-not-eligible=19`，没有任何 case 因效果检查通过而获得生产资格。

### 4.2 关键结果

| Case | 观察 | 发布 |
|---|---|---|
| `clean-all-pass` | 四维全部 pass，required coverage 完整 | `deliverable-complete` |
| `linebreak-isolated` | visual fail，仅非关键断行；用户允许 partial 且可隔离 | `deliverable-partial` |
| `pixel-background` | visual partial，仅背景像素 | `deliverable-partial` |
| `asset-noncritical` | asset fail，仅非关键图片来源 | `deliverable-partial` |
| `coverage-gap` | 非关键 asset check 未采样，保持 unknown | `deliverable-partial` |
| `geometry-critical` | critical geometry fail | `blocked-critical` |
| `parent-critical` | critical parent fail | `blocked-critical` |
| `boundary-critical` | critical boundary fail | `blocked-critical` |
| `native-critical` | visual pass、edit fail | `blocked-critical` |
| `unknown-critical` | critical geometry unknown | `blocked-unknown` |
| `no-ground-truth-critical` | critical native text 无 ground truth | `blocked-no-ground-truth` |
| `critical-partial-not-allowed` | critical geometry partial，用户不允许 partial | `blocked-partial-not-allowed` |
| `critical-not-sampled` | critical geometry 未采样 | `blocked-coverage` |
| `tiny-price-error` | critical price 错一位 | `blocked-critical` |
| `high-area-background-pass` | 大面积背景通过，关键价格失败 | `blocked-critical` |
| `unsupported-browser` | 未支持环境得到 unknown | `blocked-unknown` |
| `partial-not-allowed` | 非关键缺口存在，但用户不允许 partial | `blocked-partial-not-allowed` |
| `reference-only` | 只要求视觉参考 | `reference-only` |
| `preflight-ownership-unknown` | 输出归属未知 | `blocked-preflight` |

### 4.3 Tiny price 与高面积对照

实际生成 `$129` 与 `$139` 页面，逐像素 diff 为：

```text
481 / 912,000 px = 0.0527%
```

该错误极小，但 `V-CONTENT-PRICE` 是 critical，因此释放状态为 `blocked-critical`，`complete_export_allowed=false`。

高面积对照中：

- 背景 pass area `180,000 px`，占页面 19.7%；
- 全页 area pass ratio `99.947%`；
- 关键价格 fail 仍阻断；
- `area_used_as_release_score=false`。

这说明面积只能作为覆盖信息，不能替代关键项和维度硬门禁。

### 4.4 检查记录计数

209 条记录中：

| 状态 | 数量 |
|---|---:|
| `pass` | 186 |
| `fail` | 9 |
| `partial` | 2 |
| `unknown` | 2 |
| `no-ground-truth` | 1 |
| `not-sampled` | 2 |
| `not-required` | 7 |

`no-ground-truth` 与 `not-sampled` 都没有进入 PASS 分子。

### 4.5 合同检查

22/22 通过，覆盖：

- 19 个 case 与 209 条记录完整；
- 六类故障分别注入；
- unknown 与 no-ground-truth 分开；
- critical partial 未允许与 critical not-sampled 均阻断；
- tiny price 与高面积背景不能绕过 critical；
- 视觉 pass 不能抵消 edit fail；
- 非关键隔离缺口可 partial，但分母不变；
- 不允许 partial 时阻断；
- clean 才 complete；
- reference-only 不升级；
- unsupported browser 不为 pass；
- production 不从效果检查推导；
- 无 95%/N 通用阈值；
- area 不作为 release score；
- critical 依赖闭包生效；
- not-required 不伪装 pass；
- 基合同有效且 30/30 变异被拒绝。

### 4.6 负向变异

30/30 被拒绝，覆盖：

- critical fail/unknown/no-ground-truth 改 pass；
- not-sampled 改 pass；
- 视觉通过覆盖编辑失败；
- 面积覆盖 critical 失败；
- 非关键缺口直接 complete；
- 未允许 partial 直接放行；
- 分母缩小；
- no-ground-truth / not-sampled 进入 pass 分子；
- 加入 95% 或 N 样本阈值；
- 未支持浏览器判 complete；
- 缺少生产前置仍判 production eligible；
- pilot 冒充 deliverable-complete；
- reference-only 冒充 complete；
- 删除关键项依赖闭包；
- 忽略 asset 维度；
- preflight 失败仍放行；
- 用维度平均分替代硬门禁；
- unknown 仍声称 coverage complete；
- 删除 evidence 或 threshold source；
- `not-required` 改 pass；
- linebreak fail 降级 warning；
- area 作为 release score；
- clean 页面宣称 critical closure 失败；
- tiny price 错误忽略；
- 使用未支持的 `verified` release 状态。

这些变异只证明当前校验器拒绝列出的错误，不等于穷尽所有发布语义错误。

## 5. 发现

1. 四维验收必须先分类，再做页面汇总。`visual=pass` 不能覆盖 `edit=fail`，`asset=fail` 也不能被视觉高分掩掉。
2. `no-ground-truth` 与 `not-sampled` 必须与 fail/unknown 分开记录，但都不能进入 PASS 分子。
3. 关键项依赖闭包比“取最差维度”更强：一个关键字段 fail 会阻断包含它的对象和原合同发布。
4. 面积不是发布分数。`99.947%` 的 area pass 仍不能抵消 481 像素的关键价格错误。
5. `deliverable-partial` 是受限交付，不是完整通过；只有非关键缺口可隔离且用户允许时才成立，原合同分母不缩小。
6. `deliverable-complete` 需要所有 required checks pass 且 required coverage 完整；不能由平均分或样本比例推出。
7. reference-only 是独立发布口径，`not-required` 不能伪装 pass，也不能升级 complete。
8. 未支持浏览器必须保持 unknown 或被阻断，不能因为其他检查通过而默认支持。
9. pilot 只能作为有限、人工复核、明确 provisional 的试点口径，不等于 deliverable complete。
10. 效果验收通过不产生生产资格；生产还需要恢复、幂等、权限、持久化、环境覆盖和监控。

## 6. 对生产发布门禁的建议

1. 合同先声明 required dimensions、critical items、dependency closure、scope、partial permission 与 coverage policy。
2. 每次检查记录保留对象键、维度、criticality、阈值来源、实际值、证据、覆盖状态、原因与修复建议。
3. 页面汇总按前置门禁 → 关键项闭包 → required dimensions → coverage 的顺序执行；任一关键项 fail/unknown/no-ground-truth/未允许 partial 阻止原合同发布。
4. `no-ground-truth`、`not-sampled` 不进入通过分子；不能为了达到比例而补默认 pass。
5. 不允许通用 95% 或 N 样本阈值。每个关键 required check 必须执行并具备可核实真值。
6. 面积只作为诊断和覆盖信息，不参与 release score；高面积 pass 不能抵消关键缺陷。
7. partial 只在缺口可隔离且用户允许时成立，保留原合同分母和 visible gap。
8. pilot、deliverable、production 为独立 profile；production 需要单独满足运行安全与运维前置。
9. 未支持环境保持 unknown/blocked，不能默认 pass。
10. release status 与四维评分分开记录；`verified` 不应是本实验可用的 release 状态。

## 7. 限制

1. 19 个 case 是 authored gate model，不是真实页面样本。
2. 六类故障是注入状态，未运行真实 linebreak/pixel/geometry/parent/boundary/native 检测器。
3. R3-EXP-11 阈值只作为合同引用；已有文档明确其中若干族没有对应故障标定。
4. 11 条 canonical checks 不足以覆盖真实业务字段、依赖图和页面状态。
5. tiny price 使用生成的 `$129/$139` raster，diff 481 px；不代表所有价格错误面积。
6. Area pass ratio 只按 authored page/background 计算，不是业务价值权重。
7. 生产前置项固定缺失，因此 production 全为 not eligible；未验证真实生产系统。
8. reference-only applicability 是模型声明，没有真实只读交付物。
9. 未做用户研究，不能证明状态词、图例或 blocked actions 可被理解。
10. 30 个变异只覆盖本脚本定义的门禁错误。

## 8. 不得宣称

- 不得写“四维验收硬门禁已 `verified`”。
- 不得写“linebreak/pixel/geometry/parent/boundary/native 检测阈值已标定”。
- 不得写“288/288 是真实页面精度”。
- 不得写“面积达到 95% 或 N 样本即可通过”。
- 不得写“视觉 pass 能抵消编辑/结构/资产 fail”。
- 不得写“pilot 或 deliverable-complete 等于生产资格”。
- 不得写“reference-only 等于 complete”。
- 不得写“未支持浏览器默认通过”。
- 不得把 22/22、30/30、481 px 或 99.947% 写成生产发布安全证明。

## 9. 目视检查

2026-10-19 已人工查看：

- `r5_exp_05_check_matrix.png`：19 个 case × 11 个检查状态，fail/partial/unknown/N/A 可辨识；
- `r5_exp_05_page_summary.png`：四维、critical、release、export 列完整；
- `r5_exp_05_area_vs_critical.png`：背景 pass area 与 481 px 关键 diff 对照，release 文案清楚；
- `r5_exp_05_release_profiles.png`：pilot、deliverable、production、reference-only 四口径完整，production 全部 not eligible；
- `r5_exp_05_price_error_evidence.png`：`$129 / $139 / 481 px diff` 三幅证据可读。

目视检查只确认图和表格可读，不替代自动断言或生产验收。

## 10. 证据文件

- `output/_r5_experiments/r5_exp_05_acceptance_gate/result.json`：环境、21 项检查、30 项变异、限制与最终哈希。
- `contracts.json`：19 个 case 的合同、关键项闭包、partial 权限与 coverage policy。
- `checks.json`：209 条检查记录。
- `page_summaries.json`：每 case 的四维、关键项、coverage、area 与三个发布 profile。
- `release_ledger.json`：页面级发布账本与策略。
- `mutations.json`：30 个负向变异与拒绝原因。
- `artifacts/reference_page.png`：`$129` 参考页。
- `artifacts/price_error_page.png`：`$139` 错误页。
- `artifacts/price_error_diff.png`：481 px 差异图。
- `r5_exp_05_check_matrix.png`
- `r5_exp_05_page_summary.png`
- `r5_exp_05_area_vs_critical.png`
- `r5_exp_05_release_profiles.png`
- `r5_exp_05_price_error_evidence.png`
