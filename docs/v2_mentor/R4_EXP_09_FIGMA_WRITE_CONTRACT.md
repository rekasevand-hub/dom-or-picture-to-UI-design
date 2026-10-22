# R4-EXP-09 · 混合来源字段的 Figma 写入合同

> 状态：`completed-for-current-scope`（2026-10-18），不是 `verified`。  
> 范围：19 个受控混合来源字段用例、11 个节点、10 个 bridge 动作；只读回放为 9 条 bridge-shaped 命令（1 条画板 + 8 条写入），并验证 8 个非法输入变异。  
> 证据：`output/_r4_experiments/r4_figma_write_contract.json`、`output/_r4_experiments/r4_figma_write_artifacts/`，以及 `r4_figma_write_flow.png`、`r4_figma_write_matrix.png`、`r4_figma_write_occlusion.png`、`r4_figma_write_assets.png`。  
> 边界：本实验本身未连接 Figma、未打开设计稿、未创建真实节点、未修改 `src/` 或 `figma_bridge/`；所有命令只进入内存 mock executor。2026-10-19 的 Smoke C 另行把实际发出的 8 条写入命令重放到真实 Figma 并回读 16/16；同日的 Smoke D 用独立实验动作验证了真实 Auto Layout 重排、缺字体严格失败与部分遮挡/裁剪。两者仍不覆盖 19 个字段决策、事务或回滚。

## 1. 目的与边界

本实验回答 `R4-O08`：当融合结果中的文本、颜色、资产和遮挡字段来自不同权威来源时，进入 Figma 写入边界后应发生什么。

本实验验证的是**写入前的决策合同、命令形状与失败关闭行为**，不是 Figma 插件运行结果。具体覆盖：

- DOM 文本、双引擎 OCR 晋升文本、冲突文本、歧义文本和未观测文本；
- DOM 颜色、仅截图颜色和缺失颜色；
- 已验证原图、显式光栅降级、未验证资产和 native CSS；
- 完全遮挡、遮挡未知、截图层序与 DOM 顺序相反、最高层 modal。

不覆盖真实 Figma 节点、真实字体加载、Figma 渲染像素、部分遮挡、真实资产下载、生产 IR、持久化或并发写入。

## 2. 环境与可复现性

| 项目 | 值 |
|---|---|
| 操作系统 | Windows 11（`10.0.26300`） |
| Python | 3.12.0（`C:\Users\lzq\.conda\envs\omni\python.exe`） |
| Matplotlib | 3.11.0 |
| Pillow | 12.2.0 |
| bridge 源 | `figma_bridge/code.js` |
| bridge 动作 | 10 个（含 `create_text` / `create_rectangle` / `create_image` / `create_frame`） |
| 用例 / 节点 | 19 / 11 |
| 检查 | 38/38 通过 |
| 非法变异 | 8/8 安全 |

重跑命令：

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe output/_r4_experiments/r4_figma_write_contract.py
```

脚本重建 3 个确定性 PNG 资产、生成写入计划与决策、执行内存 mock executor、运行 8 个输入变异并重绘四张图。`content_hash` 覆盖除自身外的完整 JSON；写盘后可复算。

本次结果：

```text
content_hash = f8b19768e1e53dc5b9df35d30c6af3987d534e6c64fee109b851b2331ca71a47
```

## 3. 方法与合同

### 3.1 输入模型

每个用例显式记录：

- `kind`：`text / color / asset / occlusion`；
- `authority` 与 `selected_source`；
- `status`、`selected`（或显式 `null`）；
- `provenance`：被选与未选观测；
- 节点级 `visible_state / occlusion / z_order`；
- 资产的 `claim / validated / sha256 / bytes`。

19 个用例的分布是：6 个文本、3 个颜色、5 个资产、5 个遮挡/层序。所有观测是作者构造的受控夹具；没有运行 OCR、CV 或像素分类器。

### 3.2 写入前门

顺序固定如下：

1. **可见性门**：完全遮挡或遮挡未知时，节点级字段不进入写入。
2. **字段权威门**：
   - 文本只接受 DOM 值，或已通过双引擎 exact 晋升的 OCR 值；
   - 颜色只接受选中 DOM provenance；
   - 资产只接受已验证原图、显式 `flat-raster-crop`，或标记为尚无可写实现的 native 来源。
3. **命令验证**：动作必须存在于 `figma_bridge/code.js`，参数必须满足对应 `create_*` 形状。
4. **mock 执行**：校验 `imageBase64` 可解码且 SHA-256 与资产记录一致。

文本 OCR 晋升门槛沿用 `R4-EXP-02`：至少两个不同引擎、逐字符 exact、最小置信度 ≥ `0.85`、最小跨引擎 bbox IoU ≥ `0.50`。门槛是实验合同值，不是通用接受率。

### 3.3 命令映射

| 字段 | 写入动作 | 关键参数 |
|---|---|---|
| 文本 | `create_text` | `text`、`textColor`、`fontSize`、`fontFamily`、`fontWeight`、`textAnchor` |
| 颜色 | `create_rectangle` | `fillColor` |
| 原图/降级裁片 | `create_image` | `imageBase64`、`width`、`height` |
| 画板 | `create_frame` | `name`、`width`、`height`、`backgroundColor` |

计划按截图 `z_order` 升序发出写入命令。DOM 顺序不决定层序。

### 3.4 遮挡能力边界

`figma_bridge/code.js` 的 action 列表中没有 `set_visible` 或 `hide_node`，`create_*` 参数也没有节点 `visible` 属性。因此本实验不伪造 `visible=false`：

- 完全遮挡节点：`skipped`，零命令；
- 遮挡未知节点：`deferred`，零命令；
- 可见节点：按截图 z-order 写入。

这意味着“未写”是本实验中唯一忠实的隐藏内容处理方式；它不等于已经在 Figma 中实现了遮挡保真。

## 4. 结果

### 4.1 总览

| 结果 | 数量 | 含义 |
|---|---:|---|
| `written` | 8 | 生成并通过 mock 执行的写入命令 |
| `deferred` | 7 | 保留输入但拒绝写入，等待晋升、验证或人工确认 |
| `skipped` | 4 | 无可用值或节点被遮挡，不产生命令 |
| 命令总数 | 9 | 1 条 `create_frame` + 8 条写入 |
| 文本 / 颜色 / 图像命令 | 5 / 1 / 2 | 与字段决策一致 |

8 条写入的截图 z-order 为 `10, 12, 30, 32, 40, 45, 60, 101`，严格升序；modal 标题最后写入。

### 4.2 文本

- `T01`：DOM 与截图一致，使用 DOM provenance 写入 `create_text`，颜色取 DOM `#0f172a`。
- `T02`：单引擎 OCR 候选只保留 provenance，输出 `screenshot-candidate-not-authoritative`，不写文本。
- `T03`：Tesseract `0.94` 与 EasyOCR `0.92` exact 命中，IoU 均为 `0.71`，通过双引擎门，写入文本。
- `T04`：DOM 与截图内容不同，输出 `external-conflict-no-winner`，不选择任一侧。
- `T05`：重复候选无唯一配对，输出 `pairing-ambiguous`。
- `T06`：两侧均未观测，输出 `no-observed-value`，不发明抽屉标题。

### 4.3 颜色

- `C01`：DOM `#dc2626` 与截图 `#ef4444` 不同；DOM 为颜色权威，写入 `#dc2626`，截图值保留为未选观测。
- `C02`：仅截图提供颜色，输出 `screenshot-only-color-not-promoted`。
- `C03`：无颜色观测，跳过。

### 4.4 资产

- `A01`：已验证原图（220 字节）生成 `create_image`，`effective_claim=original-asset`。
- `A02`：只有元素截图裁片（202 字节）时仍可生成 `create_image`，但 `effective_claim=flat-raster-crop`，并明确 `cannot_claim=[original-asset, native-editability, dom-identity]`。
- `A03`：未通过验证的字节不进入 `create_image`，输出 `asset-not-validated`。
- `A04`：native CSS 渐变输出 `native-capability-not-implemented`，不静默光栅化。
- `A05`：资产本身有效，但所在卡片完全被 modal 遮挡，因此跳过且零命令。

本实验验证的是 payload 身份和降级标签，不是 Figma 对 PNG/图片填充的实际接受率。

### 4.5 遮挡与层序

- `O01` / `O02`：DOM 顺序为上层先出现、下层后出现，但截图 z-order 为 `30 < 32`；命令顺序按截图排序，避免 DOM 顺序反转层序。
- `O03`：被遮挡卡片标题即使有 DOM 文本，也不写为可见文本。
- `O04`：遮挡状态未知时保留节点观测但 defer。
- `O05`：modal 标题 z-order `101`，是第 8 条写入、也是最后一条写入命令。
- 被遮挡卡片的文本和资产合计贡献 0 条命令。

## 5. 检查

38/38 检查通过，覆盖：

- 19 个用例唯一，全部到达预期决策；
- DOM 文本写入并使用 DOM 颜色；
- 单引擎 OCR 拒绝、双引擎晋升通过、门槛值正确；
- 文本冲突与配对歧义保持未决；
- unknown 不发明值；
- DOM 颜色覆盖截图颜色，截图-only 颜色不写；
- 原图 payload 哈希、flat crop 降级声明与 `cannot_claim`；
- 未验证资产与 native CSS 均零命令；
- 完全遮挡文本/资产零命令，遮挡未知 defer；
- 写入命令按截图 z-order 升序，modal 最后；
- 所有 action 存在于 bridge 动作表，命令不含 `visible` 属性；
- 每个 written 用例都有 selected provenance，deferred/skipped 无命令索引；
- mock executor 每条命令执行一次，两个图像 payload 均解码并核对 SHA-256；
- 重建计划得到相同 `replay_hash`；
- 8/8 非法变异保持安全；
- 只读边界与 `content_hash` 复算通过。

## 6. 非法变异

| 变异 | 预期 | 实际结果 |
|---|---|---|
| 单引擎 OCR 被标为 `ocr-promoted` | 不写 | defer：`ocr-promotion-unverified` |
| 双引擎晋升但一个置信度降到 `0.80` | 不写 | defer：`ocr-promotion-unverified` |
| flat crop 被改标为原图 | 仍标降级 | write：`effective_claim=flat-raster-crop` |
| 未验证资产被改标为原图 | 不写 | defer：`asset-not-validated` |
| 删除 DOM 文本 provenance | 不写 | defer：`provenance-missing` |
| unknown 文本被强行填值 | 不写 | skip：`no-observed-value` |
| 截图颜色被升格为选中来源 | 不写 | defer：`screenshot-only-color-not-promoted` |
| 被遮挡文本被强行填值 | 不写 | skip：`occluded-element-not-written` |

## 7. 对生产写入的建议

1. 写入 API 必须把“决策”与“执行”分开；只有 `written` 决策才能生成命令，deferred/skipped 必须保持零命令。
2. 文本写入前必须携带选中 provenance；OCR 晋升必须是显式上游结果，写入层不得再次猜测。
3. 颜色写入只接受 DOM 选中来源；截图颜色只能作为保留观测。
4. 资产写入必须携带 claim；`flat-raster-crop` 与 `original-asset` 不能共用同一标签。
5. 遮挡和 z-order 必须在字段写入前处理；命令顺序应按截图 z-order，不按 DOM 顺序。
6. 若目标编辑器不支持 `visible`，隐藏内容应省略或显式 deferred，不能写入成可见节点。
7. 执行前校验 action 白名单、必填参数和资产 payload 哈希；失败应阻断该命令，而不是退回静默默认值。
8. 生产实现还需要真实 Figma 回读、节点计数、字体加载失败和部分写入事务的验收。

## 8. 限制

1. 19 个字段观测是受控夹具，不是真实 OCR/CV/截图算法输出。
2. mock executor 只镜像 bridge 动作名与必填参数，不是 Figma 插件运行时。
3. 未打开 Figma 文档、未建立 bridge WebSocket、未创建真实节点或回读图层。
4. bridge 没有 `visible` 写入能力；本实验只证明“隐藏内容应不写”，不证明 Figma 遮挡保真。
5. 资产验证限定为确定性 PNG 字节与 SHA-256，不是生产下载、MIME、解码或 CDN 验收。
6. 本实验本身未覆盖部分遮挡、半透明、混合模式、滚动容器裁剪、动态 z-index 和真实重叠检测；Smoke D 只补上子节点顺序与 `clipsContent` 的基础部分遮挡，仍不覆盖半透明、mask、effects 与动态 z-index。
7. 合同未接入 `src/` 或 `figma_bridge/`，不构成生产 API、持久化或写入事务。
8. 2026-10-18 的 `R4_SMOKE_B_READBACK.md` 已在真实 Figma 中执行 frame/text/rectangle/image 四类节点并回读 12/12；它只验证 bridge 的基础写入与属性回读，不验证本实验的 19 个字段决策、遮挡或事务边界。
9. 2026-10-19 的 `R4_SMOKE_C_WRITE_CONTRACT.md` 已在真实 Figma 中重放本实验实际发出的 8 条写入命令（1 个画板 + 8 个节点），命令 ID、子节点顺序、字体、资产哈希、颜色/文本/几何与延迟节点缺席共 16/16 通过；它仍只覆盖本实验已发出的命令，不验证 deferred/skipped 决策在真实来源下的正确性，也不验证事务、回滚、并发或跨版本。
10. 2026-10-19 的 `R4_SMOKE_D_AUTOLAYOUT_FONT_OCCLUSION.md` 已在真实 Figma 中验证：Auto Layout 纵向 HUG 与横向 `layoutGrow` 重排、严格字体探针与严格 `create_text` 缺族失败关闭、子节点顺序形成的部分遮挡，以及 `clipsContent=true/false` 的导出差异（240×160 对 280×160）。但 Auto Layout 走的是独立实验动作 `set_layout_flow`，不是生产 `set_autolayout`；默认 `create_text` 缺族仍会静默回退到 `Inter / Regular`；未覆盖 Grid、wrap、min/max、baseline、透明度、mask、效果、事务、回滚或并发。

## 9. 不得宣称

- 不得写“本实验已在 Figma 中验证混合来源写入”；本实验没有连接 Figma。Smoke C 只证明实际发出的 8 条命令可在真实 Figma 落地并回读，不证明 19 个字段决策。
- 不得把 38/38 写成生产写入成功率、插件兼容率或真实设计稿还原度。
- 不得把 mock executor 写成 Figma bridge runtime 或生产 write API。
- 不得把 `flat-raster-crop` 写成原始资产、可编辑资产或原生 SVG。
- 不得把截图-only 颜色写成已提升的原生颜色。
- 不得把 `deferred` / `skipped` 写成成功写入或静默缺省。
- 不得声称 bridge 已支持 `visible`、遮挡或 mask 写入。
- 不得写“生产 Auto Layout 已在 Figma 端到端验证”；Smoke D 的流式重排走的是实验动作 `set_layout_flow`，生产 `set_autolayout` 仍把子项钉成 `ABSOLUTE`。
- 不得写“缺字体策略已合规”；Smoke D 证明严格模式可以失败关闭，但默认 `create_text` 仍会静默回退到 `Inter / Regular`。
- 不得把本次 19 个受控用例外推到真实站点、任意资产或任意 Figma 字体环境。

## 10. 证据文件

- `output/_r4_experiments/r4_figma_write_contract.json`：完整结果、计划、决策、变异、检查与哈希。
- `output/_r4_experiments/r4_figma_write_artifacts/write_plan.json`：画板、8 条写入命令、19 条决策。
- `output/_r4_experiments/r4_figma_write_artifacts/commands.json`：公开命令日志（图像 payload 以哈希和长度记录）。
- `output/_r4_experiments/r4_figma_write_artifacts/decisions.json`：字段级写入决策。
- `output/_r4_experiments/r4_figma_write_artifacts/assets/`：3 个确定性 PNG 资产。
- `output/_r4_experiments/r4_figma_write_flow.png`：门与 mock executor 流程。
- `output/_r4_experiments/r4_figma_write_matrix.png`：19 个用例的决策矩阵。
- `output/_r4_experiments/r4_figma_write_occlusion.png`：截图 z-order、遮挡与命令序列。
- `output/_r4_experiments/r4_figma_write_assets.png`：原图、降级裁片与未验证资产。
