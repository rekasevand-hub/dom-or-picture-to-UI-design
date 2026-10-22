# R3-EXP-08 · OCR、低清、压缩与文本验收阈值（受控实验）

> 状态：`completed-for-current-scope`（2026-10-18）。  
> 范围：单个受控合成页面，13 个文本用例 × 27 个条件标签 × 2 个 OCR 引擎 = 702 条记录。  
> 证据：`output/_r3_experiments/exp08_text_acceptance.json`、`exp08_text_site/`、`exp08_glyph_site/`、`exp08_contact_sheet.png` 及条件图。  
> 边界：本实验只标定当前字体、渲染器、OCR 引擎与版本下的失败边界；不构成通用阈值，也不得写成 `verified`。

## 1. 目的与边界

本实验回答四个问题：

1. 内容转写、可见断行、文本框和字形能否分别判定，而不是被一个 OCR 分数或一个 IoU 覆盖。
2. 缩放、原生小字号、JPEG 压缩、模糊和遮挡分别在什么位置开始破坏文字。
3. OCR 原始置信度能否作为自动接受门槛。
4. 相似汉字、`0 / O / 〇`、`1 / l / I`、全角标点和省略号在什么条件下仍可分。

页面文字、行盒与基线由同一作者预先编写。DOM 几何只用于评估 ground truth，不进入任何 OCR 引擎；OCR 只看到降质后的栅格图。本实验自身没有从静态截图测量基线；`R3-EXP-14` 已在已知字体/字号下补做静态基线估计（最大误差 0.5px），未知字体/字号仍为 `not-evaluated`。

本实验不覆盖真实站点截图、其他字体/渲染器/OCR 版本、竖排或旋转文字、跨 DPI 或真实 Figma 导入。

## 2. 环境与可复现性

| 项目 | 值 |
|---|---|
| 操作系统 | Windows |
| Python | 3.12（`C:\Users\lzq\.conda\envs\omni\python.exe`） |
| Playwright | 1.62.0 |
| Chromium | 151.0.7922.34 |
| 页面字体 | Microsoft YaHei 32px 基准；DPR 2 截图后 Lanczos 下采样到 1x |
| Tesseract | 5.5.0.20241111，`chi_sim+eng --psm 11` |
| EasyOCR | 1.7.2，GPU，`ch_sim+en`，`mag_ratio=1.0`，`canvas_size=2560` |
| 页面 | `output/_r3_experiments/exp08_text_site/index.html` |
| 字形表 | `output/_r3_experiments/exp08_glyph_site/*.html` |
| 网络 | 仅本地文件 |

脚本：`output/_r3_experiments/exp08_text_acceptance.py`。重跑会重新生成页面、条件图、字形表、联系表和完整 JSON。

## 3. 方法

### 3.1 用例

13 个用例分两组：

| 组别 | 用例 |
|---|---|
| 对抗字符（6） | `hanzi_confuse`（未末己已巳土士人入）、`zero_o`（`0O〇`）、`one_lI`（`1lI`）、`fullwidth`（全角标点）、`ellipsis`（`……` 与 `…`）、`three_dots`（`...`） |
| 普通文本（7） | 中英混排换行、中文正文换行、金额/日期/编号、拉丁文与数字、金额与百分比标点、可见省略号截断、显式三行顺序 |

其中 `evidence` 和 `punct_amount` 设为严格用例：任何字符错误都算内容失败。其余用例允许 CER 小于等于 10% 时记 `partial`。

### 3.2 条件矩阵

27 个条件标签：

- 缩放：`scale_100`、`scale_075`、`scale_05`、`scale_0375`、`scale_025`、`scale_01875`，有效字号约 32/24/16/12/8/6px。
- 原生字号：24、20、16、14、12、10、8px。
- JPEG：32px 文本下 q90/q70/q50/q30/q15；16px 文本下 q70/q40。
- 高斯模糊：σ = 0.5/1.0/1.5/2.0/3.0px（32px 文本）。
- 遮挡：三个区域，分别覆盖 `evidence` 的编号值、`mixed_wrap` 中段和 `cjk_wrap` 中段。

`native_fs_32` 与 `scale_100` 指向同一张图，因此 27 个条件标签只有 26 张不同图像。每条记录仍按标签分别保留。

### 3.3 记录字段

每条记录包含：

- 内容：`expected`、`ocr_text`、`exact`、`cer`、`core_exact`、`core_cer`、`edit_ops`、`candidate_chars`。
- 断行：`line_count_expected`、`line_count_ocr`、`line_count_match`、`line_texts_match`、`line_status`。
- 文本框：`ocr_bbox`、`gt_ink_bbox`、`gt_line_bbox`、`box_iou`、`ink_iou`、`box_edge_errors`、`box_status`。
- OCR 原始置信度：`ocr_tokens` 保存逐 token 的 `text / conf / conf_raw / bbox`；另记 `mean_conf`、`min_conf`。
- 复核：`review_status` 为 `not-reviewed` 或 `manual-review-required`；严格用例与遮挡记录强制后者。
- 遮挡：`content_status=unknown`、`content_status_reason=occluded-region`；用户补文单独记 `user-supplied-unverified`。
- 基线：本实验记录为 `baseline_status=not-evaluated`；已知字体/字号的静态估计见 `R3-EXP-14`。

其中 Tesseract 的 `conf_raw` 为 0–100，EasyOCR 的 `conf_raw` 为 0–1；两者都保留原始口径，不解释为跨引擎概率。

### 3.4 字形可分性

字形表用同一字体合成 14 对字符，按 8/10/12/14/16/20/24/32px 渲染。每对计算紧裁切、中心填充后的 NCC 距离，并与同字形 0.25px 位移的类内距离比较，得到 `ratio = between / within`。本实验的局部可分阈值为 `ratio >= 2.0`。

该阈值只对当前字体、抗锯齿和合成方式有效，不是通用字形阈值。

## 4. 总结果

### 4.1 全量

| 指标 | 结果 |
|---|---|
| 记录 | 702 |
| 严格 `exact`（含标点与空格归一化） | 81 / 702 |
| 核心字符 `core_exact`（只保留字母与数字） | 230 / 702 |
| 行数匹配 | 677 / 702 |
| 文本框 `pass / partial / fail / unknown` | 122 / 319 / 246 / 15 |
| 内容状态 `pass / partial / fail / unknown` | 81 / 60 / 540 / 21 |
| 复核状态 | `not-reviewed` 590 / `manual-review-required` 112 |
| 逐 token 置信度 | 3792 个 token，全部带 `text / conf / conf_raw / bbox` |

### 4.2 对抗字符

6 个对抗用例共 324 条记录：

- `exact`：0 / 324。
- 核心字符 `core_exact`：71 / 324。
- 相似汉字、数字/字母/`〇`、全角标点和省略号都没有在任一条件下达到严格 exact。

这意味着：OCR 可以给出候选，但不能把对抗字符类文本自动定稿。

## 5. 逐条件结果

### 5.1 缩放与原生字号（7 个普通用例）

| 条件 | 有效字号 | Tesseract 核心 exact | EasyOCR 核心 exact |
|---|---:|---:|---:|
| `native_fs_32` / `scale_100` | 32 | 5/7 | 3/7 |
| `scale_075` | 24 | 4/7 | 4/7 |
| `scale_05` | 16 | 4/7 | 3/7 |
| `scale_0375` | 12 | 4/7 | 2/7 |
| `scale_025` | 8 | 0/7 | 0/7 |
| `scale_01875` | 6 | 0/7 | 0/7 |
| `native_fs_24` | 24 | 4/7 | 4/7 |
| `native_fs_20` | 20 | 4/7 | 3/7 |
| `native_fs_16` | 16 | 4/7 | 4/7 |
| `native_fs_14` | 14 | 2/7 | 3/7 |
| `native_fs_12` | 12 | 1/7 | 2/7 |
| `native_fs_10` | 10 | 1/7 | 0/7 |
| `native_fs_08` | 8 | 0/7 | 0/7 |

即使 32px 普通文本也只有 5/7 或 3/7 核心 exact；不存在“到了某个字号就统一可读”的阈值。原生 12px 与缩放得到 12px 的表现也不同，不能互相替代。

### 5.2 严格证据字段

严格用例只有 2 个；Tesseract 在有效 32px 的少数条件下通过 1/2：

- `native_fs_32`、`scale_100`、`jpeg_q90`、`jpeg_q70`、`jpeg_q15`、`blur_s2.0`：Tesseract `1/2`。
- 其余所有条件：Tesseract `0/2`。
- EasyOCR：全部条件 `0/2`。
- 所有 24px 及以下条件：两个引擎均为 `0/2`。

EasyOCR 在 32px 清晰图上仍把 `¥` 识别为 `半`，把 `¥99.00` 识别为 `半99.00`。金额、日期、编号等字段不能靠单引擎自动放行。

### 5.3 JPEG 压缩

| 条件 | Tesseract exact / core | EasyOCR exact / core |
|---|---|---:|
| q90 | 4/13 / 7/13 | 1/13 / 5/13 |
| q70 | 4/13 / 7/13 | 1/13 / 5/13 |
| q50 | 3/13 / 7/13 | 1/13 / 5/13 |
| q30 | 3/13 / 7/13 | 1/13 / 5/13 |
| q15 | 4/13 / 8/13 | 1/13 / 5/13 |
| q70 + 0.5 缩放 | 3/13 / 5/13 | 1/13 / 8/13 |
| q40 + 0.5 缩放 | 1/13 / 2/13 | 1/13 / 5/13 |

Tesseract 的 exact 随质量下降不是单调的：q90 与 q15 都是 4/13，q50/q30 反而只有 3/13。不能把 JPEG 质量单独作为通过阈值。

### 5.4 模糊

| σ | Tesseract 核心 exact | EasyOCR 核心 exact | 观察 |
|---:|---:|---:|---|
| 0.5 | 4/7 | 3/7 | 部分可用 |
| 1.0 | 4/7 | 5/7 | 部分可用 |
| 1.5 | 5/7 | 5/7 | 仍可部分识别 |
| 2.0 | 3/7 | 0/7 | EasyOCR 内容失败 |
| 3.0 | 1/7 | 0/7 | 基本失败 |

边界大致在 σ = 1.5–2.0px，但强依赖文本内容和引擎；不能把单一 σ 作为全页阈值。

### 5.5 遮挡与用户补文

遮挡条件覆盖三个区域：

- `evidence`：遮挡矩形覆盖 `编号` 后的数字串 `000123`；可见标签 `编号` 在矩形外。用户补文记 `text=000123`、`context=编号 000123`、`status=user-supplied-unverified`，不进入 exact 通过。
- `mixed_wrap`：Tesseract 输出 `FAIZ ... iX RATS Peel`，EasyOCR 也丢失中段；两者都产生了看似合理但与原文不符的文本。
- `cjk_wrap`：中段被遮挡后出现 `F 予`、`亨`、`半1,280.00` 等替换；金额字段同样被破坏。

所有遮挡记录都标 `content_status=unknown`。OCR 的输出不能证明遮挡区域原文；用户补文只是待复核来源。

## 6. 四个维度分别判定

| 维度 | 本实验结果 | 状态 |
|---|---|---|
| 内容转写（普通清晰文本） | 32px 普通用例 T 5/7、E 3/7；16px 各 4/7；12px 为 1/7、2/7；8px 为 0/7、0/7 | `partial` |
| 内容转写（对抗字符） | 324 条 exact 为 0；核心字符 71/324 | 严格 exact `fail`；核心字符 `partial` |
| 内容转写（证据字段） | 仅 Tesseract 在有效 32px 的少数条件通过 1/2；EasyOCR 全部 0/2 | `fail`（窄边界之外） |
| 可见断行 | 677/702 行数匹配；但其中 447 条核心字符错误；EasyOCR 0.25 缩放 13/13 行数匹配而核心 exact 0/13 | `partial`，必须由内容可读性门控 |
| 文本框 | 122 pass / 319 partial / 246 fail / 15 unknown；整体 IoU 中位数 0.810（p10–p90 0.616–0.929） | `partial`，不能证明内容正确 |
| 字形可分性 | 32px 4/14 对不可分；16px 5/14；12px 12/14；10px 10/14；8px 9/14 | `partial`，仅本字体/渲染器局部标定 |
| 基线 | 本实验未从静态截图测量；OCR 框底与 DOM 基线差中位数 0.406 倍墨迹高度，p10–p90 0.125–0.656。`R3-EXP-14` 在已知字体/字号下补测，最大误差 0.5px | 本实验 `not-evaluated`；已知字体/字号下 `partial`（`R3-EXP-14`），未知字体/字号仍 `unknown` |

### 6.1 文本框不能替代内容

- exact 记录的 line-box IoU：中位数 0.803，范围 0.654–0.946。
- 内容错误记录的 IoU：中位数 0.819，范围 0.024–0.965。
- 687 条有 IoU 的记录中，整体中位数 0.810。

错误内容的框甚至可能比正确内容更“像”。因此高 IoU 只能说明框接近，不能说明文字正确。

### 6.2 行数匹配不能单独通过

702 条中有 447 条“行数匹配但核心字符错误”。尤其是 EasyOCR 在 0.25 缩放时 13/13 行数匹配、核心 exact 0/13。断行验收必须先满足内容可读性门控，再判断行数和行序。

### 6.3 OCR 置信度不能单独通过

| 引擎 | mean_conf ≥ 0.8 接受 | 其中错误 | 高置信错误 |
|---|---:|---:|---:|
| Tesseract | 188 | 128 | 128 |
| EasyOCR | 50 | 36 | 36 |

高置信错误共 164 条。代表例子：

- EasyOCR 置信度 0.983：`省略号……测试…` → `省略号测试`，省略号和三点全部丢失。
- EasyOCR 置信度 0.981：`三点...测试...` → `三点测试`。
- Tesseract 置信度 0.957：`0O〇 O0〇 00OO` → `000 000 0000`。
- Tesseract 置信度 0.960：`三点...测试...` → `三点测试`。

原始置信度只能作为候选排序或复核优先级，不能作为自动接受门槛。

## 7. 阈值与失败边界

1. **没有统一字号阈值。** 16px 原生文本两个引擎都只有 4/7 核心 exact；12px 降到 1/7 与 2/7；8px 为 0/7。32px 也不是全通过。
2. **没有统一压缩阈值。** JPEG q90–q15 的 exact 非单调；q15 与 q90 同为 4/13，q50/q30 为 3/13。
3. **模糊边界约在 σ 1.5–2.0px，但内容相关。** EasyOCR 在 σ2.0 降到 0/7；Tesseract 仍有 3/7。
4. **缩放 0.25 与 0.1875（有效 8/6px）两个引擎核心 exact 均为 0/7。** 0.375（12px）仍有 T 4/7、E 2/7，说明不能只按“等效字号”推断，重采样与原生渲染不同。
5. **行数、IoU、OCR 置信度都不能单独通过。** 它们分别只覆盖断行、框和引擎自评，不覆盖字符正确性。
6. **证据字段必须严格 exact。** 窄通过的只有 Tesseract + 有效 32px + 少数条件；EasyOCR 在清晰 32px 仍会把 `¥` 识别错。
7. **字形阈值只在本环境成立。** 32px 下 `l/I`、`未/末`、`土/士`、`，/,` 仍不可分；16px 还增加 `人/入`。12px 有 12/14 对不可分。16px JPEG q50 有 8 对不可分，blur σ1 有 7 对。
8. **遮挡与补文不能转成事实。** OCR 会编造合理文本；`user-supplied` 保持 `unverified`，并与 OCR 输出分开。

## 8. 观测、推导与推断

| 层 | 内容 |
|---|---|
| 观测 | PNG/JPEG 像素；逐 token 文本、框和原始置信度；受控页 DOM 行盒/基线（仅评估） |
| 推导 | `exact`、CER、核心 CER、行数匹配、IoU/edge error、置信度扫描、字形 NCC 距离与 ratio |
| 推断 | 双引擎候选 + 人工复核的验收策略；失败边界解释；按内容类型分级的建议 |
| 未测 | 未知字体/字号的静态基线、其他字体/渲染器/OCR 版本、旋转/竖排、真实站点、语义纠错、跨 DPI、Figma 写入；已知字体/字号的静态基线见 `R3-EXP-14`，跨渲染器见 `R3-EXP-13`（Firefox 未覆盖） |

## 9. 验收建议（推断，不是已验证策略）

- 普通文本：双引擎各自输出候选；核心字符一致时进入复核，不一致时保留 `candidate_chars` 和框。
- 证据字段（金额、日期、编号、姓名）：必须严格 exact；任引擎不一致即 `manual-review-required`，不能自动接受。
- 对抗字符（相似汉字、`0/O/〇`、`1/l/I`、全角标点、省略号）：始终保留候选与失败边界，不设自动通过。
- 断行：先通过内容可读性门控，再比较行数和行序；行数匹配本身不构成通过。
- 文本框：只用于输出框估计和人工定位，不作为内容验收证据。
- 基线：未知字体/字号保持 `unknown`；只有已知字体文件与字号时，才允许使用 `R3-EXP-14` 的静态估计，并保留其误差与适用边界。

## 10. 不得宣称

- 不得宣称“12px 或 16px 文本统一可读”。
- 不得宣称“OCR 置信度大于 0.8 即可接受”。
- 不得宣称“JPEG 质量高于某个值即可接受”。
- 不得宣称“行数匹配等于断行正确”。
- 不得宣称“文本框 IoU 高等于文字正确”。
- 不得宣称“字形 ratio 阈值可跨字体通用”。
- 不得把 `R3-EXP-14` 的已知字体/字号估计写成通用基线验证；未知字体/字号仍不得宣称基线。
- 不得宣称“OCR 恢复了被遮挡内容”或“用户补文已验证”。
- 不得把本实验外推到真实站点、其他语言、其他字体或其他 OCR 版本。

## 11. 证据文件

- `output/_r3_experiments/exp08_text_acceptance.py`
- `output/_r3_experiments/exp08_text_acceptance.json`（含逐 token `ocr_tokens`、`review_status`、完整 summary）
- `output/_r3_experiments/exp08_text_site/index.html`
- `output/_r3_experiments/exp08_glyph_site/*.html`
- `output/_r3_experiments/exp08_contact_sheet.png`
- `output/_r3_experiments/exp08_fs_08..32[_dpr2].png`
- `output/_r3_experiments/exp08_scale_*.png`
- `output/_r3_experiments/exp08_jpeg_q*.jpg`
- `output/_r3_experiments/exp08_blur_*.png`
- `output/_r3_experiments/exp08_occlusion.png`
- `output/_r3_experiments/exp08_glyph_index*.png`

## 12. 状态与后续

- 本实验状态：`completed-for-current-scope`，不是 `verified`。
- 未闭合：未知字体/字号的静态基线、跨字体/渲染器/OCR 版本标定、真实站点、旋转/竖排、跨 DPI、语义纠错、人工复核完成度。已知字体/字号的静态基线由 `R3-EXP-14` 补做，跨渲染器由 `R3-EXP-13` 补做（Firefox 未覆盖）。
- `R2-EXP-01` 已在 authored DOM 上完成，见 `R2_EXP_01_DOM_FLOW_PERTURBATION.md`；其扰动类型也由 `R3-EXP-10` 在输出合同层覆盖，但原站 DOM 与原站响应式仍未验收。`R2-EXP-02` 已并入 `R3-EXP-09`。
- 该记录完成时下一步为 `R3-EXP-09`；后续 `R3-EXP-09–15` 均已完成当前范围。R4 已由用户明确同意并完成 `R4-EXP-01–10` 当前范围。
