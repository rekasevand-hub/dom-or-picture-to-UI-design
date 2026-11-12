# Image → Figma · 交接文档（2026-11-12）

**日期：** 2026-11-11 下午 — 2026-11-12 上午
**性质：** 第 4 族 holdout 的逐项收口（目标 / 完成 / 文件 / 明细 / 测试 / 遗留 / 下一步 / 禁改）
**前置文档：**
- `20261111image to Figma-handoff.md`（11-11 下午单页交接）
- `NATIVE_TEXT_GATE_EVIDENCE_2026-11-11.md`（**只读取证**：金稿旁路、门禁量错目录、三处退化测量）
- `NATIVE_TEXT_GATE_INSTRUMENT_FIX_2026-11-11.md`（门禁仪器修正明细）
- `HOLDOUT_CONTENT_REVIEW_2026-11-11.md`（**主文档**：§8 感知、§9 装饰层、§10 控制调色板、§12 假边框、§13 字号、§14 字重）

**本次提交：**

| commit | 内容 |
|---|---|
| `ebf58bf` | fix(calibration): 关掉金稿旁路，`move` 需仲裁 agreement |
| `02a32b3` | fix(acceptance): 原生文字改在**发射节点框**上量 |
| `9851580` | fix(structure): 容器外元素不再触发 `KeyError: 'container'` |
| `395c681` | docs: 三份证据文档 |
| `3256ecf` | feat(fidelity): 装饰层 / 字号宽度通道 / 字重笔画比（13 files, +2874/−108） |

**运行环境：** `C:/Users/lzq/.conda/envs/omni/python.exe`
**Bridge：** `python -m src.app.services.bridge_server`（ws://localhost:8765，插件自动重连）。**交付时已关闭**，下次跑 Figma 写入前需重新启动并重载插件。

---

## 0. 速览

四组终态（`--acceptance-policy 2.1`，`--reuse-prepared`，同一份冻结感知）：

| 组 | within30 | critical | native |
|---|---|---|---|
| dark-card-grid | 94.71 | 27/27 | 1/30 |
| light-form | 92.20 | 24/24 | 30/33 |
| light-table | **96.33** | 30/30 | 38/59 |
| **holdout #4**（内容审核页） | **94.46**（起点 89.67） | 18/18 | 4/18（起点 1/18） |

本轮做了四件事，都落在 holdout 上，三族全部不回归：

| # | 事情 | 关键数字 |
|---|---|---|
| 1 | **感知：段落漏读 + 整段单行** | critical 17/18 → **18/18**，右栏段落由一行巨型字变两行 22.86 |
| 2 | **装饰层** | 卡片底色/边框/圆角/进度条/竖条/页面底色，within30 89.67 → **94.46** |
| 3 | **字号：宽度通道** | 同栏 7 个 label 字号 16.25–20.75 → **18.25–20**，size 类失败 5 → 1 |
| 4 | **字重：笔画比** | 5 个元素拿到参考笔画，**8 个 owner 现在只差 position** |

---

## 1. 本次任务的目标

用户指令按时间序：读交接文档总结现状 → 起 bridge 做**只读**取证 → 质疑「这是盯着黄金稿反向修代码吗」→ 问 VLM 仲裁器能否解决 → 「按 1→2 动手」（关旁路 + 修口径）→ 跑全量对照 → 查左偏 → 提供第 4 族 holdout 原图 → 「先不提交，接着做第 3 项」→ 「接着做 §6.3」→ 「接着查这 3px」→ 「开始第 5 项」→ 「接着做第 6 项」。

归成两句：

1. **先证明门禁本身可信**。前三族的高分若来自「金稿坐标」或「量错地方」，那么拿它当泛化证据是自欺。所以第一件事是只读取证，把门禁和校准里所有「信了不该信的东西」的地方找出来。
2. **再用唯一的干净考卷（第 4 族）逐项收口**。按 `HOLDOUT_CONTENT_REVIEW` §7 的性价比排序做：感知 → 装饰层 → 字号/字重。每一件都必须三族隔离验证，不许为这一族加 `if family == ...`。

---

## 2. 已经完成的内容

### 2.1 仪器与旁路：先拆掉三个「假高分」来源 ✅

只读探针（`scripts/p1_native_text_gate_probe.py`）暴露了三件事，全部修掉：

| 问题 | 后果 | 修法 |
|---|---|---|
| 门禁读 `figma/`，实际产物在 `figma_ink_converged/` | 量的是未校准的渲染 | 探针与门禁都指向收敛后的目录 |
| 校准里按 `benchmark_families/<family>` 路径嗅探，`_gold_positions()` 直接取 `gold_tree.json` 的 bbox | **金稿坐标进了设计**，跑基准的路径普通截图永远走不到 | 整段删除；`move` 类仲裁必须 `agreement is True` |
| 门禁在**元素框**上量墨迹，不是发射出去的节点框 | 22px 的框量不出 24px 的字，指标失真 | 改在 readback 节点框上量（+4px halo） |

旁路关掉后 4/4 局部更差（`展开查询` 48% → 8.3%），light-table 反而 **+0.10**——说明原先那一批「校准」是在拟合金稿，不是在拟合图。

### 2.2 第 1 项 感知：段落漏读 + 整段单行 ✅

`critical 17/18`，缺的是整段正文的前两行。三层证据证明**不是 VLM 的锅**：

1. VLM 返回的是完整整段（`.vision_cache/86a44964….json`，`bbox [238,500,1075,65]`，文本一字不差）；
2. EasyOCR 也读到了（第 1 行 `y=499`、第 2 行 `处理状态。` `y=545`）；
3. 丢在 `merge_ocr_candidates` 的两条规则互相踩：第 1 行命中 `already-covered` 被跳过，第 2 行命中 `overlong` 把 grounding 的整段删掉，**而唯一能重建它的那一行已经被跳过**。

修法是一张**分工表**：文本内容归 VLM（OCR 有标点错、断词 `访问环`/`境`），行几何归 OCR 行框（VLM 只吐整段框）。落地为 `_attach_paragraph_line_groups`：若一个元素被 ≥2 条上下堆叠的 OCR 行覆盖、且拼起来与元素文本相似度 ≥0.8，则保留元素文本、把行框挂成 `measuredLines`。并排的框（表格单元格）判为 `columns`，仍走精确替换。

`measuredLines` 要穿过三处字段白名单（`inventory` → `som/annotate` → `fixed_canvas_compiler`），字号按行框反解（正文 61.75 → 25.71、右栏 56 → 22.86），不再把整块高度当一行。

### 2.3 第 3 项 装饰层 ✅

缺的不是「发射」，是「形状」这一类对象根本没有。三条路试过，只有一条站得住：

| 路 | 为什么不行 |
|---|---|
| 颜色洪泛 | 白卡与白页同色，没有边界 |
| 边框线检测 | 参考图里多数卡片无边框 |
| 背景差分 | 参考图只有一张，没有「无元素」底图 |

站得住的是**量化颜色 + 连通分量**（`step=4` 量化后取 4-连通域）：白卡因为与页面之间有 1-2 个色阶差和圆角阴影，量化后落进不同桶。落地为 `decoration_pixels.py`：`panels`（面板）、`solid_blocks`（实心块/进度条/竖条）、`corner_radius`（按角点覆盖率反解）、`border_of`（三边同色才算边框）。

页面底色踩过一个坑：用「图像主色」的众数会把 dark 从 `#1a1917` 拉成 `#100808`（within30 −0.51）。改成「元素之外剩余区域的截尾中位数（10–90%）」，且**只在近白画布（min channel ≥230）生效**——深色画布自己就是对的。

### 2.4 §6.3 控制调色板：不是配色错，是 fill/ink 互换 ✅

36 个控件里 21 个的「边框」是 `_contrast_border_color()` 编出来的（`#c8d1de` / `#64748b`）。`_sample_border_color()` 找不到边框时返回默认值，于是**每个控件都被画上一条边框**。

修法 `control_palette()`：从参考像素判定控件是否真有自有底色（≥0.55 占比），无底色则 `fillColor` 透明 + `borderWidth 0`；边框交给 `border_of()`——距边缘 1px 与 0px 两条线都探、至少三边同色、且不等于外部环色。

### 2.5 §12 `社区` 的 3px：一条凭空生成的边框 ✅

`控制台` 修好后，同帧的 `社区` 从 native pass 掉到 fail（`dx=dy=3`）。第一反应「去掉边框后文字框定位变了」是**错的**：设计元素、Figma 节点、字号三者 before/after 完全相同，变的只有导出墨迹 `(1205,42,59,29)` → `(1207,45,54,26)`。

结论：before 的墨迹**根本不是文字**，是那条边框——它 59×29，正好等于参考文字的 60×29，于是 position/size 全对、`dx=dy=0`。**它的 pass 是假的。**

### 2.6 第 5 项 字号：宽度是精细仪表 ✅

`ink-convergence` 只用**墨迹高度**做闭环。18px 字的墨迹高只有 17–19px，±1px 就是 ±6%，与被校正的误差同量级；而同一行的墨迹宽是 72–140px，1px 只有 1.4%。证据是同栏四个并列 label 的字号分散在 `16.25 / 18 / 19.5 / 20.75`，而它们的参考墨迹高都只有 17–18。

宽度通道的难点不在公式，在**参考侧的框不是紧框**：`ink_bbox` 是元素框（`请求编号` 那一格 328px，四个字只占 72），还越界到下一列并混进浅灰分隔线。第一版直接用它，字号被放大到 24.5。

`_text_run_width()` 三道闸：阈值 60（单元格浅灰条离页面只有 51，最浅的标签 `#818790` 离页面 122）、先去掉贯穿窗口的 ≤2px 细带、只取**最左**一段（标签在框内左对齐）。主循环再加三条保护：只对单行用宽度；宽度比超出 `[0.55, 1.8]` 视为混入邻元素；**宽高方向相反则跳过**（`系统运行正常` 是源字形更宽且更矮，属字族差异，按任一方向缩放都让另一个更差）。

七个 label 收成 18.25–20，size 类失败 5 → 1。

### 2.7 第 6 项 字重：笔画比，不是面积 ✅

§13.5 猜「控件底色不对」——**猜错了**。实测按钮填充参考 `(255,254,255)`、渲染 `(252,252,252)`，差 3 个色阶。之前的 `(153,176,228)` 来自对文字窗口**全部像素**取中位数，而 72×18 的窗口四成是笔画。按窗口边框取就是白的。

面积也不能当判据：`请求编号` 参考墨迹面积比渲染多 **26%**，但笔画完全一样粗，差的是文字深浅。改用 `2·面积/周长`——一笔宽 `w` 长 `L`，面积 `wL`、周长 `2L`，商就是 `w`；字形不是一笔，但同一段文字在两个字重下**骨架相同**，比值就是字重比。

字重独立成组 `font-tone`（产物 `figma_font_tone`），排在 `ink-convergence` 之后——字号和字重都改墨迹，同一帧上量两个会互相重复计数。步进 `(笔画比−1)/(0.44/300)`，0.44/300 是实测：Noto Sans SC 的 stem 400 是 0.055 em、700 是 0.078 em。

**拉丁加粗会变宽，CJK 不会**：`处理进度` 400→700 节点宽 78→78；`REQ-OIBFZVUES` 400 时 140px，推到 800 变 184px 而参考 172，亲手制造了一个 size fail。所以拉丁步进上限收到 300（一次一档）。

---

## 3. 已修改的文件

### 新增（5）

| 文件 | 行数 | 作用 |
|---|---|---|
| `src/app/services/structure/fidelity/decoration_pixels.py` | 858 | `ReferencePixels`：量化颜色 + 连通分量，产出面板/实心块/圆角/边框/页面底色 |
| `scripts/p1_native_text_gate_probe.py` | 648 | 只读门禁探针（`--symmetric` / `--recompute`） |
| `tests/v2/test_decoration_pixels.py` | 201 | 10 例 |
| `tests/v2/test_weight_convergence.py` | 175 | 5 例 |
| `tests/v2/test_graph_assign_ids.py` | 33 | 容器外元素 |

### 修改（9）

| 文件 | 增/删 |
|---|---|
| `src/app/services/structure/fidelity/text_calibration.py` | +478 / −75 |
| `src/app/services/structure/image_contract.py` | +292 / −13 |
| `src/app/services/evidence/native_text_quality.py` | +220 / −18 |
| `src/app/services/structure/fidelity/fixed_canvas_compiler.py` | +134 / −11 |
| `src/app/services/structure/fidelity/calibration_strategies.py` | +38 / −12 |
| `src/app/services/structure/fidelity/inventory.py` | +22 / −15 |
| `src/app/services/structure/graph.py` | +10 / −3 |
| `src/app/services/som/annotate.py` | +5 |
| `scripts/conflict_adjudicator.py` | +9 / −51 |

### 文档（4 新增 + 1 更新）

- 新增 `NATIVE_TEXT_GATE_EVIDENCE_2026-11-11.md`、`NATIVE_TEXT_GATE_INSTRUMENT_FIX_2026-11-11.md`、`HOLDOUT_CONTENT_REVIEW_2026-11-11.md`（+454 行，含 §8–§14）、本文件
- 更新 `20261111image to Figma-handoff.md`

### 测试（3 新增 + 3 修改）

`tests/v2/test_adjudicated_conflicts.py`（4 例）、`tests/v2/test_native_text_quality.py`（+189）、`tests/v2/test_grounding_text_calibration.py`（+62）、`tests/v2/test_image_contract.py`（+151）、`tests/v2/test_ink_convergence_band.py`（+63）、`tests/v2/test_fixed_canvas_compiler.py`（+43 改）

---

## 4. 每个文件修改了什么

### `decoration_pixels.py`（新）

`ReferencePixels` 类，全部从参考图像素读：`page_color`（元素外剩余区域的截尾中位数，仅近白画布）、`ring_color`（元素外环色）、`mode_of`、`corner_radius`（角点覆盖率）、`panels`（面板）、`solid_blocks`（实心块）、`border_of`（边框判定）。模块级 `control_palette`（控件填充/描边）、`page_background`、`panel_decorations`、`solid_decorations`、`hex_to_rgb`、`color_gap`、`_covers_content`、`_overlap_ratio`。

面板去重必须**双向**判断重叠率——单向会把嵌套卡片当重复丢掉。

### `text_calibration.py`

| 位置 | 改动 |
|---|---|
| `apply_adjudicated_conflicts` | `move` 类决策要求 `agreement is True`，否则不落 |
| `_render_ink_bbox` | `inset = 0 if element_type == "text" else 3`——控件框内缩 3px 再量，文字不缩 |
| `_ink_extent` | 由 `_ink_height` 拆出，同时返回宽高 |
| `_text_run_width` | 新增。阈值 60 + 去贯穿细带 + 取最左段 + 用渲染墨迹宽 2.4 倍封顶 |
| `_stroke_width` | 新增。`2·面积/周长`，掩码阈值 40 |
| `calibrate_ink_convergence_from_render` | 增加宽度通道：单行 + 宽度够长 + 宽高不冲突时用宽度比；冲突则跳过；`type == "text"` 放宽成「有 text」，控件标签一并纳入 |
| `calibrate_weight_from_render` | 新增。笔画比 → wght，`(ratio−1)/(0.44/300)`，两侧高度差 >15% 跳过，拉丁步进上限 300 |
| `_weight_value` / `_latin_dominant` | 新增辅助 |

### `image_contract.py`

新增 `_attach_paragraph_line_groups`（段落行框分组主逻辑）、`_attach_measured_lines`、`_line_arrangement`（判 `lines` / `columns`）、`_split_text_across_lines`、`_split_text_by_kept_counts`、`_kept_candidate_char`。`merge_ocr_candidates` 里段落分支优先于 `already-covered` / `overlong` 两条老规则；`build_image_design` 把 `measuredLines` 透传给设计元素。

### `native_text_quality.py`

- `_compact_gate_text`：门禁比对文本前先做空白归一（去空白身份）
- `_text_node_boxes` / `_select_node_box`：在**发射节点框**上量（+4px），不再用元素框
- `_text_ink_mask`：≤2px 厚且覆盖 80% 的跨框线才抑制（照抄 80% 规则会吃掉密集标签行）
- `unverified` 单列：无墨迹证据的 owner 不再阻塞门禁，但也不计入 pass

### `fixed_canvas_compiler.py`

- `_control_element` 接入 `control_palette`（≥0.55 占比判定自有底色；无底色 → `transparent` + `borderWidth 0`）、`reference_pixels.border_of`
- 装饰层接线：`panel_decorations` / `solid_decorations` 发射为 `rectangle`
- `page_background` 替换原「图像主色」众数
- `measuredLines` 透传：按文本重挂行框，字号按 `line_box / line_height_factor` 反解

### `inventory.py` / `som/annotate.py`

`measuredLines` 穿过字段白名单（清单 → SOM），此前被静默吃掉。

### `calibration_strategies.py`

- 删掉 `benchmark_families` 路径嗅探（判据改成只读 `<run>/conflict_adjudication/decisions.json`）
- 新增 `_weight_convergence` runner 与 `font-tone` 组（`render_suffix="figma_font_tone"`，`always=True`，无调整时不渲染）

### `graph.py`

孤儿元素 `container=None`，取值改 `.get`——修 `KeyError: 'container'`（第一次跑 holdout 直接崩在这里）。

### `conflict_adjudicator.py`

删 `_gold_positions()`：不再从 `gold_tree.json` 取 bbox 写进裁决。

---

## 5. 已运行的测试及结果

**单测：** `tests/v2` **1510 passed / 8 failed**（88 s）。

8 个失败全部是既有环境项，与本轮无关：4 个 axure manifest 的冻结输入哈希、4 个 p5 探针（需要真实协作环境）。改动前基线是 1505 passed / 8 failed，本轮净增 5 条。

新增/扩写的测试：

| 文件 | 覆盖 |
|---|---|
| `test_weight_convergence.py`（新，5 例） | 笔画粗→加粗、相同→不动、尺寸不符→跳过、已粗→900 上限、拉丁→一档 |
| `test_decoration_pixels.py`（新，10 例） | 面板/实心块/圆角/边框/页面底色/双向去重 |
| `test_ink_convergence_band.py`（+4 例） | 宽度通道生效、宽高反向跳过、多行保留高度通道、原死区/钳位不变 |
| `test_image_contract.py`（+151 行） | 段落行框分组、columns 判定、相似度阈值 |
| `test_native_text_quality.py`（+189 行） | 节点框测量、空白归一、跨框线抑制、unverified 单列 |
| `test_adjudicated_conflicts.py`（新，4 例） | 无 decisions 文件不生效、move 需 agreement |
| `test_graph_assign_ids.py`（新） | 容器外元素不崩 |

**端到端**（`--acceptance-policy 2.1 --reuse-prepared`，同一份冻结感知）：

| 组 | within30 | 变化 | native | 变化 |
|---|---|---|---|---|
| dark-card-grid | 94.71 | +0.09 | 1/30 | 不变 |
| light-form | 92.20 | −0.02 | 30/33 | +1 |
| light-table | 96.33 | +0.07 | 38/59 | +3 |
| holdout #4 | 94.46 | **+4.79**（起点 89.67） | 4/18 | **+3** |

`critical` 四组全满（27/27、24/24、30/30、18/18）。ruff 对全部改动文件通过。

---

## 6. 当前仍存在的问题

1. **position 是 holdout 唯一的批量障碍。** 14 个 native fail 里 **8 个只差 position**：`请求编号` −5、`处理进度` −5、`系统正在对当前内容进行安全审核` −5、`CONTENT REVIEW CENTER` −5、`© 2026 …` −4、`内容完整性检查` +2、`风险特征识别` +2、`44` −2。修好即可 4/18 → 12/18。
2. **`检查状态` coverage 0.59。** 700 已是 Noto Sans SC 能给的最近档位；再往上 CJK advance 不变、面积只多 8–10%，补不上 0.16 的差。判断是字族更饱满，不用字号/字重追。
3. **`内容正在审核中` edgeF1 0.24（96pt 大标题）。** 尺寸位置都对、面积差 15%，笔画比只有 1.10（未达 1.22 阈值）。最佳平移 (−3,−3) 也只能把 F1 抬到 0.41，说明不是对齐问题。
4. **footer chrome 0.31（阈值 0.05）。** 该区域四个 label 的字节全部对上了，坏像素集中在底部一条与文字无关的装饰带上，未定位。
5. **dark 的 native 1/30** 是四组最差：coverage 29 个不达标、position 37、size 22。深色底上浅色文字的掩码行为与浅色页不同，`stroke`/`coverage` 两个量具在那一族还没标定。
6. **light-table `刘治强` 回归**：字重轮里 coverage 0.96 → 0.68，它本身不在调整名单里，怀疑是同帧相邻元素的渲染顺序变化。
7. **按钮描边仍缺**：`检查状态` 参考有 1px `#dde3ea`，渲染无。`border_of()` 在这里没判出来，属 §12.3 判据的覆盖问题。

---

## 7. 下一步应该从哪里继续

**第 7 项：文字定位（dx 两簇）。** 这是当前性价比最高的一步——8 个 owner 只差它，一次修好把 holdout 从 4/18 拉到 12/18。

已知线索：

- `dx` 分两簇：左区（x≈234–273）**−5**，右区（x≈1294）**+2**，两点连线的零点在 x≈990。
- 门槛是 2px，所以这不是「差一点」，是**系统性的口径差**：元素框含 padding，而文本从框左上角起排。
- 先量三件事：①每个 owner 的 `measureBBox.x` 与 `referenceInkBBox.x` 之差（左侧 padding）；②渲染节点 `x` 与墨迹左边缘之差（Figma 的行内留白）；③同一容器内这些差是否恒定——若是，就是一个 per-container 的 padding 常量，不是逐元素修。

**不要**用「把 x 平移 5px」的方式修：那会把右区从 +2 变成 −3，两簇都会 fail。

第 8 项之后可以考虑：footer 装饰带（第 4 条遗留）、dark 的掩码标定（第 5 条）。

---

## 8. 哪些内容禁止再次修改

| 禁改项 | 原因 |
|---|---|
| **金稿旁路**（`benchmark_families` 路径嗅探、`_gold_positions()`） | 它让基准路径吃到普通截图走不到的数据。重新引入等于让泛化结论失效。裁决数据必须随 run 走（`<run>/conflict_adjudication/decisions.json`） |
| **门禁阈值**：position 2px、size `max(3, 3%)`、coverage 0.75–1.35、edgeF1 0.55 | 这组数是用金稿自身标定的（`gold_edge_f1_median`：light-form 0.9688、dark 0.6785）。放宽容差等于把门禁关掉 |
| **`ink-convergence` 高度通道的死区 0.85–1.175 与钳位 0.7–1.5** | 2026-11-10 两次实测：收紧到 ±0.05 让 light-table 94.07 → 93.33；丢掉钳位再掉到 93.44。宽度通道是**新增**，不是替换 |
| **用墨迹面积做字重判据** | 面积同时被文字颜色影响（`请求编号` mass 1.26 而 stroke 1.02）。只有 `2·面积/周长` 能分开「粗」和「深」 |
| **`_text_run_width` 的阈值 60 与「取最左段」** | 40 会把单元格 204 的浅灰条当成墨迹；取全段会把下一列的字算进来 |
| **`page_background` 只在近白画布生效** | 众数方案把 dark 从 `#1a1917` 拉成 `#100808`，within30 直接 −0.51 |
| **面板去重的双向重叠判断** | 单向判断会把嵌套卡片当重复丢掉 |
| **`_INK_HEIGHT_EM`（cjk 0.90 / latin 0.72）与 `_ADVANCE_EM`（cjk 1.0）** | 这两个是字体度量，用来判断「这个切法能不能同时解释宽度和高度」，不参与几何输出。改它们等于改判据语义 |
| **为第 4 族加任何 `if family == ...` 或手写常量** | 它是唯一的干净考卷。一旦被调过就失去意义，之后所有「泛化」都是自证 |
| **`native_text_quality` 的 `unverified` 单列** | 无墨迹证据的 owner 不能被算作 pass，也不能重新变成阻塞项 |
