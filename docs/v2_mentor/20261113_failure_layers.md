# 失败分层落地：只有 light-table 会变绿 — 2026-11-13

> 一句话：分层做完是**只读**的（`enforcement: "report"`），五族里只有 **1 个族**
> 会因此变绿。它买的是「这一位到底在说什么」，不是分数。

## 1. 做了什么

| 层 | 位置 | 职责 |
|---|---|---|
| 分类 | `native_text_quality._failure_class` | 按读数把每条失败归到一类（测量） |
| 映射 | `IMAGE_MVP_POLICY_V21.native_text_failure_layers` | 哪一类挡发布（产品决策） |
| 统计 | `image_figma_acceptance._with_failure_layers` | 按门禁范围计数 + 只读推演 |

owner 级新增 `failureClass`，summary 新增 `failureClassCounts`，报告新增
`native_text_quality.failureLayers`（含 `hypothetical.wouldPass`）。
`checks` / `status` / `blockers` **一个字没动**——分层开关打开之前，门禁行为与 11-13 上午一致。

## 2. 分类顺序（这就是那条被认可的补丁规则）

1. 四维全过 → `pass`
2. **未贴边的轴上有位移** → `mechanical`
3. **只有贴边轴上有位移** → `instrument-capped`
4. 宽超、高在容差内、**横向未贴边** → `typeface-advance`
5. 尺寸失败且至少一个未贴边轴 → `mechanical`
6. 几何全过、只有 coverage/edgeF1 差 → `typeface-glyph`

第 2 条排在第 4 条前面，是这条规则的关键。`REQ-OIBFZVUES`（宽 +6、高 +2、位移 0）
落 `typeface-advance`；`系统运行正常`（宽 −5、高 +2、**dy −6**）落 `mechanical`。
两者形状一样，差别只有一个：**位移是否干净**。只看「高宽不自洽」会把 13px 的间距缺陷
放进「不挡发布」那一层——这正是补丁规则必须先看位移的原因。

## 3. 五族分布（15:0x 那批产物离线重算）

| 族 | 门禁 owner | 失败 | 机械 | 字形 | 宽度轴 | 量具 | 阻塞 | 假设绿灯 |
|---|---|---|---|---|---|---|---|---|
| content-review | 18 | 4 | 1 | 2 | 1 | 0 | 1 | 否 |
| dark-card-grid | 30 | 18 | 2 | 5 | 1 | 10 | 2 | 否 |
| light-form | 33 | 3 | 2 | 0 | 0 | 1 | 2 | 否 |
| light-table | 59 | 10 | **0** | 5 | 0 | 5 | **0** | **是** |
| atomgit-home | 34 | 23 | 9 | 2 | 2 | 9 | 10（含 1 条不可测） | 否 |
| 合计 | 174 | 58 | 14 | 14 | 4 | 25 | 15 | 1 / 5 |

三条读数：

1. **分层不是通行证。** 58 条失败里 25 条是量具、14 条是字形、4 条是宽度轴——真正
   「换族才能修」的合计 18 条；剩下 **14 条机械 + 1 条不可测**仍然挡着四个族。
2. **atomgit 是唯一以机械失败为主的族**（9/23）。它是没被调过参的那张，说明前四族的
   高分里有相当一部分是「把机械项磨掉了」，不是「字族问题更少」。
3. **light-table 今天就该绿**：10 条失败全是字形与量具，机械层为零。它会是分层打开后
   第一个、也可能是唯一一个立刻变绿的族。

对照 11-13 上午的人工归因：content-review 的 4 条被分类器复现为 1 机械 + 2 字形 +
1 宽度轴，与 `20261113_owner_attribution.md` 逐条一致。

## 4. 意外发现：复跑会取到别人的节点框

单族复跑（content-review）出现了一次不可用的测量：

| | 导出 sha | bad_pixel | native | 测量框 |
|---|---|---|---|---|
| 同批次 | `40149c8c…` | 100687 | 14/18 | 128–313 px |
| 单族复跑 | `40149c8c…`（**相同**） | 100687（**相同**） | **12/18** | 307–907 px |

导出逐字节相同、设计 IR 逐位相同（`ebd77d5bd1ec`），但 owner 的 `measureBBox` 全部变宽
2–3 倍，`measurementSource` 仍是 `emitted-node`。也就是说：**渲染没变，回读取到了别的节点**。
最可能是画布上存在同坐标的残留帧（同一 origin 连跑两次），回读按名字/文本匹配时命中了另一棵。

处置：该产物归档为 `output/_benchmark_families/rerun_content_review_polluted_20261113_1540`，
字段落盘证据留在 `_layer_field_evidence_20261113.json`，`rerun/content-review` 已恢复成同批次产物。
**本节的分布表用离线重算，不用那次复跑。**

## 5. 新增禁改项

| 禁改项 | 原因 |
|---|---|
| **不要用「高宽不自洽」单独判字族** | `系统运行正常` 同样宽超高平，但它是机械缺陷；必须先看位移是否干净 |
| **不要在画布有同坐标残留帧时复跑并采信 owner 数** | 导出可以逐字节相同，回读仍可能取到另一棵树的节点框（14→12 就是这么来的） |
| **不要用 `failureLayers` 去改 `status`** | 它现在是 report；要改先改 policy 的 `enforcement`，并重跑五族拿分布 |
| **不要把 `unmeasured` 归进任何一层** | 它没有 checks，归进去等于把「没测」当成「测过且合格」 |

## 6. 打开分层之前要决定的事

`enforcement: "block"` 一旦打开，light-table 会立刻 `pass`，其余四族仍 `blocked-fail`。
所以打开它不会让产线「全绿」，只会让绿灯**第一次有意义**。真正要修的是那 14 条机械失败
——其中 atomgit 占 9 条，且它是最诚实的族。
