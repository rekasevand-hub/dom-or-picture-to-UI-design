# R2-EXP-01 · 五个 DOM 容器的 flow 扰动

> 状态：`completed-for-current-scope`（2026-10-18），不是原站 `verified`。  
> 范围：按 R2 候选表 authored 的五个 DOM 容器，在 Chromium 中执行 24 个内容/尺寸变体。  
> 证据：`output/_r2_experiments/r2_dom_flow_perturbation.json`、`r2_dom_flow_site/`、`r2_dom_flow_captures/`、`r2_dom_flow_contact.png`。

## 1. 基线

| 容器 | 基线尺寸 |
|---|---:|
| `new_books_recommend` | 1440×238 |
| `new_books_catalog` | 790×259 |
| `book_card` | 142×236.97 |
| `recommend_rank` | 378×276 |
| `ancient_catalog` | 790×365 |

五个容器在 authored DOM 中都声明了单主轴 flow；`source_behavior` 仍标 `inferred`，因为夹具不是原站 DOM。

## 2. 扰动结果

- 左栏高度 +40：父容器高度 238→278，增长被传递。
- 新书目录插入/删除卡片：宽度按 ±152 变化，卡片不被 Fill 均分。
- 长标题：`faithful` 保持固定标题槽；`adaptive` 标题卡高度 237→281。
- 推荐排行展开 +40：条目与分隔线同步下移；插入/删除条目高度变化 ±44。
- 古籍目录首行 +40：父容器、第二行与分隔线同步；删除行后布局折叠。
- 宽度 -10%：记录溢出，不静默压缩卡片或改写固定宽度。
- 合同检查：42/42；5 容器 L1/L2 静态结构检查全部通过。

## 3. 解释边界

该实验证明这组 authored DOM 在 Chromium 中具有可解释的 flow 行为，并给出了 faithful/adaptive 的分歧点。它**不**证明原站 DOM 或原站响应式规则，也不证明 Figma Auto Layout 已实际参与。

## 4. 限制

- 夹具由 R2 测量表构造，不是原站 DOM。
- Chromium 布局不等于 Figma 布局引擎。
- 宽度 ±10% 是约束测试，不是原站断点或响应式行为。
- 固定 790/380/142×237 等值是候选表尺寸，不是全站所有实例的普适常量。

## 5. 不得宣称

- 不得写“五个 DOM 容器已在原站 verified”。
- 不得写“Figma Auto Layout 已扰动通过”。
- 不得把 authored DOM 的增长/溢出结果外推为原站响应式规则。

