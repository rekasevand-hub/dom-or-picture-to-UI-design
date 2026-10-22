# R1-EXP-01 · 五个 DOM 候选的离线 true-flow 写计划

> 状态：`completed-for-current-scope`（2026-10-18），不是 `verified`。  
> 范围：五个 DOM 候选的离线 Figma 写入命令、L1/L2 设置合同，以及基于 R2-EXP-01 Chromium 测量的 L3 行为模型。  
> 证据：`output/_r1_experiments/r1_true_flow_contract.json`。  
> 边界：没有连接 Figma、没有插件运行时、没有写入真实画布，也没有修改 `src/` 或 `figma_bridge/`。

## 1. 为什么先审计 V1

静态审计 `figma_bridge/code.js:429-469` 得到：

- `layoutMode`、`itemSpacing`、padding 与对齐会被设置，因此 V1 达到 L1“设置”；
- 子项随后全部被设为 `layoutPositioning = "ABSOLUTE"`；
- 子项快照的 `x/y` 被写回，因此 flow 并不是实际参与布局的唯一几何来源。

结论：V1 的自动布局路径**没有真正达到 L2“引擎参与布局”**，更不能据此宣称 L3 行为正确。

## 2. 离线写计划

实验生成 22 条写计划命令，覆盖五个容器：

| 容器 | 主轴 | gap | padding（上/右/下/左） | 子项策略 |
|---|---|---|---:|---|
| `new_books_recommend` | HORIZONTAL | 20 | 18/125/18/125 | 左右栏 FIXED，父级 Hug |
| `new_books_catalog` | HORIZONTAL | 10 | 21/19/1/21 | 5 张卡 FIXED 142×237 |
| `book_card` | VERTICAL | 9.28 | 0/8/16.04/8 | 封面与信息组在流，信息组内再纵向排布 |
| `recommend_rank` | VERTICAL | 0 | 1/1/1/1 | 条目在流；底部分隔线 ABSOLUTE |
| `ancient_catalog` | HORIZONTAL | 21 | 21/7/0/16 | 两列在流；纵向分隔线 ABSOLUTE |

写计划中所有 flow 子项都声明 `layoutPositioning=AUTO` 且 `write_x_y=false`；只有分隔线等显式装饰例外保留绝对定位。

## 3. 结果

- 5 个容器均有可执行写计划，22 条命令中不含在流子项的重复坐标写入。
- 离线模型 L1：5/5。
- 离线模型 L2：5/5，表示按计划设置后子项应参与主轴布局；这不是 Figma 实际回读。
- 离线模型 L3：31/31，使用 `R2-EXP-01` 的基线、+40、长标题、增删与宽度 ±10% 结果做算术核对。
- 合同检查：47/47。

## 4. 关键解释

`L2=5/5` 是**离线计划层**的通过：命令组合在模型上满足 flow 语义。真实 Figma 是否实际参与布局、是否产生正确的 Hug/Fill/间距，必须通过插件回读和扰动才能升级。当前实验不能把该数字写成生产 bridge 的 L2/L3 通过率。

嵌套信息组是必需设计：Figma 每层只有一个 `itemSpacing`，`book_card` 的封面—信息组间距 9.28 与标题—作者间距 7.68 不能放在同一层表达。

## 5. 限制

- 五个容器来自 authored DOM 夹具，不是原站 DOM。
- L3 使用 Chromium 布局结果与离线算术模型，不是真实 Figma Auto Layout 的行为。
- 绝对分隔线的锚定方式只是设计建议，生产 bridge 尚未实现或回读。
- 文本行高与增长仍依赖独立文本度量证据，本实验不提供通用字体阈值。

## 6. 不得宣称

- 不得写“V1 已达到真实 L2/L3”。
- 不得把 5/5、31/31 写成 Figma 插件运行时成功率。
- 不得写“五个容器已在原站或生产 bridge 上验证”。
- 不得把离线写计划当成已经写入画布。

