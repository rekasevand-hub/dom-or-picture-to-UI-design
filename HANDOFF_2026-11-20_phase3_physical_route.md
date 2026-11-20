# 交接：阶段三 physical 主链收官（2026-11-20）

> 上一份交接是 `HANDOFF_2026-11-16_phase2_physical_perception.md`（阶段二，OmniParser + OCR +
> CV 三路分权落地）。本文件接在它后面：阶段二之后又做了三件事——**physical 路由成为正式
> 主链**、**行带升格成表**、**OCR 换 RapidOCR**，并跑通了首次真实 VLM 闭环 A/B。
> 变更全在 `feat/visual-fidelity-pass` 分支。

---

## 1. 一句话现状

七页截图全部可以冷启成 Figma 稿，`--route physical`（`arbiter=off`）下均值
**within30 94.35 / within15 91.38 / mean 7.570**，单页 **27s**（上一轮 94.13 / 91.16 / 52s）。
七页冻结红线 **13/6/10/14/9/3/6** 未变，全量单测 **1673 passed / 9 skipped / 0 failed**。

主链已定：`physical 感知 → fixed_canvas_compiler → Figma 发射`。VLM 闭环（`arbiter`）已接通
但默认关闭，实测在两页上收益≈0（安全，无一条补丁改坏画面）。

---

## 2. 复现入口

```bash
PY=C:/Users/lzq/.conda/envs/omni/python.exe      # 生产链路用 omni
cd C:/Users/lzq/WorkBuddy/Worktrees/Figma_auto_agent/feature-precise-agent-router-496e1371

# 依赖服务（两个都不在线时先起）
$PY -m src.app.services.omniparser.omniparser_server \
    --omniparser-root OmniParser/OmniParser-master \
    --som-model-path OmniParser/OmniParser-master/weights/icon_detect/model.pt \
    --caption-model-path OmniParser/OmniParser-master/weights/icon_caption_florence \
    --box-threshold 0.05                       # 127.0.0.1:8000
$PY -m src.app.services.bridge_server          # ws://localhost:8765

# 单页冷启（真机导出）
bash scripts/run_image_pipeline.sh \
  --image output/_fresh_prep/FluxWeaver.png \
  --truth output/_fresh_prep/FluxWeaver.truth.json \
  --out   output/_phys_FluxWeaver

# 七页冻结红线（离线重编译已存 pagegraph，不需要服务，1.5 分钟）
$PY scripts/replay_pagegraph.py --out-suffix _gate

# 首次真实 VLM 闭环 A/B（需要 VLM key，见 §5）
$PY scripts/arbiter_ab.py FluxWeaver --mode A --emit      # 确定性基线
$PY scripts/arbiter_ab.py FluxWeaver --mode B --rounds 2 --emit
```

**Figma 侧**：桌面端 Figma 里运行 `figma_bridge/` 插件，bridge 才连得上；插件加载的是**主检出**
目录（不是 worktree），改完 `code.js` 要在 Figma 里重载一次。

产物（每次冷启）：

| 文件 | 内容 |
|---|---|
| `pipeline/10_pagegraph.json` | 感知计划（结构真源） |
| `pipeline/12_design.json` | 编译器产出（帧、成员、zIndex、字号都在这里） |
| `figma/export.png` | **首轮真机导出**（当前验收口径） |
| `figma_ink_converged/export.png` | 回环校准后导出（**本轮不采用**，见 §6.1） |
| `acceptance.json` | 管线自己的度量（三通道平均、max 通道命中率） |

---

## 3. 验收基线

### 3.1 七页冷启（`--route physical`，`arbiter=off`，首轮导出）

| 页面 | 帧数 | 冻结基线 | within30 | within15 | mean | 耗时 |
|---|---|---|---|---|---|---|
| AtomGit | 9 | 13 | 91.42 | 87.73 | 10.337 | 34s |
| FluxWeaver | 7 | 6 | 95.39 | 94.07 | 5.258 | 24s |
| inventory | 7 | 10 | 94.14 | 93.31 | 8.330 | 33s |
| inventory2 | 13 | 14 | 94.87 | 92.80 | 7.523 | 26s |
| marketplace | 6 | 9 | 95.12 | 93.87 | 6.653 | 27s |
| review | 5 | 3 | 93.31 | 82.88 | 8.688 | 20s |
| wecom-modal | 1 | 6 | 96.16 | 94.98 | 6.200 | 25s |
| **均值** | — | — | **94.35** | **91.38** | **7.570** | **27s** |

**两个"帧数"含义不同，别混**：

* **冻结基线 13/6/10/14/9/3/6** 是 `replay_pagegraph.py` 在**已存 pagegraph** 上重编译的
  结果，用来守编译器回归。它必须一动不动，这是硬红线。
* 上表"帧数"是**全链路冷启**（新 OCR → 新 pagegraph → 编译器）的结果。它随感知变准而变，
  不是回归指标。

冷启帧数下降的三页（AtomGit 13→9、inventory 10→7、wecom 6→1）原因同一类：RapidOCR 读出的
行更完整，原来能成帧的卡片多出一个"单成员子容器"，被 `_has_nested_container` 挡住，结构变平。
像素三项都升了，所以按"像素优先"收在这里。要继续追见 §6.3。

### 3.2 测试

`$PY -m pytest tests/ -q` → **1673 passed / 9 skipped**（213 个用例文件）。
9 条 skip 全是"依赖 `output/` 下实验产物"的 P5/axure 探针，产物不在检出里时跳过并写明原因。

---

## 4. 代码地图（本轮增改）

### 4.1 感知

| 文件 | 职责 |
|---|---|
| `src/app/services/structure/physical_perception.py` | 三路分权：CV 容器 / OCR 文字 / OmniParser 图标；行带分组、**行带升格成表**、分隔线 |
| `src/app/services/structure/image_contract.py` | `extract_ocr_observations()`，`OCR_BACKEND=rapidocr\|easyocr`（默认 rapidocr，缺依赖自动回退） |
| `src/app/services/structure/line_rulers.py` | 尺线检测（表格列线、行带共用） |
| `src/app/services/structure/router.py` | `physical` 进合法路由；`precise_agent` 用 `CVProvider(strict=True)`，不回退 |

### 4.2 编译器（`src/app/services/structure/fidelity/`）

| 函数 / 文件 | 干什么 |
|---|---|
| `attach_layout_frames` | 成帧：每个叶子归"装得下它的最小容器"，一个父至少要两个成员 |
| `_has_nested_container` | 子容器未成帧则挡父帧；**透明单成员层豁免**（否则 wecom 弹窗 0 帧） |
| `_table_groups`（text_calibration） | 结构分组：表体 = `role: table` 的全部 text 子元素；表头带 = `role: table-header` 的子元素 |
| `_align_table_body_fonts` | 整表一个比值（墨迹宽比中位数 × 正文尺寸中位数），组内跳过逐格收敛 |
| `_adopt_label_plates` | 标签底板归进那颗字所在的帧（`刷新` 蓝底白字靠这条） |
| `_fit_locked_text_geometry` | 行内三守卫：同句碎片统一字号 / 邻接撞字收敛 / 容器内右溢出收敛；**帧锁定后只改 fontSize** |
| `TEXT_SNAP_MAX_SHIFT` | OCR 吸附与 `_promote_ocr_text` 的位移上限，挡住"同名同行的另一处"被搬走 |
| `alpha_matte.py` / `post_frame_align.py` | 图标透明通道、帧后对齐 |

### 4.3 仲裁（`vlm_arbiter.py`）

`refine(design, reference, rendered, ...)`：提名 → 10px 刻度裁片 → VLM 回补丁 → 四重守卫。
守卫顺序：`apply_quantitative` 可行性（frozen 只锁帧容器）→ 帧数不减 → 局部 ROI 真降
（`ROI_MIN_GAIN=0.02`）→ 整页误差不涨。任一条不过即回滚并写日志。

### 4.4 脚本

`scripts/arbiter_ab.py`（A/B 发射+度量）、`replay_pagegraph.py`（红线）、`probe_*`（离线定位）、
`run_image_pipeline.sh`（默认 physical）、`figma_bridge/code.js`（支持 `textAlign=right`）。

---

## 5. 改之前必须知道的六条

1. **零页面特调**。所有判据都用结构/几何/像素可表述，不许出现页面名或坐标常量。评审会看这个。
2. **红线是硬约束**。任何编译器改动都要跑 `replay_pagegraph.py`，结果必须是 13/6/10/14/9/3/6。
   改动前后还要比冻结页分数（`_gate*` 产物），波动应 ≤0.03。
3. **帧锁定之后只许改 `fontSize`**。行内三守卫之所以安全，就是因为它不碰 x/y/width、
   不碰 `layoutChildren`、不碰 zIndex。想改框，得走成帧之前的阶段。
4. **度量口径固定**：三通道平均误差，`max` 通道 ≤30/≤15 记为命中。粒度用 `figma/export.png`
   （首轮导出），**不要混用** `figma_ink_converged/`。
5. **VLM 默认关**（`ARBITER_MAX_ROUNDS=1`）。开它只在 A/B 里，且必须两边同脚本同度量。
6. **`output/` 与 `.workbuddy/` 不入库**。金标截图在 `samples/image_screenshots/`；
   `samples/base/` 是等价副本，已忽略。

---

## 6. 已知缺口（按 ROI 排序）

### 6.1 Figma 插件回调失效 + ink 收敛反而更差（最该先处理）

本轮冷启全部只到 `figma/export.png`：导出后的回环校准报
`Attempted to invoke callback with invalid id`，需要**在 Figma 里重载一次插件**。

顺带量到一件事：**首轮导出在四页上都优于收敛后导出**——FluxWeaver 95.39 vs 95.09、
inventory 94.14 vs 94.09、review 93.31 vs 92.99、wecom 96.16 vs 95.86。
RapidOCR 的字框更准之后，墨迹收敛迭代变成了过冲。**建议直接关掉这一轮迭代**
（`--no-roundtrip` 或停用该策略），白捡 +0.1~0.3，并让口径只剩一个。

### 6.2 VLM 闭环收益≈0，且一半补丁在空转

首次真实 A/B（`qwen3-vl-plus`，rounds=2）：

| 页面 | A | B |
|---|---|---|
| FluxWeaver | 95.22 / 5.711 | 95.22 / 5.711（出图**逐像素相同**） |
| AtomGit | 90.89 / 12.020 | 90.90 / 12.014（采纳 1 条 `dx=-10`） |

8 条补丁里 5 条是 `dw`，全部 `roi-not-better` 且 ROI 一模一样（`25.84→25.84`）——文本是自动
宽度，改框不改墨。**下一阶段的第一件事**：补丁解析阶段按 `kind` 过滤字段，单行 `text` 只收
`dx / dy / fontSize / letterSpacing`，`dw / dh` 只给 `container / image / rectangle`。
（已记在 `NOTES` §22.4，本轮未动代码。）

### 6.3 冷启帧数变平（AtomGit 9 / inventory 7 / wecom 1）

像素更好但结构更平。要继续追：对目标页打印 `_has_nested_container` 的实际阻塞子项
（`members` 里的单成员容器），逐个判断"它本来能不能成帧"。这活有 ROI 但要小心——
把不透明单成员容器也豁免，会让父帧吞掉按钮底板（实测 inventory 10→8、AtomGit 13→12）。

### 6.4 其它遗留

* `复制` 灰底：`_recover_text_backdrops` 对紧贴文字的标签用 `_frame_colour(inset=2)`，
  采到的是字形抗锯齿混色而非白色面。改采样源会影响所有页底板，未动。
* `review` ink 75（七页最高）：整页只有一句 40px 大标题 + 少量正文，字形宽度差被放大。
  与 §6.2 同一个根因——真正拉低分数的是字宽，不是坐标。
* 表格首列 `#` 与 1..5：EasyOCR 读不出单个数字；RapidOCR 后**尚未逐格复核**这项。

---

## 7. 下一阶段（VLM Loop 升级）建议顺序

1. 关掉 ink 收敛迭代，统一到首轮导出口径（§6.1），并把插件重载后补一次真机验证。
2. 补丁字段按 `kind` 过滤（§6.2），让每轮少一半无效往返。
3. 给闭环加**字宽自由度**：`letterSpacing` / 字重 / 字体族。当前只有坐标与字号，而分数
   瓶颈在字宽——这是唯一可能真涨分的方向。
4. 全图语义巡检（不是逐块补丁）：整页丢元素、错位区块、颜色反转这类，现在的 ROI 局部
   度量看不见。
5. 之后再决定是否把 `arbiter` 从 opt-in 变默认。

---

## 8. 文档索引

| 文件 | 内容 |
|---|---|
| `HANDOFF_2026-11-16_phase2_physical_perception.md` | 阶段二：三路分权感知的起点与硬约束 |
| `NOTES_2026-11-16_dom_to_figma_swarm_reuse.md` | 全过程实测笔记（§21 表格 / §22 A-B / §23 七页收官 / §24 OCR + 守卫） |
| `DESIGN_2026-11-16_ruler_grid.md` | 尺线网格设计 |
| `.workbuddy/memory/2026-11-19.md` | 逐日工作日志（本机，不入库） |
