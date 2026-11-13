# 失败分层落地：只有 light-table 会变绿 — 2026-11-13

> 一句话：分层做完是**只读**的（`enforcement: "report"`），换上新尺子后**五族没有一族会绿**。
> 它买的是「这一位到底在说什么」，不是分数。

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

## 3. 五族分布（新尺子，15:57 真机五族 `--rerun`，8m17s）

产物 `gitDirty=false` / `gitSha=42d610d2`，五族同一把尺子（`report_state` 的 holdout 行
已从 `_p25_clean` 指向 `rerun/content-review`）：

| 族 | 门禁 owner | 失败 | 机械 | 字族 | 量具 | 阻塞 | 会绿 |
|---|---|---|---|---|---|---|---|
| content-review | 18 | 6 | 1 | 5 | 0 | 1 | 否 |
| dark-card-grid | 30 | 18 | 5 | 13 | 0 | 5 | 否 |
| light-form | 33 | 3 | 2 | 1 | 0 | 2 | 否 |
| light-table | 59 | 13 | 4 | 8 | 1 | 4 | 否 |
| atomgit-home | 34 | 23 | 16 | 5 | 2 | 16 | 否 |
| 合计 | 174 | 63 | **28** | 32 | **3** | 28 | **0 / 5** |

三条读数：

1. **量具层塌了：25 → 3。** 墨迹归属口径不再让参考墨迹贴在窗口边上，`instrument-capped`
   从「四分之一的失败」变成个位数。这枚尺子做的第一件事就是**取消借口**。
2. **机械层翻倍：14 → 28。** 旧口径下被「贴边封顶」解释掉的失败，新口径里是实打实的
   位移/缩放问题。总数 58 → 63，其中新增的几乎全部落在机械层。
3. **没有一个族会绿。** 旧口径下 light-table 机械层为零；新口径下它也有 4 条机械失败。

## 3.1 被推翻的一条：旧尺子下「light-table 会绿」

这条在本文件 15:45 版里写过，**已不成立**，留档如下：

| 族 | 机械 | 字族 | 量具 | 阻塞 | 会绿 |
|---|---|---|---|---|---|
| light-table（legacy 口径） | 0 | 5 | 5 | 0 | **是** |

差别全部来自量具层：legacy 把 5 条读不完的宽度算成「不计分」，归属口径把它们读全了，
其中 4 条是机械失败。这也说明一件事——**「分层后有几个族会绿」这个数，完全取决于尺子；
尺子换掉之前不该拿它做决策**。

对照 11-13 上午的人工归因：content-review 的 4 条仍是 1 机械 + 2 字形 + 1 宽度轴
（新口径下该族共 6 条失败，多出的 2 条是新增的字族项），分类器与人工判断一致。

## 4. 踩到的坑：在脏工作区复跑，把别人的口径当成自己的回归

单族复跑（content-review）出现了一次不可用的测量：

| | gitSha | gitDirty | 导出 sha | native | 测量框 |
|---|---|---|---|---|---|
| 同批次（15:0x） | `b90bedee` | **false** | `40149c8c…` | 14/18 | 128–313 px |
| 单族复跑（15:38） | `e1cbd4e7` | **true** | `40149c8c…`（相同） | **12/18** | 307–907 px |

导出逐字节相同、设计 IR 逐位相同（`ebd77d5bd1ec`），但 owner 的 `measureBBox` 全部变宽
2–3 倍，`measurementSource` 仍是 `emitted-node`。**渲染没变，尺子变了。**

原因不是画布残留，是**另一个会话在同一棵工作树上未提交的「墨迹归属」改动**
（15:41 提交为 `d84667d`）：参考窗口从「节点框 + pad」改成
`union(source_bbox, 节点框) + pad`，再按归属取 run。该提交自己的记录也写着
「离线重算：critical 116→111、content-review 14→12」——正是我看到的 14→12。

**这条禁改项早就在 11-13 交接里（`gitDirty = true` 的运行不能当基线），这次是我自己踩的。**
复跑前先看 `git status`，或者只看产物里的 `runtime.gitDirty`；两秒钟的事。

处置：该产物归档为 `output/_benchmark_families/rerun_content_review_dirty_ink_ownership_20261113_1540`，
字段落盘证据留在 `_layer_field_evidence_20261113.json`，`rerun/content-review` 已恢复成同批次产物。

## 4.1 口径已统一，这条不再需要打补丁

§3 现在是**新尺子的真机产物**，五族同一口径。过渡期那句「分布算在 legacy 产物上、
要当基线得再跑一次」已经完成——8m17s 的五族 `--rerun` 就是那一次，旧产物归档在
`output/_benchmark_families/rerun_legacy_20261113_1548`。

留给下一个人一条方法：**换尺子的当天不要同时改判据**。这次顺序是对的——先换尺子、
重跑五族、再重述分层；如果先打开 `enforcement: "block"`，light-table 会在旧尺子上
变绿一天，然后在换尺子时无声变红。

## 5. 新增禁改项

| 禁改项 | 原因 |
|---|---|
| **不要用「高宽不自洽」单独判字族** | `系统运行正常` 同样宽超高平，但它是机械缺陷；必须先看位移是否干净 |
| **不要在 `gitDirty = true` 时复跑并采信数字** | 15:38 那次就是：导出 sha 逐字节相同，owner 14→12，差的是别人未提交的尺子。复跑前看 `runtime.gitDirty` |
| **不要用 `failureLayers` 去改 `status`** | 它现在是 report；要改先改 policy 的 `enforcement`，并重跑五族拿分布 |
| **不要把 `unmeasured` 归进任何一层** | 它没有 checks，归进去等于把「没测」当成「测过且合格」 |

## 6. 打开分层之前要决定的事

新尺子下 `enforcement: "block"` 一旦打开，**五族仍然全红**——没有一族机械层为零。
所以打开它不会让产线变绿，只会让绿灯**第一次可解释**：红是「我们有 bug」，不是
「参考用了别的字体」。

真正要修的是 **28 条机械失败**，分布很不均：

| 族 | 机械失败 | 占该族失败 |
|---|---|---|
| atomgit-home | 16 | 70% |
| dark-card-grid | 5 | 28% |
| light-table | 4 | 31% |
| light-form | 2 | 67% |
| content-review | 1 | 17% |

atomgit 一个人占 16 条，而且它是唯一没被调过参的族——**先修它才有泛化意义**，
修前四族只是在已经磨过的图上再磨一遍。

