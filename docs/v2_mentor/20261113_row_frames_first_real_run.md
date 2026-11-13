# 行级 Frame 首次上真机：绑定错设计 → 修好后仍有 3.8pp 回退 — 2026-11-13

> 一句话：P2（light-table 单页）**像素过关、结构没过**。95.60 → 95.59（Δ −0.0045）是因为
> 最后修掉了两个真 bug；但 10 个行组只有 **1 个** 能建成 Frame，其余 9 个被
> `covers-other-element` 拒掉——卡点在绘制序交错，不在 Frame 机制。

## 1. 第一个坑：分区绑在了另一版设计上

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

- `semantic_partition.design_fingerprint()`：id + 类型 + 几何，按列表顺序 sha256。
- `image_figma_mvp --dump-partition-design`：把**它真正要用的那份元素列表**写出来
  （`figma_design_pre_partition.json`），然后退出，不写 Figma。
- 探针优先读这份 dump；冻结分区时写入 `designSha256`。
- mvp 应用前比对：不等则 `blocked-environment`，报
  `partition-design-mismatch: <分区绑定> vs <当前设计>`，**不静默错位**。

修好后重出分区：正确几何下 **10/10 组全部通过**（错几何上是 8/10）——这条本身说明
「在错的几何上，守门是失效的」。

## 3. 修好绑定后：一路踩到「灰底」和「帧根本建不出来」

| 版本 | 做了什么 | within30 | 建成帧 |
|---|---|---|---|
| 绑定设计后 | 只是分区对了 | 91.8138 | 10 个**矩形**（不是 Frame） |
| 再让透明容器不计深度 | `paint_order` 忽略 `transparent` | 74.0126 | 10 个矩形，每行多一条灰底 |
| 再给容器 `fillColor: transparent` | 被拒的容器不上色 | **95.5949** | **1 个 FRAME + 9 个无填充矩形** |

`--partition` 关闭时导出 `d88b97ec`，与台账逐字节相同——这条从头到尾都成立。

### 3.1 两个真 bug

**① 被拒的容器会被画成灰矩形。** `resolve_frames` 拒绝一个组之后，容器退回普通矩形
绘制；矩形没有 `fillColor` 时插件填 Figma 默认灰 `#d9d9d9`。一页 10 行就是 10 条灰带：
像素差异 26.34%，且**均匀分布在每一行**（每 40px 带 ~79.5k 像素）。修法是把容器的
`fillColor` / `borderColor` 都设成 `transparent`。

**② 透明容器会抬高成员的绘制深度。** `_depth` 统计「被多少个矩形覆盖」，容器算一层，
成员的深度整体 +1；深度是主序，成员与非成员的相对笔序就翻了。修法：`transparent`
的元素既不参与覆盖计数，自身深度也记 0。修完后 152 个共同元素的相对笔序与基线
**逐位一致**，且五个现有族没有元素级 `transparent`，基线导出不变（实测 sha 相同）。

## 4. 真正没过的那一关：只有 1/10 能建成

修完之后 `resolve_frames` 的判定是：

```
建成 1 / 10       拒绝 9，全部 covers-other-element
```

第 3 节表格里那两次「10 个建房」都不是真建成——那是被拒的容器退回矩形，看起来像
节点，实际没有层级。

**这条才是 P2 的结论**：行与行之间夹着非成员（表格的竖分隔线、行底色、相邻行边缘），
`resolve_frames` 的成员闭包要求「夹在成员中间、与 Frame 相交的图元都必须是成员」，
于是整行建不成。

之前「正确几何下 10/10 通过」的读数，是在**错的绘制序**上得到的——顺序一修，真相就变。
所以那条数字不能再引用。

## 5. 现在的位置

- 像素：**95.5949 vs 95.5994，Δ −0.0045**，远在 −0.3 门槛内。差异只剩 2,547 px
  （0.075%），集中在唯一建成的那一条页脚（x 1928–2137、y 1183–1208）。
- 结构：**1 个 Frame**。离「行级可编辑」还差 9 行。
- 所以 P2 的结论是：**发射链路是安全的（不回归），但结构收益接近于零**，
  卡点不在 Frame 机制，在绘制序交错。

## 6. 下一步的两条路

1. **让成员的绘制区间可嵌套**：表头/表格行的竖分隔线与行底色如果算进组内，闭包就能闭合。
   代价是组的定义要包含「视觉上属于这一行的线」，而 VLM 现在的分组不含它们。
2. **换族**：light-form 的行组天然带底色（表格行整条），闭包更容易闭合。
   先用 `--dump-partition-design` + 探针在 light-form 上量一遍，成本 0.002 元。

## 7. 新增禁改项

| 禁改项 | 原因 |
|---|---|
| **分区文件必须带 `designSha256`** | 不带就等于允许跨版本静默错位（95.60 → 59.37 就是它） |
| **不要拿校准后的 `figma_design.json` 当分区输入** | 那是终版，发射用的是校准前；89/152 个坐标不同 |
| **在错的几何/错的绘制序上，不要相信 `resolve_frames` 的通过数** | 同一批分组：错几何 8/10、错序 10/10、真实 1/10 |
| **分区容器必须有 `fillColor: transparent`** | 被拒时退回矩形，没 fill 就填默认灰，一页掉 26 个点 |
| **不要让透明容器参与 `_depth`** | 成员深度 +1 → 笔序翻转；修好后共同元素序逐位回到基线 |

## 8. 复现

```bash
PY="C:/Users/lzq/.conda/envs/omni/python.exe"
$PY scripts/image_figma_mvp.py --image <ref> --truth <truth> --out output/_dump \
    --acceptance-policy 2.1 --reuse-prepared --dump-partition-design
$PY scripts/vlm_partition_probe.py --family light-table --run-dir output/_dump --refresh
$PY scripts/image_figma_mvp.py --image <ref> --truth <truth> --out output/_run \
    --acceptance-policy 2.1 --reuse-prepared --partition output/_structure_partition/light-table/partitions.json
```
