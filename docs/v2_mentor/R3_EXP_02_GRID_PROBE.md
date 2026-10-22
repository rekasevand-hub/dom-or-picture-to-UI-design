# R3-EXP-02 grid / wrap 能力与序列化回读

> 状态：`completed-for-current-scope`，不是全量 `verified`。  
> 已完成：两轮基础探测 27/27 步、补充探测 32/32 步、HUG/FLEX 隔离复测 13/13 步，共 72 步返回成功；覆盖固定轨道、手动定位、自动轨道、一维 wrap、增删移动、跨列/跨行、`FILL`、`MIN/CENTER/MAX` 对齐、`FLEX` 比例轨道、HUG 列与 HUG 父帧、追加定位、行列重排、导出，以及保存关闭重开后的逐字段回读。  
> 未覆盖：嵌套 grid、直接创建 HUG 轨道并搭配 `FILL` 子项时的宽度求解、自动轨道与 `FLEX/HUG` 的混合组合、约束/最小最大尺寸、长文本与图片内在尺寸、全页面编辑流程、生产 bridge 集成、其他 Figma 版本与协作冲突。  
> 本文件只支持“当前环境、当前文件、当前实验范围内的能力结论”，不得写成 Figma adaptive grid 已整体通过。

## 1. 环境与边界

| 项目 | 值 |
|---|---|
| 实验日期 | `2026-10-18` |
| Figma 桌面端 | `126.9.13` |
| 可编辑文件 | `FigmaAgent复刻UI` |
| 页面 | `Page 1` |
| 插件类型定义 | `@figma/plugin-typings 1.142.0` |
| 实验插件 | `UI Reconstruct Grid Probe` |
| 插件源码 | `output/_r3_experiments/grid_probe_plugin/` |
| 桥接地址 | `ws://localhost:8765` |
| 生产 bridge | `figma_bridge/code.js`，本次未改动 |

实验使用独立插件，不经过生产 bridge 的写入路径。桥接服务只负责在插件 UI 与 Python 驱动之间转发消息。

当前文件内保留以下实验节点：

- `EXP_R3_GRID_5x10`
- `EXP_R3_WRAP_400`
- `EXP_R3_GRID_5x2`
- `EXP_R3_GRID_SPAN`
- `EXP_R3_GRID_FLEX`
- `EXP_R3_GRID_HUG`
- `EXP_R3_HUG_FLEX_PROBE`

这些节点只用于能力探测，不代表生产布局模板，也不代表生产实现已经支持 grid / wrap。

## 2. 方法

每轮实验由 Python 通过桥接发送 `exp_grid_probe` 命令，插件执行 Figma 插件 API，并返回完整节点状态。状态包括：

- 父节点尺寸、布局模式、行列数、gap、padding；
- 行列轨道类型与值；
- 子节点相对坐标、尺寸、`layoutSizingHorizontal/Vertical`、锚点、跨行跨列、对齐方式；
- 导出字节数。

第一轮 15 步、第二轮 12 步、补充轮 32 步、隔离复测 13 步全部成功。未出现插件异常或桥接异常。

补充实验期间发生过一次实验驱动缺陷：旧版 `delete` 按全页面同名节点删除，误伤了 `EXP_R3_GRID_5x10` 与 `EXP_R3_GRID_5x2`。该次结果已另存为 `grid_span_fill_run_misfire.json`，不作为能力证据；修复后按保存前快照恢复节点并重新运行。恢复记录见 `grid_repair_run.json`：5×10 按原步骤重建后逐字段一致，5×2 仅子节点数组顺序不同，锚点、坐标、尺寸与父状态一致。

序列化回读流程：

1. 读取并保存实验前状态；
2. 在 Figma 中执行 `Ctrl+S`；
3. 关闭当前文件标签页；
4. 从 Recents 重新打开同一文件；
5. 重新运行实验插件并连接到 8765；
6. 读取保存后状态，与保存前逐字段比较。

## 3. 5×10 手动定位 grid

### 3.1 创建

创建参数为 5 列、10 行、固定 80×60 子项、列 gap 10、行 gap 10、四边 padding 8。实测结果：

| 项目 | 实测值 |
|---|---|
| 父帧尺寸 | `456×706` |
| 布局模式 | `GRID` |
| 行数 / 列数 | `10 / 5` |
| 子项数 | `50` |
| 行轨道 | 10 条 `FIXED 60` |
| 列轨道 | 5 条 `FIXED 80` |
| 列 gap | `10` |
| 行 gap | `10` |
| padding | `8 / 8 / 8 / 8` |
| 子项定位 | `MANUAL` |

子项 `x` 取值为 `8, 98, 188, 278, 368`，列步长约 `90`。  
子项 `y` 取值为 `8, 78, 148, 218, 288, 358, 428, 498, 568, 638`，行步长约 `70`。  
步长与 `80+10`、`60+10` 的推导一致；步长是推导值，坐标是实测值。

### 3.2 删除、增加与移动

| 操作 | 实测结果 |
|---|---|
| 删除 `cell-01`、`cell-05`、`cell-06` | 子项数从 50 变为 47；空槽为 `[0,0]`、`[0,4]`、`[1,0]` |
| 新增 `cell-51` | 自动填入第一个空槽 `[0,0]`；子项数变为 48 |
| 将 `cell-50` 移动到 `[1,0]` | 目标位置更新为 `x=8, y=78`；原空槽被占用 |

在 `MANUAL` 模式下，子项不会自动重排。新增子项会优先填入已有空槽，而不是追加到末尾。

### 3.3 跨列

将 `cell-49` 的 `gridColumnSpan` 设为 2 后：

- `columnSpan=2` 生效；
- 子项宽度仍为 `80`；
- 父帧宽度仍为 `456`。

因此本次实验只证明了 **跨度字段可以设置并回读**，没有证明跨度会自动拉伸子项，也没有证明父轨道或父帧会重新计算。该行为不能直接当作“合并单元格”能力使用。

补充实验进一步确认：跨度本身仍不拉伸；把子项尺寸设为 `FILL` 后才会占满跨过的轨道与间隙，见 5.1。

### 3.4 自动流

将 `gridItemsPositioning` 改为 `ROW_AUTO_FLOW` 后，剩余 48 个子项按行连续填充，空槽被压缩：

- 新增的 `cell-51` 落在 `[9,2]`；
- 末端空槽为 `[9,3]`、`[9,4]`；
- 子项序列保持连续，不再保留删除产生的三个空洞。

这说明 `MANUAL` 与 `ROW_AUTO_FLOW` 是两种不同的编辑语义，不能混写。

### 3.5 导出

`EXP_R3_GRID_5x10` 导出 PNG 为 `2981` bytes。本次只验证导出调用和字节产出，不把字节数当视觉等价证据。

## 4. 5×2 grid、自动轨道与重排

### 4.1 创建与自动行

创建 5 列×2 行的 grid，实测父帧为 `456×146`，10 个子项。把 `gridAutoTracks` 设为 `ROWS` 后，新增第 11 个子项 `cell-11`：

- 行数从 `2` 自动增加到 `3`；
- `cell-11` 落在 `[2,0]`；
- 子项数为 `11`。

该现象说明自动行轨道能响应新增子项，但本次没有测试列方向的自动扩展。

### 4.2 固定轨道与子项高度

首行轨道为 `FIXED 60` 时，把 `cell-01` 高度改为 `100`：

- 首行轨道仍为 `FIXED 60`；
- 第二行 `y` 仍为 `78`；
- 父帧高度仍为 `216`；
- 子项高度为 `100`，发生溢出。

因此固定轨道不会因子项变高而自动传播尺寸。

把首行轨道改为 `HUG` 后：

- 首行轨道类型变为 `HUG`；
- 第二行 `y` 从 `78` 变为 `118`；
- 父帧高度仍为 `216`，因为父帧 `layoutSizingVertical` 仍是 `FIXED`。

这说明 `HUG` 轨道会响应子项高度，但父帧是否继续增长还取决于父帧自身的尺寸策略。本次没有测试父帧改为 `HUG` 后的完整链路。

该链路已在补充实验中补齐：父帧设为水平 `HUG` 后，HUG 列的内容宽度会传播到父帧，见 5.4；`FLEX` 轨道在父帧 `HUG` 时会被改写，见 5.5。

### 4.3 指定位置追加

删除 `cell-01` 后，使用 `appendChildAt(cell-12, 0, 0)`：

- `cell-12` 落在 `[0,0]`；
- `x=8, y=8`；
- 子项数恢复为 `11`。

### 4.4 行重排

`reorderRows({fromIndices:[0], insertionIndex:2})` 返回：

```json
[{"from": 0, "to": 1}]
```

重排后，原第 0 行内容移动到第 1 行，原第 1 行内容移动到第 0 行。也就是说，行内容和锚点随轨道移动，而不是只交换视觉坐标。

### 4.5 列重排

`reorderColumns({fromIndices:[0], insertionIndex:5})` 返回：

```json
[{"from": 0, "to": 4}]
```

原第 0 列被移到最后一列，原第 1–4 列整体左移一列。子项的 `columnAnchor` 和 `x` 均随之更新。

### 4.6 导出

`EXP_R3_GRID_5x2` 导出 PNG 为 `1026` bytes。

## 5. 补充：跨度、FILL、对齐、FLEX 与 HUG

补充实验使用三个独立节点：`EXP_R3_GRID_SPAN`（3×3）、`EXP_R3_GRID_FLEX`（3×2）、`EXP_R3_GRID_HUG`（3×2），并另建 `EXP_R3_HUG_FLEX_PROBE` 做隔离复测。基础参数仍为 80×60 子项、gap 10、padding 8。

### 5.1 跨列 / 跨行与 `FILL`

在 3×3、父帧 `276×216` 的 grid 上删除 `cell-02` 后，把 `cell-01` 设为跨 2 列：

| 步骤 | `columnSpan` | `rowSpan` | 子项尺寸 | 位置 |
|---|---:|---:|---|---|
| 仅设置跨 2 列 | `2` | `1` | `80×60` | `(8,8)` |
| 再设水平 `FILL` | `2` | `1` | `170×60` | `(8,8)` |
| 再设跨 2 行 | `2` | `2` | `170×60` | `(8,8)` |
| 再设垂直 `FILL` | `2` | `2` | `170×130` | `(8,8)` |

推导关系与实测一致：

- 跨 2 列宽度 `170 = 80 + 10 + 80`；
- 跨 2 行高度 `130 = 60 + 10 + 60`。

结论：**只设置跨度不会自动改变子项尺寸**；必须同时把对应方向的子项尺寸策略设为 `FILL`，子项才会占满跨过的轨道与间隙。这一结论修正了基础探测中“跨度只写字段”的观察，但仍只覆盖 `MANUAL` 定位与固定轨道。

### 5.2 子项对齐

在固定 80 宽列轨道内，把 `cell-03` 宽度改为 `40`，依次设置水平对齐：

| `gridChildHorizontalAlign` | 实测 `x` |
|---|---:|
| `MIN` | `188` |
| `CENTER` | `208` |
| `MAX` | `228` |

在固定 60 高行轨道内，把同一子项高度改为 `30`，依次设置垂直对齐：

| `gridChildVerticalAlign` | 实测 `y` |
|---|---:|
| `MIN` | `8` |
| `CENTER` | `23` |
| `MAX` | `38` |

对齐只改变子项在单元格内的位置，不改变子项尺寸，也不改变轨道尺寸。`AUTO` 在本次固定轨道、固定尺寸场景下表现为左上起点；本次没有验证 `AUTO` 与 `FILL`、HUG 轨道组合时的语义。

### 5.3 `FLEX` 轨道比例

3×2 grid 的父帧为 `276×146`，内容宽度 `260 = 276 - 8×2`，列间隙共 `20`。把三列设为 `FLEX 1 / 2 / 1` 后，再把所有子项设为水平 `FILL`：

| 列 | `FLEX` 权重 | 实测子项宽度 |
|---|---:|---:|
| 第 0 列 | `1` | `60` |
| 第 1 列 | `2` | `120` |
| 第 2 列 | `1` | `60` |

可分配宽度为 `260 - 20 = 240`，`240 / (1+2+1) = 60`，与实测一致。行方向设为 `FLEX 1 / 2` 后，所有子项垂直 `FILL`，两行高度分别为 `40` 和 `80`，同样符合 `120 / 3` 的权重分配。

子项为 `FIXED` 且尺寸大于轨道时不会自动缩小；只有设为 `FILL` 后，子项尺寸才跟随轨道。`FLEX` 轨道本身不会把固定尺寸子项“压缩”到轨道宽度。

### 5.4 HUG 列与 HUG 父帧

3×2 grid 初始父帧 `276×146`。把 `cell-02` 宽度改为 `100`，将第 1 列设为 `HUG`，再把父帧水平尺寸策略设为 `HUG`：

- 第 1 列轨道变为 `HUG`；
- 该列实测宽度为 `100`；
- 第 2 列起点从 `188` 变为 `208`；
- 父帧宽度从 `276` 变为 `296`；
- 父帧高度仍为 `146`。

推导关系与实测一致：`296 = 8 + 80 + 10 + 100 + 10 + 80 + 8`。

结论：HUG 列会取该列子项的内容宽度；只有父帧也设为 `HUG`，新增宽度才会传播到父帧。若父帧仍为 `FIXED`，轨道可以变宽，但父帧尺寸不跟随。

### 5.5 HUG 父帧与 `FLEX` 轨道的副作用

隔离节点 `EXP_R3_HUG_FLEX_PROBE` 用于确认组合行为。初始为 `FLEX 1 / 2 / 1`、子项水平 `FILL`、父帧 `276×146`；把父帧水平策略改为 `HUG` 后：

- 三条列轨道全部从 `FLEX` 变为 `HUG`；
- 父帧宽度仍为 `276`；
- 子项尺寸与位置未变。

再把父帧恢复为 `FIXED`，三条列轨道仍保持 `HUG`，不会自动恢复为 `FLEX`。之后可以单独把某一列重新设为 `FLEX`，说明混合轨道类型本身是允许的，但“设置父帧 HUG”会先改写现有 `FLEX` 列。

实现约束：不要在保存 `FLEX` 轨道之后无条件把父帧设为 `HUG`；应先记录并恢复每条轨道的类型。该行为是当前 Figma 版本的实测副作用，不能假设为跨版本稳定语义。

### 5.6 导出与视觉抽查

| 节点 | 1× PNG 字节数 | 2× PNG |
|---|---:|---|
| `EXP_R3_GRID_SPAN` | `910` | `grid_span.png` |
| `EXP_R3_GRID_FLEX` | `672` | `grid_flex.png` |
| `EXP_R3_GRID_HUG` | `693` | `grid_hug.png` |
| `EXP_R3_HUG_FLEX_PROBE` | `672` | `grid_hug_flex.png` |

2× PNG 已人工查看：跨列/跨行区域完整占满，`MAX/MAX` 对齐位于右下，`FLEX` 比例与 `HUG` 列宽可见。视觉抽查只用于发现明显裁剪或错位，不作为像素等价或原站行为等价证据。

## 6. 一维 wrap

创建 `HORIZONTAL + WRAP` 帧，子项 80×60，gap 10，padding 8。宽度变化后的每行子项数为：

| 宽度 | 子项数 | 每行数量 |
|---:|---:|---|
| `400` | 12 | `4 / 4 / 4` |
| `400` 加入第 13 项 | 13 | `4 / 4 / 4 / 1` |
| `300` | 13 | `3 / 3 / 3 / 3 / 1` |
| `520` | 13 | `5 / 5 / 3` |

行 `y` 取值为 `8, 78, 148, 218, 288`，行步长仍为 `70`。导出 PNG 为 `1804` bytes。

这证明当前环境中的 `WRAP` 可以按可用宽度重新包行，且最后一行不补造子项。该结论不等于原网页的 `flex-wrap`、响应式规则或 DOM 顺序已经等价。

## 7. 保存、关闭、重开回读

基础第二轮与补充实验完成后，分别执行保存、关闭标签页、从 Recents 重开、重新运行插件，并读取同一批节点。保存前后比较字段包括：

- 父节点：尺寸、布局模式、行列数、gap、padding、轨道类型与值、定位模式、子项数；
- 每个子节点：名称、`id`、相对坐标、尺寸、`layoutSizingHorizontal/Vertical`、行锚点、列锚点、跨行、跨列、对齐方式。

基础节点结果：

| 节点 | 保存前子项数 | 重开后子项数 | 结构比较 |
|---|---:|---:|---|
| `EXP_R3_GRID_5x10` | 48 | 48 | 全部比较字段一致 |
| `EXP_R3_WRAP_400` | 13 | 13 | 全部比较字段一致 |
| `EXP_R3_GRID_5x2` | 11 | 11 | 全部比较字段一致 |

补充节点结果：

| 节点 | 保存前子项数 | 重开后子项数 | 结构比较 |
|---|---:|---:|---|
| `EXP_R3_GRID_SPAN` | 6 | 6 | 全部比较字段一致 |
| `EXP_R3_GRID_FLEX` | 6 | 6 | 全部比较字段一致 |
| `EXP_R3_GRID_HUG` | 6 | 6 | 全部比较字段一致 |

`EXP_R3_HUG_FLEX_PROBE` 是回读之后新增的隔离复测节点，未纳入保存重开比较表。

上述六个父节点及其子节点的 `id` 在本次重开后也未变化。补充比较覆盖了跨行跨列、`FILL`、三档对齐、`FLEX` 轨道与 HUG 轨道/父帧。该结论只覆盖当前文件、当前 Figma 版本和本次保存方式，不覆盖多人协作冲突、离线编辑或跨版本打开。

## 8. 证据分层

`observed`：

- `GRID`、`WRAP` 相关 API 在当前环境可调用并返回成功；
- 固定轨道、手动定位、自动行、`appendChildAt`、`reorderRows`、`reorderColumns` 的实际状态变化；
- 跨列/跨行只有在子项设为 `FILL` 后才占满跨过的轨道与间隙；
- `MIN/CENTER/MAX` 在固定单元格内的定位偏移；
- `FLEX` 轨道按权重分配空间，子项 `FILL` 后尺寸与轨道一致；
- HUG 列取内容宽度，父帧 `HUG` 时宽度传播；
- 父帧设为 `HUG` 会把现有 `FLEX` 列改写为 `HUG`，恢复父帧 `FIXED` 后轨道类型不会自动恢复；
- 增删后的空槽与自动流压缩；
- wrap 在不同宽度下的分行数量；
- 导出 PNG 字节数；
- 保存关闭重开后的逐字段一致性。

`derived`：

- 列步长 `90 = 80 + 10`、行步长 `70 = 60 + 10`；
- 父帧尺寸与轨道、gap、padding 的算式关系；
- 跨 2 列的 `170 = 80 + 10 + 80`、跨 2 行的 `130 = 60 + 10 + 60`；
- `FLEX 1/2/1` 的 `60/120/60` 与 `FLEX 1/2` 的 `40/80`；
- HUG 父帧宽度 `296 = 8 + 80 + 10 + 100 + 10 + 80 + 8`；
- 行/列重排后的锚点映射解释。

`unknown / not-covered`：

- 跨度在 `ROW_AUTO_FLOW`、HUG 轨道或自动轨道下的自动尺寸行为；
- 直接创建 HUG 轨道并把子项设为 `FILL` 时的宽度求解；HUG 与 `FLEX` 混合轨道在内容变化后的重算稳定性；
- 自动轨道 `ROWS/COLUMNS` 与 `FLEX/HUG` 的组合；
- 子项 `STRETCH`、`AUTO` 与 `FILL` 组合的精确语义；
- 嵌套 grid、grid 内的 Auto Layout 子节点；
- 长文本、变宽子项、图片、自动布局子节点与 grid 的冲突；
- 全页面编辑、批量重建、撤销/重做和多人协作；
- 生产 bridge 的 grid/wrap 命令与回滚策略；
- 其他 Figma 版本、其他账号权限和其他文件类型。

## 9. 不得宣称

- 不得写“Figma adaptive grid 已整体验证通过”；
- 不得写“生产 bridge 已支持 grid/wrap”；
- 不得写“设置跨度后子项会自动拉伸”；
- 不得写“只设置跨度就会改变子项或父帧尺寸”；只有配合 `FILL` 才在本次范围内观察到拉伸；
- 不得写“HUG 父帧与 `FLEX` 轨道可以无损共存”；实测会改写轨道类型；
- 不得写“wrap 已验证与原网页 flex-wrap 等价”；
- 不得把一次导出成功当作视觉等价；
- 不得把局部实验的 `observed` 结果升级为全量 `verified`。

## 10. 对实现的影响

在本次实验范围内，grid / wrap 可以作为 adaptive 布局的候选实现路径，但落地时必须显式保存和恢复：

- 行列数、轨道类型与值；
- gap、padding、父帧尺寸策略；
- 子项锚点、跨行跨列和对齐；
- 子项 `layoutSizingHorizontal/Vertical`；跨度必须与 `FILL` 一起保存，否则回读后不会占满；
- 设置父帧 `HUG` 前先备份轨道类型，避免 `FLEX` 被改写；
- `MANUAL` 与 `ROW_AUTO_FLOW` 的定位语义；
- 指定位置追加与行列重排后的锚点映射；
- 保存重开后的回读校验。

实现不能假设：

- 固定轨道会随子项尺寸自动增长；
- 跨度会自动改变子项宽度或父帧宽度；
- 对齐方式会改变轨道或子项尺寸；
- HUG 父帧会保留既有 `FLEX` 轨道；
- `HUG` 轨道一定能让父帧一起增长；
- wrap 能替代原站响应式规则或 DOM 顺序。

生产 `figma_bridge/code.js` 仍未加入 grid/wrap 命令。本实验只解除“能力未知”的阻塞，不等于已完成生产集成。

## 11. 复现与产物

驱动脚本：

- `output/_r3_experiments/run_grid_experiment.py`
- `output/_r3_experiments/run_grid_experiment_2.py`
- `output/_r3_experiments/run_grid_span_fill_experiment.py`
- `output/_r3_experiments/run_grid_hug_flex_probe.py`
- `output/_r3_experiments/repair_grid_nodes.py`
- `output/_r3_experiments/capture_grid_state.py`
- `output/_r3_experiments/capture_grid_span_state.py`
- `output/_r3_experiments/compare_grid_readback.py`
- `output/_r3_experiments/export_grid_span_images.py`

机器可读产物：

| 文件 | SHA-256 |
|---|---|
| `output/_r3_experiments/grid_probe_run.json` | `49FEB766AB38BB1E93FF02949951791721A2FC2ABB5A631164C722EC07AE718F` |
| `output/_r3_experiments/grid_probe_run_2.json` | `44B9C51DDD77D4041295F17D748A007F283BF8BEA38DA1566EAAC0A1FC2FCE4B` |
| `output/_r3_experiments/grid_probe_summary.json` | `EC5C526BCDFF0C225703CCD08DE9D3FD4911002F18953DDE3656A574119E3EBA` |
| `output/_r3_experiments/grid_probe_summary_2.json` | `2B3625428A3BE986CE1C7BC56CD33BC565E7299FAD2B044E6593AA4DFF17415D` |
| `output/_r3_experiments/grid_2_pre_save.json` | `653298E2413B15DAF494DC0CD3BC833F3A35F5173AB4F2F8E6B691E68241E1AD` |
| `output/_r3_experiments/grid_2_post_save.json` | `568FC11FF130FE103A7C1A974E81364B65DD3D79A8F1630A4D603AC83D2A1359` |
| `output/_r3_experiments/grid_2_readback_compare.json` | `0249C17BF29B87C55B19A0B45917638626F7D87E6BD3DDF17F283152A9192981` |
| `output/_r3_experiments/grid_span_fill_run.json` | `86400936C7844500669AE47702C7951008C229BC1516F4C062AC9A062D43F08D` |
| `output/_r3_experiments/grid_span_pre_save.json` | `6520C3219219CD703110F3BE2AA0AF8BB51A63E323B3998989918DE453057FC2` |
| `output/_r3_experiments/grid_span_post_save.json` | `A6EBAC63A5445518E1D73C068935AD062936DF6D550E0E0B4178CBB639E9B904` |
| `output/_r3_experiments/grid_span_readback_compare.json` | `08A79C13D16FE5BB87B26CCA94ACC053C922DCF534C3526ADAFB2EA2A2B04BC3` |
| `output/_r3_experiments/grid_hug_flex_probe.json` | `F868F99F64D1D1162A420B31E7D542E394FE868BE0F89A12C3F7697EC9A1FC2F` |
| `output/_r3_experiments/grid_span_images.json` | `CCD41E7E08B7A74EC37BFBC81E4030F24CB4BC8C2E00E0C5B20512139FA4D498` |
| `output/_r3_experiments/grid_span.png` | `423FF1F1C227502867DE157ABBA8577F81A75C66DA5F2EE1430CD577AF8F270A` |
| `output/_r3_experiments/grid_flex.png` | `1AA45A5AF827C22143DF7CC3DA451BAF12983B64655723D95A68D49969106975` |
| `output/_r3_experiments/grid_hug.png` | `F40605DAE727EBE3B5B06CC0E0DCA7993C71E1DBB586B04022D29494CDE23B6B` |
| `output/_r3_experiments/grid_hug_flex.png` | `F4CB1F25285DD4549C9EAAE753B731576A93B781ECE1D844FB1BD4D513CF8353` |

事故与修复记录（不作为能力证据）：

| 文件 | SHA-256 |
|---|---|
| `output/_r3_experiments/grid_span_fill_run_misfire.json` | `7D983D6720EE5E2D72EDA04C0923C1ADCEB0E1F1FC347782920E3C4BE052BCBF` |
| `output/_r3_experiments/grid_repair_run.json` | `6C67FAA45B69657D333AD188B85777CACDFB8DBB6162C53D183E2AE7BB23177B` |

## 12. 未决与下一步

- 验证直接创建 HUG 轨道并搭配 `FILL` 子项、自动轨道与 `FLEX/HUG` 的混合组合；
- 验证跨度在 `ROW_AUTO_FLOW`、自动轨道与约束下的尺寸行为；
- 验证 grid 与嵌套 Auto Layout、图片、长文本的冲突；
- 在全页面样例上验证增删、重排、撤销/重做和保存协作；
- 在独立分支或实验开关后，评估是否把 grid/wrap 命令加入生产 bridge；
- 在实现前保持 `R3-EXP-03` 至 `R3-EXP-12` 的原状态，不因本实验自动启动 R4。
