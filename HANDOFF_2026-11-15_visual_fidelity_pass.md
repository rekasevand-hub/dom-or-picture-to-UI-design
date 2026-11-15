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
