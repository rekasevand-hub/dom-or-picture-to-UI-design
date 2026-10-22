# R4 Smoke D · 真实 Figma Auto Layout、缺字体与部分遮挡

> 状态：`completed-for-current-scope`（2026-10-19），不是 `verified`。  
> 目的：在真实 Figma 中验证三项尚未覆盖的写入行为：Auto Layout 的真实流式重排、缺字体时的默认回退与严格失败、部分遮挡与裁剪的像素结果。  
> 证据：`output/_figma_smoke_d/figma_smoke_d.json`、`readback_tree.json`、`smoke_d_render.png` 及四张分区 PNG；脚本 `scripts/figma_smoke_d.py`。

## 1. 范围

- 单个本地 Figma 文档、一次连续运行；
- 1 个 `SmokeD Root` 画板（1000×640）；
- Auto Layout：一个纵向 HUG 列、一个横向 FIXED 行，覆盖 `itemSpacing`、四边 padding、`STRETCH`、`FILL`、`layoutGrow`、追加子项与改宽重排；
- 字体：`Inter 700`、一个刻意缺失的字体族、缺失族 + `Inter` 的 CSS 栈；默认回退与 `fontPolicy=strict` 两条路径；
- 遮挡：两个重叠矩形、一个被部分覆盖的文本节点、左右/底部越界子项、`clipsContent=true/false` 的导出差异；
- 26 项检查，其中 Auto Layout 9 项、字体 8 项、遮挡/裁剪 8 项，另 1 项根画板导出。

本冒烟不覆盖 CSS Grid、Figma Grid、wrap、min/max、baseline、组件、变量、字体缺失后的生产交付策略、事务、回滚或并发。

## 2. 方法

前置条件：bridge server 监听 `ws://localhost:8765`，Figma 桌面端运行开发插件。

```powershell
python -m src.app.services.bridge_server
python scripts/figma_smoke_d.py --out output/_figma_smoke_d
```

为让真实布局引擎参与，`figma_bridge/code.js` 新增了三个实验能力：

- `set_layout_flow`：打开真正的 `layoutMode` 流式布局，不把子项钉成 `ABSOLUTE`；生产用的 `set_autolayout` 保持不变；
- `font_strict_probe`：请求字体栈完全不存在时返回 `FONT_NOT_AVAILABLE`，不退回 `Inter`；
- `create_text` 的 `fontPolicy: "strict"`：缺族时失败关闭；默认行为仍保留原有回退，便于对照；
- `get_node_tree` 增加 `layoutMode / itemSpacing / padding* / sizing / layoutAlign / layoutGrow / layoutPositioning / clipsContent / visible` 回读。

`create_text` 已改为先解析字体、再创建节点，因此严格模式失败不会留下未挂载的孤立文本节点。

## 3. Auto Layout 结果

### 3.1 纵向 HUG 列

初始 3 个子项（100×40、120×40、80×40），`VERTICAL`、`itemSpacing=12`、四边 padding `16`、`primaryAxisSizingMode=AUTO`、`counterAxisSizingMode=FIXED`、第一项 `layoutAlign=STRETCH`：

| 项目 | 结果 |
|---|---|
| 列尺寸 | 320×176（高度由内容 Hug） |
| Item 0 | `[16, 16, 288, 40]`，`layoutAlign=STRETCH`，`layoutSizingHorizontal=FILL` |
| Item 1 | `[16, 68, 120, 40]` |
| Item 2 | `[16, 120, 80, 40]` |

追加 90×40 的 Item 3 后，列高从 176 变为 228，Item 3 落在 `[16, 172, 90, 40]`。把列宽从 320 改为 360 后，列高保持 228，Item 0 宽度从 288 变为 328。

### 3.2 横向 FIXED 行

3 个 60×40 子项，`HORIZONTAL`、`itemSpacing=10`、四边 padding `10`、固定 400×80、中间项 `layoutGrow=1` 且 `layoutAlign=STRETCH`：

| 项目 | 结果 |
|---|---|
| Row Item 0 | `[10, 10, 60, 40]` |
| Row Item 1 | `[80, 10, 240, 60]`，`layoutGrow=1` |
| Row Item 2 | `[330, 10, 60, 40]` |

内容总宽 `10 + 60 + 10 + 240 + 10 + 60 + 10 = 400`，与固定宽度一致；中间项在主轴吃满剩余空间，在交叉轴被拉伸到 60。

## 4. 字体结果

| 场景 | 结果 |
|---|---|
| `Inter` 700 探针 | `Inter / Bold`，`fallback=false` |
| 缺失族 700 探针 | **退回 `Inter / Regular`，`fallback=true`** |
| 严格探针：缺失族 | `available=false`，`FONT_NOT_AVAILABLE` |
| 严格探针：`缺失族, Inter` | `available=true`，`Inter / Bold` |
| 默认 `create_text` + 缺失族 | 写入成功，实际字体 `Inter / Regular` |
| 严格 `create_text` + 缺失族 | 失败，`FONT_NOT_AVAILABLE`；页面子节点数 4 → 4，无新增节点 |
| 严格 `create_text` + `Inter` 700 | 写入成功，`Inter / Bold` |
| 严格 `create_text` + `缺失族, Inter` 700 | 写入成功，`Inter / Bold` |

关键发现：**默认 `create_text` 不是严格模式**。请求字体族完全不存在时，它会静默退回 `Inter / Regular`，与已确认的“缺字体不自动替换”产品策略不一致。本冒烟只记录了该差异，没有修改生产默认值；严格模式可用于生产 IR 边界。

## 5. 遮挡与裁剪结果

`Occlusion Frame` 为 240×160、白色、`clipsContent=true`。子节点顺序与像素结果：

| 子节点 | 几何 | 检查 |
|---|---|---|
| `Base` | `[20, 20, 200, 100]`，`#2563eb` | `(40,100)` 为蓝色 |
| `Occluded Label` | 文本 `PARTIAL`，`Inter Bold 16`，白色 | 节点仍存在且内容完整 |
| `Occluder` | `[70, 20, 100, 100]`，`#dc2626` | `(100,40)` 为红色，覆盖 Base |
| `Clip Left` | `[-40, 120, 80, 40]`，`#f59e0b` | `(5,130)` 为橙色，左侧越界被裁 |
| `Clip Bottom` | `[20, 140, 100, 40]`，`#16a34a` | `(50,150)` 为绿色，底部越界被裁 |

导出尺寸为 240×160，说明 `clipsContent=true` 时导出严格限制在画板内。

对照组 `NoClip Frame` 为 240×160、`clipsContent=false`，子项在 `x=-40` 处越界 40px。导出尺寸变为 **280×160**，`(5,130)` 为橙色：Figma 会把 `clipsContent=false` 的溢出纳入导出边界。这一差异必须写入交付 manifest，否则“导出尺寸”会被误读为画板尺寸。

## 6. 与 R4-EXP-09 的关系

Smoke D 补上了 `R4-EXP-09` 限制中的三项真实运行时证据：

- Auto Layout 的真实流式重排可以由 Figma 引擎完成，但生产 `set_autolayout` 仍按既有策略把子项钉成 `ABSOLUTE`；两条路径必须分开命名；
- 缺字体可以在写入前失败关闭，且不会留下节点；但默认路径仍会静默回退；
- 部分遮挡可以由子节点顺序真实表达，裁剪由 `clipsContent` 真实执行；像素检查确认了覆盖与裁剪结果。

它仍不证明 `R4-EXP-09` 的 19 个字段决策、遮挡判定、权威链或事务边界在真实环境中成立。

## 7. 边界

- 单文档、单次运行；节点 ID 每次变化，检查按名称、属性和像素采样。
- Auto Layout 只覆盖纵向/横向、spacing、padding、固定尺寸、`STRETCH`、`FILL`、`layoutGrow`；未覆盖 Grid、wrap、min/max、baseline、绝对子项与 Auto Layout 内嵌组件。
- 字体只覆盖一个刻意缺失族与 `Inter`；未覆盖 CJK 字体、可变字体、字体加载失败、跨平台字体库与字体缺失后的自动交付策略。
- 遮挡只覆盖纯色矩形与一个文本节点；未覆盖透明度、mask、effects、混合模式、旋转、图片遮挡与抗锯齿阈值。
- 像素检查是小范围精确采样，不是整图像素或感知哈希比较。
- 没有注入部分写入失败；严格字体失败是写入前的单节点失败，不代表事务或回滚已实现。
- 冒烟会在当前文档留下 `SmokeD Root`，供人工检查；它不是生产写入路径。
- `src/` 未修改；`figma_bridge/code.js` 增加了实验动作与回读字段，生产写入默认行为除 `create_text` 的“先解析字体”外未改变。

## 8. 不得宣称

- 不得写“生产 Auto Layout 已在 Figma 端到端验证”；本冒烟走的是独立实验动作 `set_layout_flow`。
- 不得写“缺字体策略已合规”；默认 `create_text` 仍会静默回退到 `Inter / Regular`。
- 不得把 26/26 写成生产写入成功率、插件兼容率或跨版本稳定性。
- 不得写“部分遮挡已完整支持”；本冒烟只覆盖子节点顺序与 `clipsContent`，没有 `visible`、mask 或半透明语义。
- 不得把 `clipsContent=false` 的 280×160 导出写成画板尺寸；它包含溢出边界。
- 不得把单次文档回读写成事务、回滚、并发或部分失败安全。

## 9. 证据文件

- `output/_figma_smoke_d/figma_smoke_d.json`：26 项检查、字体探针、发现项、渲染哈希与 `content_hash`。
- `output/_figma_smoke_d/readback_tree.json`：根画板与全部子节点的真实回读树。
- `output/_figma_smoke_d/smoke_d_autolayout_column.png`：360×228，纵向 HUG 列。
- `output/_figma_smoke_d/smoke_d_autolayout_row.png`：400×80，横向 grow 行。
- `output/_figma_smoke_d/smoke_d_occlusion.png`：240×160，遮挡与裁剪。
- `output/_figma_smoke_d/smoke_d_noclip.png`：280×160，`clipsContent=false` 的溢出导出。
- `output/_figma_smoke_d/smoke_d_render.png`：1000×640，整页视觉证据。
