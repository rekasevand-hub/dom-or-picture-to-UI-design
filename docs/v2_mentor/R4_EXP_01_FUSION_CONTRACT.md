# R4-EXP-01 · 逐字段融合合同与来源审计（受控实验）

> 状态：`completed-for-current-scope`（2026-10-18），不是 `verified`。  
> 范围：1 个合成页面、4 个状态签名、24 个逐字段合同用例、20 个裁片、14 项合同检查。  
> 证据：`output/_r4_experiments/r4_fusion_contract.json`、`output/_r4_experiments/r4_fusion_artifacts/dom_route.json`、`screenshot_route.json`、`fusion_output.json`、4 张视口截图、`crops/` 20 张裁片，以及 `r4_fusion_matrix.png`、`r4_fusion_flow.png`、`r4_fusion_status.png`。  
> 边界：只验证“两条路线融合时，每个字段是否有唯一权威来源、状态门是否先于字段比较、未决项是否保留证据”。不验证 OCR/CV 自动感知、真实站点分布、生产融合实现或 Figma 写入。

## 1. 目的与边界

本实验回答五个问题：

1. DOM 路线与截图路线都给出观测时，能否为每个字段指定唯一权威来源，而不是逐用例临时选边。
2. 轮播帧、滚动和 modal 覆盖层造成的状态差异，能否在字段比较之前被状态门阻断。
3. 两侧都缺失、只有一侧观测、配对歧义和内容 hash 不等时，是否停在 `unknown / ambiguous / external-conflict`，而不是强行给答案。
4. bbox 小误差能否只用绝对容差收敛；超差时是否拒绝平均值。
5. 截图裁片能否只作为降级栅格，而不被宣称为原始资产或原生可编辑文本。

所有页面、元素和状态都是实验者编写的合成夹具。4 张视口截图由 Playwright 真实渲染；但截图路线中的 `visible_state / occlusion / z_order / rendered_effect / bbox` 等观测值是**夹具输入**，附着在真实截图上，**不是 OCR、CV 或像素分类的结果**。因此本实验证明的是融合政策与审计结构，不是感知能力。

未修改 `src/`、`figma_bridge/`，未执行 Figma 写路径，未调用 OCR/CV 模型。

## 2. 环境与可复现性

| 项目 | 值 |
|---|---|
| 操作系统 | Windows 11（`10.0.26300`） |
| Python | 3.12.0（`C:\Users\lzq\.conda\envs\omni\python.exe`） |
| Chromium | 151.0.7922.34（Playwright headless） |
| Pillow | 12.2.0 |
| 视口 / DPR | 1200×900 CSS px / 1 |
| 状态 | S0 默认、S1 frame 1、S2 scroll 600、S3 modal |
| 合成页面 | `output/_r4_experiments/r4_fusion_artifacts/site/index.html` |

重跑命令：

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe output/_r4_experiments/r4_fusion_contract.py
```

脚本会重建合成页面、4 张截图、20 张裁片、三份路线/融合 JSON 与三张图；本次完整重跑约 2 秒。

## 3. 方法

### 3.1 两条路线

DOM 路线记录：

- `text / font / color / role / editability / asset_source`；
- `bbox`；
- `content_hash`（规范化文本的 SHA-256）。

截图路线记录：

- `visible_state / occlusion / z_order / rendered_effect`；
- `bbox`；
- `content_hash`（规范化文本的 SHA-256；本实验中 C18 代表陈旧渲染）；
- 真实裁片的 `crop.sha256`，只作为裁片身份，不参与内容 hash 比较。

每条观测都有 `evidence_id`、`state`、`basis` 与 `verification`。截图路线的 `basis` 统一为 `fixture-input`，并显式记录 `derived_from_pixels=false`、`ocr_or_cv_used=false`。

### 3.2 状态签名与状态门

状态签名由 `scroll_y / frame / overlay / zoom` 组成。只要两侧都有观测且签名不同，解析器立即返回 `state-mismatch`，不进入字段比较：

- C13：DOM `frame 0` vs 截图 `frame 1`；
- C14：DOM `scroll 0` vs 截图 `scroll 600`。

当 DOM 侧本来就没有该元素观测时（C21、C23 的 modal 覆盖层），不拿“DOM 缺失”去和“截图有观测”做状态比较，否则会把合法的 `screenshot-only` 误判成 `state-mismatch`。该规则在首次运行中触发过 2 个错误，修正后 24/24 符合预期。

### 3.3 字段权威表

| 字段 | 权威 | 规则 |
|---|---|---|
| `text` | DOM | 字符内容、空格与可编辑文本以 DOM 为准 |
| `font` | DOM | 字体栈、字重、字号与行高以 DOM 为准 |
| `color` | DOM | 计算样式颜色以 DOM 为准 |
| `role` | DOM | 语义角色以 DOM 为准 |
| `editability` | DOM | 原生文本/可编辑性只由 DOM 宣称 |
| `asset_source` | DOM | 原始资产来源以 DOM 为准 |
| `visible_state` | 截图 | 实际可见性以渲染结果为准 |
| `occlusion` | 截图 | 遮挡关系以渲染结果为准 |
| `z_order` | 截图 | 实际层序以渲染结果为准 |
| `rendered_effect` | 截图 | 渐变、阴影等渲染效果以截图为准 |
| `content_hash` | 交叉核对 | 只比较同域规范化内容；不等即冲突 |
| `pairing` | 交叉核对 | 没有唯一配对证据即 `ambiguous` |
| `bbox` | 几何 | 绝对误差 ≤ `2.0 px` 收敛；超差即冲突 |

`2.0 px` 是合同值，不是从缺陷样本拟合出的通用阈值。

### 3.4 决策顺序

解析器严格按以下顺序执行，后一步不能静默撤销前一步：

```text
scope-gate
→ state-gate
→ pairing-ambiguity
→ both-missing
→ dom-only
→ screenshot-only
→ both-present
→ bbox-tolerance
→ dom-field-policy
→ screenshot-field-policy
→ conflict
```

### 3.5 结果状态

| 状态 | 含义 |
|---|---|
| `agreement` | 两路一致，且字段有权威定义 |
| `dom-preferred` | DOM 为该字段权威，截图值保留但不选 |
| `resolved-by-tolerance` | bbox 在绝对容差内，选 DOM 框 |
| `dom-preferred-with-fallback` | DOM 资产来源优先，截图裁片保留为降级 |
| `screenshot-preferred` | 截图为渲染字段权威 |
| `screenshot-only` | 只有截图观测，且是渲染事实 |
| `screenshot-candidate` | 只有 OCR 类候选，未验证 |
| `dom-only-outside-capture` | DOM 有值，但截图视口未覆盖 |
| `state-mismatch` | 状态签名不同，禁止字段比较 |
| `ambiguous` | 配对不唯一，禁止强配 |
| `external-conflict` | 冲突无权威可裁决，winner=`null` |
| `unknown` | 双侧均缺失，不发明值 |

## 4. 结果总表

| 指标 | 结果 |
|---|---:|
| 合成页面 | 1 |
| 状态签名 | 4 |
| 真实视口截图 | 4 |
| 合同用例 | 24 |
| 裁片 | 20 |
| 已裁决 | 13 |
| 有范围的部分证据 | 5 |
| 未决 | 6 |
| `agreement` | 2 |
| `dom-preferred` | 6 |
| `resolved-by-tolerance` | 1 |
| `dom-preferred-with-fallback` | 1 |
| `screenshot-preferred` | 3 |
| `screenshot-only` | 3 |
| `screenshot-candidate` | 1 |
| `dom-only-outside-capture` | 1 |
| `state-mismatch` | 2 |
| `ambiguous` | 1 |
| `external-conflict` | 2 |
| `unknown` | 1 |
| 字段政策未分类 | 0 |
| 静默覆盖 | 0 |
| 合同检查 | 14/14 |
| 与预期状态不一致 | 0 |

## 5. 逐用例结果

| 用例 | 元素 | 字段 | DOM 观测 | 截图观测 | 结果 | 选中来源 |
|---|---|---|---|---|---|---|
| C01 | hero-title | text | 让设计稿自己长大 | 同左 | `agreement` | both |
| C02 | price | text | `¥ 299.00` | `¥299 (OCR 估计)` | `dom-preferred` | dom |
| C03 | card-title-box | bbox | `[80,250,320,60]` | `[81,250,320,60]` | `resolved-by-tolerance` | dom |
| C04 | sidebar | bbox | `[920,250,240,420]` | `[980,250,240,420]` | `external-conflict` | — |
| C05 | price | color | `#ef4444` | `#ee4444` | `dom-preferred` | dom |
| C06 | hero-title | font | `Microsoft YaHei · 700 · 44px` | `Microsoft YaHei · 44px (估)` | `dom-preferred` | dom |
| C07 | buy-button | role | `button` | `visual-button-candidate` | `dom-preferred` | dom |
| C08 | cover | asset_source | `asset://cover-01.jpg` | `flat-raster-crop://cover` | `dom-preferred-with-fallback` | dom |
| C09 | cookie-banner | visible_state | 缺失 | `visible` | `screenshot-only` | screenshot |
| C10 | header | occlusion | `overlap 0` | `overlap 14 px → hero-kicker` | `screenshot-preferred` | screenshot |
| C11 | fixed-toast | z_order | `auto` | `top-layer, stacking=50` | `screenshot-preferred` | screenshot |
| C12 | badge | rendered_effect | 纯色、无阴影 | 渐变 + 阴影 | `screenshot-preferred` | screenshot |
| C13 | carousel-title | text | frame 0 文案 | frame 1 文案 | `state-mismatch` | — |
| C14 | article-title | text | scroll 0 | scroll 600 | `state-mismatch` | — |
| C15 | footer-link | text | `隐私政策` | 视口外 | `dom-only-outside-capture` | dom |
| C16 | tooltip | text | 缺失 | `按 Ctrl+K 打开快速搜索` | `screenshot-candidate` | screenshot（unverified） |
| C17 | duplicate-card | pairing | 2 个同名候选 | 2 个框候选 | `ambiguous` | — |
| C18 | article | content_hash | 当前文本 hash | 陈旧渲染 hash | `external-conflict` | — |
| C19 | footer-copy | text | `© 2026 Design Lift Lab` | 同左 | `agreement` | both |
| C20 | hero-title | editability | `native-text` | `not-observable` | `dom-preferred` | dom |
| C21 | promo-overlay | visible_state | 缺失 | `visible`（S3） | `screenshot-only` | screenshot |
| C22 | drawer-title | text | 缺失 | 缺失 | `unknown` | — |
| C23 | modal-scrim | visible_state | 缺失 | `visible`（S3） | `screenshot-only` | screenshot |
| C24 | divider | color | `#e2e8f0` | `#dfe5ec` | `dom-preferred` | dom |

## 6. 关键结论

### 6.1 状态门必须先于字段比较

C13 与 C14 的文本即使相同或高度相似，也不进入比较。C14 尤其说明：同一句话在 scroll 0 和 scroll 600 下是两个观测状态，不能因为“文本相等”就宣称同态。守卫后字段比较错误为 0。

### 6.2 DOM 权威字段不允许截图反向覆盖

文本、字体、颜色、角色、可编辑性和资产来源共 9 个 DOM 政策用例（含 2 个 agreement）全部由 DOM 定权。截图值作为 retained observation 保留，但没有一个用例出现“截图文本覆盖 DOM 文本”或“截图宣称原生可编辑”。

### 6.3 截图权威字段只覆盖渲染事实

遮挡、层序、渲染效果和可见性类覆盖层全部由截图定权。C10 的顶部 header 层实际压住 kicker 14 px；C11 的 toast 位于页面内容之上；C12 的渐变与阴影只存在于渲染结果。这些字段由 DOM 的 `auto / none / 纯色` 值覆盖会丢失真实渲染事实。

### 6.4 bbox 容差不平均

C03 的 1.0 px 误差在 `2.0 px` 合同容差内收敛到 DOM 框；C04 的 60.0 px 超差保持 `external-conflict`，`winner=null`。解析器没有产生任何平均框。

### 6.5 资产来源与降级栅格分离

C08 选择 DOM 的 `asset://cover-01.jpg`，同时保留 `flat-raster-crop://cover` 作为 `raster-fallback`。裁片记录显式声明：

```text
claim: flat-raster-crop
cannot_claim: [original-asset, native-editability, dom-identity]
```

因此“有可用像素”不等于“拿到原始资产”，也不等于“可编辑文本”。

### 6.6 未决项保持未决

- C04、C18 为 `external-conflict`，没有 winner；
- C17 为 `ambiguous`，两个 DOM 候选与两个截图候选全部保留；
- C22 为 `unknown`，没有发明标题；
- C13、C14 为 `state-mismatch`，没有借用另一状态的字段值；
- C15 为 `dom-only-outside-capture`，没有说“截图确认过”；
- C16 为 `screenshot-candidate`，可编辑性保持 `unverified`。

6 个未决用例全部保留双侧观测或明确的缺失记录，决策审计为 24/24。

## 7. 合同检查

| # | 检查 | 结果 | 证据 |
|---|---|---|---|
| 1 | 异态观测进入字段比较前被阻断 | 通过 | C13/C14 均为 `state-mismatch`，无 provenance |
| 2 | 每个比较字段都有唯一权威路线 | 通过 | 未分类字段 0 |
| 3 | 每个用例都有可审计决策记录 | 通过 | 24/24 有 status、reason 与 provenance 或 retained observations |
| 4 | 不存在静默选边 | 通过 | 静默覆盖 0；未决态 `selected=null` |
| 5 | bbox 只用绝对容差 | 通过 | C03 收敛、C04 冲突，无平均框 |
| 6 | 可见/遮挡/层序/效果由截图定权 | 通过 | C10/C11/C12 均为 `screenshot-preferred` |
| 7 | 仅截图可见的覆盖层不被 DOM 否决 | 通过 | C09/C21/C23 均为 `screenshot-only` |
| 8 | 截图来源不宣称原生文本/可编辑性 | 通过 | 越权声明 0；C16 保持 `unverified` |
| 9 | 裁片不被宣称为原始资产 | 通过 | C08 `cannot_claim` 含 `original-asset` |
| 10 | 歧义配对不按首个候选强配 | 通过 | C17 `ambiguous`，双侧候选保留 |
| 11 | 双侧缺失不发明字段值 | 通过 | C22 `unknown`，`selected=null` |
| 12 | DOM 权威时保留截图降级候选 | 通过 | C08 保留 `raster-fallback` |
| 13 | 朴素等值比较会触发可测错误 | 通过 | 18/24 与合同状态不一致 |
| 14 | 同一夹具重复解析结果一致 | 通过 | 规范化结果 SHA-256 两次一致 |

## 8. 朴素比较的反例

如果直接采用“有 DOM 就用 DOM、没有就用截图；值不等就是缺陷”的朴素策略，24 个用例中有 18 个会得到错误状态。首批反例：

| 用例 | 朴素判决 | 合同状态 | 错误原因 |
|---|---|---|---|
| C02 | `conflict` | `dom-preferred` | DOM 文本的空格差异被当成缺陷 |
| C03 | `conflict` | `resolved-by-tolerance` | 1 px 抖动被当成真实几何差异 |
| C04 | `conflict` | `external-conflict` | 恰好同名，但缺少 winner 与保留结构 |
| C05 | `conflict` | `dom-preferred` | 抗锯齿取样被当成颜色错误 |
| C06 | `conflict` | `dom-preferred` | 截图无法给出完整字体栈 |
| C07 | `conflict` | `dom-preferred` | 视觉按钮候选被当成语义角色 |

其余错误还包括：把 OCR 候选当成已验证文本、把两个同名卡片强行配对、把视口外当成缺失、把状态差异当成字段差异。融合层如果不带来源政策和状态门，错误会集中在“看起来像缺陷、实际是证据域不同”的位置。

## 9. 限制与未验证

- **不是感知基准**：截图路线字段是附着在真实截图上的夹具输入，`derived_from_pixels=false`；本实验没有运行 OCR/CV。
- **不是真实站点**：只覆盖 1 个合成页面、4 个状态签名和 24 个用例，不代表真实页面分布、广告注入、懒加载或第三方组件。
- **不是生产实现**：没有修改 `src/`、`figma_bridge/`，没有定义生产 IR 的 provenance 数据结构，也没有执行 Figma 写入。
- **不是阈值标定**：`2.0 px` 是合同值，不是从缺陷样本拟合的参数；其他分辨率、DPR、缩放和字体渲染下的容差仍为 `not-evaluated`。
- **不是完整状态模型**：只覆盖静态 frame、scroll、modal overlay 和 zoom=1；过渡、动画、视频帧、拖拽和异步加载未覆盖。
- **C18 的陈旧渲染是夹具输入**：用于验证“同域文本 hash 不等 → external-conflict”，不是从真实后端或缓存系统观察到的版本冲突。

## 10. 可写入 2.0 规格的结论

可以写入：

1. 融合前必须先过 scope/state 门；异态、瞬态和遮挡状态不得进入字段比较。
2. 字段权威固定为：DOM 负责 `text / font / color / role / editability / asset_source`；截图负责 `visible_state / occlusion / z_order / rendered_effect`；`content_hash / pairing` 只做交叉核对。
3. bbox 只用绝对容差；超差返回 `external-conflict`，禁止平均或多数投票。
4. 每个结果必须有 `status`、`reason` 与 provenance；未决态保留双侧观测且 `winner=null`。
5. 截图裁片只能标 `flat-raster-crop`，不得宣称原始资产、原生可编辑或 DOM 身份。
6. `screenshot-candidate` 的文本与可编辑性保持 `unverified`，不得直接进入成品交付。

仍不能写入：

- 生产融合 API、IR schema 或 Figma 写入策略；
- 通用 OCR/CV 置信度阈值与自动接受规则；
- 跨站点、跨 DPR、跨浏览器的 bbox 容差；
- 真实站点的自动状态识别与配对算法；
- 多页面、多轮对话和增量更新的权威链。

## 11. 下一步候选

以下仅为候选，本实验不自动开启：

- `R4-EXP-02`：接入真实 OCR/CV 候选，验证 `screenshot-candidate` 通道能否在低置信度下保持未验证。
- `R4-EXP-03`：把状态门扩展到真实滚动、懒加载和动画帧，验证状态签名是否足够。
- `R4-EXP-04`：设计生产 IR 的字段级 provenance 结构，并做只读回放验证。

## 12. 产物清单

| 产物 | 路径 |
|---|---|
| 脚本 | `output/_r4_experiments/r4_fusion_contract.py` |
| 总 JSON | `output/_r4_experiments/r4_fusion_contract.json` |
| DOM 路线 | `output/_r4_experiments/r4_fusion_artifacts/dom_route.json` |
| 截图路线 | `output/_r4_experiments/r4_fusion_artifacts/screenshot_route.json` |
| 融合输出 | `output/_r4_experiments/r4_fusion_artifacts/fusion_output.json` |
| 视口截图 | `output/_r4_experiments/r4_fusion_artifacts/capture_s0.png`、`capture_frame1.png`、`capture_scroll600.png`、`capture_modal.png` |
| 裁片 | `output/_r4_experiments/r4_fusion_artifacts/crops/`（20 张） |
| 矩阵图 | `output/_r4_experiments/r4_fusion_matrix.png` |
| 决策流程图 | `output/_r4_experiments/r4_fusion_flow.png` |
| 状态分布图 | `output/_r4_experiments/r4_fusion_status.png` |
