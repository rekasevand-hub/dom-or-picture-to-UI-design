# 行级 Frame 首次上真机：绑定错设计 → 修好后仍有 3.8pp 回退 — 2026-11-13

> 一句话：P2（light-table 单页）**没过**。第一版 95.60 → 59.37 是因为分区绑错了设计；
> 修好绑定后 → **91.81**，回退收敛到 3.8pp，但仍在门槛（−0.3）之外。

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

## 3. 修好绑定后的结果

| | 导出 sha | within30 | native | critical |
|---|---|---|---|---|
| 不带开关 | `d88b97ec`（与台账逐字节相同） | 95.5994 | 46/59 | 30/30 |
| 带开关 | `39c6ea70` | **91.8138** | 45/59 | 30/30 |

`--partition` 关闭时零副作用这条**通过**（逐字节相同）。

## 4. 3.8pp 回退落在哪

两张导出图逐像素比对（同尺寸 2544×1336）：

| 项 | 值 |
|---|---|
| 差异像素 | 166,944（**4.91%**） |
| 范围 | x 470–2503、y 447–1208 |
| 最集中的 y 带 | **440–470**（表头行）、**1060–1120**（末尾两行） |
| 横向 | 铺满表格宽度，不集中在某一列 |

表头与末尾行整条带一起变，横向铺满——像是**底色与文字的先后翻转**，不像单个元素位移。

## 5. 最可能的机制（未验证）

建 Frame 会让成员在 `paint_order` 的 `_depth` 计数里各多一层（容器覆盖它们一次）。
深度是主序，成员与**非成员**的相对顺序就可能翻——表头/末尾行恰好是相邻组之间的边界，
最容易被翻到。

如果这条成立，处置有两条，都不便宜：

1. 让容器**不参与** `_depth` 计数（改 `paint_order`，影响面大）；
2. 只对「底色也在组内」的行建 Frame（组内自带底板，翻序不影响像素）——但上一轮
   「补底板」实测净收益 0，且细行会把整张表当底板。

## 6. 新增禁改项

| 禁改项 | 原因 |
|---|---|
| **分区文件必须带 `designSha256`** | 不带就等于允许跨版本静默错位（这次 95.60→59.37 就是它） |
| **不要拿校准后的 `figma_design.json` 当分区输入** | 那是终版，发射用的是校准前；89/152 个坐标不同 |
| **在错的几何上不要相信 `resolve_frames` 的通过数** | 同一批分组，错几何 8/10 通过、正确几何 10/10，结论完全相反 |

## 7. 复现

```bash
PY="C:/Users/lzq/.conda/envs/omni/python.exe"
$PY scripts/image_figma_mvp.py --image <ref> --truth <truth> --out output/_dump \
    --acceptance-policy 2.1 --reuse-prepared --dump-partition-design
$PY scripts/vlm_partition_probe.py --family light-table --run-dir output/_dump --refresh
$PY scripts/image_figma_mvp.py --image <ref> --truth <truth> --out output/_run \
    --acceptance-policy 2.1 --reuse-prepared --partition output/_structure_partition/light-table/partitions.json
```
