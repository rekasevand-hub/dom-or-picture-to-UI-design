# 第 5 族金稿施工单（AtomGit 首页）

金稿是**答案**，不是我们 pipeline 的输出。所以这份单子里**我只给字符串和目标规格，不给坐标**——
坐标必须从截图自己量，否则 `ink_ratio` 量的就是我们自己的复读能力，不是还原能力。

## 目标规格

| 项 | 值 |
|---|---|
| 画布 | 单根 FRAME，**1920×1008**（与 `reference.png` 同尺寸，`scale_to_reference = 1.0`） |
| 布局 | **绝对定位，不用 Auto Layout**（金稿历史上 55 个 FRAME 全是 `NONE`） |
| 字体 | 按截图目测选族；字号/字重要能让文本框落在墨迹上 |
| 文本 | 逐字转录，**一个字都不能改** |
| 数量参考 | 截图约 47 个独立文本节点、39 个图标位（图标可以直接用矩形占位，本页没有照片） |

## 必须逐字一致的 28 条

这 28 条就是 `truth.json` 的 `critical_texts`，出现任何改写都会让 critical 门禁直接掉分：

```
AtomGit / AtomCode / 探索更多 / 登录 / 注册
推荐 / G-Star / CANN / OpenHarmony / openEuler / Cangjie / openJiuwen
大模型 / 数据集 / 智能体开发 / 昇腾生态
热门推荐 / 更新时间: 23 分钟前
TOP 1 / modern-web-guidance-src / TOP 2 / astryx / TOP 3 / MiniMax-H3-Image
LongCat-2.5 / Nex-N2.6 / skrstop-components
你的云端 AI 编程助手
```

> 注意 `昇腾生态` 与 `TOP 1`：我们自己的感知现在把这两个读错（`舁腾生态` / `TOPI`）。
> **金稿要写对的**，错的是感知，不是答案。

## 建议一并转录的（配对用，非门禁）

六张卡片的描述段、`CodingPlan`、`AtomGit企业版`、`CANNLab`、`昇腾模型生态`、`HiS` 频道页签、
`TypeScript · 2 天前` 这类元信息行。它们不进 critical，但每一个都是 `ink_ratio` / `dy_median` 的抽样点；
少一条就少一个可测样本（`_size_metrics_scope` 要求 ≥ 20 对，否则 size 指标静默跳过）。

## 禁止事项（都是踩过的坑）

1. **不要转述**。历史事故：`项目代码` 被写成 `项目编号`，所有按字符串配对的指标当场失效，而画布上看不出来。
2. **不要缩放**。金稿是 1920×1008 就导 1920×1008 的 node；缩放会把 `scale_to_reference` 和每一处 ink 判定一起带偏。
3. **不要用 Auto Layout 重排**。金稿要的是「照抄」，不是「更合理地布局」。
4. **不要为了过审去改字符串**。审不过说明重建有问题，改字符串只是把问题藏起来。

## 三步验收

金稿做好后，在 Figma 里选中那根 FRAME，抄下 node id（形如 `169:171`），然后：

```bash
PY="C:/Users/lzq/.conda/envs/omni/python.exe"

# 1) 先干跑：校验金稿尺寸与 reference.png 是否一致（不写文件）
$PY scripts/export_gold_tree.py --node <frame_id> \
  --out output/_holdout5_atomgit_gold/gold_tree.json --dry-run

# 2) 正式导出
$PY scripts/export_gold_tree.py --node <frame_id> \
  --out output/_holdout5_atomgit_gold/gold_tree.json

# 3) 预审（staging 目录，不会让这一族进任何门禁）
$PY scripts/audit_gold_tree.py --dir output/_holdout5_atomgit_gold
```

`--dir` 是 2026-11-13 新加的入口：`--family` 只能审已经登记在
`tests/fixtures/benchmark_families/` 下的族，而**目录里一出现 `family.json` 就等于登记**，
所以候选金稿必须能在外面先审。staging 目录里已经有 `family.json`（`pipeline_run` 先指着一个还不存在的
`output/_holdout5_atomgit_run`，等第一次全量跑完再对上）。

判据（与三个已登记族同一把尺）：

| 项 | 门槛 | 三族实测 |
|---|---|---|
| 文本框落在墨迹上 | ≥ 80% | 100% / 100% / 100% |
| 金稿字符串能对上 pipeline 输出 | ≥ 80% | 85.1% / 96% / 93.9% |
| 行距与截图一致 | 有规则序列时必须吻合 | light-table 81.0px vs 81.0px |
| 总判定 | `usable` | 三族全 `usable` |

第一次跑完还要回头复查一次 `text agreement`——它需要一次真实的 readback 才有分母，预审阶段是 `n/a`。

## 验收通过之后

1. 把 `reference.png` / `truth.json` / `gold_tree.json` 复制进
   `tests/fixtures/benchmark_families/atomgit-home/`；
2. **最后**才写 `family.json`（`gold.frame_id` 填真值，`pipeline_run` 指向那次全量跑）；
3. 第一次 `check_benchmark_families --family atomgit-home` 会把当天数字写成基线——
   所以第一次必须跑在认可的版本上。
