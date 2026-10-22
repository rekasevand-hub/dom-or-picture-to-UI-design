# R5-EXP-03 · DOM / 截图字段权威矩阵

> 状态：`completed-for-current-scope`（2026-10-19），不是 `verified`。  
> 范围：8 个 authored Chromium 场景、50 个字段行、17 类字段；19/19 合同检查通过，22/22 定向负向变异被拒绝；同一脚本连续 2 次运行得到相同 `content_hash`。  
> 证据：`output/_r5_experiments/r5_exp_03_authority_matrix/result.json`、`matrix.json`、`mutations.json`、`fixtures/`、`scenes/`、`full_page_m0.png`、`full_page_m1.png`、`r5_exp_03_authority_matrix.png`、`r5_exp_03_evidence_report.png`、`r5_exp_03_contact_sheet.png`、`r5_exp_03_stack_sample.png`。  
> 边界：只覆盖本机 headless Chromium 的单页 authored fixture、DPR 1 与高对比英文 OCR；不连接 Figma，不运行生产采集/融合/写入器，不证明跨浏览器、真实站点或生产权威实现。

## 1. 目的与边界

本实验回答 `R5-Q03`：系统能否先区分字段类型与状态，再决定 DOM 或截图是否提供该字段的证据，而不是按节点一键切换来源。

本实验验证：

- CSS `text-transform`、CSS counter、canvas、可访问 iframe、不可访问 iframe、closed shadow root、DOM 隐藏旧文案、水合切换和复杂堆叠上下文；
- 原始 DOM 文本、`innerText`、生成内容、截图 OCR、CSS 声明色与合成像素色分开记录；
- 伪元素、canvas、iframe、shadow DOM、隐藏文本、截图-only 文本与局部遮挡按字段/状态矩阵处理；
- OCR 只提出或提升 `text-content`，不自动提升 `role / editability / asset-source`；
- `external-conflict / unknown / unsupported` 分别保留；
- 不从一次局部像素采样推断页面全局 z-order；
- 22 个定向错误修改全部被同一字段级校验器拒绝。

本实验不验证：

- 生产 DOM 采集器、融合器、IR 或 Figma 写入链；
- 真实站点的 DOM、iframe、shadow DOM、canvas 或复杂 CSS 分布；
- Firefox、WebKit、移动端、浏览器缩放或跨平台字体；
- OCR 的通用准确率、中文、低清、艺术字或遮挡文本；
- 页面全局绘制顺序、自动遮挡检测或任意叠放上下文；
- 真实用户对候选、未知与不支持状态的理解。

`ROUND_05_OPEN_ITEMS.md` 总表写“6 类边界场景”，正文列出了 8 个最低条目。本实验按正文执行 8 个 authored 场景，没有为对齐总表数字删减用例；矩阵图将它们归入 6 个权威家族：文本变换/生成内容、canvas、iframe、shadow、隐藏/水合、堆叠/颜色。

## 2. 环境与可复现性

| 项目 | 值 |
|---|---|
| 操作系统 | Windows 11 |
| Python | 3.12.0（`C:\Users\lzq\.conda\envs\omni\python.exe`） |
| 浏览器 | Playwright Chromium `151.0.7922.34` |
| OCR | Tesseract `5.5.0.20241111` |
| viewport / DPR | `1280 × 900` / `1` |
| Figma / bridge | 未连接 |
| 场景数 | 8 |
| 字段行 | 50 |
| 字段类型 | 17 |
| 合同检查 | 19/19 通过 |
| 负向变异 | 22/22 被拒绝 |
| 连续运行 | 2 次 |
| 最终 `content_hash` | `e954d75a4db5b5b2a8093d1ca000615b3ffc8e3fe41ef47e9a077f3f89a11edf` |

重跑命令：

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe scripts\r5_exp_03_authority_matrix.py
```

脚本只清理并重建：

```text
output/_r5_experiments/r5_exp_03_authority_matrix/
```

不修改 `src/`、`figma_bridge/`、用户实验产物或其他工作树文件。

## 3. 方法

### 3.1 真实浏览器采集

脚本生成一个本地 authored HTML fixture，由 headless Chromium 实际渲染：

| 场景 | 观测重点 |
|---|---|
| S01 | `textContent`、`innerText`、CSS uppercase、`::before` counter 与截图 OCR |
| S02 | canvas fallback、canvas 绘制字形、DOM overlay 与局部遮挡 |
| S03 | 同源 iframe 的独立文档作用域、文本、`heading` role 与静态编辑性 |
| S04 | `sandbox="allow-scripts"` 的不透明来源 iframe；页面脚本不可读子 DOM |
| S05 | closed shadow root；host 可读，shadow descendant 不可读 |
| S06 | `display:none` 旧价格仍存在于 `textContent`，但不进入可见文本 |
| S07 | 显式 M0 → M1 水合；分别截图并采集两个状态 |
| S08 | 两个 transform + z-index 堆叠上下文、DOM 顺序冲突、CSS 色与 opacity 合成 |

每个场景保存真实截图；全文另保存 `full_page_m0.png` 与 `full_page_m1.png`。OCR 输入来自截图或截图裁片，不读取生产页面结构。

### 3.2 字段观测分离

矩阵把以下量分别记录，不允许互相当作同一个 winner：

| 观测 | 例子 |
|---|---|
| `raw-dom-text` | S01 `textContent = "sale item alpha"` |
| `visible-dom-text` | S01 `innerText = "SALE ITEM ALPHA"` |
| generated content | S01 computed `::before` 声明含 `counter(...)` |
| `screenshot-ocr-text` | S01 OCR 得到 `01 / SALE ITEM ALPHA` |
| `css-declared-color` | S08 `rgb(220, 38, 38)` |
| `composited-pixel-color` | S08 实际像素 `rgb(233, 143, 144)` |
| `local-occlusion` | S08 在采样点观察到 `ctx-high` 位于 `ctx-low` 上方 |
| `global-z-order` | 保持 `unsupported`，不生成 |

每个矩阵行至少包含：

- `row_id / scene_id / object_id / field_type`；
- `authority = dom | screenshot | dom+screenshot | none`；
- `decision_status = authoritative | observed | candidate | external-conflict | unknown | unsupported | not-applicable`；
- `selected_value`、`release_eligible`、`cannot_promote`、理由与证据引用。

矩阵只做字段裁决；`node_authorities` 必须为空。负向变异里的整节点截图权威会失败。

### 3.3 状态规则

| 状态 | 本实验含义 |
|---|---|
| `authoritative` | 当前字段可由指定观测满足，值可用于该字段 |
| `observed` | 观测已记录，但不自动成为最终裁决 |
| `candidate` | 截图/OCR 只提供候选，默认不可发布 |
| `external-conflict` | 两份观测来自不同状态或相互矛盾 |
| `unknown` | 缺少足够证据，不能写成空值或默认值 |
| `unsupported` | 请求明确，但当前页面可访问能力不支持 |
| `not-applicable` | 该字段不适用于该对象 |

状态先于权威切换。只要水合状态、文档作用域或可访问能力不一致，字段比较就不能继续。

## 4. 结果

### 4.1 状态与权威计数

| 决策状态 | 行数 |
|---|---:|
| `authoritative` | 31 |
| `observed` | 4 |
| `candidate` | 4 |
| `external-conflict` | 3 |
| `unknown` | 5 |
| `unsupported` | 3 |
| 合计 | 50 |

| 权威 | 行数 |
|---|---:|
| `dom` | 34 |
| `screenshot` | 7 |
| `dom+screenshot` | 3 |
| `none` | 6 |
| 合计 | 50 |

### 4.2 逐场景结果

| 场景 | 关键观测 | 字段裁决 |
|---|---|---|
| S01 | raw `sale item alpha`；innerText `SALE ITEM ALPHA`；OCR `01 / SALE ITEM ALPHA` | raw/visible 分离；最终文本由 DOM 源文本 + 截图生成内容共同确认；role/editability 仍由 DOM |
| S02 | canvas fallback `CANVAS FALLBACK`；OCR `SHOT ONLY 42`；DOM overlay 局部在上 | canvas 文本为 `screenshot / candidate`；role=`img`、editability=`none`、asset=`canvas-bitmap`；只记录局部遮挡 |
| S03 | 页面可读 iframe，标题 `FRAME ACCESSIBLE 7`，role=`heading` | 文本、role、editability、frame scope 均由子文档 DOM 提供 |
| S04 | 页面访问为 false；sandbox 不允许同源；截图裁片 OCR `FRAME OFFLINE 88` | text-content 为 `screenshot / candidate`；role/editability/asset=`unknown`；frame-access=`unsupported` |
| S05 | host role=`article`，`shadowRoot=null`；OCR `CLOSED SHADOW 3` | 文本为截图候选；host role 可读；shadow 内 role/editability/asset 未知；shadow-access=`unsupported` |
| S06 | raw 同时含 `LEGACY PRICE 19 CURRENT PRICE 29`；可见文本仅为 `CURRENT PRICE 29` | hidden 状态由 DOM 确认；旧文案不进入 text-content |
| S07 | M0=`DRAFT COPY`，M1=`LIVE COPY`，两张截图与两个 DOM 状态分开 | M0/M1 配对为 `external-conflict`；只有当前 M1 文本可裁决 |
| S08 | DOM 顺序 `ctx-high → ctx-low`；后者 DOM 更晚；重叠采样像素为 `rgb(249, 115, 22)` | 只记录 `ctx-high` 在采样点上方；`global-z-order=unsupported` |

关键颜色结果：

- S01 CSS `rgb(220, 38, 38)`，50% opacity 后像素 `rgb(237, 145, 145)`；
- S08 声明 CSS `rgb(220, 38, 38)`，50% opacity 后像素 `rgb(233, 143, 144)`；
- S08 堆叠重叠点像素 `rgb(249, 115, 22)`，与 high context 的 CSS fill 一致，而不是后出现的 blue context。

### 4.3 合同检查

19/19 通过：

1. 8 个场景均有真实 Chromium 截图；
2. `textContent`、`innerText` 与 counter 声明分开；
3. OCR 恢复生成 counter；
4. canvas fallback 与可见 bitmap 文本不同；
5. 可访问 iframe 独立作用域、heading role 与 OCR 一致；
6. 不可访问 iframe 没有被当作空文档；
7. closed shadow 没有被写成 DOM 可读；
8. 隐藏旧文案没有进入可见文本；
9. 水合 M0/M1 状态门生效；
10. 局部堆叠采样与 DOM 栈上下文一致；
11. CSS 色与像素色没有合并；
12. 原始文本、可见文本、CSS 色、像素色同时存在；
13. 三种未决状态同时存在；
14. OCR 从未拥有 role/editability/asset-source；
15. 没有伪造全局 z-order；
16. 基矩阵通过同一校验器；
17. 22 个变异全部拒绝；
18. 截图/OCR/整页证据文件齐全；
19. 运行确实来自浏览器而非固定 JSON 退化。

### 4.4 负向变异

22/22 被拒绝，覆盖：

- 把 raw text 当作可见文本；
- 丢掉 CSS counter；
- 把 CSS 色当作像素色；
- 让 canvas OCR 晋升 editability、role 或原始资产来源；
- 把 iframe 合并进父文档作用域；
- 把不可访问 iframe 写成空文档或可读文档；
- 从 closed shadow 像素猜 role 或声称 DOM 可读；
- 把隐藏旧文案重新写成可见文本；
- 让水合 M0 旧值胜出；
- 把 `external-conflict` / `unsupported` 折叠成 `unknown`；
- 从截图顺序推断全局 z-order；
- 用 DOM 顺序替代局部像素叠放结果；
- 让 OCR 候选 release；
- 删除语义晋升限制；
- 写入整节点截图权威；
- 用像素色替换 CSS 声明色。

这些变异只证明当前校验器会拒绝列出的错误，不等于穷尽所有权威错误。

## 5. 发现

1. `textContent`、`innerText` 与截图可见文本是三个不同口径。S01 的 raw 文本、transformed 文本与 counter 前缀分别出现，不能用任一口径覆盖其余两者。
2. CSS 生成内容可以是可见文本的一部分，但不能同时证明原始 DOM 文本或可编辑性。OCR 可提升 `text-content`，语义字段仍需分开裁决。
3. canvas 可见文字可以成为文本候选，但 canvas  bitmap 不自动提供可编辑文本、heading role 或原始字体/矢量来源。
4. 可访问 iframe 必须保留独立文档作用域；不可访问 sandbox iframe 只能保留像素证据。`pageAccess=false` 是 `unsupported`，不是空字符串或空文档。
5. closed shadow root 只能证明 host 语义与可见像素。shadow descendant 的 role、editability 与 asset source 不能从 OCR 或宿主属性补造。
6. `display:none` 旧文案仍可能存在于 `textContent`。它应保留为原始证据，但不能写成可见节点或当前价格。
7. 水合切换必须先建立状态签名。M0 DOM 与 M1 截图配对时应为 `external-conflict`，不能先比较文本再碰运气。
8. 复杂堆叠上下文中，DOM 顺序不是绘制顺序。截图像素能回答一个局部采样点上的前后关系，但不能恢复全局 z-order；本实验的 later-DOM/low-z 蓝色块没有盖住 earlier-DOM/high-z 橙色块。
9. CSS 声明色与合成像素色回答不同问题。opacity/blend/filter 使两者数值不同是预期现象，不构成 CSS 错误或颜色冲突。
10. 字段级状态机比“节点来自 DOM 或截图”更可靠。同一节点可以同时有 DOM 文本、截图可见文本、DOM role 与像素外观，不能整节点切换权威。

## 6. 对生产采集与融合的门禁建议

1. 观测记录增加 `observation_kind`，至少区分 `raw-dom-text / visible-dom-text / screenshot-ocr-text / css-declared-color / composited-pixel-color / local-occlusion`。
2. 每个字段单独记录 `authority / decision_status / reason / evidence_refs / cannot_promote`；禁止节点级 authority map。
3. `text-content` 的截图候选必须带 `release_eligible=false` 与非空语义晋升限制，直到业务规则明确允许。
4. iframe 必须记录父页面与子文档作用域；不可访问与空文档分开。closed shadow 必须记 host 可读边界。
5. 先比较状态签名、页面修订与文档作用域，再比较字段；`external-conflict`、`unknown`、`unsupported` 不得合并。
6. `visibility=hidden` 由 DOM/计算样式或等价证据确认；`textContent` 存在不等于可见内容。
7. z-order 只记录带几何、候选对象和采样点的 `local-occlusion`；没有额外证据时 `global-z-order=unsupported`。
8. CSS color 与 composited pixel color 都保留；像素采样不得直接替换 fill。视觉近似需要单独的批准政策。

## 7. 限制

1. 只覆盖一个本地 authored 页面、一个 Chromium 构建和 DPR 1。
2. 8 个场景是边界夹具，不是真实站点抽样，也没有响应式、滚动、动画、懒加载或跨页面状态。
3. S04 的不可访问性来自 `sandbox="allow-scripts"` 的不透明来源；Playwright 仍能控制浏览器并截图，不能把自动化工具能力当成页面脚本能力。
4. S01、S02、S04、S05 的 OCR 结果来自高对比英文和选定裁片；Tesseract 结果不代表中文、低清或艺术字准确率。
5. S02 只采样 overlay 背景像素；S08 只采样一个重叠点。两者都不构成自动遮挡检测。
6. S08 的“全局 z-order unsupported”来自证据边界，不表示页面没有全局绘制顺序；它只表示本实验不能从现有采样恢复。
7. 50 个字段行是人工设计的合同矩阵，不代表生产页面的字段分布。
8. 未运行生产 DOM 采集、融合、IR、Figma 写入、验收或发布门禁。
9. 22 个变异是本脚本定向构造的非法修改，不覆盖所有可能的语义错误。
10. 没有做 Firefox、WebKit、移动端、缩放、跨平台字体或用户理解测试。

## 8. 不得宣称

- 不得写“DOM/截图权威矩阵已经 `verified`”。
- 不得写“DOM 永远负责文本”或“截图接管全部字段”。
- 不得写“生产融合器已经实现字段级权威矩阵”。
- 不得写“系统已经能自动恢复页面全局 z-order”。
- 不得写“OCR 可以恢复原语义、原可编辑性或原始资产来源”。
- 不得写“不可访问 iframe 的内容等于空”。
- 不得写“closed shadow root 的内部语义已被采集”。
- 不得把 19/19、22/22、50 个字段行写成真实站点成功率或生产覆盖率。
- 不得把本实验外推到 Firefox、WebKit、移动端或任意复杂站点。

## 9. 目视检查

2026-10-19 已人工查看：

- `r5_exp_03_contact_sheet.png`：8 个场景均按设计渲染；S01 counter、S02 canvas/overlay、S03/S04 iframe、S05 shadow、S06 hidden copy、S07 live copy 与 S08 叠放均可辨识；
- `r5_exp_03_authority_matrix.png`：标题、列标题、8 行场景与图例完整，无裁切；
- `r5_exp_03_evidence_report.png`：状态计数、检查数、变异数、关键观测与图例可读；
- `r5_exp_03_stack_sample.png`：采样十字落在橙色 high context 与蓝色 low context 的重叠区，像素标签与实际采样一致。

目视检查只确认产物可读和 fixture 没有明显渲染错位，不替代自动断言或生产验收。

## 10. 证据文件

- `output/_r5_experiments/r5_exp_03_authority_matrix/result.json`：环境、输入、DOM/OCR/像素观测、19 项检查、22 项变异、限制与最终哈希。
- `output/_r5_experiments/r5_exp_03_authority_matrix/matrix.json`：50 个字段级权威行及完整证据引用。
- `output/_r5_experiments/r5_exp_03_authority_matrix/mutations.json`：22 个负向变异与拒绝原因。
- `output/_r5_experiments/r5_exp_03_authority_matrix/fixtures/index.html`：真实 Chromium authored fixture。
- `output/_r5_experiments/r5_exp_03_authority_matrix/scenes/S01/`–`S08/`：逐场景截图与 OCR 源/裁片。
- `output/_r5_experiments/r5_exp_03_authority_matrix/full_page_m0.png`：水合前整页截图。
- `output/_r5_experiments/r5_exp_03_authority_matrix/full_page_m1.png`：水合后整页截图与像素采样源。
- `output/_r5_experiments/r5_exp_03_authority_matrix/r5_exp_03_authority_matrix.png`：字段权威矩阵图。
- `output/_r5_experiments/r5_exp_03_authority_matrix/r5_exp_03_evidence_report.png`：状态计数、运行摘要与关键观测图。
- `output/_r5_experiments/r5_exp_03_authority_matrix/r5_exp_03_contact_sheet.png`：8 场景联系表。
- `output/_r5_experiments/r5_exp_03_authority_matrix/r5_exp_03_stack_sample.png`：局部叠放采样标注图。
