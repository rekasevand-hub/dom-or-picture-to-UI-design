# R4 Smoke B · 真实 Figma 写入与节点回读

> 状态：`completed-for-current-scope`（2026-10-18），不是 `verified`。  
> 目的：在真实 Figma 中验证 bridge → 插件 → 节点写入 → `get_node_tree` 回读的最小闭环，补上 `R4-EXP-09` 的“真实 Figma 未连接”边界中的基础部分。

## 1. 范围

- 一个本地 Figma 文档、一个 480×320 画板；
- 3 类子节点：`TEXT`、纯色 `RECTANGLE`、图片填充 `RECTANGLE`；
- 写入后通过新增的 `get_node_tree` 命令回读真实属性，导出 PNG 作为视觉证据；
- 不重放 `R4-EXP-09` 的 19 个字段决策，也不覆盖部分遮挡、事务或回滚。

## 2. 方法

```powershell
python -m src.app.services.bridge_server
python scripts/figma_readback_smoke.py --out output/_figma_smoke_b
```

脚本每次先执行 `remove_nodes_by_name("SmokeB", prefix)`，因此重复运行不会累积旧画板。共 12 项检查：写入 ID、画板类型与尺寸、子节点顺序、文本内容/字号/字体、文本位置与颜色、矩形几何/填充/圆角、图片几何/图片填充、PNG 导出。

## 3. 结果（最后一次运行）

| 项目 | 结果 |
|---|---|
| 检查 | 12/12 通过 |
| 画板 | `2:59`，480×320 |
| 子节点 | text `2:60`、rect `2:61`、image `2:62`，顺序一致 |
| 文本 | `Smoke B Readback`，Arial Bold 24，`#0f172a` |
| 矩形 | 120×72 @ (24,96)，`#1d4ed8`，四角 8px |
| 图片 | 120×72 @ (168,96)，`IMAGE` 填充，`imageHash=fa790a8b...` |
| 导出 | `smoke_b_render.png`，4772 字节，SHA-256 `7767048a6b72a4fe...` |
| `content_hash` | `322023b5af9ce6730ac537397fbe714c1d7855dced70fe19f7f133c16ba05826` |

产物：`output/_figma_smoke_b/figma_readback_smoke.json`、`readback_tree.json`、`smoke_b_render.png`。两次独立运行均为 12/12，节点 ID 每次变化，检查结果一致。

## 4. 边界

- 只覆盖单个本地文档与单次运行；未覆盖跨版本、跨平台、并发写入或大文件。
- 只覆盖 frame、text、rectangle、image；未覆盖 Auto Layout、组件、mask、effects、混合模式与 Arial 之外的字体。
- 回读是当前属性快照；undo、回滚、事务边界和部分写入失败仍为 `not-evaluated`。
- 冒烟会在当前文档留下 `SmokeB Root` 画板，供人工检查；它不是生产写入路径。
- 不证明 `R4-EXP-09` 的字段权威、遮挡决策或 `flat-raster-crop` 声明已在真实 Figma 中成立。

## 5. 不得宣称

- 不得写“R4-EXP-09 已在 Figma 端到端验证”；本冒烟只覆盖 3 类核心节点。
- 不得把 12/12 写成生产写入成功率、插件兼容率或跨版本稳定性。
- 不得把单次文档回读写成事务、回滚或并发安全。
