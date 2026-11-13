# 行级 Frame 首次上真机：三个 bug，一层一层剥 — 2026-11-13

> 一句话：P2（light-table 单页）的像素一直没问题，结构一直没通。三个 bug 全部修完后，
> **离线判定 light-table 10/10、light-form 12/12 全部建成**，且共同元素的绘制序与基线
> 逐位一致。真机复验卡在插件的回调表上（`invalid id`），需在 Figma 里重载插件。

## 0. 五次读数，一次比一次接近真相

| 版本 | 改了什么 | 建成 | within30 |
|---|---|---|---|
| 绑定错设计 | 分区对着终版几何算 | 10 / 10（**假**） | 59.37 |
| 绑定设计指纹 | 分区对上校准前几何 | 10 个**矩形** | 91.81 |
| 透明容器不计深度 | `paint_order` 剔除 `transparent` | 1 / 10（Frame） | 74.01 |
| 容器 `fillColor: transparent` | 被拒的容器不上色 | 1 / 10 | **95.5949** |
| **深度不再固定成 0** | 透明容器按「被多少不透明元素覆盖」算深度 | **10 / 10**（离线） | 待真机 |

前四次都是真机读数，最后一行是离线，等插件重载后补真机。

## 1. 坑一：分区绑在了另一版设计上

探针原本读 `figma_design.json`，那是**校准四轮之后**的终版；mvp 把分区应用在**校准之前**。

| | 值 |
|---|---|
| 元素数 / 顺序 | 152 vs 151，顺序一致 |
| **坐标不同的元素** | **89 / 152** |
| 后果 | 组 bbox、成员闭包、绘制序全变；`resolve_frames` 在错几何上放行 10 组 |
| 像素 | 带开关 **59.37**（基线 95.60） |

同一个组在两版几何下的 bbox 根本不是一回事：`行 04` 终版 `[470,671,2032,68]`、校准前
`[115,608,2261,119]`。

## 2. 修法：分区绑定设计指纹

| 件 | 内容 |
|---|---|
| `semantic_partition.design_fingerprint()` | 对 id、类型、几何按顺序取 sha256 |
| `image_figma_mvp --dump-partition-design` | 写出 mvp **真正要用**的那份元素列表后退出，不写 Figma |
| 探针 | 优先读这份 dump；冻结分区时写 `designSha256` |
| mvp 应用前 | 比对指纹，不一致 → `blocked-environment`，不静默错位 |

## 3. 坑二：被拒的容器会被画成灰矩形

`resolve_frames` 拒绝一个组后，容器退回普通矩形绘制；矩形没有 `fillColor` 时插件填
Figma 默认灰 `#d9d9d9`。一页 10 行就是 10 条灰带。

- 像素差异 **26.34%**，且**均匀分布在每一行**（每 40px 带约 79.5k 像素）；
- 修法：容器的 `fillColor` / `borderColor` 都设成 `transparent`；
- 修完后差异降到 **0.075%**（2,547 px）。

## 4. 坑三：透明容器的深度

`_depth` 统计「被多少个矩形覆盖」，容器算一层，成员深度整体 +1；深度是主序，
成员与非成员的相对笔序就翻。所以第一版修法是「透明容器不参与覆盖计数」。

**但那一步同时把它自己的深度也固定成了 0**——这是错的：

```
祖先区块 depth=1，行 Frame depth=0 → Frame 排在祖先之前
→ 祖先落进 `resolve_frames` 的「Frame 之后」窗口
→ 判定 `covers-other-element`，整组被拒
```

light-form 12 个组全灭、light-table 掉到 1/10，都是这条。正确的算法是：**透明容器
不参与别人的覆盖计数，但它自己的深度仍按「被多少不透明元素覆盖」算**——算出来正好
等于成员所在的那一层，靠下标（容器插在最早成员之前）决定它先于成员落笔。

| 族 | 修前建成 | 修后建成 | 共同元素笔序 |
|---|---|---|---|
| light-table（10 组） | 1 / 10 | **10 / 10** | 与基线逐位一致 |
| light-form（12 组） | 0 / 12 | **12 / 12** | 与基线逐位一致 |

## 5. light-form 的负结论与正结论

原计划「换 light-form，它的行天然带整条底色，闭包更容易闭合」——**前半句被证伪**：
在修深度之前，light-form 是 0/12，比 light-table 还差。原因不是底色，是它的行夹在
`form-section` 这类**祖先容器**与整幅底图之间，Frame 一旦排到祖先之前就全灭。

修完深度后，同为 12/12。所以「哪个族更容易」不取决于底色，取决于 Frame 与祖先的相对笔序。

## 6. 现在的位置

| 项 | 状态 |
|---|---|
| 像素（不带开关） | 真机 **95.5994**、导出 `d88b97ec`，与台账逐字节相同 |
| 像素（带开关） | 真机 95.5949（Δ −0.0045，门槛 −0.3）——这是在**只有 1 个 Frame** 时测的 |
| 结构（带开关） | 离线 10/10，真机待复验 |
| 回归 | `1601 passed / 8 failed`（8 个既有环境项），17 例分区单测 |
| 真机 | **被插件回调表挡住**：`Attempted to invoke callback with invalid id -32701` |

插件那条按 `20261110image to Figma-handoff.md` §295 的记载：长会话后回调表失效，
**重启 bridge 无效，必须在 Figma 里重载插件**。

## 7. 禁改项（新增四条）

| 禁改项 | 原因 |
|---|---|
| **分区文件必须带 `designSha256`** | 不带就等于允许跨版本静默错位（95.60 → 59.37 就是它） |
| **不要拿校准后的 `figma_design.json` 当分区输入** | 那是终版，发射用的是校准前；89/152 个坐标不同 |
| **在错的几何 / 错的绘制序上，不要相信 `resolve_frames` 的通过数** | 同一批分组：错几何 8/10、错序 10/10、真实 1/10、修好后 12/12 |
| **透明容器的深度不能固定成 0** | Frame 会排到祖先之前，祖先被当成外人，整族全灭 |

## 8. 复现

```bash
PY="C:/Users/lzq/.conda/envs/omni/python.exe"
$PY scripts/image_figma_mvp.py --image <ref> --truth <truth> --out output/_dump \
    --acceptance-policy 2.1 --reuse-prepared --dump-partition-design
$PY scripts/vlm_partition_probe.py --family <name> --run-dir output/_dump --refresh
$PY scripts/image_figma_mvp.py --image <ref> --truth <truth> --out output/_run \
    --acceptance-policy 2.1 --reuse-prepared --partition output/_structure_partition/<name>/partitions.json
```

离线判定（不写 Figma，0 成本）：`build_partition_containers` → `paint_order` →
`resolve_frames`，`reasons` 为空即全部可建。
