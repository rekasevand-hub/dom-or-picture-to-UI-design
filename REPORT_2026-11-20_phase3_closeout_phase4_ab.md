# 阶段三收尾 + 阶段四 A/B 报告（2026-11-20）

> 交接文档 `HANDOFF_2026-11-20_phase3_physical_route.md` 之后的两步：
> **一是把 RapidOCR 换掉之后暴露的两处肉眼退化收掉、把回环校准默认关掉**；
> **二是把 `vlm_arbiter` 从"只会改坐标"升级成带语义工具的巡检闭环，并跑三页真机 A/B**。
> 变更全在 `feat/visual-fidelity-pass`。

---

## 1. 一句话结论

七页冷启 **94.34 / 91.37 / 7.571**（基线 94.35 / 91.38 / 7.570，差 −0.01，等价），
帧数 **9/7/7/13/6/5/1** 与基线逐页相同，七页红线 **13/6/10/14/9/3/6 未动**，
全量单测 **1700 passed / 8 skipped / 0 failed**。

两处退化都修好了，但**代价与收益都记在账上**：FluxWeaver 拿回 3 行数据、页分 −0.09
（表格整体字号偏小 25%，见 §6）；wecom 的 `取消` 原样恢复、页分 −0.01。
回环校准默认关掉后，单页省 **5.1s**、首轮导出比收敛后导出高 **+0.34**。

VLM 闭环升级完成，三页 A/B：**+0.01 / +0.01 / 0.00**，9 条补丁采纳、25 条回滚，
**没有一页被改坏**——但它也没能把分数推上去，原因和交接文档预判的一致，见 §7。

---

## 2. 收尾一：导出后墨迹回环校准默认关闭

`image_figma_mvp.py` 新增 `--ink-roundtrip`（默认关），关掉的是 calibration 组
`ink-convergence`（`INK_ROUNDTRIP_GROUP`）。默认行为：

* 只跑首轮导出，`figma/` 是唯一产物目录，`figma_ink_converged/` 不再生成（口径只剩一个）；
* 少一次真机往返，也就是少一次 `Attempted to invoke callback with invalid id` 的机会；
* `font_calibration.json` 里新增 `skipped_groups: ["ink-convergence"]`，报告不再假装跑过。

同一页（FluxWeaver）实测开关差异：

| | within30 | mean | 产物目录 | 墙钟 |
|---|---|---|---|---|
| 关（新默认） | **95.30** | 5.331 | `figma/export.png` | **30.1s** |
| 开（`--ink-roundtrip`） | 94.96 | 5.740 | `figma_ink_converged/export.png` | 35.2s |

即 **+0.34 分、−5.1s/页**，且七页口径统一到首轮导出。

---

## 3. 收尾二：FluxWeaver 表格 `执行结果` 列丢 3 行

### 3.1 定位结果：不是去重，是**识别**丢的

按"从 RapidOCR 原始输出到 design"逐段打印，五行同字符串的踪迹：

| 阶段 | 出现次数 |
|---|---|
| RapidOCR `eng(image)`（默认 `text_score=0.5`） | **3**（第 3、5 行 + 表单里那个 SUCCESS） |
| RapidOCR 检测阶段（`use_rec=False`） | **5 行全有框** |
| `ocr_supplement.observations` | 3 |
| `10_pagegraph.json` | 2（第 3、5 行） |
| `12_design.json` | 2 |

检测器五行都出了框；识别阶段第 1、2、4 行输出的是
`SSOnSaeessa.SOnS.oe)`（置信度 0.30~0.34），被 `text_score=0.5` 滤掉。
同一块像素**单独**再读一次是 0.94~0.97 —— 退化来自 rec 的批内宽度归一
（`max_wh_ratio` 取整批最大值），跟着邻居走。

调参证实这条路走不通：`box_thresh` 0.5→0.1、`det_thresh` 0.2、
整页 1.0/1.5/2.0× 缩放、`score_mode=slow` 全都时灵时不灵（同一页 3~6 行之间跳）。

### 3.2 通用修复：低分框单独重读一次（`_rapidocr_reread`）

1. 整页读一次，`text_score` 临时压到 0（拿到**所有**框，含读糊的），读完立刻还原；
2. 保留 ≥0.5 的框（几何、顺序与旧行为逐字节相同）；
3. 对 <0.5 的框，按原坐标裁出来**一次一个**重读（批处理正是故障来源），
   重读 ≥0.6 才收；斜排字（上下沿高差 >4px）跳过，不硬读。

成本 +0.3~0.6s/页，FluxWeaver 由 78 → 81 条观测，五行齐全。
其余六页条数不变或 +1，无新增噪声。

### 3.3 代价

新增的 3 行继承了这张表**系统性的字号偏小**（见 §6），所以像素分反而降：
FluxWeaver 页 95.39 → 95.30（表格区域 91.51 → 90.00）。
但空单元格比"字略小"严重得多——按"肉眼可见缺陷优先"收在这里。

---

## 4. 收尾三：wecom-modal `取消` 变空白

**根因是绘制顺序，不是漏识别、不是字色反转。** 设计里 `取消` 的文字色 `#10141a`
正确、`chip-outline` 白底也在，但：

* `_recover_chip_outlines` 把装饰层插在**扁平列表里标签之前**；
* 标签是 `card:container-0` 这个帧的成员，帧在扁平列表的第 1 位——
  早于装饰层——于是装饰层实际画在**整个帧之后**，把 `取消` 盖住了。

真实 Figma 回读证据：根层顺序 `Page ground → card(frame) → Chip outline → …`，
`取消` 在 frame 内（19 个孩子里第 18 个），白底在它之后。

修复：`_insert_under_label()` —— 标签属于帧时，把装饰层插进**该帧的
`layoutChildren`**、紧跟标签之前；不属于任何帧时保持旧行为。
`取消` 与白底胶囊在真机导出里都回来了（页分 96.16 → 96.15，等价）。

---

## 5. 七页冷启（`--route physical`，`arbiter=off`，首轮导出）

| 页面 | 帧数 | 基线帧数 | within30 | 基线 | within15 | mean | 基线 mean |
|---|---|---|---|---|---|---|---|
| AtomGit | 9 | 9 | 91.43 | 91.42 | 87.73 | 10.334 | 10.337 |
| FluxWeaver | 7 | 7 | **95.30** | 95.39 | 93.97 | **5.331** | 5.258 |
| inventory | 7 | 7 | 94.14 | 94.14 | 93.31 | 8.332 | 8.330 |
| inventory2 | 13 | 13 | 94.91 | 94.87 | 92.83 | 7.449 | 7.523 |
| marketplace | 6 | 6 | 95.12 | 95.12 | 93.87 | 6.653 | 6.653 |
| review | 5 | 5 | 93.31 | 93.31 | 82.88 | 8.689 | 8.688 |
| wecom-modal | 1 | 1 | 96.15 | 96.16 | 94.97 | 6.211 | 6.200 |
| **均值** | — | — | **94.34** | 94.35 | **91.37** | **7.571** | 7.570 |

**红线**：`replay_pagegraph.py --fresh` → **13/6/10/14/9/3/6**，与交接文档一致。

---

## 6. 顺手量到的一件事：整张表的字都小了 ~25%（下一阶段最高 ROI）

修 FluxWeaver 时量到，同一张表的每一列都比原图窄：

| 单元格 | 原图墨迹宽 | 导出墨迹宽 | 偏差 |
|---|---|---|---|
| 执行时间 `2026-11-01 03:30:00` | 149px | 106px | **−29%** |
| 持续时长 `31649` | 42px | 30px | −29% |
| 启动时间 | 149px | 106px | −29% |
| 表头 `执行时间` | 65px | 58px | −11% |
| `执行结果` JSON 串 | 308px | 256px | −17% |

不是这一列的问题，是 `_align_table_body_fonts` 给的"整表一个比值"系统性偏低
（字号 11.5 而原图约 14）。整表等比放大会一次性抬高三页的表格区，
但那是编译器改动、会动冻结页分数——本轮**没有动**，留作下一阶段第一件事。

---

## 7. 阶段四：`vlm_arbiter` 工具链升级

### 7.1 Schema 与 Prompt 纠偏（消灭无效 `dw` 空转）

* `WorkOrder` 新增 `element_type` / `hint`，`kind` 区分 `text`（单行）与 `text-block`；
* `patch_fields_for(order)`：单行文字只给 `dx/dy/fontSize/letterSpacing/fontWeight`，
  **`dw/dh` 只给** `container / image / rectangle`（按钮、输入框也不给：它们的盒子由字与内边距决定）；
* `parse_round_edits()` 按类型裁剪，`apply_round_edit()` 再挡一道（调用方忘了过滤也不会落到文字上）；
* Prompt 明写："文本框宽高由字自动决定，看着宽窄请改 fontSize 或 letterSpacing"，
  并逐条列出本次哪些工单是单行文字、哪些可以改框。

### 7.2 三个轻工具（仍受四重守卫）

| 工具 | 能落到的节点 | 确定性前置门 |
|---|---|---|
| `setText` | 仅 `text` | **不许删句**：拒绝前缀/后缀截断、拒绝缩短超过 2 字、长文本要求相似度 ≥0.34 |
| `textColor` / `fillColor` | 文字取 `textColor`，其余取 `fillColor` | **必须与原图实测色一致**（≤18/通道），否则只丢这个字段、不废整条补丁 |
| `zIndex` | 任意非帧节点 | 帧容器拒绝（改层序等于重排成员） |

三条门槛都是"上一轮真实 A/B 教出来的"：

* 6 条补丁里 4 条是 `#000000`——模型把"渲染偏细"当成"字色不对"，颜色门直接挡掉；
* 唯一一条被像素门**奖励**的 `setText` 是"把标题后半句删掉"（AtomGit，
  ROI 24.77→22.13）——删字让空白更接近原图浅灰，比错位的字形"更像"；
* `setText` 落在整列容器上（误差带跨 5 行）时会空转——现在会自动转投给框内最大的文本节点。

### 7.3 全图语义巡检提名器

每轮闭环开头多一次调用：`macro_panels`（整页并排 + 上/中/下三段 1:1）→
模型点名最多 3 处硬伤（缺字/重叠/错字/缺图标/对比度）→ 给个大概 bbox →
`sweep_work_orders()` 吸附到节点（重叠优先、同分取**最小**节点、文案类缺陷优先
框内文本节点、已被像素提名的不重复）→ 与像素 Top-K 合并成同一批 2× 标尺裁片 →
同一套定量补丁 + 四重回滚。

---

## 8. 三页真机 A/B

口径：A = `figma_design_initial.json` 原样发射；B = 同一份设计跑 `refine(rounds=2,
sweep 开、新工具开)` 后发射；两侧同脚本 `figma_replay.py --no-roundtrip`、同度量。

| 页面 | A within30 | B within30 | Δ | A mean | B mean | Δmean | 采纳/回滚 | B 闭环耗时 |
|---|---|---|---|---|---|---|---|---|
| FluxWeaver | 95.30 | **95.31** | +0.01 | 5.678 | 5.661 | −0.017 | 2 / 10 | 46.3s |
| AtomGit | 91.42 | **91.43** | +0.01 | 11.320 | 11.312 | −0.008 | 4 / 7 | 47.1s |
| marketplace | 95.12 | 95.12 | 0.00 | 7.920 | 7.918 | −0.002 | 3 / 8 | 50.2s |
| **均值** | 93.95 | **93.95** | **+0.007** | 8.306 | 8.297 | −0.009 | 9 / 25 | 47.9s |

**采纳的 9 条**（全部是数值微调，没有一条语义工具活下来）：

* FluxWeaver：`text:24baf…` `dx+2/fontSize−1`（20.59→20.10）、再 `fontSize−1`（20.07→18.92）；
* AtomGit：`text:e832…` `dx−2/dy+1`（28.30→28.27）、`text:2260…` `dx−2/dy+1`（27.14→27.00）、
  再 `text:e832…` `dx+3/dy−1`（26.21→26.15）、`text:204e…` `dx−1/fontSize−0.8`（25.70→25.64）；
* marketplace：`text:0792…` `dx+3/dy−2/fontWeight−100`（41.68→41.54）、
  `text:9cd7…` `dx−1/letterSpacing+0.5`（29.53→29.06）、
  `text:8f02…` `dx−1/fontWeight−200`（47.85→45.21）。

**回滚的 25 条**按原因：`roi-not-better` 13、`text-buried` 2、`text-edit-not-a-correction` 6、
`refused-no-op` 4。**没有一条触发 `frames-lost` / `new-collision` / `page-worse`**——
帧结构与整页误差全程没被补丁动过。

### 8.1 巡检实际点名的 18 处

| 页面 | 轮 | 点名 |
|---|---|---|
| FluxWeaver | 0 | typo「执行结果列 JSON 截断」· missing-text「输入关键字过滤菜单」· missing-icon「放大镜」 |
| FluxWeaver | 1 | typo「0303**? 少问号」· typo「执行结果缺结尾引号大括号」· missing-text「表头 执行者」 |
| AtomGit | 0 | missing-text「AtomCode 你的云端 AI 编程助手」· typo「15 应为 150多个」· overlap「悬浮框压卡片」 |
| AtomGit | 1 | missing-text「·TSX·4小时前」· typo「LongCat-2.5」· overlap「正文与描述重叠」 |
| marketplace | 0 | missing-text「￥1.16」· overlap「本期好价」· typo「5.8 偏粗偏位」 |
| marketplace | 1 | missing-text「￥1.16」· overlap「官方价…一行看全」· typo「￥20.24 起 ￥23.00」 |

**这些点名大多是真的，但改不动**——原因见 §8.2。

### 8.2 为什么补丁拿不到分：剩下的可见缺陷在**发射端**，不在设计端

以 AtomGit 最典型的一条为例：巡检说"渲染里 `15` 应为 `150多个`，明显截断"。
查 Figma 回读：

```
characters : 从Meta内部走出来的开源设计系统：150多个可访问组件加主题体系，   ← 全文都在
width      : 526      ← 设计里是 655
textAutoResize : null / layoutSizingHorizontal: FIXED
```

设计端文字是完整的，是 Figma 里那个文本框只有 526 宽、按 FIXED 裁掉了尾巴。
同类还有：悬浮提示框里的字（`AtomCode 你的云端 AI 编程助手`）、
`￥1.16`、`·TSX·4小时前`——都是**设计有、导出没有**。

这正是 `probe_target_candidates()` + `figma_replay --roundtrip` 负责的"只在目标端
出现的差异"那一类；本轮的 `setText` 只能改设计里的字，改不动发射宽度，
所以模型越老实回答 `setText`，越容易被 `text-edit-not-a-correction` 挡下。

---

## 9. 下一阶段建议顺序（改自交接文档）

1. **修发射端文本宽度**（最高 ROI）：文本节点按设计宽度落地/开 `textAutoResize`，
   别让 Figma 按 526 裁 655 的内容。三页巡检点名的 18 处里至少 6 处是这一类。
2. **整表字号**（§6）：`_align_table_body_fonts` 现在整表小 25%，等比放大
   一次性抬高 FluxWeaver / inventory / inventory2 三页表格区。
3. 闭环里补"目标端差异"通道：把 `roundtrip` 的 `target-*` 探针并进 `refine`，
   让"设计有、导出没有"也能在闭环里被修（现在它俩是两条互不相通的路）。
4. `arbiter` 仍保持 opt-in：本轮 +0.007 的收益还不值得默认开启的 40~50s。

---

## 10. 产物索引

| 路径 | 内容 |
|---|---|
| `output/_p4_<page>/` | 七页新冷启（`figma/export.png` 为首轮导出） |
| `output/_p4b_FluxWeaver/` | 同一页开 `--ink-roundtrip` 的对照（§2） |
| `output/_p4_wecom-modal/cancel.png` | `取消` 修复后的真机裁片 |
| `output/_p4_FluxWeaver/table_cmp.png` | 表格区原图 / 新导出上下对照 |
| `output/_abA_<page>/` `output/_abB_<page>/` | 三页 A/B 的 design、readback、`figma_compare.png`、`ab_report.json` |
| `output/_ab_summary/B_*.png` | 三页 B 组真机对照图（原图 \| 渲染） |
| `output/_abB_AtomGit/title_cmp.png` | "删句"守卫的证据：原图 / A / B 三行对照 |
