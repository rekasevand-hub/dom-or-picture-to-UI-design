# Phase 5 的坐标前提：探针推翻了一条既有假设（2026-11-13）

`docs/v2_mentor/20261113image to Figma-handoff.md` §7.1 写着：

> 做第 5 项之前必须先解这个：`code.js` 的 `applyGeometry()` 在 `appendToParent()` **之后**写
> `node.x = params.x`（绝对坐标）。父级原点非 0 时这会二次偏移。

**这句话在三个方面都不成立**，实测与代码都推翻了它。

## 事实

1. **顺序相反**：`createFrame` / `createRectangle` / `createText` 都是
   `applyGeometry()` → `appendToParent()`，不是之后。
2. **spec 里的坐标不是绝对坐标，是父级局部**。`figma_design.json` 里 `banner` 在 `x=129`，
   而根帧建在 `x=22000`——如果 spec 是绝对的，129 会落在画布最左边。它是局部值，正好吻合。
3. **`appendChild` 确实会重新解释**：探针里父帧在 31000、子节点传 31100，回读仍是 31100
   （即被当成局部值，实际落在 62100）。但这不是 bug——调用方本来就传局部值。

## 我试过什么，结果如何

按假设在 `appendToParent` 里加了一次换算（`node.x = params.x - parent.absoluteBoundingBox.x`），
把 `BRIDGE_BUILD` 提到 `2026-11-13-parent-relative-geometry`，同步到 `D:/LLM-Data` 并重载插件后实测：

| | within30 | native | 直接子节点回读 |
|---|---|---|---|
| 基线 | 94.80 | 14/18 | `banner x=129` |
| 加了换算 | 95.05 | **12/18** | `banner x=-21871` |

`banner` 被推到 `-21871`——正是 `129 - 22000`。**整块直接子节点被推出画布**，靠裁剪掩盖了一半，
`native` 掉了 2 个 owner。已 `git revert` 两笔，插件文件也同步回旧构建。

## 正确的结论

- **`code.js` 不需要改。** 它按局部坐标处理是对的，调用方也按局部坐标传。
- Phase 5 真正要做的是**调用方**：把容器的子项坐标减去容器原点。这个机制已经存在——
  `_offset_spec(spec, origin)` 就是干这个的，裁剪容器（clip frame）已经在用。
- 所以第 5 项的前置条件不是"修插件坐标"，而是"让容器子项走 `_offset_spec`，
  并把容器的 `(x, y)` 当成后续子项的 origin"。这是 Python 侧改动，可单测，不需要重载插件。

## 顺带留下的一条纪律

**不要用裸 `_send` 探针去推断整条流水线的语义。** 探针只证明了 `appendChild` 的行为，
而我拿它去推断"spec 是绝对坐标"，漏掉了 `_offset_spec` 与根帧 `x=22000` 这两个事实。
判据应该是**跑一页并对比 within30 / native**，不是探针读数漂亮就够了。
