# R3-EXP-11 · 四项验收样例集与评分校准（受控实验）

> 状态：`completed-for-current-scope`（2026-10-18），不是 `verified`。  
> 范围：24 个合成基础样例（标定集 12 + 验收集 12）× 6 个变体 = 144 张截图；每集 288 次四维状态比较。  
> 证据：`output/_r3_experiments/exp11_acceptance_calibration.json`、`output/_r3_experiments/exp11_acceptance_site/`、`output/_r3_experiments/exp11_artifacts/`、`exp11_contact_sheet.png`、`exp11_variant_strip.png`、`exp11_typo_zoom.png`、`exp11_asset_strip.png`。  
> 边界：只验证“四项验收器能否在受控差分中把已注入缺陷定位到对应维度”。不验证生产重建器、OCR、Figma 写入、真实站点或截图结构推断。

## 1. 目的与边界

本实验回答五个问题：

1. 固定样例集能否覆盖中文、英文、混排、图标/logo、复杂背景、长页六类页面，并各含清晰与困难输入。
2. 同一样例只注入一个缺陷时，四项维度能否分别给出 `pass / partial / fail / unknown`，而不是用单一像素分数代替。
3. 在标定集上选出的阈值冻结后，能否在独立验收集上复现同样的状态判断。
4. 能否区分“视觉相同但资产不可替换”“视觉通过但编辑传播失败”“视觉通过但结构角色错误”。
5. 报告能否写清评分分母、`partial` 的有效/无效区域、`unknown` 与未测项，而不是把未覆盖部分算进通过分子。

所有页面都是实验者编写的合成夹具，候选页是“基准页 + 一个受控变体”的差分，不是独立重建结果。因此本实验标定的是**验收判定器**，不是截图 → Figma 重建器的准确率。具体边界：

- 内容 exact 使用基准页与候选页的 DOM 文本回读，不是 OCR；它验证比较器与阈值，不验证 OCR 识别能力。
- 结构树来自夹具 DOM 的 authored 候选树，不是从截图自动推断；遮挡下的截图结构推断未测。
- 编辑探针使用 DOM 文本节点与 CSS 布局传播，不是 Figma 原生文本层或 Auto Layout 写入。
- 资产探针使用已知 DOM 图片层与隐藏层操作；生产环境是否有同样的探针未知。
- 未调用 Figma 写路径，未修改 `src/`、`figma_bridge/`。

## 2. 环境与可复现性

| 项目 | 值 |
|---|---|
| 操作系统 | Windows 11（`10.0.26300`） |
| Python | 3.12.0（`C:\Users\lzq\.conda\envs\omni\python.exe`） |
| Chromium | 151.0.7922.34（Playwright headless） |
| 视口 | 1100×900，DPR 1 |
| 页面宽度 | 1040 px |
| 字体 | Microsoft YaHei / Segoe UI（系统字体） |
| 捕获 | full-page PNG |
| 脚本 | `output/_r3_experiments/exp11_acceptance_calibration.py` |

重跑命令：

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe output/_r3_experiments/exp11_acceptance_calibration.py
```

脚本会重建 `exp11_acceptance_site/` 与 `exp11_artifacts/`，为每个样例生成基准页与 6 个变体；每页另存 `tile_visible` / `tile_hidden` 探针图。当前产物为：

- 144 个 HTML、72 个站点资源（每样例 `tile_bg`、`logo_layer`、`composite`）；
- 144 张变体截图、288 张资产探针图，共 432 张 PNG；
- 1 个 JSON、4 张联系/放大图。

## 3. 方法

### 3.1 样例矩阵

每个集合 12 个基础样例 = 6 类 × 2 个难度；两个集合共 24 个。页面宽度统一为 1040 px；除长页外，目标卡片是第 1 段，长页目标卡片是第 3 段。每页第 1 段有一个 160×160 的品牌 tile；长页共 5 段。

| 类别 | clear | hard | 主要差异 |
|---|---|---|---|
| 中文 `zh` | `cal/val-zh-clear` | `cal/val-zh-hard` | 正文宽 680→320 px、字号 17→13 px、低对比、窄栏断行 |
| 英文 `en` | `cal/val-en-clear` | `cal/val-en-hard` | 正文宽 650→240 px、字号 16→12 px、长单词与字距 |
| 混排 `mixed` | `cal/val-mixed-clear` | `cal/val-mixed-hard` | 中文、Latin runs、tabular numbers；字距 0.25→0.30 px |
| 图标/logo `icon_logo` | `cal/val-icon_logo-clear` | `cal/val-icon_logo-hard` | 细线、低对比、小尺寸 logo；正文 650→520 px |
| 复杂背景 `complex_bg` | `cal/val-complex_bg-clear` | `cal/val-complex_bg-hard` | 纹理 + 渐变背景；半透明面板 alpha 0.86→0.55 |
| 长页 `long_page` | `cal/val-long_page-clear` | `cal/val-long_page-hard` | 5 段、目标第 3 段；hard 源输入缺少 `s3-kicker`，第 4 段重复标题 |

长页 hard 的缺 kicker 与重复标题是**源输入异常**，在基准页和所有候选中保留，不是注入缺陷，也不是缺项缺陷样例。报告必须原样披露，不能自动补全。

### 3.2 六个变体与预期

| 变体 | 注入方式 | 预期 visual | 预期 structure | 预期 edit | 预期 asset |
|---|---|---|---|---|---|
| `baseline` | 无变化 | pass | pass | pass | pass |
| `typo` | 目标正文替换一个字符 | fail | pass | pass | pass |
| `occlusion` | 目标正文上覆盖一个不透明块 | partial | pass | pass | pass |
| `synthetic_asset` | 第 1 段 tile 换成“背景 + logo”的烘焙合成图 | pass | pass | pass | fail |
| `no_propagation` | 目标卡固定高度，页脚改为绝对定位 | pass | pass | fail | pass |
| `structure_role` | 目标标题从 `h2` 改为 `p` | pass | fail | pass | pass |

`synthetic_asset` 是“视觉相同但资产不可替换”的构造反例：合成图是基准 tile 的烘焙截图，像素接近由构造保证；隐藏图片层后背景不会保留。`no_propagation` 与 `structure_role` 用来证明视觉 pass 不能替代编辑/结构结论。

### 3.3 四项状态判定

| 维度 | 主要证据 | 判定规则 |
|---|---|---|
| visual | 对象级内容 exact、字符级 exact、行数、文本框 IoU、局部字形误差、目标卡像素 MAE | 内容或字符低于阈值即 `fail`；否则行数、字形、几何、像素依次判定。有对象因遮挡而内容未知时，其他有效指标通过则 `partial`，否则 `fail` |
| structure | 稳定对象 id 上的角色、父关系、边界 IoU | 有缺项/多项、角色或父关系低于阈值、边界 IoU 低于阈值则 `fail`；本实验只产生 `pass/fail` |
| edit | 目标卡 3 个原生文本对象比例、受控文本增长后的传播误差 | 原生文本比例 <1 或传播误差 >16 px 则 `fail`；探针无效则 `unknown` |
| asset | 隐藏图片层后的变化比例、四角是否保留 | `layer_isolation` <0.5 或 `corner_unchanged` <0.5 则 `fail`；本实验只产生 `pass/fail` |

状态函数不读取变体标签；标签只用于标定集上的阈值选择与最终评分。`unknown` 不进入通过分子；`partial` 也不是完全通过。

### 3.4 阈值标定与冻结

14 个指标分别在标定集上做一维候选网格扫描，选择使二分类状态最接近预期标签的阈值；可分离时取“通过侧最小值与失败侧最大值的中点”并吸附到候选网格。没有注入对应缺陷的指标使用合同值或干净噪声边界。阈值选择只使用标定集，随后冻结；验收集只用于评分，不参与扫描。

因此“可判别”只表示本夹具上存在正间隔，不表示阈值是唯一最优点。例如 `edit_propagation_error_px_max` 在 0.25–16 px 的全部候选上都得到 72/72，`asset_layer_isolation_min` 在 0.2–0.85 上都得到 72/72；这些值只是平台区间内的工程选择。

### 3.5 独立性审计

- 标定集 12 张 baseline 截图哈希互不相同；验收集 12 张也互不相同。
- 跨集合没有重复截图、没有重复 HTML、没有重复正文。
- 两集使用不同 sample id、不同正文与页脚；但由同一实验者、同一生成器、同一浏览器/字体/DPR 生成。这里的“独立”是留出样本独立，不是独立作者或独立环境。

## 4. 标定集结果

| 指标 | 结果 |
|---|---|
| 四维状态匹配 | 288/288（1.0） |
| 故障目标维度命中 | 60/60（1.0） |
| 跨维度误报 | 0/180（0.0） |
| baseline 假报警 | 0/12 |

逐变体状态（12 个样例）：

| 变体 | visual | structure | edit | asset |
|---|---|---|---|---|
| `baseline` | pass 12 | pass 12 | pass 12 | pass 12 |
| `typo` | fail 12 | pass 12 | pass 12 | pass 12 |
| `occlusion` | partial 12 | pass 12 | pass 12 | pass 12 |
| `synthetic_asset` | pass 12 | pass 12 | pass 12 | fail 12 |
| `no_propagation` | pass 12 | pass 12 | fail 12 | pass 12 |
| `structure_role` | pass 12 | fail 12 | pass 12 | pass 12 |

## 5. 验收集结果

验收集与标定集逐项一致：

| 指标 | 标定集 | 验收集 |
|---|---|---|
| 四维状态匹配 | 288/288 | 288/288 |
| 故障目标维度命中 | 60/60 | 60/60 |
| 跨维度误报 | 0/180 | 0/180 |
| baseline 假报警 | 0/12 | 0/12 |

两个集合的四维混淆表相同（每格为 12 个样例 × 6 个变体 = 72 次比较）：

| 预期 \ 观测 | pass | partial | fail | unknown |
|---|---|---|---|---|
| pass | visual 48 / structure 60 / edit 60 / asset 60 | 0 | 0 | 0 |
| partial | 0 | visual 12 | 0 | 0 |
| fail | 0 | 0 | visual 12 / structure 12 / edit 12 / asset 12 | 0 |
| unknown | 0 | 0 | 0 | 0 |

表中 `structure/edit/asset` 没有 `partial` 或 `unknown` 预期行，用 0 表示未出现；`visual` 的 48 个 pass 来自 baseline 与三个非视觉故障变体。所有观测都没有落在 `unknown` 列。

## 6. 四项独立报告

| 维度 | 证据链 | 标定集分母 | 标定集结论 | 验收集结论 | 未测 |
|---|---|---|---|---|---|
| visual | 对象/字符 exact、行数、字形、几何、像素 | 79 个文本对象、2693 字符、135 个几何对象、2,474,048 个目标卡像素 | typo fail 12/12；occlusion partial 12/12；其余 pass | 同左，字符数 2691 | 字体替换、OCR、压缩、低清、断行/边界/几何专项缺陷 |
| structure | 稳定 id 的角色、父关系、边界 IoU | 135 个结构对象、135 个边界配对 | role fail 12/12；其余 pass | 同左 | 截图自动结构推断、parent-only/boundary-only 缺陷、遮挡下结构推断 |
| edit | 目标卡 3 个原生文本对象、文本增长传播 | 12 个目标卡、12 个传播用例、36 个原生文本对象 | no_propagation fail 12/12；其余 pass | 同左 | 其他卡片/段落、Figma 原生文本与 Auto Layout 写入 |
| asset | 隐藏图片层探针 | 12 个资产槽 | synthetic_asset fail 12/12；其余 pass | 同左 | 多资产、`reference-only`/`constrained` 资产、生产探针可用性 |

要点：

- 视觉维度的 `typo` 失败由对象/字符 exact 与局部字形共同支持；目标卡像素 MAE 只作辅助，单字符错字不一定超过 0.1。
- 结构维度的 `structure_role` 只改一个对象的角色；单页 7/8=0.875，长页 27/28=0.964286。父关系与边界在本实验中没有对应缺陷，不能称为已验证判别阈值。
- 编辑维度的 `no_propagation` 让正文增长 375–760 px，但页脚与卡片增长为 0；传播误差为 375–760 px，其他视觉指标不变。
- 资产维度的 `synthetic_asset` 让隐藏图片层后的变化比例达到 0.995234–0.995820，隔离度降到 0.00418–0.00477；正常资产隔离度为 0.966133–0.979141。

## 7. 定位、裕量与失败模式

| 故障 | 目标维度 | 目标观测 | 目标命中 | 跨维误报 | 关键实测 |
|---|---|---|---|---|---|
| 单字符错字 | visual | fail | 12/12 | 0/36 | 对象 exact 1.0 → 0.75–0.95；字符 exact 1.0 → 0.99115–0.99843；字形 0–1.54 → 9.13–43.02 |
| 目标正文遮挡 | visual | partial | 12/12 | 0/36 | 变化区域占目标卡 4.18%–10.01%；非遮挡最大 0.25%；区域 MAE 105.59–172.99 |
| 烘焙合成资产 | asset | fail | 12/12 | 0/36 | 隔离度 0.966–0.979 → 0.00418–0.00477；四角保留 1.0 → 0.0；视觉字形仍 0–1.54 |
| 不传播高度 | edit | fail | 12/12 | 0/36 | 正文增长 375–760 px，页脚/卡片增长 0；传播误差 0 → 375–760 |
| 结构角色错误 | structure | fail | 12/12 | 0/36 | 角色准确率 1.0 → 0.875–0.964286；父关系/边界仍 1.0 |

可分性说明：

- 错字的对象 exact 裕量为 0.05（1.0 vs 0.95），字符 exact 裕量约 0.00157；两者都依赖对象数量与页面字符数。当前页面只有 4–20 个文本对象、113–638 个字符；在更大的页面上，单个错字可能被比例阈值稀释，本轮没有覆盖。
- 字形局部误差的裕量为 7.59（通过 0–1.54，失败 9.13–43.02），是本实验最稳定的视觉信号之一。
- 传播误差的裕量为 375，阈值 16 px 是候选网格上限，不是 375 的中点；它足以分离本夹具，但不是精确的工程最优值。
- 遮挡面积比在 2% 阈值两侧为 0.25% 与 4.18%–10.01%；小于 2% 的遮挡是否仍可检出未测。
- 资产隔离度与四角保留都出现巨大间隔；但只测了一个 tile 槽，不能替代 EXP-09 的资产分类与替换成本结论。

## 8. 阈值、来源与状态

| 阈值 | 值 | 通过侧实测 | 失败侧实测 | 间隔 | 来源/性质 |
|---|---:|---|---|---:|---|
| `content_object_exact_min` | 0.98 | 1.0 | 0.75–0.95 | 0.05 | 标定；对象级 exact |
| `content_character_exact_min` | 0.999 | 1.0 | 0.99115–0.99843 | 0.00157 | 标定；字符级 exact |
| `linebreak_match_min` | 1.0 | 1.0 | 无失败样本 | — | 合同值；无断行专项缺陷 |
| `glyph_local_mae_max` | 4.0 | 0–1.54297 | 9.1328–43.0234 | 7.5898 | 标定；16×16 局部块最大误差 |
| `pixel_card_mae_max` | 0.1 | 0–0.005833 | 无干净失败样本；typo 0.0102–0.2053 | — | 干净噪声上界 + 余量；不是错字判别阈值 |
| `geometry_min_iou_min` | 0.999 | 1.0 | 无失败样本 | — | 干净噪声边界；无几何专项缺陷 |
| `structure_role_accuracy_min` | 0.98 | 1.0 | 0.875–0.964286 | 0.035714 | 标定；authored id 角色匹配 |
| `structure_parent_accuracy_min` | 0.999 | 1.0 | 无失败样本 | — | 干净噪声边界；无 parent-only 缺陷 |
| `structure_boundary_min_iou_min` | 0.999 | 1.0 | 无失败样本 | — | 干净噪声边界；无 boundary-only 缺陷 |
| `edit_native_text_ratio_min` | 1.0 | 1.0 | 无失败样本 | — | 合同值；所有夹具保留原生文本 |
| `edit_propagation_error_px_max` | 16.0 | 0 | 375–760 | 375 | 标定；候选网格上限，非精确中点 |
| `asset_layer_isolation_min` | 0.5 | 0.966133–0.979141 | 0.00417969–0.00476562 | 0.961367 | 标定；隐藏图片层探针 |
| `asset_corner_unchanged_min` | 0.5 | 1.0 | 0.0 | 1.0 | 标定；四角探针 |
| `change_region_ratio_min` | 0.02 | 遮挡 0.0418–0.1001 | 非遮挡 0–0.0025 | 0.0393 | 标定；最大变化块占目标卡比例 |

其中 `linebreak / pixel / geometry / parent / boundary / native` 没有对应的注入故障变体，只能写“干净噪声上界、合同值或未测”，不能写成“已标定判别阈值”。`pixel_card_mae_max` 尤其不能替代内容与字形：一个字符的错字像素 MAE 可低至 0.0102，低于 0.1。

## 9. `partial`、`unknown` 与源输入异常

本实验唯一出现的维度级 `partial` 是 12 个遮挡样例的 visual。报告要求如下：

- **有效区域**：目标卡内未被变化块覆盖的区域，约占目标卡 89.99%–95.82%。
- **不可用/未知区域**：变化块本身，占目标卡 4.18%–10.01%；每个样例恰好覆盖一个正文对象（单页 `s1-body`，长页 `s3-body`）。
- **缺口**：该正文对象的内容、断行与字形证据为 `unknown`，不进入内容通过分子；目标卡其余 3 个文本对象与其他段落仍可验证。
- **影响**：不能宣称整个目标卡内容通过；不能从遮挡区域反推原文字；不能用其他区域的平均值掩盖该缺口。
- **不可做的编辑**：不能在没有原分辨率证据时改写、补全或重排被遮挡正文；不能用生成式补图冒充原内容。
- **人工复核项**：提供被遮挡正文的原分辨率图、截图源或准确转写；用户补文必须记 `user-supplied`，并重新做内容、断行与字形验收。
- **结构限制**：遮挡样例的结构 `pass` 来自夹具 authored DOM 未变化，不是从遮挡截图推断出结构；因此不能写成“遮挡下结构推断通过”。

另外两点必须披露：

1. 顶部 `unknown` 状态没有被实际触发。本实验的四维观测只有 `pass / partial / fail`；遮挡的正文对象在内容诊断中为 `unknown`，但维度状态是 `partial`。因此“维度级 unknown 的报告格式”仍未验证。
2. 长页 hard 的 `s3-kicker` 缺失与第 4 段重复标题是源输入异常，基准和候选都保留；本实验没有注入“缺项”或“重复项”作为独立缺陷，也没有验证自动修复策略。

## 10. 评分分母与覆盖

| 分母 | 标定集 | 验收集 | 说明 |
|---|---:|---:|---|
| 页面 | 12 | 12 | 每集合 6 类 × 2 难度 |
| 目标区域 | 12 | 12 | 每页一个目标卡；长页为第 3 段 |
| 文本对象 | 79 | 79 | 单页 4 个；长页 clear 20 个、hard 19 个（缺 kicker） |
| 字符 | 2693 | 2691 | 两集正文与页脚不同，字符数略有差异 |
| 结构对象 | 135 | 135 | 单页 8 个；长页 28/27 个 |
| 边界配对 | 135 | 135 | 稳定 id 与矩形 IoU 配对 |
| 目标卡像素 | 2,474,048 | 2,474,048 | 12 张目标卡合计，均值约 206,171 像素/卡 |
| 编辑探针卡 | 12 | 12 | 每页只探测一个目标卡 |
| 传播用例 | 12 | 12 | 每目标卡一次受控文本增长 |
| 原生文本对象 | 36 | 36 | 每目标卡 3 个（标题、正文、页脚；kicker 未纳入） |
| 资产槽 | 12 | 12 | 每页第 1 段一个 tile 槽 |
| 段落总数 | 20 | 20 | 10 个单段页 + 2 个 5 段长页 |
| 已探测编辑段 | 12 | 12 | 每页仅目标段 |
| 未探测编辑段 | 8 | 8 | 两个长页各 4 个非目标段 |

因此，本实验的四维结论只覆盖上表列出的分母。编辑只覆盖 12/20 段，8 个非目标段未探测；长页的其他段落、其他卡片、其他资产槽没有进入通过分子；资产槽与编辑目标段在长页上也不是同一区域（资产在第 1 段，编辑目标在第 3 段）。

## 11. 限制与未测

1. 所有夹具由同一实验者编写；候选是基准加单缺陷的差分，不是独立重建，也不是真实站点。
2. 标定与验证使用同一浏览器、OS、字体栈与 DPR=1；跨渲染器、跨 DPI、跨字体回退未测。
3. 结构候选树来自夹具 DOM；纯截图结构推断、尤其遮挡下的推断未测。
4. 未注入字体替换、OCR、压缩、低清、断行专项、边界专项、几何专项、缺项、多状态缺陷。
5. 资产替换用已知 DOM 图片层与隐藏层探针测量；生产环境是否有该探针未知。
6. 合成图是基准 tile 的烘焙截图，视觉相同是构造保证，不是自然合成结果。
7. 阈值是本夹具集的局部工程边界，不是通用产品阈值；没有独立人工标注或标注者一致性。
8. 每个样例只测一个 tile 槽与一个目标卡；其他卡片/段落未探测。
9. 没有宣称四项验收器生产就绪或已通用验证。
10. 维度级 `unknown` 未触发；`partial` 只在 visual 出现，结构/编辑/资产的 `partial` 报告未测。
11. 当前页面规模为 4–20 个文本对象、113–638 个字符；比例阈值在更大页面上可能失去单字符敏感性。
12. 长页 hard 的缺 kicker 与重复标题是源输入异常，不是缺陷注入；缺项缺陷仍未实例化。
13. 编辑探针是 DOM 文本节点与 CSS 传播，不是 Figma 原生文本或 Auto Layout 写入。
14. 没有真实站点、懒加载、轮播帧、sticky/fixed、多状态参考或人工复核数据。

## 12. 不得宣称

- 不得宣称“四项验收器已通用验证”或“生产就绪”。
- 不得把 288/288 写成真实站点准确率、重建质量或 OCR 准确率。
- 不得把视觉 `pass` 写成资产可替换；`synthetic_asset` 就是视觉相同但资产 `fail` 的反例。
- 不得把结构 `pass` 写成截图结构推断通过；结构树是 authored DOM。
- 不得把编辑 `pass` 写成 Figma 原生文本可编辑或 Auto Layout 传播通过。
- 不得把 `unknown` 当作可接受误差或 0；不得把 `partial` 写成完全通过。
- 不得自动修复长页 hard 的源输入异常，或把源输入异常算作重建错误。
- 不得把本实验阈值外推到其他字体、浏览器、DPR、页面规模或真实站点。
- 不得用单一像素分数、平均相似度或总分替代四项独立结论。

## 13. 证据文件

- `output/_r3_experiments/exp11_acceptance_calibration.py`
- `output/_r3_experiments/exp11_acceptance_calibration.json`
- `output/_r3_experiments/exp11_acceptance_site/`（144 个 HTML、72 个资源）
- `output/_r3_experiments/exp11_artifacts/`（144 张变体截图、288 张探针图）
- `output/_r3_experiments/exp11_contact_sheet.png`（24 个 baseline 样例）
- `output/_r3_experiments/exp11_variant_strip.png`（6 个变体状态）
- `output/_r3_experiments/exp11_typo_zoom.png`（单字符错字放大）
- `output/_r3_experiments/exp11_asset_strip.png`（可见/隐藏层探针）

## 14. 状态与后续

- 本实验状态：`completed-for-current-scope`，不是 `verified`。
- 当前范围：六类 × 两难度 × 六变体的四项验收状态标定与留出验证；`unknown` 维度级报告、真实站点、OCR、Figma 写入、多状态参考均未覆盖。
- 后续 `R3-EXP-12–15` 均已完成当前范围；R4 已由用户明确同意并完成 `R4-EXP-01–10` 当前范围。
