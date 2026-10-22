# R3-EXP-09 · 裁片来源、替换能力与共享图成本（受控实验）

> 状态：`completed-for-current-scope`（2026-10-18）。
> 范围：单个受控合成页面，9 个资产用例，1x/2x 两档成本，9 次矩形替换。
> 证据：`output/_r3_experiments/exp09_asset_contract.json`、`exp09_asset_site/`、`exp09_contact_sheet.png`、`exp09_replacement_diff_sheet.png`。
> 边界：本实验只定义当前受控页面的工程边界；不构成通用分类器，也不得写成 `verified`。

## 1. 目的与边界

本实验回答五个问题：

1. `provenance`（来源）与 `replaceability`（可替换能力）能否分开判断，而不是用一个“派生/独立”标签覆盖。
2. 同封面重复、裁切、缩略、文字盖图、阴影图标、低清 logo、原生徽章和干净照片，能否仅凭截图像素归到正确的替换类别。
3. 相同来源的裁片能否被识别为候选关系，精确重复能否去重，同时不误报无关资产。
4. 共享整页图与独立裁片在 1x/2x、PNG/JPEG 下的导出字节与替换成本差异。
5. 矩形替换是否会误伤窗口内的非目标像素，尤其是合成或受限资产。

页面、素材与 ground truth 由同一作者预先编写。DOM 只用于测量评估窗口；分类只使用隐藏元素后得到的像素差 mask 与图像指标。DOM 窗口矩形与规格矩形在 1x 上逐项比较，`max_dom_rect_delta_css_px=0`。

本实验不覆盖真实站点截图、用户上传截图、Figma 导入/序列化/编辑、透明通道恢复、缺失素材重建或跨页面通用阈值。

## 2. 环境与可复现性

| 项目 | 值 |
|---|---|
| 操作系统 | Windows 11（`10.0.26300`） |
| Python | 3.12.0（`C:\Users\lzq\.conda\envs\omni\python.exe`） |
| Playwright | 1.62.0 |
| Chromium | 151.0.7922.34 |
| OpenCV / NumPy / Pillow | 4.10.0 / 1.26.4 / 12.2.0 |
| 视口/截图 | 1200×900 CSS；DPR 2 截图后 Lanczos 下采样到 1x |
| 字体 | Microsoft YaHei |
| 网络 | 仅本地文件 |
| 页面 | `output/_r3_experiments/exp09_asset_site/index.html` |

脚本：`output/_r3_experiments/exp09_asset_contract.py`。完整重跑约 13 秒，会重新生成页面、DPR2/1x 截图、逐资产隐藏图、mask、裁片、替换图、联系表与 JSON。

```powershell
& 'C:\Users\lzq\.conda\envs\omni\python.exe' output/_r3_experiments/exp09_asset_contract.py
```

## 3. 方法

### 3.1 资产矩阵

9 个资产覆盖四类能力与三种来源关系：

| ID | 构造 | Ground truth 来源 | Ground truth 替换类别 | 1x 窗口 |
|---|---|---|---|---|
| `cover_full_a` | 封面素材 1:1 | `authored-original` | `independent` | 80,120,200×300 |
| `cover_full_b` | 同一封面再次 1:1 使用 | `authored-original` | `independent` | 320,120,200×300 |
| `cover_left_crop` | 封面左 60%，`object-fit:cover` | `authored-source-crop` | `independent` | 560,120,120×300 |
| `cover_small` | 封面缩到 50% | `authored-source-rescale` | `independent` | 1060,170,100×150 |
| `text_over_photo` | 照片 + 不透明标题与价格条 | `composite-photo-and-opaque-overlay` | `reference-only` | 80,520,360×240 |
| `icon_shadow` | RGBA 图标 + CSS `drop-shadow` + 纹理底 | `composite-alpha-icon-shadow-texture` | `reference-only` | 480,520,220×220 |
| `logo_lowres` | 40×40 logo 放大到 160×160 | `authored-low-res` | `constrained` | 740,520,160×160 |
| `flat_badge` | 原生圆角渐变徽章 + 文字 | `native-css` | `constrained` | 940,560,220×90 |
| `clean_photo` | 干净照片 1:1 | `authored-original` | `independent` | 720,170,300×200 |

`flat_badge` 的 ground truth 约束来自“内部文字/渐变必须可编辑”，不是像素低清；这一点与观测原因不一致，见 7.3。

### 3.2 窗口与 mask

对每个资产：

1. 读取测量选择器的 DOM 矩形，仅作为评估窗口。
2. 隐藏该元素，重新截图 DPR2 与 1x。
3. 用隐藏前后最大通道绝对差生成 mask；1x 阈值 3，DPR2 阈值 6。
4. 在 1x 上计算纯度、边界和孔洞等指标；在 2x 上复算 `purity_2x` 与 `boundary_target_ratio_2x`。

mask 隔离的是 CSS 元素，不是语义资产边界。`text_over_photo` 与 `icon_shadow` 的合成关系由页面构造决定，分类器只能看到“窗口内存在非目标像素”这一后果。

### 3.3 指标与分类

| 指标 | 定义 |
|---|---|
| `purity` | 目标 mask 像素 / 窗口像素 |
| `boundary_target_ratio` | 2px 内边界带中的目标 mask 覆盖率 |
| `non_target_std` | 窗口内非目标像素的逐通道标准差均值 |
| `non_target_edge_density` | 非目标像素中 Sobel 幅值 > 20 的比例 |
| `mask_hole_ratio` | 由 border flood fill 隔离出的封闭非目标像素 / 窗口像素 |
| `sharpness_norm` | 长边缩到 200px 后的 Laplacian 方差 |
| `acutance` | `sharpness_norm / grayscale_std²`，内容归一化高频能量 |
| `detail_residual` | 半分辨率往返后的平均绝对误差 |
| `ring_std` | 8px 外环的灰度标准差 |

分类顺序：

1. `purity < 0.02` → `missing`。
2. 任一合成信号成立 → `reference-only`：
   - `purity < 0.75`；或
   - `mask_hole_ratio >= 0.010` 且 `non_target_std >= 8.0`；或
   - `non_target_edge_density >= 0.020` 且 `non_target_std >= 8.0`。
3. `acutance < 0.05` → `constrained`。
4. `purity >= 0.98` 且 `boundary >= 0.98` → `independent`。
5. 其余 → `constrained`。

阈值在页面执行前声明，只作为本页局部工程边界；第 10 节披露首轮失败与被否决的规则。

### 3.4 同源检测

- 灰度 `TM_CCOEFF_NORMED`，模板尺度 0.2–2.0 共 37 档，双向匹配，模板面积至少为另一方的 5%。
- 候选阈值 `0.95`。
- 像素 hash 相同的裁片记 `exact_duplicate`。
- 结果是“同源候选”，不是原文件恢复；不同尺度/裁切的同源裁片仍保留为独立导出项。

36 个有序配对中，6 对为预期同源（封面家族 4 个资产的组合），其余 30 对为负例。

### 3.5 成本与替换

成本模式：

| 模式 | 含义 |
|---|---|
| `shared_page` | 一张整页栅格供 9 个用途共享 |
| `independent_separate` | 9 个独立裁片，不去重 |
| `independent_deduped` | 合并精确像素重复；不同尺度同源裁片不合并 |
| `hybrid_deduped` | 去重裁片 + `flat_badge` 原生重建；`reference-only` 仍作参考栅格 |

PNG 使用默认压缩；JPEG 为 q90、4:4:4。字节数为内存编码长度，不是文件系统占用；另记 1 个紧凑 JSON manifest 为 1636 B，不计入栅格总量。

替换实验把确定性合成图贴入整页或独立裁片，重新编码 PNG，并把变化像素与目标 mask 比较。`collateral_ratio_of_window` = 窗口内被改变的非目标像素 / 整个矩形窗口。替换成本对 9 个资产逐一执行后求和；共享模式每次都重编码整页。

## 4. 总结果

| 指标 | 结果 |
|---|---|
| 资产 | 9 |
| 观测类别 | `independent` 5 / `reference-only` 2 / `constrained` 2 |
| Ground truth 类别 | 5 / 2 / 2 |
| 标签一致 | 9 / 9 |
| 原因一致 | 8 / 9 |
| 同源候选 | 6 TP / 0 FP / 0 FN；precision 1.0、recall 1.0 |
| 精确重复 | `cover_full_a == cover_full_b` |
| 同源最高非候选分 | 0.8739 |
| 同源最低候选分 | 0.9983 |
| 共享整页替换窗口外变更 | 每次 0 像素，其他资产窗口 0 次受影响 |

9/9 标签一致只说明本页 9 个构造用例符合规则；不能据此宣称通用资产分类器已验证。

## 5. 逐资产结果

| ID | purity | boundary | hole | edge | std | sharpness | acutance | 观测 | GT | 原因 |
|---|---:|---:|---:|---:|---:|---:|---:|---|---|---|
| `cover_full_a` | 1.000 | 1.000 | 0.000 | 0.000 | 0.0 | 2030.9 | 0.330 | independent | independent | 一致 |
| `cover_full_b` | 1.000 | 1.000 | 0.000 | 0.000 | 0.0 | 2030.9 | 0.330 | independent | independent | 一致 |
| `cover_left_crop` | 1.000 | 1.000 | 0.000 | 0.000 | 0.0 | 2721.0 | 0.463 | independent | independent | 一致 |
| `cover_small` | 0.999 | 1.000 | 0.001 | 1.000 | 0.6 | 5271.5 | 0.841 | independent | independent | 一致 |
| `text_over_photo` | 0.853 | 0.914 | 0.096 | 0.462 | 93.6 | 2303.6 | 0.709 | reference-only | reference-only | 一致 |
| `icon_shadow` | 0.335 | 0.000 | 0.000 | 0.433 | 4.1 | 98.7 | 0.060 | reference-only | reference-only | 一致 |
| `logo_lowres` | 0.897 | 1.000 | 0.103 | 0.117 | 0.2 | 97.7 | 0.011 | constrained | constrained | 一致 |
| `flat_badge` | 0.972 | 0.911 | 0.021 | 0.665 | 0.6 | 372.0 | 0.506 | constrained | constrained | **不一致** |
| `clean_photo` | 1.000 | 1.000 | 0.000 | 0.000 | 0.0 | 514.9 | 0.279 | independent | independent | 一致 |

2x 复算与 1x 同向：独立资产 `purity_2x` 为 1.000（`cover_small` 为 1.000），`text_over_photo` 为 0.844，`icon_shadow` 为 0.277，`logo_lowres` 为 0.895，`flat_badge` 为 0.965；`icon_shadow` 与 `flat_badge` 的边界覆盖在 2x 仍不足（0.000 与 0.880）。

### 5.1 独立资产

- 4 个封面用途的 `purity` 均 >= 0.999，`boundary` 均 1.000；缩略封面有 9 个非目标像素（0.06%），属窗口边缘抗锯齿。
- `clean_photo` 完全隔离，说明普通不透明照片窗口在该页面上可达到 `independent`。
- `cover_small` 的 `edge=1.000` 但 `non_target_std=0.6`，不触发合成规则；这说明边界像素孤立存在时不能被当作叠层证据。

### 5.2 合成资产

- `text_over_photo`：标题与价格条形成 9.58% 的封闭孔洞，非目标区域 std 93.6，边缘密度 0.462；两条规则同时成立。
- `icon_shadow`：窗口纯度仅 0.335，阴影和纹理底占大部分；边界覆盖为 0，因为目标图标没有贴住窗口内边界。主判定是 `purity < 0.75`。

### 5.3 受限资产

- `logo_lowres`：1x 纯度 0.897、边界 1.000，但 `acutance=0.0111`，远低于 0.05。40×40 源放大 4 倍后的高频能量被内容归一化指标稳定隔离。
- `flat_badge`：纯度 0.972、边界 0.911，未达到 `independent` 的 0.98/0.98；圆角使内边界带不完整，因此观测为 `constrained`。

## 6. 来源与四项能力分离

观测来源全部是 `page-screenshot-crop`，没有一项能回溯到截图之上的原文件。9 个资产的 `traceable` 都是 `partial`：

| 范围 | 资产 | 说明 |
|---|---|---|
| `exact-duplicate-group` | 4 个封面用途 | 可追到精确像素重复组，但未恢复原文件 |
| `composite-window` | `text_over_photo`、`icon_shadow` | 可追到截图窗口，不可追到单一可恢复源层 |
| `single-crop` | `logo_lowres`、`flat_badge`、`clean_photo` | 可追到单个截图裁片，截图之上的来源未知 |

四项能力分别报告：

| ID | 可追溯 | 可导出 | 可独立替换 | 内部可编辑 |
|---|---|---|---|---|
| `cover_full_a` | partial（重复组） | yes | independent | not-observable-from-flat-crop |
| `cover_full_b` | partial（重复组） | yes | independent | not-observable-from-flat-crop |
| `cover_left_crop` | partial（重复组） | yes | independent | not-observable-from-flat-crop |
| `cover_small` | partial（重复组） | yes | independent | not-observable-from-flat-crop |
| `text_over_photo` | partial（合成窗口） | yes | reference-only | not-observable-from-flat-crop |
| `icon_shadow` | partial（合成窗口） | yes | reference-only | not-observable-from-flat-crop |
| `logo_lowres` | partial（单裁片） | yes | constrained | not-observable-from-flat-crop |
| `flat_badge` | partial（单裁片） | yes | constrained | not-observable-from-flat-crop |
| `clean_photo` | partial（单裁片） | yes | independent | not-observable-from-flat-crop |

- “可导出”不等于“可独立替换”：`reference-only` 仍可作为参考图或整窗贴图导出，但不能在不改 baked 内容的前提下独立替换。
- “可独立替换”不等于“内部可编辑”：扁平裁片无法证明文字、渐变或图层参数是否保留。`flat_badge` 的 ground truth 明确要求内部文字/渐变可编辑，但像素观测只能给出 `not-observable-from-flat-crop`。
- 来源可追溯也不等于原始素材已恢复；`exact-duplicate-group` 只证明像素关系。

## 7. 同源候选、去重与误判

### 7.1 封面家族

| 配对 | 分数 | 尺度 | 方向 |
|---|---:|---:|---|
| full_a / full_b | 1.0000 | 1.0 | 精确重复 |
| full_a / left_crop | 0.9999 | 1.0 | 裁片在完整封面内 |
| full_a / cover_small | 0.9988 | 0.5 | 完整封面在缩略图内 |
| full_b / left_crop | 0.9999 | 1.0 | 裁片在完整封面内 |
| full_b / cover_small | 0.9988 | 0.5 | 完整封面在缩略图内 |
| left_crop / cover_small | 0.9983 | 0.5 | 裁片在缩略图内 |

6 对全部命中，0 误报。非候选最高分为 `cover_left_crop / clean_photo` 的 0.8739，低于 0.95 阈值；最低非候选分为 0.2395。

### 7.2 精确重复

`cover_full_a` 与 `cover_full_b` 的 PNG 编码均为 30165 B，裁片 SHA-256 均为 `d5170aaa672ebbc19b7ceee319811ed4e412c533f87c1de8f7d7d4433a17ff28`。去重后 1x PNG 从 181942 B 降到 151777 B，1x JPEG 从 124397 B 降到 106403 B。

### 7.3 `flat_badge` 原因不一致

- 观测：`purity=0.9721`、`boundary=0.9109`，因圆角边界不完整而归 `constrained`。
- Ground truth：内部 `NEW` 文字和渐变必须可编辑，因此归 `constrained`。
- 两者标签相同只是结果巧合；像素分类没有观察到“内部可编辑性”。该条不能计入“原因判断正确”。

## 8. 共享整页图与独立裁片成本

### 8.1 导出字节

| 档位 | 格式 | 共享整页 | 独立不去重 | 独立去重 | 混合去重 |
|---|---|---:|---:|---:|---:|
| 1x | PNG | 161540 | 181942 | 151777 | 145036 |
| 1x | JPEG q90 | 146746 | 124397 | 106403 | 101837 |
| 2x | PNG | 249999 | 239119 | 200740 | 183102 |
| 2x | JPEG q90 | 351640 | 275056 | 237096 | 228726 |

比值（shared/separate）：

| 档位 | PNG | JPEG q90 |
|---|---:|---:|
| 1x | 0.888 | 1.180 |
| 2x | 1.046 | 1.278 |

结论只能写成“在本页本编码器下”：

- 1x PNG 共享整页更小；
- 1x JPEG 与 2x 两种格式，独立裁片更小；
- 去重始终降低独立裁片总量（1x PNG 0.834×、1x JPEG 0.855×、2x PNG 0.840×、2x JPEG 0.862×）；
- 不存在“共享图必然更省”的单调结论。

### 8.2 替换成本

9 次替换的总成本：

| 档位 | 共享整页耗时 / 字节 | 独立裁片耗时 / 字节 | 时间比 | 字节比 |
|---|---:|---:|---:|---:|
| 1x | 188.238 ms / 1,776,774 B | 26.987 ms / 333,626 B | 6.98× | 5.33× |
| 2x | 558.679 ms / 3,422,891 B | 139.171 ms / 1,000,209 B | 4.01× | 3.42× |

共享整页模式每次替换都重编码整页，所以成本随页面尺寸增长；独立裁片只重编码局部窗口。共享模式在 9 次替换中，窗口外变更像素均为 0，其他资产窗口均未被波及。

## 9. 矩形替换碰撞

替换目标覆盖率均为 1.000（`icon_shadow` 为 0.9999，差 1 个抗锯齿像素）。窗口内非目标像素的误伤比例：

| ID | 类别 | 碰撞像素 | 占窗口 | 占非目标 |
|---|---|---:|---:|---:|
| `cover_full_a` | independent | 0 | 0.0000 | 0.0000 |
| `cover_full_b` | independent | 0 | 0.0000 | 0.0000 |
| `cover_left_crop` | independent | 0 | 0.0000 | 0.0000 |
| `cover_small` | independent | 8 | 0.0005 | 0.8889 |
| `clean_photo` | independent | 0 | 0.0000 | 0.0000 |
| `text_over_photo` | reference-only | 12628 | 0.1462 | 0.9968 |
| `icon_shadow` | reference-only | 32181 | 0.6649 | 1.0000 |
| `logo_lowres` | constrained | 2572 | 0.1005 | 0.9742 |
| `flat_badge` | constrained | 522 | 0.0264 | 0.9457 |

独立资产的碰撞为 0 或 0.0005；合成/受限资产为 2.64%–66.49%。`icon_shadow` 的矩形把阴影和纹理底整体替换，`text_over_photo` 的矩形覆盖了标题/价格条，`logo_lowres` 与 `flat_badge` 的碰撞主要来自圆角或白色图形与页面底色的 mask 盲区。

`cover_small` 的 8 个碰撞像素占窗口仅 0.0005，占其极少的非目标像素为 0.8889；读表时应同时看两个分母。

`exp09_replacement_diff_sheet.png` 只显示被误伤的 non-target 像素，黑色表示未被替换为合成图的差异区域；其白色区域是合成图与原图恰好相同的部分，不代表未替换。

## 10. 阈值来源与迭代披露

### 10.1 首轮失败

首轮规则把 `logo_lowres` 与 `flat_badge` 判成 `reference-only`。原因：

- 仅凭“存在封闭孔洞”判断合成，会把白色 logo 图形、徽章白字和圆角背景误当作 baked overlay；
- Laplacian 绝对锐度与“跨内容中位数比值”受图像对比度和内容构成影响，不能稳定隔离低清资产。

首轮失败在本节与 10.3 的 sweep 中披露；最终 JSON 只保留现行规则的结果，不保留该次错误分类记录。

### 10.2 最终规则

- 封闭孔洞只有在 `hole_ratio >= 0.010` **且** `non_target_std >= 8.0` 时才触发合成。
- 低清使用 `acutance = sharpness_norm / grayscale_std²`，阈值 0.05。
- 绝对锐度 30 与中位数比值 0.5 保留为报告指标，但明确标记为被否决的规则。

### 10.3 敏感性 sweep

| 规则 | 扫描范围 | 结果 |
|---|---|---|
| 绝对锐度 | 10–80（6 档） | 所有档位都漏掉 `logo_lowres`（`assets_below=[]`） |
| `acutance` | 0.01–0.20（7 档） | 0.01 漏掉 `logo_lowres`；0.02–0.20 均只隔离 `logo_lowres`，0 FP / 0 FN |

该 sweep 只覆盖 9 个资产，不能证明 0.05 是通用边界。

### 10.4 mask 盲区

像素差 mask 看不见与页面底色完全相同的资产内容：

- `logo_lowres` 的白色 logo 图形形成 10.31% 的封闭孔洞，但其 `non_target_std=0.162 < 8.0`，因此没有触发合成；
- `flat_badge` 的白色 `NEW` 字形成 2.12% 的孔洞，其 `non_target_std=0.62 < 8.0`，同样不触发合成。

这些孔洞是资产内容，不是外部叠层。碰撞统计必须与这一限制一起读。

## 11. 观测、推导、推断与未测

| 层 | 内容 |
|---|---|
| 观测 | DPR2/1x 页面截图；逐资产隐藏图；1x/2x 纯度与边界；编码字节与耗时；矩形替换像素与目标 mask |
| 推导 | purity/boundary/hole/edge/sharpness/ring 指标；同源分数与精确重复组；成本比值与碰撞比例；观测替换类别 |
| 推断 | 资产合同策略候选；哪些合成区域应保持 `reference-only`；何时原生重建优于栅格裁片 |
| 未测 | 真实站点截图；Figma 导入或编辑；透明通道恢复；仅凭像素判断内部可编辑性；原站 DOM flow 扰动（authored DOM 已由 `R2-EXP-01` 覆盖）；跨页面/字体/编码器通用阈值 |

## 12. 不得宣称

- 不得宣称“资产分类器已验证”或“9/9 即通用准确率”。
- 不得宣称“每个裁片都是原始素材”；本实验所有观测来源都只到截图裁片，`traceable=partial`。
- 不得宣称“`derived` 必然可独立替换”；裁切/缩放关系与替换能力是两件事。
- 不得宣称“近似外观可补造 logo 或封面”，也不得宣称单张截图能恢复缺失像素。
- 不得宣称“共享整页图必然更省字节”；1x JPEG 与 2x 结果相反。
- 不得宣称“矩形替换不会误伤内容”；合成/受限资产的碰撞为 2.64%–66.49%。
- 不得宣称“扁平截图证明了透明通道”或“与底色相同即为透明”。
- 不得把 `flat_badge` 的标签一致写成“像素可判断内部可编辑性”；其原因并不一致。
- 不得把本页阈值外推到其他页面、字体、编码器或真实站点。
- 不得宣称 `missing` 状态已被样例覆盖；实验只实现并定义该分支，没有实例化缺失资产。

## 13. 证据文件

- `output/_r3_experiments/exp09_asset_contract.py`
- `output/_r3_experiments/exp09_asset_contract.json`（含逐资产指标、同源配对、成本、替换与限制）
- `output/_r3_experiments/exp09_asset_site/index.html` 与 `assets/`
- `output/_r3_experiments/exp09_page_dpr2.png`、`exp09_page_1x.png`
- `output/_r3_experiments/exp09_masks/`
- `output/_r3_experiments/exp09_crops_1x/`、`exp09_crops_2x/`
- `output/_r3_experiments/exp09_replacement/`
- `output/_r3_experiments/exp09_contact_sheet.png`
- `output/_r3_experiments/exp09_replacement_diff_sheet.png`

## 14. 状态与后续

- 本实验状态：`completed-for-current-scope`，不是 `verified`。
- 已并入 `R2-EXP-02`（共享整页图 vs 独立裁片的字节、导出与替换成本）。
- `R2-EXP-01` 已完成 authored DOM 的 flow 扰动；`R3-EXP-10` 也在输出合同层覆盖了扰动类型，但原站 DOM 与原站响应式仍未验收。
- 后续 `R3-EXP-10–15` 均已完成当前范围；R4 已由用户明确同意并完成 `R4-EXP-01–10` 当前范围。
