# P3 编辑能力

> 状态：`p3-current-scope-complete`，2026-10-21。  
> 范围：Grid/Wrap、component instance、多级 Auto Layout 传播、部分编辑失败恢复。  
> 结论：五项真实 Figma 探针均通过；风险与未覆盖组合继续单独跟踪，不计作全量生产准入。

## 1. Grid

生产 bridge 的 `set_layout_flow` 已接入 `GRID`：

- `gridRowCount` / `gridColumnCount`；
- `gridRowGap` / `gridColumnGap`；
- `FIXED` / `FLEX` / `HUG` track size；
- `MANUAL` / `ROW_AUTO_FLOW`；
- `gridAutoTracks=NONE/ROWS`；
- 子项 row/column anchor、row/column span；
- `layoutSizingHorizontal/Vertical`；
- `gridChildHorizontalAlign/VerticalAlign`。

所有参数先校验，再修改父节点。非法 mode、track、anchor、span 或 sizing 会 fail-closed。

真实探针使用 2×3 Grid、固定 60/80 track、10px row/column gap、8px padding：

- 父节点进入 `GRID`；
- 5 个子项按 2+1 / 1+1+1 排布；
- 首项 `columnSpan=2` 且水平 `FILL` 后宽度 `170 = 80 + 10 + 80`；
- row/column anchor、跨列、水平/垂直 align 均可回读；
- 探针创建节点在 finally 中清理。

报告：

`output/_p3_grid_layout_round2/figma_grid_layout_probe.json`

```text
status: pass
content_hash: 1b07a8e9504f9aab45d85b303913d63952256c50f358d6d25592c3512558e574
```

## 2. Wrap

`HORIZONTAL + WRAP` 已在生产 `set_layout_flow` 中落地。真实 300px 探针得到 2 行，非法 `MASONRY` mode 被拒绝且原布局模式与 Wrap 状态保持不变。

报告：

`output/_p3_wrap_layout_round2/figma_wrap_layout_probe.json`

```text
status: pass
rows: 2
content_hash: c10d0544406807e92346f9bff94d17db96150cc7d798e2c982116acaa3273e8f
```

## 3. Component Instance

`component_instance_probe` 创建 owned frame、component 和 source text，再创建 instance 并只覆盖 instance 内文本。

真实结果：

- instance type 为 `INSTANCE`；
- instance 文本可覆盖；
- component source 文本保持不变；
- root 在 finally 中清理。

报告：

`output/_p3_component_instance_round2/figma_component_instance_probe.json`

```text
status: pass
instance_id: 37:237
content_hash: bf5e909a3948aa09f22f533d10b9586d7cc17c3f61155c2278d4daaed811d021
```

## 4. 多级 Auto Layout

真实探针验证语义传播，而不只是属性写入：

- inner 文本高度变化后 inner frame 高度增长；
- outer frame 高度随之增长；
- inner sibling 的 y 发生传播位移；
- outer sibling 的 y 发生传播位移；
- 恢复文本后两级布局回到原状态。

报告：

`output/_p3_multilevel_autolayout_round2/figma_multilevel_autolayout_probe.json`

```text
status: pass
content_hash: cfbd4b0015b81a6409fa75494e3d7c3169c9d6eac1cc80f1340e99d3ea7740df
```

## 5. 部分编辑失败恢复

新增 `apply_edit_batch`，支持：

- `set_text`；
- `replace_image_fill`；
- `set_name`；
- `set_visibility` / `set_visible`；
- `set_layout_flow`。

合同：

1. 事务必须有 `transactionId`，最多 50 个 action；
2. 全部 action 先 preflight，任一失败则零写入；
3. 运行时中途失败时，按反向顺序恢复已成功编辑；
4. Grid/Wrap 快照包含父 frame 属性、尺寸、track、padding、gap 与子项 anchor/span/alignment/sizing/几何；
5. 返回 `committed`、`rejected`、`rolled-back` 或 `rollback-incomplete`；
6. rollback 失败必须逐节点列出，不能降级为成功。

真实 Figma：

- 4 个顺序编辑提交成功；
- 后续事务预检遇到非 TEXT 节点，整批拒绝；
- 拒绝后名称、可见性、文本与图片填充保持上一事务结果。

报告：

`output/_p3_partial_edit_recovery_round1/figma_partial_edit_recovery_probe.json`

```text
status: pass
content_hash: 247c53bf452c9d2b1c6e74c813d7a4da74efcd967c63d405d21ffb3e53a6c6ab
```

运行时中途故障的回滚由确定性注入测试证明：

- `tests/bridge/test_edit_batch_rollback.js`；
- `tests/bridge/test_layout_transaction_rollback.js`。

新增真实 Figma Grid 约束故障注入：

- 同一事务先改文本，再让 Grid span 触发“相邻列已有子项”错误；
- preflight 全部通过，因此错误发生在真实 apply 阶段；
- 首次真实运行暴露 `rollback-incomplete`，定位到两个缺陷：
  - 失败动作快照未进入 rollback 栈；
  - Grid anchor 被当作可写属性，而真实 API 要求 `setGridChildPosition`；
- 修复后结果为 `rolled-back`，rollback `2/2`，零失败；
- 事务前/后的文本与完整布局快照一致。

报告：

- `output/_p3_runtime_fault_round1/figma_runtime_fault_probe.json`
- `scripts/figma_runtime_fault_probe.py`

网络/上传中断、多人协作冲突和 API 版本异常仍未覆盖，因此 RR-006 保持开放。

## 6. Complex Grid Holdout

新增可恢复探针，创建后保留 owned 节点，支持插件重载或文档重开后按节点
ID 回读：

- manual 2×3 Grid + nested 2×2 Grid；
- `FIXED / FLEX / HUG` track 同场组合；
- row/column span、对齐与 sizing；
- `ROW_AUTO_FLOW` + `gridAutoTracks=ROWS`；
- 长文本与图片 fill；
- 0.5px 几何容差，其余层级、track、span、文本和图片 hash 精确比较。

真实 Figma 结果：

```text
create: pass
plugin_reload_readback: pass
document_reopen_readback: pass
manual_nested_mixed_grid differences: 0
row_auto_flow_grid differences: 0
```

报告：

- `output/_p3_grid_complex_holdout_round1/figma_grid_complex_create.json`
- `output/_p3_grid_complex_holdout_round1/figma_grid_complex_verify.json`

边界与复现见 `P3_GRID_COMPLEX_HOLDOUT.md`。真实 Figma 标签关闭、从最近关闭项
重开、重新启动插件后的回读也为零差异；跨版本回读和自动 track 超出显式 row
count 仍未验证，因此 RR-005 保持开放。

## 7. 未覆盖

- Grid/Wrap 跨版本回读；
- 自动 Grid track 超出显式 row count 的扩展行为；
- 多人协作冲突、撤销/重做和编辑器锁；
- 网络/上传中断和 API 版本异常下的自动回滚；
- component instance 的 swap、detach、nested component 与 variant 属性传播。
