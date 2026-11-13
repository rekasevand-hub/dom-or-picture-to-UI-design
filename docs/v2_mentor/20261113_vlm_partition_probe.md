# VLM 语义分区：首轮 18/32，行级稳定、卡片全拒 — 2026-11-13

> 一句话：**VLM 能分出语义块，但我们的绘制序接不住。** 32 个合法组里 18 个能建成
> Frame，拒绝几乎全是 `covers-other-element`；稳定拿到的是**行级结构**（表格行、
> 列表行、导航条、页脚），卡片级一个都没过。补底板不解决（净收益 0）。

探针：`scripts/vlm_partition_probe.py`（只读，不连 Figma，不改流水线）。
模块：`src/app/services/structure/fidelity/semantic_partition.py`（纯函数）。

## 1. 方法：让 `resolve_frames` 判，不另写校验

VLM 只回答「哪些元素属于同一块」，输出扁平 `groups`（不下发层级、坐标、样式）。
代码把每组包成 `layout: {"mode": "NONE"}` 的合成容器（`transparent=True`，插件会清空
fills），再走真链路：

```
合成容器 → paint_order → resolve_frames（四条守门）→ 逐组 accepted / rejected + 原因
```

**判据不自建**：`resolve_frames` 就是发射端判据，被拒的组退回扁平，逐像素与不开分区相同。
分区冻结在 `output/_structure_partition/<family>/partitions.json`，`--replay` 复算 0 成本——
调容器逻辑不许重新调模型。

预算：5 族各 1 次调用，`temperature=0`，单价 0.002 元/张，**合计 0.01 元**。

## 2. 结果

| 族 | 组 | 容器 | 建成 | 接受率 |
|---|---|---|---|---|
| atomgit-home | 9 | 6 | **1** | 16.7% |
| content-review | 3 | 3 | **1** | 33.3% |
| dark-card-grid | 7 | 6 | **2** | 33.3% |
| light-form | 7 | 7 | **6** | 85.7% |
| light-table | 10 | 10 | **8** | 80.0% |
| 合计 | 36 | 32 | **18** | 56.3% |

拒绝原因：`covers-other-element` **14**、`schema:member-claimed-twice` 2、
`schema:fewer-than-two-members` 1、`schema:group-too-large` 1。

## 3. 三条读数

**① 建成的全是行。** light-table 的 7 个「列表项·第 N 行数据」+ 页脚；light-form 的
5 个「表格行·历史记录 N」+ 表头 + 页头；dark 的页头标题区与一条卡片行。
**表格行/列表行是唯一稳定通过的类别**——恰好也是设计师最想要的那层结构（可复用行）。

**② 卡片级全拒，原因不是模型分错。** 模型给的「卡片·安全检查项列表」语义上是对的；
拒绝来自成员的**绘制序被兄弟元素切开**：`resolve_frames` 要求成员是绘制序里连续的
一段，而 `paint_order` 按 `paintDepth` 排序，兄弟容器的子树天然交错。
这条在 `20261113_phase5_grouper_verdict.md` §3 里预判过，现在有数了。

**③ 模型自己也有 4 次 schema 错**：2 次把同一元素分进两个组、1 组 11 个成员超上限、
1 组只有 1 个元素。说明「一组一个父级」这条约束模型会违反，必须由代码挡（已挡）。

## 4. 被推翻的假设：补底板能救 `covers-other-element`

**假设**：卡片底板被模型漏掉（它只圈文字与图标），底板成了那个「夹在成员中间的
外人」；把它补进成员就能过。

**实测（同一份冻结分区，只改容器构造，0 成本 A/B）**：

| 构造 | 建成 |
|---|---|
| 现状（不补） | **18 / 32** |
| 补底板（无面积上限） | 12 / 32 —— light-form 从 6 → **0** |
| 补底板 + 面积比 ≤8 | 17 / 32 |
| 补底板 + 面积比 ≤4 | 17 / 32 |
| 补底板 + 面积比 ≤2 | 18 / 32（与不补持平） |

**净收益 0，无约束时反而更差。** 原因很直接：一行表格的「底板」是整张表，补进来
Frame 就撑到全表，立刻撞 `covers-other-element`；而卡片即便补上底板，成员之间的外人
依然存在（同排的邻居、图片、分隔线）。**底板不是病根，绘制序才是。**

## 5. 已知上限：扁平分组只能到 depth 2

本轮 schema 是**扁平**的（一组一个容器，容器之间不嵌套）。即使接受率 100%，
depth 也只有 2；金稿要 2（atomgit）–7（dark）层。要往上走只有两条：

1. **允许「组的组」**（schema 加一层），但嵌套会让 `member-order` 更难过，不是更松；
2. **先让绘制序支持嵌套**（兄弟子树连续），那是渲染侧改动，像素风险由 `resolve_frames` 兜。

两条都不在首轮范围内。首轮的任务是回答「VLM 分组值不值得接」，答案是：**行级值得，
卡片级要先解决绘制序**。

## 6. 新增禁改项

| 禁改项 | 原因（实测） |
|---|---|
| **不要用「补底板」解 `covers-other-element`** | 18 → 12（无约束）/ 17（有上限），净收益 ≤0 |
| **不要为了刷接受率去调 prompt，尤其是对着 atomgit** | 它是唯一没被调过参的族，按它调参等于把考卷变成练习题 |
| **不要在 `--replay` 之外重复调模型** | 冻结分区就是为了让容器逻辑的每次改动都 0 成本可复算 |
| **不要把分区容器设成有填充** | Frame 默认白底会盖住下面的内容；必须 `transparent=True` |

## 7. 复现

```bash
PY="C:/Users/lzq/.conda/envs/omni/python.exe"
$PY scripts/vlm_partition_probe.py --dry-run          # 只看元素表，不花钱
$PY scripts/vlm_partition_probe.py --max-calls 15     # 五族，≤0.03 元
$PY scripts/vlm_partition_probe.py --replay           # 冻结分区复算，0 元
```
