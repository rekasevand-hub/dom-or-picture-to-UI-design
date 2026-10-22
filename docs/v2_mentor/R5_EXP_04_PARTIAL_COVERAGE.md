# R5-EXP-04 · 部分交付表达与 coverage map

> 状态：`completed-for-current-scope`（2026-10-19），不是 `verified`。  
> 范围：4 个同坐标空缺变体、12 个覆盖区域、19/19 合同检查通过、24/24 定向负向变异被拒绝；固定 raster 分母保留，连续 2 次运行得到相同 `content_hash`。  
> 证据：`output/_r5_experiments/r5_exp_04_partial_coverage/result.json`、`canvas.json`、`report.json`、`manifest.json`、`coverage_map.json`、`mutations.json`、`artifacts/` 与 5 张结果图。  
> 边界：完全离线；画布、报告、manifest、coverage map 和 raster diff 均为实验模型，不连接 Figma，不证明真实导出限制、用户理解或生产发布门禁。

## 1. 目的与边界

本实验回答 `R5-Q04`：当同一位置因不同原因没有交付时，系统能否让用户和机器分别看懂：

- `intentional-omission`：按策略有意省略；
- `write-failed`：要求写入但写入失败；
- `observed-absent`：目标状态中观测到不存在，不等于删除；
- `not-captured`：没有采集到该区域，不能推断为不存在。

同时验证：

- PARTIAL 根名、独立报告、图例与不可做操作；
- coverage map 包含坐标、状态、原因、证据、受影响维度与对象键；
- 面积、对象、文字、关键项覆盖分开计算；
- 重叠面积按并集，不按区域矩形相加；
- 诊断占位可以从局部 diff 排除，但原合同分母不缩小；
- 即使 masked diff 为 0，发布状态仍为 `partial`，不能升级为完整导出。

本实验不验证：

- 真实 Figma 根节点、报告 Frame、锁、独立页面或手动导出阻断；
- 真实截图/OCR、DOM 采集、写入失败或捕获失败；
- 真实用户能否理解四种状态词；
- 生产 coverage map、manifest 或 release gate 的实现；
- 任意形状 mask、自动生成缺口几何或真实站点覆盖率。

## 2. 环境与可复现性

| 项目 | 值 |
|---|---|
| 操作系统 | Windows 11 |
| Python | 3.12.0（`C:\Users\lzq\.conda\envs\omni\python.exe`） |
| 依赖 | 标准库 + `numpy`、`Pillow`、`matplotlib` |
| Figma / bridge | 未连接 |
| 空缺变体 | 4 |
| 覆盖区域 | 12 |
| 合同检查 | 19/19 |
| 负向变异 | 24/24 被拒绝 |
| case 缺口坐标 | `x=600, y=290, width=500, height=120` |
| 页面 raster 分母 | `912,000 px`（`1200 × 760`） |
| 连续运行 | 2 次 |
| 最终 `content_hash` | `94f843feb23279dc6b090303f36edd00692b52e7b0c642475b2a9aa9b08e7ea2` |

重跑命令：

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe scripts\r5_exp_04_partial_coverage.py
```

脚本只清理并重建：

```text
output/_r5_experiments/r5_exp_04_partial_coverage/
```

不修改 `src/`、`figma_bridge/` 或其他用户产物。

## 3. 方法

### 3.1 同位置四变体

四个 case 使用同一份参考画布、同一 `price-panel` 矩形和同一空白业务输出；只有报告中记录的缺口原因、证据、当前显示行为、不可做操作和下一步不同。

| Case | 用户可见占位 | coverage state |
|---|---|---|
| `intentional-omission` | `NOT DELIVERED / INTENTIONAL OMISSION` | `missing` |
| `write-failed` | `NOT DELIVERED / WRITE FAILED` | `missing` |
| `observed-absent` | `NOT DELIVERED / OBSERVED ABSENT` | `missing` |
| `not-captured` | `NOT CAPTURED / OBSERVATION UNKNOWN` | `unknown` |

`observed-absent` 明确记录 `not_deleted=true`；`not-captured` 使用 `unknown_count`，不进入 `missing_count`。

### 3.2 层与表达分离

每个 case 生成：

- `[PARTIAL]` 业务根名；
- `Business Content` flow；
- 独立 `Coverage Diagnostics` 层；
- flow 外的 `Coverage / Gaps Report`；
- manifest、coverage map 与不可做操作。

诊断占位不属于设计内容，不能复用为页面内容。报告包含四种状态的图例和每类缺口的下一步。

### 3.3 覆盖维度

coverage map 分开报告：

- 面积：`denominator_px / covered_px / missing_px / unknown_px`；
- 对象：`denominator_count / covered_count / missing_count / unknown_count`；
- 文字：字符数，不用对象数替代；
- 关键项：价格面板和 CTA 两个关键项；
- 对象键、source/output 坐标、状态、原因、证据、受影响维度、允许/禁止操作。

重叠覆盖使用矩形并集。本 fixture 的区域矩形总面积 `454,250 px`，并集 `363,200 px`，重叠 `91,050 px`；coverage 使用并集。

### 3.4 raster diff 与诊断 mask

参考图包含 `price-panel`，业务输出图在同一位置留空，随后在独立诊断层绘制斜线占位。diff 使用业务输出，不把诊断占位当成原设计。

固定分母为整页 `912,000 px`。诊断 mask 仅覆盖 `60,000 px` 的缺口矩形：

```text
raw diff              = 60,000 / 912,000 = 6.5789%
valid compare         = 852,000 px
masked diff           = 0 / 912,000
denominator after mask = 912,000
release status         = partial
```

0% masked diff 只说明被排除区域是已知诊断层，不代表页面完整。

## 4. 结果

### 4.1 覆盖计数

| 维度 | 已覆盖 | 分母 | 已知覆盖 |
|---|---:|---:|---:|
| 面积 | 303,200 px | 363,200 px | 83.48% |
| 对象 | 11 | 12 | 91.67% |
| 文字字符 | 127 | 148 | 85.81% |
| 关键项 | 1 | 2 | 50.00% |

前三个 missing case 有 1 个 missing object；`not-captured` 有 1 个 unknown object、0 个 missing object。四类 case 的数字分母相同，空缺状态不同。

### 4.2 同位置状态区分

| Case | result |
|---|---|
| `intentional-omission` | 报告明确为策略省略；不能声称完整交付或把占位当设计内容 |
| `write-failed` | 报告明确为写入失败；不能声称写入成功或静默跳过重试 |
| `observed-absent` | 报告明确为目标状态不存在；`not_deleted=true`，不合成替代内容 |
| `not-captured` | 报告明确为未采集；coverage 为 `unknown`，不推断为 absent |

四类 case 都在报告和 coverage map 中保留自己的状态，没有折叠成一个笼统的 `missing`。

### 4.3 合同检查

19/19 通过：

1. 四个 case 使用同一缺口坐标；
2. 四种 gap status 在 report、manifest、coverage map 中保留；
3. 所有根名与 manifest 都标记 PARTIAL；
4. 业务 flow、诊断层与报告 Frame 分离；
5. 每个缺口有非空诊断文字；
6. 报告有四种图例和 blocked actions；
7. 用户摘要分区域、对象、文字字段、字符和关键项计数；
8. 面积/对象/文字/关键项 coverage 分开；
9. 面积使用并集且 fixture 存在重叠；
10. 关键缺口使对象、文字和关键项覆盖低于 100%；
11. `not-captured` 保持 unknown；
12. `observed-absent` 不是删除；
13. mask 后 denominator 不变；
14. masked diff 为 0 仍保持 partial；
15. lock/独立页面没有写成导出安全边界；
16. 基矩阵通过同一校验器；
17. 24 个变异全部拒绝；
18. raster、mask、诊断和合成图文件存在；
19. 运行没有连接 Figma。

### 4.4 负向变异

24/24 被拒绝，覆盖：

- 删除 `[PARTIAL]` 或声称 complete；
- 把报告/诊断层塞进业务 flow；
- 删除图例、blocked actions 或 next step；
- 用空白代表缺口；
- 把 intentional omission 与 write failure 互相改名；
- 把 observed absent 写成 deleted；
- 把 not-captured 写成 observed-absent；
- 删除 coverage reason/evidence/object keys/affected dimensions；
- 扭曲 source→output 坐标；
- 合并 coverage 成一个总分；
- mask 后缩小分母；
- masked diff 为 0 后升级 complete；
- 用区域面积之和替代并集；
- 摘要加入混合单位 total；
- 把 Figma lock 写成手动导出安全边界；
- 允许自动 complete export。

这些变异只证明当前校验器拒绝列出的错误，不等于穷尽所有 partial/release 语义错误。

## 5. 发现

1. PARTIAL 状态必须同时出现在用户可见根名、独立报告、manifest 和 coverage map，不能只藏在一个字段里。
2. 四种空缺原因必须有独立状态、独立证据和独立下一步。`intentional-omission / write-failed / observed-absent / not-captured` 不能共用一个“missing”标签。
3. `observed-absent` 不等于删除；`not-captured` 不等于空。二者分别在输出、coverage 和 blocked actions 中保留。
4. 面积、对象、文字和关键项覆盖必须并行报告。该实验的面积覆盖 83.48%，但仍有关键项覆盖 50%，不能以面积或总分抵消关键内容失败。
5. 诊断占位必须在独立层，且要带状态文字、原因和图例；空白不能作为缺口表达。
6. coverage map 必须记录 source/output 坐标与映射。否则同一缺口在报告、画布和 diff 中可能对不上。
7. 重叠面积按区域之和会高估覆盖；本 fixture 的矩形和比并集多 91,050 px。
8. 诊断 mask 可以把已知占位从局部 diff 排除，但原合同分母必须保留。masked diff 为 0 只能说明 mask 覆盖了已知差异，不能说明页面完整。
9. 锁、独立页面或根名不是安全边界；当前模型明确 `manual_export_can_be_blocked=false`。
10. 报告与诊断层必须与业务 flow 分离，不能把报告或占位当作最终设计内容。

## 6. 对生产交付的门禁建议

1. 根名、独立报告、manifest 和 coverage map 同时记录 `PARTIAL`；禁止只靠一个字段声明。
2. coverage map 至少包含 `region_id / coordinate_system / coverage_status / reason / evidence / affected_dimensions / object_keys / blocked_actions / next_step`。
3. 四种空缺使用固定枚举，新增原因必须显式扩展，不能复用一个 `missing`。
4. 面积、对象、文字字符/字段、关键项分别计算；任何单一覆盖分数都不能替代硬门禁。
5. 区域面积使用并集；mask 只排除已知诊断区域，分母保持原合同。
6. masked diff、raw diff、有效对比像素和未测区域同时输出；diagnostic 排除区不能变成绿色通过。
7. `not-captured` 保留 unknown；`observed-absent` 保留证据和未删除声明，等待状态/合同确认。
8. `[PARTIAL]` 诊断占位放独立层，不能进入业务 flow；锁和页面隔离只做防误改，不作为导出安全承诺。
9. 自动导出必须区分 complete 与 explicit partial；没有能力时不得声称门禁已实现。

## 7. 限制

1. 这是一个离线 authored fixture，不是生产页面或真实 Figma 交付。
2. 四个 case 共用同一缺口几何，不能证明自动发现任意缺口区域。
3. coverage 的区域、对象、文字与关键项是人工合同单位，不代表业务价值权重。
4. raster diff 是矩形 mask 实验，不覆盖不规则遮罩、抗锯齿边缘、字体渲染差异或半透明图层。
5. `not-captured` 是模型化缺失证据，不是浏览器、代理、截图或采集进程的真实失败注入。
6. `observed-absent` 只表达“目标状态没有该对象”，没有测试 tombstone、删除权限或用户并发修改。
7. 未验证真实锁、独立页面、Figma 报告 Frame、手动导出或组织权限。
8. 未做用户研究，不证明用户能自行理解四种状态词、图例或不可做操作。
9. 未运行生产 coverage map、manifest 或 release gate；校验器只覆盖本实验定义的合同。
10. 24 个负向变异不等于对所有可能错误或所有真实交付状态的完备拒绝。

## 8. 不得宣称

- 不得写“PARTIAL 交付表达已 `verified`”。
- 不得写“生产 coverage map 已实现”。
- 不得写“Figma 锁、独立页面或根名能阻止手动导出”。
- 不得写“遮罩排除后页面已经通过”或“masked diff 为 0 即完整”。
- 不得写“observed-absent 等于删除”。
- 不得写“not-captured 等于 observed-absent”。
- 不得写“面积、对象、文字、关键项可以用一个总分替代”。
- 不得把 19/19、24/24、12 个区域或 83.48% 写成真实页面覆盖率或生产安全证明。

## 9. 目视检查

2026-10-19 已人工查看：

- `r5_exp_04_case_contact_sheet.png`：四个 case 在同一 `price-panel` 位置显示四种不同诊断占位，根名均带 `[PARTIAL]`；
- `r5_exp_04_coverage_map.png`：12 个区域边界、缺口 `price-panel` 与固定分母图例可读；
- `r5_exp_04_coverage_matrix.png`：四类 case 的 area/object/text/critical 与 masked diff 表头及数据完整，首列未截断；
- `r5_exp_04_mask_denominator.png`：原始分母 `912,000`、有效比较 `852,000`、mask 与 raw diff `60,000`、masked diff `0` 清晰；
- `r5_exp_04_delivery_report.png`：四个 `[PARTIAL]` 根名、原因、覆盖状态与 blocked actions 可读，报告没有并入业务 flow。

目视检查只确认模型图和状态标签可读，不替代自动断言或生产验收。

## 10. 证据文件

- `output/_r5_experiments/r5_exp_04_partial_coverage/result.json`：环境、19 项检查、24 项变异、限制与最终哈希。
- `output/_r5_experiments/r5_exp_04_partial_coverage/canvas.json`：四个变体的根名、业务 flow、诊断层与报告 Frame。
- `output/_r5_experiments/r5_exp_04_partial_coverage/report.json`：四个缺口的图例、原因、证据、blocked actions 与下一步。
- `output/_r5_experiments/r5_exp_04_partial_coverage/manifest.json`：PARTIAL 状态、引用、四维 coverage 与 export gate。
- `output/_r5_experiments/r5_exp_04_partial_coverage/coverage_map.json`：12 个区域、bundle 坐标、coverage 与 diff 对账。
- `output/_r5_experiments/r5_exp_04_partial_coverage/mutations.json`：24 个负向变异与拒绝原因。
- `output/_r5_experiments/r5_exp_04_partial_coverage/artifacts/`：参考图、mask、逐 case business/diagnostic/delivery 与 diff 图。
- `r5_exp_04_case_contact_sheet.png`
- `r5_exp_04_coverage_map.png`
- `r5_exp_04_coverage_matrix.png`
- `r5_exp_04_mask_denominator.png`
- `r5_exp_04_delivery_report.png`
