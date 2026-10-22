# R3-EXP-10 · 截图 flow 扰动与 DOM 冲突隔离（受控实验）

> 状态：`completed-for-current-scope`（2026-10-18），不是 `verified`。  
> 范围：7 个合成输出合同场景 + 1 个合成 DOM 顺序冲突夹具。  
> 证据：`output/_r3_experiments/exp10_flow_perturbation.json`、`output/_r3_experiments/exp10_flow_plugin/`、`EXP10_*_contact.png`、`exp10_dom_conflict_fixture.png`。  
> 边界：只验证“所选输出规则是否满足获准的编辑合同”。通过项只能写 `verified_for=output-contract`、`source_behavior=inferred`；不证明原站响应式规则。

## 1. 目的与边界

本实验回答五个问题：

1. 页面、卡片集合、卡片信息、主栏/侧栏与页脚的内容行，在 `+40` 高度、长标题、条目增删、宽度 `±10%` 与高低交换下，是否保持顺序、数量、间距与传播关系。
2. L1 已设置、L2 布局确实参与、L3 在声明范围内行为正确，能否分开记录，而不是用 `layoutMode` 数量代替。
3. 绝对定位的底部分隔线在父级变高时是否参与 resize，并保持底边锚定。
4. 复杂叠放在无法线性化时，是否保留固定坐标并明确披露，而不是强行套 Auto Layout。
5. 截图轨与 DOM 轨冲突时，是否只记 `external-conflict` 与对应 reference，不用 DOM 覆盖截图证据。

所有场景都是实验者编写的合成夹具。它们验证的是输出合同，不是“猜对了原站”。原始网站的断点、字体、真实文本度量与响应式规则均未测。

## 2. 环境与可复现性

| 项目 | 值 |
|---|---|
| 操作系统 | Windows 11（`10.0.26300`） |
| Python | 3.13.9（`D:\LLM_condas\python.exe`） |
| Node.js | 24.18.0 |
| Figma 编辑器 | `editorType=figma`，Plugin API `1.0.0` |
| 文件 / 页面 | `FigmaAgent复刻UI` / `Page 1` |
| 插件 | `UI Reconstruct EXP10 Flow Probe` |
| 桥接 | `ws://localhost:8765`，仅实验插件协议 |
| 字体 | Inter Regular（Figma 字体引擎） |
| 节点前缀 | `EXP10_` |

脚本：`output/_r3_experiments/exp10_flow_perturbation.py`。完整重跑约 6 秒，会清理并重建所有 `EXP10_` 根节点、导出每个状态的 PNG、生成联系表与 JSON。

```powershell
python output/_r3_experiments/exp10_flow_perturbation.py
```

插件源码在 `output/_r3_experiments/exp10_flow_plugin/`。它只实现实验所需的建场、编辑、回读与导出操作，不调用生产 bridge 的 `setAutoLayout` 或其他写路径；因此 `src/` 与 `figma_bridge/` 未被修改。

## 3. 方法

### 3.1 三级记录

每个场景分别记录：

- **L1 已设置**：轴、sizing、间距、padding、在流/绝对定位与约束已写入并回读。
- **L2 布局参与**：一次扰动后，子项位置或父级尺寸确实由布局引擎改变，而不是坐标被手工改写。
- **L3 行为正确**：在声明场景内，顺序、数量、间距、传播、无意外遮挡与装饰锚定均符合预期。

L3 通过也只覆盖本次输出，不证明网页原规则。全实验统一容差 `TOL = 0.6 px`。

### 3.2 场景矩阵

| 场景 | 输出策略 | 扰动 |
|---|---|---|
| `EXP10_page_stack` | 页面纵向 stack；子项横向 Fill；父级高度 Hug；子项高度固定 | 主栏 `220→260`、插入/删除 100px 通知条、宽度 `900→990` |
| `EXP10_card_row` | 单行横向集合；卡片 140px 固定；父级宽度 Hug | 插入第 6 张、删除第 2 张、宽度 `+10%`、宽度 `-10%` 后回退 |
| `EXP10_card_info` | 卡片纵向；封面固定；文本宽度固定；高度 Hug | 标题 2 行→4 行、作者 1 行→2 行 |
| `EXP10_main_sidebar` | 同一横向行；主栏/侧栏固定宽度；顶对齐；各自内部纵向 | 主栏 `496→536`、高低交换、宽度 `1440→1584/1296` |
| `EXP10_footer_rows` | 页脚纵向内容行；分隔线是最后的 1px 流子项 | 第 2 行 `+40`、插入/删除一行 |
| `EXP10_abs_divider_row` | 行内绝对定位底部分隔线，`vertical=MAX` | 行高 `44→84` |
| `EXP10_overlap_fixed` | 复杂叠放保持固定坐标 | 只验证基准状态与回退理由 |

### 3.3 判定与状态

| 状态 | 含义 |
|---|---|
| `pass` | 声明场景的 L1/L2/L3 全部满足 |
| `partial-fallback` | 可支持部分通过；宽度缩小导致固定卡片超界，按规则回退整个区域为固定坐标 |
| `partial-fixed-width` | 可支持部分通过；固定列宽没有获准的变列/最小宽度规则，缩小只报溢出并保留原宽度 |
| `fallback-fixed` | 复杂叠放不套 flow，保留固定坐标 |
| `fail` / `fatal-error` | 未通过的场景，本报告会明确披露 |

### 3.4 回退规则

- 宽度缩小导致固定宽度子项超出父级、且没有获准的换行或变列规则时，回退整个区域为固定坐标，并保留回退前的相对位置快照。
- “父 flow + 子固定”必须披露；一次扰动通过不等于全页面或原站通过。
- 复杂叠放、z-order 或装饰不可分离时，不强行线性化。

### 3.5 DOM 冲突隔离

DOM 轨只作为 reference。合成夹具的 DOM 顺序为 `A,B,C,D`，视觉顺序为 `D,C,B,A`；记录为 `external-conflict`，不参与 Figma 输出判定。在线目录的 `dom_order` 仍为 `unknown`，不因本实验变成冲突结论。

## 4. 结果总表

| 场景 | 状态 | 关键结果 |
|---|---|---|
| `EXP10_page_stack` | `pass` | 父页高 `360→400`；footer 下移 40；插入后 footer 再下移 100；宽度 990 时子项与内边距盒均为 Fill；右溢出 0 |
| `EXP10_card_row` | `partial-fallback` | 基线宽 764；插入后 +152；末卡 `x=768`；删除回 764；`+10%` 宽 840.4、无溢出；`-10%` 宽 687.6、溢出 68.4，回退为固定坐标 |
| `EXP10_card_info` | `pass` | 标题 2→4 行、高度 44→88；作者下移 44；卡片 `237→281`；作者 1→2 行后卡片 `281→299` |
| `EXP10_main_sidebar` | `partial-fixed-width` | 行高 `496→536`；交换后侧栏 536、行高仍 536；`+10%` 宽 1584、无溢出；`-10%` 宽 1296、溢出 19，保留静态宽度 |
| `EXP10_footer_rows` | `pass` | 第 2 行 44→84；第 3 行下移 40；页脚 222→262；插行 +44；删除回 262；5 条分隔线均贴行底 |
| `EXP10_abs_divider_row` | `pass` | 行高 44→84；分隔线 `y 43→83`，底边锚定 |
| `EXP10_overlap_fixed` | `fallback-fixed` | `layoutMode=NONE`；叠放面积 10800；3 个子项保留 |

首轮失败的 4 个场景已在第 7 节披露根因与修复；最终 JSON 只保留现行规则的结果。

## 5. 场景细节

### 5.1 页面纵向 stack

基线：header 80、main 220、footer 60，根高 360；main 有 20px padding 与 12px gap。主栏改为 260 后：

- footer 绝对 `y` 从 300 到 340，位移 40；
- 根高从 360 到 400，增长 40；
- 没有显式写入子项坐标，flow 兄弟无重叠。

在主栏与 footer 之间插入 100px 通知条后，顺序为 `header, main, notice, footer`，footer 再下移 100；删除后 footer 回到 340，且没有残留空隙。根宽改为 990 后，三个直接子项均变为 990，main 的两个内层子项均变为 950（990 − 左右各 20 padding），右溢出为 0。

该场景覆盖“页面纵向 + 子项 Fill + 父级 Hug”的输出合同，并保留“子项高度固定”的限制。

### 5.2 卡片横向集合

5 张 140px 卡片、4 个 12px gap、左右各 8px padding，父级 Hug 宽度为 `5×140 + 4×12 + 2×8 = 764`。基线顺序为 01–05，卡片宽度均为 `FIXED`。

在第 5 个位置插入第 6 张后：

- 数量 6，顺序为 `01,02,03,04,06,05`；
- 父宽增加 `140+12=152`；
- 原末卡 05 的 `x` 由 616 变为 768，没有写坐标。

删除卡片 02 后数量回到 5，顺序为 `01,03,04,06,05`，父宽回到 764。宽度 `+10%` 到 840.4 时，5 张卡片仍为 140，右溢出为 0；宽度 `-10%` 到 687.6 时，卡片仍为 140，右溢出 68.4。由于没有获准的换行或变列规则，整个行回退为 `layoutMode=NONE`，恢复删除后的相对位置 `8,160,312,464,616`，无兄弟重叠。

该场景只覆盖单行扁平集合；跨行重排未测。

### 5.3 卡片信息

封面 142×142 固定；信息块在卡片纵向流中，标题与作者宽度 134、行高 22/18。基线标题为 2 行（44），作者 1 行（18），信息块 Hug 高 95，卡片高 237。

标题改为 `A comprehensive handbook of modern typography and editorial design` 后：

- 标题 4 行、高 88；
- 作者下移 44；
- 卡片高 281（+44），无标题/作者重叠。

作者改为 `Alexandra Long-Name Designer and Editor` 后：

- 作者 2 行、高 36；
- 卡片高 299（再 +18）；
- 文本仍在卡片宽度内。

该场景证明“文本高度变化 → 信息块 Hug → 卡片 Hug”的传播链；行数来自 `height / lineHeight` 的估算，因为该 Figma API 回读不提供 `lineCount`。它不是同内容重排比较，也不代表原站字体度量。

### 5.4 主栏与侧栏

基线：根 1440×496，左右各 125 padding、20 gap；主栏 790×496，侧栏 380×440，顶对齐，水平行高取较高列 496。

主栏改为 536 后，行高 536，侧栏仍与行顶对齐；主栏底边与行底边重合。交换主栏/侧栏高度后，侧栏 536、主栏 440，行高仍 536，顺序保持主栏在左。

宽度 `+10%` 到 1584：两列仍为 790/380，右溢出为 0。宽度 `-10%` 到 1296：两列不变，右溢出 19；没有获准的最小宽度或变列规则，因此恢复静态宽度 1440，并记录 `partial-fixed-width`。

### 5.5 页脚内容行

5 行、每行 44（标签 43 + 分隔线 1）、根 padding 1，基线高 222，行 `y` 为 1/45/89/133/177。

第 2 行标签改为 83 后：

- 第 2 行 44→84；
- 第 3 行从 89 到 129，位移 40；
- 根高 222→262；
- 第 2 行分隔线 `y=83`，贴行底。

插入一行后根高 306（+44）；删除后回到 262，顺序恢复；5 条分隔线全部满足 `abs(divider.y - (row.height - 1)) <= 0.6` 且绝对底边对齐。

### 5.6 绝对定位底部分隔线

行 300×44，标签 43 高，分隔线绝对定位在 `y=43`，声明 `constraints={horizontal:STRETCH, vertical:MAX}`。行高改为 84 后，分隔线 `y` 从 43 到 83，参与 resize 并保持底边锚定。

该微测只覆盖单个绝对子项与一次父级 resize；它不证明所有装饰都能用绝对定位。

### 5.7 复杂叠放

320×240 固定坐标区域包含 base、overlay 与 badge，base 与 overlay 有意重叠 10800 平方像素。基准状态保留 3 个子项且 `layoutMode=NONE`。强行线性化会改变 z-order 与参考状态，因此输出 `fallback-fixed`，L1/L2/L3 记 `not applicable`，而不是伪造通过。

## 6. DOM 冲突隔离

合成夹具 `exp10_dom_conflict_fixture.html` 使用 `flex-direction:row-reverse`：DOM 顺序为 `A,B,C,D`，截图视觉顺序为 `D,C,B,A`。Chrome 无头截图成功（退出码 0）。

记录为：

```json
{"status": "external-conflict", "dom_order": ["A","B","C","D"], "screenshot_visual_order": ["D","C","B","A"]}
```

处理规则是保留截图顺序，DOM 只附 reference，不反向改写截图证据。该夹具只证明机制，不是真实站点样例；在线目录 `R3-D01` 的 `dom_order` 仍为 `unknown`，既不是冲突，也不是 DOM 证据。

## 7. 首轮失败、根因与修复

首轮 7 个场景中 4 个失败。最终 JSON 已按现行规则重跑，首轮结果不保留为通过证据；根因在此披露：

1. **HUG 被 resize 覆盖**：子节点插入父级后，实验插件先设置 `layoutSizingVertical=HUG`，随后又用 `spec.height` 调用 `resize()`，把 Hug 改回 Fixed。`EXP10_card_info_body` 回读为 `primaryAxisSizingMode=FIXED`，所以标题变高但卡片不变。修复：先应用基础宽度/高度，再按声明重设轴 sizing 与子项 sizing。
2. **页脚行声明矛盾**：`EXP10_footer_row_*` 同时声明纵向 `primaryAxisSizingMode=AUTO` 与 `layoutSizingVertical=FIXED`，后者覆盖前者。修复：行改为 Hug，分隔线仍是最后 1px 流子项。
3. **卡片行宽度预期错误**：夹具预期 768，实际 Hug 宽度为 `5×140+4×12+2×8=764`。修复：夹具与 `±10%` 预期改为 764 / 840.4 / 687.6。
4. **顶对齐检查用了绝对零点**：`main_sidebar` 场景位于 `y=600`，检查却写成 `sidebar.absoluteY == 0`。修复：比较侧栏与父行的 `absoluteY`。
5. **基线标题行数假设错误**：标题宽 128 时 `Modern typography handbook` 为 3 行；内容宽度是 134，改为 134 后恰为 2 行，基线高 95 与卡片 237 才闭合。

修复后重跑：4 `pass`、1 `partial-fallback`、1 `partial-fixed-width`、1 `fallback-fixed`，0 失败检查。

## 8. 观测、推导、推断与未测

| 层 | 内容 |
|---|---|
| 观测 | Figma 插件回读的节点几何、sizing、约束与子项顺序；每个状态的 PNG；DOM 夹具截图 |
| 推导 | 位移差、父级尺寸差、溢出量、行数估算、叠放面积、状态归类 |
| 推断 | 这些输出规则可作为同类区域的候选策略；回退边界可由扰动结果确定 |
| 未测 | 原站响应式与断点；真实 OCR/字体度量；两层 stack 跨行重组；生产 bridge 集成；跨 Figma 版本；真实站点 DOM 顺序 |

## 9. 不得宣称

- 不得宣称“原站使用了这些 flow 规则”或“原站响应式已验证”。
- 不得用 Auto Layout 数量、一次渲染成功或本实验的 `pass` 数量作为质量总分。
- 不得用 DOM 顺序覆盖截图顺序，也不得把 `unknown` 写成冲突。
- 不得把单行卡片集合的结论外推到跨行重排、换行或变列。
- 不得把复杂叠放的固定坐标写成 flow 通过。
- 不得把本实验的 4 个 `pass` 外推到所有区域、字体、视口或 Figma 版本。
- 不得把 `partial-fallback` / `partial-fixed-width` 写成完全通过。

## 10. 证据文件

- `output/_r3_experiments/exp10_flow_perturbation.py`
- `output/_r3_experiments/exp10_flow_perturbation.json`
- `output/_r3_experiments/exp10_flow_plugin/manifest.json`
- `output/_r3_experiments/exp10_flow_plugin/code.js`
- `output/_r3_experiments/exp10_flow_plugin/ui.html`
- `output/_r3_experiments/EXP10_page_stack_contact.png`
- `output/_r3_experiments/EXP10_card_row_contact.png`
- `output/_r3_experiments/EXP10_card_info_contact.png`
- `output/_r3_experiments/EXP10_main_sidebar_contact.png`
- `output/_r3_experiments/EXP10_footer_rows_contact.png`
- `output/_r3_experiments/EXP10_abs_divider_row_contact.png`
- `output/_r3_experiments/EXP10_overlap_fixed_contact.png`
- `output/_r3_experiments/exp10_dom_conflict_fixture.html`
- `output/_r3_experiments/exp10_dom_conflict_fixture.png`

## 11. 状态与后续

- 本实验状态：`completed-for-current-scope`，不是 `verified`。
- 通过项字段：`verified_for=output-contract`、`source_behavior=inferred`。
- `R2-EXP-01` 的扰动类型（`+40`、长标题、宽度 `±10%`、条目增删、高低交换）已在输出合同层覆盖并并入本实验；authored DOM 容器由 `R2-EXP-01` 另行验证，但原站 DOM 与原站响应式仍未验收，因此本实验只能记 `partial`。
- 后续 `R3-EXP-11–15` 均已完成当前范围；R4 已由用户明确同意并完成 `R4-EXP-01–10` 当前范围。
