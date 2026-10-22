# R4 Smoke C · 真实 Figma 重放写入合同

> 状态：`completed-for-current-scope`（2026-10-19），不是 `verified`。  
> 目的：把 `R4-EXP-09` 离线合同中**实际发出的 8 条写入命令**重放到真实 Figma 文档，并用 `get_node_tree` 回读节点属性，检查命令形状、顺序、资产与延迟节点在真实运行时是否成立。  
> 证据：`output/_figma_smoke_c/figma_write_contract_smoke.json`、`readback_tree.json`、`smoke_c_render.png`；脚本 `scripts/figma_write_contract_smoke.py`。

## 1. 范围

- 单个本地 Figma 文档、一次连续运行；
- 1 个 1080×720 画板，加 `R4-EXP-09` 断言可写入的 8 个节点；
- 逐条发送离线合同生成的 `create_image` / `create_text` / `create_rectangle` 命令，不重新计算字段决策；
- 写入后回读节点树，比较类型、名称、几何、文本、字体、颜色、图片填充、子节点顺序与延迟节点缺席；
- 导出画板 PNG 作为视觉证据。

本冒烟**不**重放 19 个字段决策，也**不**覆盖遮挡判定、权威链、事务、回滚、并发或跨版本行为。

## 2. 方法

前置条件：bridge server 监听 `ws://localhost:8765`，Figma 桌面端运行 `figma_bridge/manifest.json` 对应的开发插件。

```powershell
python -m src.app.services.bridge_server
python scripts/figma_write_contract_smoke.py --out output/_figma_smoke_c
```

脚本从 `output/_r4_experiments/r4_figma_write_contract.json` 读取画板参数，从 `commands.json` 读取 8 条写入命令，并用真实资产文件字节替换占位 payload。运行前按名称清理旧的 `R4-EXP-09 Artboard`，因此重复运行不会累积画板。写入完成后发送 `get_node_tree` 与 `export_frame`，再对回读结果执行 16 项检查。

由于 Figma 的 `fontName` 会附带 `variationSettings`，字体检查比较 `family` 与 `style`，不把该运行时附加字段当作差异。第一次运行因此出现 10/16，属于断言口径问题，不是写入失败；修正断言后连续运行均为 16/16。

## 3. 重放内容

| 序号 | 动作 | case | 节点名 | 回读类型 |
|---:|---|---|---|---|
| 0 | `create_frame` | — | `R4-EXP-09 Artboard` | `FRAME` |
| 1 | `create_image` | A01 | `Hero Image` | `RECTANGLE` / `IMAGE` |
| 2 | `create_image` | A02 | `Fallback Image` | `RECTANGLE` / `IMAGE` |
| 3 | `create_text` | O01 | `Layer Bottom` | `TEXT` |
| 4 | `create_text` | O02 | `Layer Top` | `TEXT` |
| 5 | `create_text` | T01 | `Hero Title` | `TEXT` |
| 6 | `create_rectangle` | C01 | `Badge Fill` | `RECTANGLE` / `SOLID` |
| 7 | `create_text` | T03 | `OCR Panel` | `TEXT` |
| 8 | `create_text` | O05 | `Modal Title` | `TEXT` |

离线合同中的 `Occluded Card`、`Unknown Occlusion`、`Drawer` 保持不写入；冒烟把“这些名称不存在”作为显式检查。

## 4. 结果（最后一次运行）

| 项目 | 结果 |
|---|---|
| 检查 | **16/16 通过** |
| 命令 | 9 条（1 条画板 + 8 条写入） |
| 画板 | `2:81`，1080×720，白色 `#ffffff` |
| 子节点 | 8 个，`2:82`–`2:89`，顺序与命令一致 |
| 延迟节点 | `Occluded Card`、`Unknown Occlusion`、`Drawer` 均不存在 |
| 字体 | Inter 600 → `Semi Bold`；Inter 700 → `Bold` |
| 原图资产 | 220 字节，`dda711baa9e708f0258ed0070958b8be6ea8658485de33e3681a26a428bf1dbc` |
| 光栅降级资产 | 202 字节，`b26f61994820e0022a6f68ca4d9d7a2b3738dece2e7c48e97c30c9db1f9b887a` |
| PNG 导出 | 13604 字节，`bd47dba1cff82697cc743d45fcbfba7a6c3ac854a7e5a68d72d4b8792479aea9` |
| `content_hash` | `186af6e44a5eecbc7ca3650a855222dd778f26c0364b2c25382b07fee2b433e2` |

16 项检查：

1. `artboard-created`：画板类型、尺寸与白色填充；
2. `command-ids-returned`：9 条命令均返回 Figma 节点 ID；
3. `child-count`：子节点数等于写入命令数；
4. `child-order`：子节点名称顺序与命令顺序一致；
5. `deferred-nodes-absent`：延迟/跳过节点未出现；
6. `asset-payload-hashes`：两类资产路径与字节数匹配；
7. `font-resolution`：600/700 字重落到预期样式；
8. `node-hero-image`：图片节点类型、几何、`IMAGE` 填充；
9. `node-fallback-image`：降级图片节点类型、几何、`IMAGE` 填充；
10. `node-layer-bottom`：文本、字号、字体、颜色与位置；
11. `node-layer-top`：文本、字号、字体、颜色与位置；
12. `node-hero-title`：文本、字号、字体、颜色与位置；
13. `node-badge`：矩形几何与 `#dc2626` 填充；
14. `node-ocr-panel`：OCR 晋升文本、字号、字体、颜色与位置；
15. `node-modal-title`：最高层 modal 文本、字号、字体、颜色与位置；
16. `render-exported`：画板导出非空 PNG。

## 5. 与 `R4-EXP-09` 的关系

`R4-EXP-09` 验证的是离线**决策与命令生成**：哪些字段可以写、哪些必须 deferred/skipped、命令按什么顺序生成、非法输入是否失败关闭。Smoke C 只补上其中“已发出的 8 条命令能否在真实 Figma 中落地并回读”的一段。

它缩小了 `R4-EXP-09` 的真实运行时边界，但没有把该实验升级为端到端验证：

- 仍不证明 19 个字段决策在真实来源下正确；
- 仍不证明遮挡、z-order 冲突或 authority 选择在真实设计稿中成立；
- 仍不证明部分写入失败时的事务、回滚或用户可见状态；
- 仍不证明跨 Figma 版本、并发写入或生产资产管线。

## 6. 边界

- 单文档、单次运行；节点 ID 每次运行变化，检查按名称与属性而非 ID 持久性。
- 只覆盖 `FRAME`、`TEXT`、`RECTANGLE` 与 `IMAGE` 填充；未覆盖 Auto Layout、组件、mask、effects、混合模式与字体缺失回退。
- 图片检查只验证 `IMAGE` 填充与几何，不验证像素相等、MIME、解码或 CDN 下载。
- 回读是写入后的当前属性快照；undo、回滚、事务边界和部分写入失败仍为 `not-evaluated`。
- 冒烟会在当前文档留下 `R4-EXP-09 Artboard`，供人工检查；它不是生产写入路径。
- `src/` 未修改；`figma_bridge/code.js` 的改动限于既有 `get_node_tree`/写入动作支持，本次冒烟没有新增生产写入能力。

## 7. 不得宣称

- 不得写“`R4-EXP-09` 已在 Figma 端到端验证”。
- 不得把 16/16 写成生产写入成功率、插件兼容率或跨版本稳定性。
- 不得把 8 条命令重放写成 19 个字段决策、遮挡或权威链已在真实环境成立。
- 不得把单次文档回读写成事务、回滚、并发或部分失败安全。
- 不得把 `flat-raster-crop` 资产写成原始资产、可编辑资产或原生 SVG。
