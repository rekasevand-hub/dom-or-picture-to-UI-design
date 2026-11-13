# Phase 5（容器嵌套）可行性判定 — 2026-11-13

> 一句话：**渲染端早就支持嵌套，缺的是感知侧的分组；而用几何启发式去补这个分组，
> 在五族上无一成立。** 这不是「还没做」，是「按现在的容器矩形做不出来」。

## 1. 渲染端已就绪，不需要改

`adapter_base.resolve_frames` 不是占位实现，它有完整的准入复核与回退：

| 能力 | 位置 | 状态 |
|---|---|---|
| 成员挂进 Frame 后**钉死**（`ABSOLUTE` + 快照 x/y） | 规则 3 | 已有，真机验收过 |
| 成员闭包（成员 + 成员里子 Frame 的成员） | `collect()` | 已有 |
| 展开绘制序翻转检测（只对**相交**图元判） | `order_flips()` | 已有 |
| 裁剪一致性 | `_pin_reason` | 已有 |
| 放弃即退回扁平绝对定位，逐像素不变 | 四条守门 | 已有 |
| 子 Frame 掉则父 Frame 必掉 | `children_ok` | 已有 |

拒绝时会给 8 类具名原因（`covers-other-element` / `member-order` / `member-outside-frame` /
`member-before-frame` / `child-frame-dropped` / `clip-mismatch` / `container-multi-node` /
`container-bad-rect`），可直接统计。

**所以「container 拆 frame + rect」这个任务描述的前提是错的** —— 拆不拆是设计侧的事，
渲染侧只要拿到 `layout` + `layoutChildren` 就能建。

## 2. 缺口在 IR 侧：`build_layout_plan` 只在有 DOM 时运行

```
direct_design.py:1769   autolayout_frames = build_layout_plan(elements, dom_nodes) if dom_nodes else 0
```

图片路径没有 `dom_nodes`，于是这一行永远返回 0。五族实测：

| 族 | 元素 | `layout` | `layoutChildren` | `container` 元素 |
|---|---|---|---|---|
| content-review | 40 | 0 | 0 | 4 |
| atomgit-home | 115 | 0 | 0 | 5 |
| dark-card-grid | 59 | 0 | 0 | 3 |
| light-form | 131 | 0 | 0 | 8 |
| light-table | 151 | 0 | 0 | 7 |

`layout_infer.infer_container` 里确实有 `_geometry_stack` 几何兜底（不依赖 CSS），
但 `build_layout_plan` 在拿到 DOM 前就返回了，兜底根本没机会跑。

## 3. 四组几何分组方案，全部实测失败

统一做法：给现有 `container` 元素合成 `layout = {mode: "NONE"}` + `layoutChildren`，
再交给 `resolve_frames` 复核（mode NONE 是金稿的实际形态：55 个 FRAME 全是 NONE）。

| 方案 | 成员规则 | content-review | atomgit | dark | light-form | light-table |
|---|---|---|---|---|---|---|
| A 完全包含 | 矩形被容器完全包住 | 0/2 | 0/5 | 1/3 | 1/8 | 0/7 |
| B 满闭包 | 与容器相交且画在其后 | 4/4 | 5/5 | 3/3 | 5/8 | 7/7 |
| C 互斥容器 + 重叠归属 | 容器两两不重叠，元素按重叠面积唯一归属 | 2/4 | 0/2 | 2/2 | 0/2 | 0/4 |
| D 重叠归属 + 容器嵌套 | 唯一父级，容器按包含嵌套 | 2/4 | 0/5 | 2/3 | 0/8 | 1/7 |

（分子 = 建成 Frame 数，分母 = 参与计算的容器数；`4/4` 表示四个容器都建成了。）

**方案 B 数字最好，但它非法**：成员集合互相重叠，一个元素会被多个容器同时认领。
`child_owner` 是单值字典，最终「后绘制的 Frame 赢」——结果是被抢走的 Frame 变成空壳，
`end` 记账与实际父子关系脱节。这属于「结构正确性靠巧合」，不能用。

方案 A/C/D 全是 `covers-other-element` 刷屏。

## 4. 为什么必然失败：两条约束互斥

守门 2（成员闭包）要求：

> 画在 Frame 之后、`end` 之前、**与 Frame 矩形相交**的图元，必须都是成员。

分区（唯一父级）要求：

> 每个元素只能有一个父级。

当 A、B 是同级容器，而某个元素 X 属于 A **却溢出到 B 的矩形里**时，两条同时成立不可能：
B 的闭包必须含 X（守门 2），X 又不能同时属于 A 和 B（分区）。

而「元素框溢出所在容器」在这批页面上是常态，不是例外：

```
content-review  banner:C1  [129, 73, 415, 40]
                其中文字    [188, 85, 415, 28]   ← 右边界 603 vs 容器 544，溢出 59px
```

这和 `REQ-OIBFZVUES` 那条同源：**元素框带 slack，不等于墨迹框**。换成 `ink_bbox` 判包含，
「容器有子」能从 2/4 升到 3/4、5/5、3/3、7/8、6/7，但 `covers-other-element` 照样拦下大半
（content-review 2/4、atomgit 0/5、light-form 0/8）。

## 5. 更根本的一条：容器矩形本身不构成分区

即使不管内容，只看容器之间：

| 族 | 容器数 | 两两重叠 |
|---|---|---|
| content-review | 4 | **0 / 6** |
| dark-card-grid | 3 | 1 / 3 |
| light-table | 7 | 7 / 21 |
| atomgit-home | 5 | **6 / 10** |
| light-form | 8 | **16 / 28** |

`sidebar:C1` 在四个族里都和 `header` / `main-content` / `form-section` 大面积重叠
（light-form 的 `sidebar × main-content` 重叠 81,576 px²）。也就是说感知给出的容器框
**不是一个分区**，而是「若干互相压着的矩形」。

content-review 是唯一容器两两不重叠的页面（0/6），可它的内容照样溢出到相邻容器，
于是也只能建成 2 个 Frame。**分区性最好的那一页都做不成，其余四页更没有机会。**

## 6. 结论

- 嵌套做不出来，**卡在感知侧**：容器矩形既不可靠（不构成分区），也不够紧（元素框带 slack）。
- 渲染侧不需要改，`code.js` 也不需要改（§7.1 的坐标假设今天已被实测推翻，见
  `20261113_phase5_coordinate_probe.md`）。
- 「container 拆 frame + rect，一天能落地」这个判断是**错的**：它不是渲染任务，是分组任务，
  而分组需要语义信息（哪块属于哪块），不是矩形运算能给出来的。

## 7. 这改变了什么

图片路径的产出结构定格为：**单根 FRAME + 扁平绝对定位**。这不是实现缺口，是这条路的
边界条件 —— 它没有 DOM，唯一的结构信号是画布上的矩形，而矩形不足以确定父子关系。

要拿到「可编辑结构」，出路只有三条，都不是一天的事：

1. **感知侧产出分组**（哪块属于哪块），而不是只产出容器框；
2. **容器框先做成真分区**（互不重叠 + 边界与内容对齐），再谈嵌套；
3. **DOM 路径**——`build_layout_plan` 本来就是为它写的，`direct_design.py` 已经在用。

## 8. 禁改项

- **不要用几何启发式伪造嵌套**。方案 B 能让五族都建出 3–7 个 Frame、审计指标立刻变好看，
  但父子关系是错的（sidebar 会「包含」整个页面），那是拿结构指标刷分。
- **不要在容器矩形还是互相压着的时候去改 `resolve_frames`**。守门拦的是真问题：
  一旦放宽 `covers-other-element`，相邻容器的内容会整块换层序，像素就开始动。
- **不要再用「元素框 = 墨迹框」的假设做几何判定**。content-review 的 banner 差 59px。
