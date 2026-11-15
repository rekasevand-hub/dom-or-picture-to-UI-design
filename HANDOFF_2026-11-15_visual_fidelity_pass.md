# HANDOFF — 七样本呈现层像素级收口（feat/visual-fidelity-pass）

**日期：** 2026-11-15
**分支：** `feat/visual-fidelity-pass`（基于 `21a62c2`，即 `feat/image-to-figma-v2` 顶端）
**本分支提交：** `338b346` → `343e393` → `b4dd527` → `6483970`，外加本次交接的语料/重放提交
**运行环境：** `C:/Users/lzq/.conda/envs/omni/python.exe`（numpy 1.26 / cv2 4.10 / pytest 8.3）
**状态：** 可交接。七样本 `written == accepted`，帧数 9/6/9/7/3/6/11 全在
**下一步优先项：** 先补渲染端 CJK 字体（Noto Sans SC），不要再往呈现层加规则

---

## 1. 当前结论

七张基准截图走的是同一条确定性链路：`PageGraph + ocr_supplement + 原图`
→ 场景计划（沿用图里那份，不重建）→ 定宽编译（像素采样、文本/表格修整、
区域恢复）→ `prototype.svg` → `render.png`。本轮把"呈现层失真"从**逐条特判**
改成了**可度量的统一规则**，并建立了量化看板。

像素对齐（`within30` = 最差通道差 ≤30 的像素占比，同画布不缩放）：

| 样本 | 起点 | 现在 | within15 | mean err | 帧数下限 |
|---|---|---|---|---|---|
| AtomGit | 87.70 | **92.36** | 90.03 | 10.59 | 9 |
| FluxWeaver | 95.65 | **96.11** | 95.68 | 5.89 | 6 |
| inventory | 90.75 | **93.12** | 91.45 | 12.01 | 9 |
| inventory2 | 90.24 | **93.40** | 91.60 | 10.98 | 11 |
| marketplace | 94.53 | **96.00** | 94.83 | 9.19 | 7 |
| review | 90.84 | **95.08** | 74.20 | 13.59 | 3 |
| wecom-modal | 96.03 | **96.36** | 95.32 | 6.47 | 6 |
| **均值** | **92.25** | **94.35** | — | — | — |

四张 ≥95。这张表来自 2026-11-15 01:51 的那次运行（与 `6483970` 同时），
原样抄在这里是因为**其中五张的原图已经丢了**（见第 6 节），数值暂时无法重算。

不能声明的事：

- 不能声明七样本全部到 95%。AtomGit 92.36 / inventory 93.12 / inventory2 93.40
  仍在 95 以下，且剩余误差的主体**不是几何错位**（见第 5 节）。
- 不能把这一轮的数字当成"渲染端一致"。渲染端缺 Noto Sans SC，CJK 走系统回退
  字体，文本框内部逐字形有差；换字体后指标会变，需要重跑一遍基线。
- 不能把 `--no-patches` 的两遍渲染当成一次跑完。补丁是第二遍的产物，关掉它
  指标会掉（见第 3 节的执行顺序）。
- 五张丢图的样本不能重放、不能重测：`scripts/replay_pagegraph.py` 现在会明确
  报 `MissingScreenshot` 并跳过，测试相应 skip，这不是"通过"。

---

## 2. 代码落点

主战场只有一个文件，改动按"规则"而不是按"截图"组织：

| 文件 | 职责 |
|---|---|
| `src/app/services/structure/fidelity/fixed_canvas_compiler.py` | 编译主链 + 全部像素恢复/清理/成帧 pass（109 个私有函数） |
| `src/app/services/structure/fidelity/style_resolver.py` | 字重改由**墨迹笔画宽**判定（`_stroke_thickness` / `_weight_for`） |
| `src/app/services/structure/image_contract.py` | `build_image_design(..., ocr_observations, residual_regions)` 透传 |
| `src/app/agents/precise_agent.py` | `_design_and_render(..., ocr_observations)` |
| `scripts/replay_pagegraph.py` | 离线重放：直接吃 PageGraph + ocr + 原图，**不重建 plan** |
| `scripts/sample_sources.py` | 原图定位（记录路径 → `samples/image_screenshots/<tag>.*`） |
| `scripts/visual_alignment.py` | `within30/within15/mean_error` + `diff.png` + 残余区域建议 |
| `scripts/rebuild_frozen_samples.py` | 不需要 VISION_API_KEY 的冻结重放，用于刷新 fixture |
| `tests/v2/test_image_presentation_rules.py` | 40+ 条规则单测（遮挡、去重、徽章、列重切、字重、裁剪…） |
| `tests/v2/test_image_sample_regression.py` | 七样本帧数下限 + `written==accepted` + 无重影 + 真实重放守卫 |

本轮四条统一原则对应的实现：

1. **字重看笔画，不看字号。** `fontSize >= 20` 不是字重判据（14px 卡片标题是粗体，
   40px 大标题不是）。半高掩膜上量 `2*area/perimeter`，`t>=2.2 且 t/size>=0.115 → 700`，
   `size>=28 且 t>=3.2 且 ratio>=0.14 → 900`。软掩膜会把整页判粗（AtomGit 55/63），
   半高掩膜后 22/63。
2. **图标/印章用像素擦除后回填。** 取消"不碰 OCR 词框"的禁令：只擦掉框内属于该词
   颜色的墨迹（`VISUAL_INK_TOLERANCE=60`，膨胀 1px），再扫 `12x12~260x120` 连通域。
   AtomCode 图标、review 蓝勾、5.8 折印章外框因此回来，印章的红色边框不是字的墨，
   所以框活下来。
3. **同行三道防线。** 单字升格只在"这一行已有别的词"时发生；微偏移重影按
   `Y 重叠>=0.5 + 相似度>=0.80 + 间隙<=24px + 宽度比<=0.4` 合并（Star 按钮因此
   不会被并成一整个）；文本右缘以最近右邻为界。
4. **父容器硬裁剪。** 只裁 `kind∈{button,input}` 或 `role∈{block,panel}`、父容器
   自身有填充且非页面色、溢出 ≤24px 的子元素；文本另走"最近右邻.x − 4"封顶。
   裁整页容器会掉结构（review 掉 2 帧、FluxWeaver -1.8），所以范围是算出来的。

---

## 3. 编译主链的执行顺序（改动前先读这段）

顺序是多轮踩坑的产物，**换顺序就会掉帧**：

```text
_anchor_table_text → _repartition_table_rows → _fit_table_text → _snap_text_to_ocr
→ _promote_ocr_text
→ [有 OCR 才跑] _recover_saturated_bars / _recover_text_backdrops
                _recover_page_fill / _recover_soft_panels
                _recover_colour_regions / _recover_visual_regions
→ _drop_page_coloured_shells → _drop_icon_descriptor_labels
→ _drop_coincident_texts → _separate_badge_icon_text
→ _restore_chip_labels → _resolve_misfiled_controls
→ _constrain_children → _evict_cross_plane_members → _trim_to_fill_boundary
→ attach_layout_frames → _lift_frame_overlays → _audit_filled_occluders
→ _keep_renderable_frames → _apply_residual_patches   ← 补丁必须在成帧之后
```

几条硬约束，别用"直觉"推翻：

- **`_apply_residual_patches` 不能进帧。** 补丁一旦成为帧成员，卡片的绘序会被
  重排，FluxWeaver 实测 96.1 → 93.8。
- **`_lift_frame_overlays` 会把成员抬到帧之后画。** 所以"属于页面底色"的成员
  必须先被 `_evict_cross_plane_members` 剥掉，否则 wecom 白底会重新压住弹窗。
- **`role="text-backdrop"` 不进 containers、不过遮挡审计、不当 `_ink_contrast`
  表面**，否则徽章底色会被当成"字下面的表面"去算对比度。
- **`role="page-ground"` 不是 `role="page"`。** 撞名会把计划里真正的 page 容器
  一起排除出成帧。

关键常量都在文件顶部：`BACKDROP_EDGE_DELTA=18`、`BACKDROP_MIN_SIDES=3`、
`PLANE_EDGE_TOLERANCE=24`、`PLANE_TRIM_MIN=4`、`SOFT_PANEL_MIN_DELTA=6`、
`FILL_CALIBRATION_DELTA=6`、`PAGE_BANDS=8`、`STROKE_BOLD_MIN=2.2`、
`VISUAL_INK_TOLERANCE=60`、`RESIDUAL_TEXT_LIMIT=0.65`、`PATCH_Z_INDEX=5`。
调这些之前先跑一遍看板，看 diff 落在哪一类区域（文字 / 图标 / 面板 / 底色）。

---

## 4. 怎么验证（三条命令）

```bash
PY=C:/Users/lzq/.conda/envs/omni/python.exe

# 1. 重放：走完整链路，产物在 output/_replay_<tag>/pipeline/
$PY scripts/replay_pagegraph.py                 # 七张；缺图的会打印 skipped 并以 exit 1 结束
$PY scripts/replay_pagegraph.py AtomGit review  # 只跑还在的两张

# 2. 度量：控制台出表，同时写 output/_replay_<tag>/pipeline/diff.png
$PY scripts/visual_alignment.py --json output/_align_roundN.json

# 3. 回归：规则单测 + 七样本帧数守卫（缺图的自动 skip）
$PY -m pytest tests/v2/test_image_presentation_rules.py \
              tests/v2/test_image_sample_regression.py -q
```

`diff.png` 是判断"下一步该改什么"的唯一依据：原图压到 1/4 亮度，超过 30 通道的
像素涂红。`residual_regions()` 会把 diff>40 的小块（14x14~240x120、文字覆盖 <65%）
列成候选补丁，重放的第二遍用的就是它。

---

## 5. 已知缺口（按 ROI 排序）

1. **渲染端字体（最大项）。** 剩余误差 68~80% 落在文本框内部。渲染端没有
   Noto Sans SC，CJK 回退系统默认字体；字号 ×1.04/1.075/1.10、字重 500/600/bold、
   换 `font-family` 都试过，`within30` 不动。装字体或把字体打进渲染镜像才是解法；
   继续在几何上加规则是白花时间。
2. **review 的 within15 只有 74.20%。** 与 within30 差 21 个点、mean error 13.59，
   形态是"整页均匀偏色"而不是局部错位。下一步该核对页面底色/容器 fill 的采样
   （`_dominant_color`、`_calibrate_container_fills`），不是几何。
3. **marketplace 划线价压在标题上。** VLM 把划线价的框量到了标题那一行，OCR 没有
   对应锚点可以纠正。属感知层测量错误，呈现层没有可靠判据。
4. **inventory2 游离的 "10"。** `control:7aed16abcc1f1b6c` 的 bbox 是整行，文字只有
   "10"；`_resolve_misfiled_controls` 里有"框与字差得太远"的判据，但这一例的框
   恰好在表内，归位会破坏表结构。
5. **AtomGit 深色"推荐"胶囊、marketplace"模型广场"红底。** 导航项没有文本节点，
   也没有 OCR 行，像素恢复能采到色块但采不到胶囊形状。要解决得让感知层产出
   导航项，或在恢复时允许"无字的圆角胶囊"。

---

## 6. 资产风险：五张原图已经丢了

`output/_v2_fit_<tag>/pipeline/image_reference.json` 里记的是绝对路径。七张图当初
来自剪贴板与微信临时文件，微信会自行清空 `RWTemp`：

| 样本 | 记录路径 | 现状 |
|---|---|---|
| AtomGit | `~/.workbuddy/clipboard-images/clipboard-2026-11-13T10-27-45-166Z-0e04b97e.jpg` | 在，已入库 `samples/image_screenshots/AtomGit.jpg` |
| review | `~/.workbuddy/clipboard-images/clipboard-2026-11-14T11-42-37-564Z-2eb29322.jpg` | 在，已入库 `samples/image_screenshots/review.jpg` |
| FluxWeaver / inventory / inventory2 / marketplace / wecom-modal | `D:\Program Files (x86)\WeChat Files\...\temp\RWTemp\2026-11\*.png` | **已消失**（目录已删，全盘按文件名搜过） |

处理方式（本次随交接提交）：

- `scripts/sample_sources.py` 统一查找：先试记录路径，再试
  `samples/image_screenshots/<tag>.{png,jpg,jpeg}`，都没有就抛 `MissingScreenshot`，
  报错里写清"把图放回来叫 `<tag>.png`"。`bind()` 同时改写 graph 与 reference 的
  路径，并校验画布尺寸与 `input.size` 一致——尺寸不同就是另一个样本。
- `scripts/replay_pagegraph.py` 单张缺图不中断其余样本，退出码 1 表示这次跑不全。
- `tests/v2/test_image_sample_regression.py::test_pixel_replay_keeps_the_frames`
  在缺图时 skip，并说明原因，不再伪装成代码失败。
- 两张在库的图与记录 sha256 逐字节一致，今天用它们重测得到 92.36 / 95.08，
  与 01:51 那次**完全对上**，说明语料回退路径没有改变度量口径。

要恢复另外五张的度量：把原图按 tag 命名放进 `samples/image_screenshots/`，
跑第 4 节的三条命令即可；`samples/image_screenshots/README.md` 有同样的说明。

---

## 7. 测试现状

```text
tests/v2:  1435 passed, 8 failed, 5 skipped   （116s）
图像两组:   85 passed,  5 skipped
```

5 个 skip 就是上面五张丢图的样本。8 个 failed **全部与本次改动无关**，
在本分支上没有被改过一行，属已知环境/资产缺口：

```text
test_axure_holdout_manifest.py      : DQ-R01 的 dom_path 不在盘上（asset 缺失）
test_axure_holdout_v2_manifest.py   : 冻结输入哈希对不上
test_axure_holdout_v3_manifest.py   : 冻结输入哈希对不上
test_axure_holdout_v4_manifest.py   : 冻结输入哈希对不上
test_p5_collaboration_race_probe.py : 'failed' != 'completed-for-current-scope'
test_p5_partial_release_probe.py    : 同上
test_p5_permission_takeover_probe.py: 同上
test_p5_region_compensation_probe.py: 同上
```

七样本帧数下限（`FRAME_FLOORS`，只当地板不当等号——多一帧不算回退）：
AtomGit 9、FluxWeaver 6、inventory 9、inventory2 11、marketplace 7、review 3、
wecom-modal 6。`inventory2` 曾经因为"纯像素成员（mark/patch/chip）被算成结构"
掉到 10，修法是让它们不阻塞父帧，**不要**去改测试下限。

---

## 8. 下一步建议

1. 先解决字体（第 5 节第 1 条），把 95% 的门槛从"几何问题"变成"字体问题"，
   再决定要不要继续在呈现层投时间。
2. 拿回五张原图，重跑一次看板建立新的基线；在此之前不要把旧数字当回归基准。
3. `review` 的整页偏色单独查一遍页面底色采样，可能是低成本的一两个点。
4. 感知层（导航项、划线价）的问题回感知层解决，别在呈现层加白名单。
