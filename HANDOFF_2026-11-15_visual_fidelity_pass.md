# HANDOFF — 七样本呈现层像素级收口（feat/visual-fidelity-pass）

**日期：** 2026-11-15
**分支：** `feat/visual-fidelity-pass`（基于 `21a62c2`，即 `feat/image-to-figma-v2` 顶端）
**本分支提交：** `338b346` → `343e393` → `b4dd527` → `6483970`，外加语料/重放与本次回库的提交
**运行环境：** `C:/Users/lzq/.conda/envs/omni/python.exe`（numpy 1.26 / cv2 4.10 / pytest 8.3）
**状态：** 可交接。七张原图已全部回库，七样本均可重放、可重测；`written == accepted`
**下一步优先项：** 剩余误差是**逐元素**的，不是全局字体或字号问题（第 5 节有两次实测），
要么做逐元素校准，要么停在这里

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
| marketplace | 94.53 | **95.99** | 94.82 | 9.20 | 7 |
| review | 90.84 | **95.08** | 74.20 | 13.59 | 3 |
| wecom-modal | 96.03 | **96.36** | 95.32 | 6.47 | 6 |
| **均值** | **92.25** | **94.35** | — | — | — |

四张 ≥95。这张表在 2026-11-15 10:16 用回库的七张原图**整套重跑**得到：
与 01:51 那次逐位相同，只有 marketplace 95.99 vs 96.00（回库的 marketplace 是重新
下载的一份，PNG 字节不同、尺寸相同，见第 6 节）。帧数 13/6/10/13/9/3/6，全部在位。

不能声明的事：

- 不能声明七样本全部到 95%。AtomGit 92.36 / inventory 93.12 / inventory2 93.40
  仍在 95 以下，剩余误差的主体在文本框内部，且**不是**单一字体或字号因子（见第 5 节）。
- 不能把这一轮的数字当成"渲染端一致"。渲染端确实用上了 Noto Sans SC，但源截图
  的字体不是靠猜能定的；换字体族实测是持平到略降（第 5 节）。
- 不能把 `--no-patches` 的两遍渲染当成一次跑完。补丁是第二遍的产物，关掉它
  指标会掉（见第 3 节的执行顺序）。
- 不能把 `within30` 与 `within15` 混着讲：review 是 95.08 / 74.20，它的误差是
  "整页轻微偏色"型，不是结构性错位。

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

1. **文本框内部（最大项，但不是字体问题）。** 剩余误差 68~80% 落在文本框内部，
   本轮已用两次实测排掉了两个最自然的猜测，**不要再重复走这两条路**：

   | 实验 | 做法 | 结果（within30） |
   |---|---|---|
   | 换字体族 | 把 SVG 里 `font-family` 换成 Microsoft YaHei / SimHei / sans-serif | AtomGit 92.36 → 92.43 / 92.50 / 92.43；review 95.08 → 94.96；wecom 96.36 → 96.27。**持平到略降** |
   | 全局放大 CJK 字号 | 含汉字的文本 `fontSize` × 1.06/1.10/1.14/1.18 | AtomGit 92.36 → 92.22/92.16/92.06/91.87；inventory 93.12 → 92.97/92.89/92.76/92.72。**单调下降** |

   两个前提也一并更正：`NotoSansSC-VF.ttf` **是安装了的**，Chromium 也确实用它渲染
   （画布字形哈希 `462514177` 与回退字体 `2509622748` 不同）；`font-family="Noto Sans SC"`
   在设计稿里也是对的。剩下的偏移是**逐元素**的：墨迹列边界显示一部分左对齐文本
   整体偏左 3~9px、CJK 宽度偏窄 6~12%（如 `热门推荐` 真值 106px / 渲染 94px），
   而拉丁文本（`astryx` 66px）宽度完全一致。要往下走只能是逐元素校准
   （每个框自己量一次 dx/字号），收益不确定、成本很实在。
2. **review 的 within15 只有 74.20%。** 与 within30 差 21 个点、mean error 13.59，
   形态是"整页轻微偏色"，不是局部错位。下一步该核对页面底色/容器 fill 的采样
   （`_dominant_color`、`_calibrate_container_fills`），不是几何，也不是字体。
3. **marketplace 划线价压在标题上。** VLM 把划线价的框量到了标题那一行，OCR 没有
   对应锚点可以纠正。属感知层测量错误，呈现层没有可靠判据。
4. **inventory2 游离的 "10"。** `control:7aed16abcc1f1b6c` 的 bbox 是整行，文字只有
   "10"；`_resolve_misfiled_controls` 里有"框与字差得太远"的判据，但这一例的框
   恰好在表内，归位会破坏表结构。
5. **AtomGit 深色"推荐"胶囊、marketplace"模型广场"红底。** 导航项没有文本节点，
   也没有 OCR 行，像素恢复能采到色块但采不到胶囊形状。要解决得让感知层产出
   导航项，或在恢复时允许"无字的圆角胶囊"。

---

## 6. 资产：七张原图已全部回库

`output/_v2_fit_<tag>/pipeline/image_reference.json` 里记的是绝对路径。七张图当初
来自剪贴板与微信临时文件，微信会自行清空 `RWTemp`；2026-11-15 上午五张曾一度消失
（目录被删，全盘按文件名搜过）。当天 10:15 用户重新提供了七张原图，现已全部入库：

| 样本 | 语料文件 | 与记录 sha256 |
|---|---|---|
| AtomGit | `samples/image_screenshots/AtomGit.jpg` | 一致 |
| FluxWeaver | `samples/image_screenshots/FluxWeaver.png` | 一致 |
| inventory | `samples/image_screenshots/inventory.png` | 一致 |
| inventory2 | `samples/image_screenshots/inventory2.png` | 一致 |
| review | `samples/image_screenshots/review.jpg` | 一致 |
| wecom-modal | `samples/image_screenshots/wecom-modal.png` | 一致 |
| marketplace | `samples/image_screenshots/marketplace.png` | **不同**（重新下载的一份：2544x1336 尺寸相同，PNG 字节不同；重测 95.99 vs 96.00） |

守住的机制（不再靠"记得别删微信临时目录"）：

- `scripts/sample_sources.py` 统一查找：先试记录路径，再试
  `samples/image_screenshots/<tag>.{png,jpg,jpeg}`，都没有就抛 `MissingScreenshot`，
  报错里写清"把图放回来叫 `<tag>.png`"。`bind()` 同时改写 graph 与 reference 的
  路径，并校验画布尺寸与 `input.size` 一致——尺寸不同就是另一个样本。
- `scripts/replay_pagegraph.py` 单张缺图不中断其余样本，退出码 1 表示这次跑不全。
- `tests/v2/test_image_sample_regression.py::test_pixel_replay_keeps_the_frames`
  在缺图时 skip，并说明原因，不再伪装成代码失败。
- 回库后七张一次跑通：`replay` 帧数 13/6/10/13/9/3/6，度量与 01:51 那次逐位相同，
  说明语料路径没有改变度量口径。

换机器或换工作树时只需 `git clone`：原图随仓库走，`output/` 下的 PageGraph 与
`ocr_supplement` 是本地产物（不入库），缺它们时重放与帧数守卫会 skip。

---

## 7. 测试现状

```text
tests/v2:  1440 passed, 8 failed, 0 skipped   （170s，七张原图回库后）
图像两组:    90 passed,  0 skipped            （77s）
```

没有 skip 了：七张原图都在，`test_pixel_replay_keeps_the_frames` 对七个样本全部
真跑（帧数 13/6/10/13/9/3/6，下限 9/6/9/11/7/3/6）。8 个 failed **全部与本次改动无关**，
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

1. 七张原图已回库、看板已重跑（第 1 节的表就是当前基线，可直接当回归基准）。
2. `review` 的整页偏色单独查一遍页面底色采样（`_dominant_color` /
   `_calibrate_container_fills`），是预期成本最低的一两个点。
3. 想突破 95% 只剩"逐元素校准"一条路：对每个文本框用墨迹列边界反推 dx 与字号
   （第 5 节第 1 条的两个实测已经把全局因子排除了）。先在一个样本上试，量到收益
   再决定是否铺开；不要再用"整体字号 ×1.x"这种全局缩放。
4. 感知层（导航项、划线价）的问题回感知层解决，别在呈现层加白名单。

---

## 9. S1 已落地：逐框文本度量校准（`f810ad9`）

第 8 节第 3 条已经做完。`src/app/services/structure/fidelity/text_metrics.py`：
在同一窗口内对原图与渲染图做墨迹行列投影，得到 dx（按对齐方式）、dy（墨迹上沿）
与尺寸比（高度 0.7 / 宽度 0.3 加权）。x/y 与墨迹是线性关系，位移可精确施加；
`fontSize` 不是——适配器基线是 `y + height/2 + 0.375em`，所以先在渲染图上量出
`ink_em`（每 em 墨迹高，本机 0.91~0.95），再按 `(ink_em − 0.375) × Δ` 反向补偿，
让墨迹上沿留在原处。窗口 8→4→2 自适应收缩；邻居贴边、整窗被填满、宽高比不一致
（那是字距不是字号）、块级文本只修左缘。改完重渲染，**整页变差就整批回滚**。

| 样本 | 校准前 | 校准后 | 变化 | 补丁面积 | 文本数 |
|---|---|---|---|---|---|
| AtomGit | 92.36 | **92.95** | +0.59 | 3.82% | 63 → 63 |
| inventory | 93.12 | **93.30** | +0.18 | 1.30% | 72 → 72 |
| wecom-modal（对照） | 96.36 | **96.62** | +0.26 | 0.73% | 41 → 41 |

帧数 13/10/6，与校准前一致；`tests/v2` 1449 passed / 8 known / 0 skipped。

**但这轮最重要的产出是一个上限，而不是这 0.59 分：**

| 样本 | 完整（校准后） | 把所有文本删掉 | 文本层净贡献 |
|---|---|---|---|
| AtomGit | 92.95 | **94.27** | −1.32 |
| inventory | 93.30 | **94.68** | −1.38 |
| wecom-modal | 96.62 | 96.93 | −0.31 |

校准让文本层的**代价**变小了（AtomGit −1.91 → −1.32，inventory −1.56 → −1.38），
但没有让它变成正收益，而且短期内不可能：矢量字形再准也只是"近似"原图字形，而
空白页与平底色是"精确"吻合。由此得到两条硬结论，后续排期应当据此调整：

1. **AtomGit 与 inventory 的 95% 不可能靠文本工作达成**——它们的"零文本天花板"
   只有 94.27 / 94.68，已经在 95 以下。要过线必须先抬高非文本像素（底色/面板/
   尚未恢复的图形），再谈文本。
2. 因此 P1（无字胶囊 / 圆角底色确定性检测）不是"锦上添花"，而是**唯一能抬高
   天花板的一类工作**；文本校准应停在"副作用最小"，不再作为主攻方向。

---

## 10. S0 已跑：Figma 导出链路的天花板是 100%

bridge 起来后（`python -m src.app.services.bridge_server`，插件自动重连，`auth` 通过）
先做了 S0：把原图整张作为 image fill 写进一个 frame、用 Figma 原生 `exportAsync`
导出，再量它与原图的差异。**这是"设计稿完全正确"时的上界。**

| 测试 | within30 | within15 | mean error |
|---|---|---|---|
| AtomGit 原图 → Figma frame → 导出 | **100.00** | 100.00 | 0.00 |

导出链路零损耗：没有重采样、没有色彩偏移。历史那份 87.71 的导出不是 Figma 的问题，
是当时编译器的状态。

随后把校准后的设计稿（S1 产物）真机写入并导出，三张一起看：

| 样本 | SVG | Figma | 差 | Figma within15 |
|---|---|---|---|---|
| AtomGit | 92.95 | 92.67 | −0.28 | 90.27 |
| inventory | 93.30 | 92.86 | −0.44 | 91.74 |
| wecom-modal | 96.62 | 96.41 | −0.21 | 95.08 |

结论：**两条渲染路径只差 0.2~0.4 个点**，之前"Figma 比 SVG 低 2~5 分"的估计作废。
所以"Figma 真机 ≥95%"和"SVG ≥95%"难度相同，门禁口径可以双轨而不互相打架；
真正的约束仍然是第 9 节那条零文本天花板（94.27 / 94.68），也就是说：
**先把非文本像素抬上去，两条路径会一起过线。**

复跑方式（bridge 起着即可）：

```bash
python scripts/figma_ceiling.py AtomGit            # S0 天花板，默认跑完即删对照 frame
python scripts/figma_replay.py --out output/_cal_<tag>/pipeline --design 12_design.json
```

注意 `figma_replay.py` 每次会按 `--screen-name Screen` 清掉上一次的帧，所以同一次
会话里它只保留最后一张；每次导出的 PNG 都落在各自的 `pipeline/figma_render.png`，
度量不受影响。`figma_ceiling.py` 的对照 frame 默认删除（`--keep` 可保留）。

---

## 11. P1 + 防折行已落地（`1f52b85`），双端指标与未解项

| 样本 | SVG 前 → 后 | Figma 前 → 后 | 补丁面积 | 文本数 | 帧数 |
|---|---|---|---|---|---|
| AtomGit | 92.95 → **93.12** | 92.67 → **93.05** | 4.21% | 62 | 13 |
| inventory | 93.30 → **93.40** | 92.86 → **93.13** | 1.62% | 72 | 10 |
| wecom-modal（对照） | 96.62 → **96.66** | 96.41 → **96.42** | 0.73% | 41 | 6 |

Figma 与 SVG 的差从 0.21~0.44 收到 0.07~0.24。`tests/v2` 1456 passed / 8 known / 0 skipped。

三处改动：

1. **胶囊矢量恢复**（`_recover_pill_shapes`）：不再看填充率（圆角使它永远低于 0.90），改看
   形状——四角都不是该色、左右中边都是该色，据此输出原生圆角矩形（`fillColor` +
   实测圆角半径），不占补丁预算。**产出很诚实：inventory 3 个，其余 0 个**——AtomGit 那个
   深色导航胶囊本来就已经被面板恢复拿到了，这一条不是天花板的主要来源。
2. **段落尾句去重**（`_drop_paragraph_tails`）：同一句被建模成"整段 + 尾句"时两框不重叠，
   原来的重合去重看不见；现在按"后缀 + 起于下一行 + 同一水平跨度"删除，比较前做同形字
   归一（现场那对是 `AI` vs `Al`）。
3. **没有空间就不许折行**：盒高只有一行的文本节点在 Figma 里会被盒宽折成两行、叠在一起；
   桥接端对这些节点强制 `WIDTH_AND_HEIGHT` 并去掉 `boundedText`。校准端同步加了闸门：
   放大后的墨迹超出盒宽或 `maxWidth` 就不放大。

**未解项（下一件该做的事）**：AtomGit 卡片正文下面那行仍在，但它**不是文本节点**——是
补丁从原图裁来的第二行，因为模型把这段当成一行、原图是两行。真正的修法是按 OCR 行
把段落切成两行（新 pass，不在本轮范围）。

---

## 12. 段落重构 + 仲裁器（`1dc93a8`）

**`_reflow_paragraphs`**：OCR 知道段落在哪断行，方案却把它压成一行。现在按 OCR 行重建
节点（`lines` + 实测行距 + 并集 bbox），模型的字保留、OCR 只提供断点（现场 OCR 把 `AI`
读成 `Al`）。链式检索必须"下一行仍是这句话的下一段"，否则会吃到下面的 `TSX`。

**`vlm_arbiter.py`**：候选是量出来的编号块，VLM 只回编号；票型只开
`MISSING_OR_FADED_TEXT` 与 `STYLE_MISMATCH`；工单按 image sha + render sha 冻结到
`15_arbiter_tickets.json`，重放直接读；四道门禁逐票判定，失败单票回滚。
本机无 `VISION_API_KEY`，冒烟结果是"8 个候选、0 张票、注明原因"——路径真实跑过，模型
调用没有被伪造。

| 样本 | SVG | Figma | 补丁% | 第二行 |
|---|---|---|---|---|
| AtomGit | 93.12 → **92.92** | 93.05 → **92.89** | 4.21 → **3.82** | 补丁 → **原生可编辑** |
| inventory | 93.40 | 93.13 | 1.62 | 无 |
| wecom-modal | 96.66 | 96.42 | 0.73 | 无 |

AtomGit 掉 0.20：被替换的补丁是原图逐像素拷贝，矢量行赢不了它，也不该赢。换来的是
可编辑的第二行与少 0.39% 的位图。`tests/v2` 1473 passed / 8 known / 0 skipped。

---

## 13. 残余误差四分类（`b037549`）

`scripts/error_attribution.py` 把每个失败像素按互斥优先级归给一个主人：
文本框 → 填充容器 → 图像/图形 → 页面底色。

| 口径 | 样本 | text | panel | graphic | ground |
|---|---|---|---|---|---|
| within30 | AtomGit | 82.7% | 17.1% | 0.0% | 0.2% |
| within30 | inventory | 65.7% | 13.9% | 0.0% | 20.3% |
| within30 | review | 73.4% | 26.6% | 0.0% | 0.0% |
| within15 | AtomGit | 73.4% | 26.4% | 0.0% | 0.2% |
| within15 | inventory | 58.4% | 25.4% | 0.0% | 16.1% |
| within15 | review | 18.4% | **81.6%** | 0.0% | 0.0% |

两条结论：graphic 类已经清零（图标/印章恢复把这块吃干净了）；15 通道口径下
**面板**是主战场（review 81.6%）。

**已修**：`_recover_page_fill` 的带色取左右边距中位数，review 顶带一边渐变一边白卡，
得到 `#dee7fb`（真值 `#f2f5fb`，一个在图上不存在的颜色）。现在左右分侧采样、剔除
已绘制区域，两侧不一致时取与上一带连续的那侧。收益诚实：review within15 +0.05，
其余不变——**带色不是那 25 个点的来源**。

**已试并否决**：review 主卡内部是 982×672 的淡渐变（中心 254、左上 245、右下 239），
平填只能在中点正确。实现六条带内嵌后实测 within15 74.46（对比 74.52）不动，且带子
被算成帧（review 3 → 7 帧），已回滚。结论：容器内让 15 通道失败的不是大渐变，而是
**大量小元素的 1px 描边与圆角**——下一轮先量这个，别再假设。

---

## 14. 仲裁器已接通 live，但门禁把票全退了（`b076ad7`）

`.env` 里的 `VISION_*` 生效后，`propose()` 走 `call_vlm` 发送编号后的 1:1 并排图，
解析容错到"裸 JSON 数组 / 围栏 / 对象"三种形态。两处修正由 live 跑出来逼出来的：
候选编号必须是**它在图里的位置**（原来是区域原始索引，模型答"第 1 张"就落空）；
仲裁必须跑在**补丁之前**（跑在后面，候选已被像素级补丁覆盖，加什么都会更差）。

| 样本 | 候选 | 返回工单 | 通过门禁 | 失败原因 |
|---|---|---|---|---|
| AtomGit | 8 | 4 | **0** | roi-worse（42.96→38.87）、frames-disagree |
| inventory | 8 | 2 | **0** | frames-disagree、roi-worse（52.14→45.66） |
| wecom-modal | 8 | 6 | **0** | roi-worse（60.6→43.63 等）、frames-disagree、page-worse |

两条根因，都有具体数字：

1. **合成的文字比不写更差。** 执行器按"墨迹中位色 + 0.95×墨迹高"造节点，那不是原图
   的字形。这与第 9 节"矢量文本相对补丁是净负"的结论互为印证。
2. **往帧里插文本会破坏该帧的绘制连序**，`written != accepted`。不变量是对的，
   执行器要像补丁那样把新节点追加在帧外。

结论：仲裁器通路真实可用、纪律有效，但当前**零产出**。冻结工单已落盘，下一轮可以把
"是否变好"当 diff 判，而不是重新问一次模型。

---

## 15. 设计神似口径定稿（宏观仲裁 + 三类门禁）

验收标准从"像素 1:1"改为"设计神似"：排版、间距、容器完整、图标、字重字号层级、整体风格。
像素指标只作诊断，不再作门禁。

**输入**：整页（缩到 1440）+ 上/中/下三段 1:1 的 `[原图 | 渲染]` 并排，附页面骨架清单
（容器/文字的 contentRef、bbox、字号、字重）。

**五类工单 → 确定性执行器**：`MISSING_TEXT_BLOCK`（先搜同位置已有节点，改前景色/字号/文本；
确实没有才新建）、`TEXT_COLLISION_OR_DRIFT`（remove/nudge）、`INCOMPLETE_GRAPHIC_OR_WIDGET`
（pill/border 底框，插最前层）、`TYPOGRAPHY_HIERARCHY`（bold/bigger/both）、`CONTAINER_CROWDING`（clamp）。
几何修改一律不许动帧内节点——原地修复只改样式。

**门禁**：帧数（≥ 下限且不得少于基线）、`kept == accepted`、补丁 ≤ 8%、文本重叠数不得增加。

三张样本，18 张工单全部生效：

| 样本 | 生效 | 代表工单 | SVG30/15 | Figma30/15 |
|---|---|---|---|---|
| AtomGit | 6/6 | 隐形文本改色、TOP1 上移、meta 行补 pill、热门推荐 700、卡片 clamp | 92.84/90.43 | 92.86/90.49 |
| inventory | 6/6 | 两处行重叠上移、两处 700、卡片 clamp、缺字原地改色 | 94.53/92.81 | 94.26/93.16 |
| marketplace | 6/6 | 看详情补 pill、本期好价 700、¥4.64 加粗放大、11月下移、C6 clamp | 96.54/95.36 | 96.17/95.01 |

两条踩坑记录：
1. 门禁拿 `written` 与 `accepted` 比，二者永不相等（编译器会丢弃渲染器拒绝的帧），
   正确口径是 `kept == accepted`——改对前所有工单被误杀；
2. 基线测量在真实 elements 上跑清理，把 AtomGit 从 13 帧减到 12，看起来像工单造成。
   测量一律在副本上做；原地修复也不许动几何。

并排对照图：`output/_compare_AtomGit.png` / `_compare_inventory.png` / `_compare_marketplace.png`。

---

## 16. 坐标审计：投影没问题，错的是词（`c20379f`）

上一轮把"真机右上角飘字"归因为 `figma_adapter` 的父子坐标换算。`scripts/coord_audit.py`
把回读树逐层累加后与方案逐节点比对，结论相反：

| 样本 | 配对 | 误差 ≤1px | 帧 | 自动布局帧 | 未钉死子项的 |
|---|---|---|---|---|---|
| AtomGit | 88 | 88 / 88 | 13 | 8 | 0 |
| inventory | 104 | 99 / 104 | 11 | 9 | 0 |
| marketplace | 60 | 60 / 60 | 10 | 6 | 0 |

- 5 个 inventory 离群全是 `textAlign: center|right`、盒子比墨迹宽：`dx + dw/2 == 0`，
  **墨迹起笔晚，节点没动**；
- 所有自动布局帧的子项都是 `ABSOLUTE`（`setAutoLayout` 先快照再写回），Figma 从不重排。

真正的缺陷是**方案把四个价格节点放到了卡片标题带里**：`¥4.64` / `¥8.00` / `¥2.00` /
`起 ¥23.00`，四者的盒子都压在 `DeepSeek V4.1 Flash` 上，而 OCR 在它们的盒子上什么也没有。
`_drop_nested_texts` 的判据因此不是"框重叠"，而是"**原图在这个位置有没有这句话**"：
字符覆盖率 ≥70% 才算有支撑（OCR 把 `输入 · 峰时` 读成 `输入 .峰时`、`谷时 ¥0.58` 读成
`谷时半0.58`，一个错字不该判一条真实文本死刑）。下一行的数值不动（自带竖直带），
inventory 表格里"冻结库存"被宽单元格包住但有 OCR 支撑，保留。

Hero 背后那块"多余黑框"是另一回事，也是这轮最有意思的一条：`_recover_page_fill` 把四边
中位色**取平均**。marketplace 上下是 `#1a1917`、左右是 `#100f0d`，平均得 `#151412`，
与声明底色只差 6 个通道 → 判定"页面已经对了"直接返回。于是页面保持浅一档，而 hero 的
`heading:C3`（`#100f0d`，本来是对的）看起来就成了一个暗色方框。现在四边**投票**，打平
时取离声明更远的那侧；与声明差 <6 的带子按接缝丢弃（6 而不是 10：wecom 的 `#666666`
对 `#5d6064` 差 9，按 10 放过它时 within15 掉 1.4 个点）。

`_restore_display_weight`：笔画测试量的是 `2*area/perimeter`，在正文尺寸上正确，在 99px
宋体上错误——竖 12px、横 2px，平均出 0.086em，Hero 被判成 Regular。现在页面最大的一行
按角色定：≥0.075em 就是展示字重，给 800。review 的"内容正在审核中"量到 0.159，同样处理。

指标（within30 / within15 / mean，SVG）：

| 样本 | 前 | 后 |
|---|---|---|
| AtomGit | 92.92/90.50/9.69 | 92.92/90.50/9.69 |
| marketplace | 96.67/95.49/7.88 | **96.74/95.72/5.59** |
| wecom-modal | 96.67/95.58/6.45 | 96.67/95.58/6.45 |
| review | 95.41/74.87/12.85 | 95.38/74.86/12.92（标题加粗） |

真机 Figma：AtomGit 92.89/90.51、inventory 94.27/93.16、marketplace **96.46/95.42**。

## 17. 倾角：一个角度，两端渲染（`c81f4eb`）

约定：角度制、逆时针为正，折进 (-180,180]，**|a|<2° 视为水平**。SVG 写
`rotate(-a cx cy)`（`rotate()` 在屏幕上是顺时针，取负）；Figma 的 `node.rotation` 同样
顺时针，但**绕节点自身原点**旋转，所以插件按 `origin = centre − R(θ)·(w/2,h/2)` 反向
补偿，用的是节点**实际**尺寸（文本会自重测），因此单独做成 `set_rotation` 命令，等
characters/换行/autoResize 全部落定后再施加。

`estimate_rotation` 给感知端一个确定性校验：`minAreaRect` 取"最大的非边框轮廓"（深色
印章压浅底、白字压深底是同一个测量的两种极性），角折进 (-45,45]（OpenCV 会因选中哪条边
而给 0 或 90、6 或 96），填充率 <0.45 不出角。实测 marketplace 的 `5.8 折` 印章 −4.6°。

状态：27 条新测试全绿（符号/折叠/中心补偿 6·30·90·135°/SVG transform/栅格化后墨迹
重心不动/6·12·−8° 量角/适配器→插件契约）。**真机未验**：正在运行的插件还是旧代码，
`set_rotation` 返回"未知命令"，需要在 Figma 里重新 Run 一次插件后才能跑真机闭环。

---

## 18. 卡片边缘、Gutter，以及三条被数据否掉的规则（`bfece59`）

**卡片描边**：`_outside_color` 原来取 y−2..y−4。marketplace 的四张模型卡片，方案盒量的是
**描边内侧**，那三行正是描边本身（`#2c2b27`），于是"外部色"=描边色，`detect_border` 把它
当背景否掉，四张卡片全部没有边。现在向外取 6~9px（越过 1px 线与其抗锯齿），只有贴着画布
顶边的盒子才回退到近环。

**圆角**：`estimate_corner_radius` 用固定 12 通道阈值对比外部色。暗色卡片与页底只差 10，
整块被判成背景 → 圆角 0。改成"实测 fill↔page 间距的一半，上限仍是 12"，暗卡与白卡同一
条规则。marketplace 卡片现在按 24px 圆角绘制。

**Gutter 隔离**：`separated_by_page` 只看两个盒子**共享的那几行**之间那条竖带是否为页底色，
`_reflow_chain` 遇到它就拒绝续接。先试过"整列全空"的全局 gutter 列表，被否决——它把卡片
**上方**的空白也当成通道，marketplace 一页就报 12 条。

三条被数据否掉、已回滚或未落地：

| 尝试 | 结果 |
|---|---|
| 卡片盒长到自己的涂色边界（把 header 规则推广到 card/panel） | marketplace 两张卡**互相重叠 61px**，守卫拒绝，一张没长；放宽行占有率后 inventory2 掉 2 帧。已回滚 |
| 衬线检测 → Noto Serif SC | 距离变换的厚度离散度：宋体 Hero 6.0，review 的**粗黑体**标题 6.3 —— 分不开，按它会误改黑体 |
| 无填充 1px 胶囊（2.0 Mini 等） | 它们的"边框"与周围已建模的按钮/输入框 1px 线不可区分，三张样本的候选全是既有控件，恢复即重复 |

指标（within30 / within15，SVG 与真机 Figma）：

| 样本 | SVG | Figma | 补丁 | 帧 |
|---|---|---|---|---|
| marketplace | 96.74/95.72 | 96.46/95.42 | 1.77% | 9 |
| AtomGit | 92.92/90.50 | 92.89/90.51 | 3.82% | 13 |
| inventory | 94.54/92.82 | 94.27/93.16 | 1.62% | 10 |

七张样本帧数 13/6/10/14/9/3/6（下限 9/6/9/11/7/3/6）。`tests/v2` 1519 passed / 8 既有失败；
图像相关 169 条全绿。

## 19. 真机旋转：插件加载的是主检出，不是这个工作树

`set_rotation` 在真机上一直报"未知命令"，即使重载插件。查清了：Figma 载入的是
`D:/LLM-Data/Figma_auto_agent/figma_bridge/code.js`（11-13 版），本工作树的改动它看不到。
已把本工作树的 `code.js` 同步过去（原件备份在 `output/_plugin_sync/code.js.orig`），
**Figma 里需要再 Run 一次插件**才会真正加载。要撤销这次同步：
`git -C D:/LLM-Data/Figma_auto_agent checkout -- figma_bridge/code.js`。

---

## 20. 真机旋转定稿：符号反了，中心现在是被证明的（`87afb65`）

真机第一次跑通，立刻暴露两处约定错误（实测 5 个角度反推，不靠文档）：

| 约定 | 实测 |
|---|---|
| 符号 | `node.rotation` **逆时针为正**（写 −4.6 得到顺时针 4.6°） |
| 原点 | 绕节点**自身原点**，`centre = origin + R_cw(rotation)·(w/2,h/2)` |

`code.js` 原来为了"顺时针"取负、又用同一取负的矩阵补偿，结果 +6° 出来是镜像的 −6° 且
偏 16px。现在角度原样写入，补偿矩阵（本来是对的）不动。

但**符号与补偿互相矛盾时，外部换角度救不回来**，所以 `_apply_rotation` 不再无条件相信
桥接：回读中心（旋转后节点的包围盒中心就是形状中心）→ 偏了就取负角重试一次 → 仍偏就用
`set_bounds` 按设计自己的代数摆位。新旧两个插件前提下都能落地。

`scripts/figma_rotation_probe.py` 是验收脚本，三条都查（能执行 / 中心不漂 / 逆时针方向），
方向用"右端标记落点"判定，因为 200×100 的框 +30° 与 −30° 包围盒完全相同：

```
angle      centre              drift    mark_y
  6.0   (400.00, 310.00)       0.00px    300.6   ← 右端上抬，逆时针
 -4.6   (400.00, 310.00)       0.00px    317.2
 30.0   (400.00, 310.00)       0.00px    265.0
-90.0   (400.00, 310.00)       0.00px    400.0
PASS: 4/4
```

marketplace 同轮真机重导出 96.46/95.42：卡片标题仍是单份、Hero 背后无假黑框、卡片保持
24px 圆角。图像测试 173 条全绿（新增 4 条：回读判定、Python 补偿、单次重试、显式摆位）。

**合并**：`feat/visual-fidelity-pass` → `feat/image-to-figma-v2` 快进合并，见下一节记录。
