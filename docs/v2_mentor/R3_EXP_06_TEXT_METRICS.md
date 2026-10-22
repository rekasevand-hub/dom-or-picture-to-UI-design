# R3-EXP-06 · `normal`、基线与字形阈值（受控实验）

> 状态：`completed-for-current-scope`（2026-10-18）。
> 范围：Windows + Chromium 单一渲染器主实验；`R3-EXP-13` 补 Chromium + WebKit 跨渲染器标定；Firefox、跨版本与其他平台仍为 `not-evaluated`。
> 证据：`output/_r3_experiments/exp06_text_metrics.json` 及同目录 PNG。

## 1. 环境与字体

| 项 | 值 |
|---|---|
| 系统 | Windows |
| Playwright | 1.62.0 |
| Chromium | 151.0.7922.34（headless） |
| 视口 | 1200×1600 |
| 主 DPR | 1 |
| DPR 复核 | 2 |
| 语言 | `zh-CN` |
| 字号 / 行高 | 24px / 32px |
| 网络 | 仅本地 `127.0.0.1`，无远程资源 |
| 动画 | CSS 动画、过渡、光标闪烁全部关闭 |

| 字体文件 | 字节 | SHA-256 |
|---|---:|---|
| `C:\Windows\Fonts\arial.ttf` | 1,045,720 | `B3658EADAE55E682B5F69EB64C439C1ECC8F196C0BB8D4756D145D13BC86476A` |
| `C:\Windows\Fonts\arialbd.ttf` | 989,780 | `E8F4E3BAF6CC35FED6FCCE3A540E8B39E8F6CDA1D22A28F2EC8F526FEF7A43F5` |
| `C:\Windows\Fonts\ariali.ttf` | 721,584 | `86B32DB9A06F9694E2A3760C42E5117BCDC5CC1255BB5186CA8CE0305E22F288` |
| `C:\Windows\Fonts\msyh.ttc` | 19,704,352 | `D79C55E68B1131EEA0CC1C47BE4F572D964F28C682E143DB2AD09C1E4CB07A3F` |
| `C:\Windows\Fonts\msyhbd.ttc` | 16,883,552 | `4508821B3DFFE01F0EF5E5326A3E60DF705A44633858811F67B6982DCE3F6EE6` |
| `C:\Windows\Fonts\seguiemj.ttf` | 12,934,920 | `451DF9BB5546055AF625FF86AA72695DF43E8E170B4C6C1316FE44E9C7A22F7C` |

## 2. 用例

| 用例 | 文本 | 字体 / 样式 | 换行 |
|---|---|---|---|
| `latin_single` | `Hamburgefonstiv` | Arial 400 normal | 否 |
| `latin_multi` | The quick brown fox… | Arial 400 normal | 是 |
| `cjk_single` | 中文测试文本 | Microsoft YaHei 400 normal | 否 |
| `cjk_multi` | 这是一段很长的中文文本… | Microsoft YaHei 400 normal | 是 |
| `fullwidth_punct` | 中文，。！？；：“”（）《》 | Microsoft YaHei 400 normal | 否 |
| `mixed` | 中文 mixed English 123，。ABC | YaHei + Arial 混排 | 是 |
| `digits` | 0123456789 123.45 -67% | Arial 400 normal | 否 |
| `ellipsis` | 省略号……测试… | Microsoft YaHei 400 normal | 否 |
| `bold` | Bold 中文测试 700 | Microsoft YaHei 700 | 否 |
| `italic` | Italic 中文测试 | Arial 400 italic + YaHei fallback | 否 |
| `missing_glyph` | U+10FFFD U+10FFFC | Arial 400 normal | 否 |
| `emoji` | 😀🎉👍 | Segoe UI Emoji 400 normal | 否 |

## 3. 行盒、行进与基线

`line-height` 的计算值在所有用例中都是 `32px`。实测行盒与基线如下；`probe` 是零尺寸、`vertical-align: baseline` 的 inline-block，其 `top` 等于基线。

| 用例 | 行数 | 行顶 | 行进 | 行高 | probe 首/末 | 首末差 | 首行偏移 | 末行偏移 | 探针期间布局变化 | 恢复后变化 |
|---|---:|---|---|---|---:|---:|---:|---:|---|---|
| `latin_single` | 1 | 22 | - | 27 | 44 / 44 | 0 | 22 | 22 | 否 | 否 |
| `latin_multi` | 4 | 102,134,166,198 | 32,32,32 | 27×4 | 124 / 220 | 96 | 22 | 22 | 否 | 否 |
| `cjk_single` | 1 | 276 | - | 31 | 301 / 301 | 0 | 25 | 25 | 否 | 否 |
| `cjk_multi` | 3 | 357,390,423 | 33,33 | 31×3 | 382 / 448 | 66 | 25 | 25 | 否 | 否 |
| `fullwidth_punct` | 1 | 504 | - | 31 | 529 / 529 | 0 | 25 | 25 | 否 | 否 |
| `mixed` | 2 | 585,618 | 33 | 31×2 | 610 / 643 | 33 | 25 | 25 | 否 | 否 |
| `digits` | 1 | 701 | - | 27 | 723 / 723 | 0 | 22 | 22 | 否 | 否 |
| `ellipsis` | 1 | 779 | - | 31 | 804 / 804 | 0 | 25 | 25 | 否 | 否 |
| `bold` | 1 | 860 | - | 31 | 885 / 885 | 0 | 25 | 25 | 否 | 否 |
| `italic` | 1 | 943 | - | 27 | 965 / 965 | 0 | 22 | 22 | 否 | 否 |
| `missing_glyph` | 1 | 1023 | - | 27 | 1045 / 1045 | 0 | 22 | 22 | 否 | 否 |
| `emoji` | 1 | 1101 | - | 32 | 1127 / 1127 | 0 | 26 | 26 | 否 | 否 |

观察：

- Arial 单行/多行的实际行进为 `32`；YaHei 多行与混排为 `33`。`line-height: 32px` 不等于所有字体的实际行进。
- 单 run 用例中，基线偏移等于该元素主字体的 `fontBoundingBoxAscent`：Arial `22`、YaHei `25`、YaHei Bold `25`、Emoji `26`。`italic` 是单个 Arial run，但中文 glyph 由 YaHei fallback 渲染；行盒仍按 Arial 的 `22` 计算，平台字体同时列出 `Arial-ItalicMT` 与 `MicrosoftYaHei`。
- 多行的首末基线差等于 `(行数-1) × 实际行进`：`latin_multi` 为 `96`，`cjk_multi` 为 `66`，`mixed` 为 `33`。
- 探针没有改变容器矩形、`scrollH`、`clientH` 或非零高度行盒；只额外产生 1–2 个零高度矩形分组。移除探针后，布局与测量前完全一致。

## 4. 混排 run 的基线交叉核对

`mixed` 的第一行包含 YaHei 与 Arial 两个 run，它们的矩形顶部不同，但基线相同：

| run | 字体 | run 顶部 | `fontBoundingBoxAscent` | 顶部 + ascent | 共享基线 |
|---|---|---:|---:|---:|---:|
| 0 `中文 ` | Microsoft YaHei | 585 | 25 | 610 | 610 |
| 1 `mixed English ` | Arial | 588 | 22 | 610 | 610 |
| 2 `123，。ABC` 第一行 | Microsoft YaHei | 585 | 25 | 610 | 610 |
| 2 `123，。ABC` 第二行 | Microsoft YaHei | 618 | 25 | 643 | 643 |

探针首/末为 `610 / 643`，首末差 `33`，与第二行行顶 `618` 减第一行行顶 `585` 的 `33` 一致。

这说明：

- `Range` 片段矩形的顶部不能直接当作行盒顶部；混排时 Arial 与 YaHei 的顶部可相差 `3px`。
- 仅按 `top` 相等分组会把同一视觉行拆成两行；本次改为按垂直重叠超过较小矩形高度的一半分组，`mixed` 从错误的 3 组恢复为 2 行。
- 行分组和基线判断应结合 run 级字体度量或可见基线探针，不能只看 `Range.top`。

## 5. Canvas 度量的边界

| 字体 | `fontBoundingBoxAscent` | `fontBoundingBoxDescent` | `actualBoundingBoxAscent` 示例 | `alphabeticBaseline` | `ideographicBaseline` | `emHeightAscent/Descent` |
|---|---:|---:|---:|---:|---:|---|
| Arial | 22 | 5 | 17 | 0 | -5 | null / null |
| Microsoft YaHei | 25 | 6 | 20–21 | 0 | -6 | null / null |
| Segoe UI Emoji | 26 | 6 | 21 | 0 | -6 | null / null |

- Canvas 度量是字体级参考；`actualBoundingBoxAscent` 只覆盖实际墨迹，不等于 CSS 行盒。
- 混排或 fallback 文本的 `measureText` 可能聚合多个字体，不能把单一 `fontBoundingBoxAscent` 当作每个 run 的基线依据。
- `alphabeticBaseline` 为 `0`，`ideographicBaseline` 为 Arial `-5`、YaHei/Emoji `-6`；这是相对 alphabetic 的字体度量，不是页面基线。
- `emHeightAscent/Descent` 在当前 Chromium 返回 null，不能用于本次结论。

## 6. 特殊项

- `bold`：平台字体为 `MicrosoftYaHei-Bold`，13 个 glyph；未观察到需要合成粗体的证据。
- `italic`：平台字体为 `Arial-ItalicMT` + `MicrosoftYaHei`；截图中的中文呈倾斜外观，符合合成斜体候选，但本实验没有证明其具体机制，标 `synthetic-oblique = candidate`。该用例是单 run 内 fallback，行盒仍按 Arial 度量（top `943` + `22` = 基线 `965`）；不能把 fallback 字体度量直接套到整个 run。
- `missing_glyph`：截图显示两个 tofu 方框；平台字体为 `ArialMT`，glyph 数 2。`document.fonts.check` 仍返回 `true`，说明它不能可靠检测缺字。缺字的可渲染性标 `unknown / not-evaluated`，只保留 `observed-tofu`。
- `emoji`：平台字体为 `SegoeUIEmoji`，3 个 glyph；彩色 emoji 正常显示。Emoji 仍按独立用例处理。
- `fullwidth_punct`：单行宽度 `336`，超过 320 的 `.text` 宽度并发生 nowrap 溢出；14 个 glyph 全部由 YaHei 渲染。
- `ellipsis`：宽度 `178.578`，8 个 glyph，均由 YaHei 渲染。

## 7. 噪声与 DPR

- 同一 DPR 1 环境下连续测量 3 次，CSS 度量完全相同。
- DPR 1 与 DPR 2 的容器、行盒、探针和 Canvas CSS 度量完全相同。
- DPR 1 截图 1200×1600；DPR 2 截图 2400×3200，CSS 尺寸仍为 1200×1600。
- 主实验使用 Chromium；`R3-EXP-13` 已补 WebKit 26.5 的 12 用例 × DPR 1/2 标定（基线最大差 0.5px、8/8 检查）。Firefox 本机启动失败（`spawn UNKNOWN`），其他 Chromium 版本和其他操作系统仍为 `not-evaluated`。

## 8. 结论

1. 本次环境中，实际行进必须实测：Arial 为 32，YaHei/混排为 33；不能直接用 `line-height` 或统一的 `1.4em` 代替。
2. 零尺寸基线探针可用于定位 alphabetic 基线：不改变容器、滚动高度、客户端高度或非零行盒；移除后布局完全恢复。探针会额外产生零高度矩形分组，报告时需区分。
3. 单字体 run 中，基线偏移与 `fontBoundingBoxAscent` 一致；混排 run 中，矩形顶部可差 3px，但基线一致。`Range.top` 不是行盒顶部，`Range` 也不是基线。
4. Canvas 度量只能作交叉参考；混排 fallback、`actualBoundingBox*` 和缺失的 `emHeight*` 都不能单独推导行盒。
5. `document.fonts.check` 对本次缺字仍返回 true，不能作为缺字检测器；缺字渲染需要视觉或其他证据。
6. 本次建立同一环境的噪声底（重复测量为 0 差异）；`R3-EXP-13` 给出 Chromium + WebKit 的当前 Windows 字体标定（换行数差 0/12、基线最大差 0.5px），但 Firefox、跨平台字体栈与通用字形阈值仍为 `not-evaluated`，不得填成误差 0。

## 9. 不得宣称

- 不得写“所有字体都按 `line-height` 精确行进”。
- 不得写“Range 矩形等于行盒”或“Range 底部减常数等于基线”。
- 不得写“字形底边就是基线”。
- 不得写“统一 1.4em 可代表所有字体行高”。
- 不得写“`document.fonts.check` 通过就没有缺字”。
- 不得把本次结果外推到 Firefox、其他 Chromium 版本或其他操作系统；WebKit 只有 `R3-EXP-13` 的当前 Windows 构建标定，不是跨平台常量。
- 不得把合成斜体候选写成已证实的合成机制。

## 10. 证据文件

| 文件 | 内容 |
|---|---|
| `output/_r3_experiments/exp06_text_metrics.py` | 可复现实验脚本 |
| `output/_r3_experiments/exp06_site/index.html` | 12 个受控文本用例 |
| `output/_r3_experiments/exp06_text_metrics.json` | 全部行盒、探针、run、平台字体、噪声与 DPR 数据 |
| `output/_r3_experiments/exp06_text_cases.png` | DPR 1 用例截图 |
| `output/_r3_experiments/exp06_text_cases_dpr2.png` | DPR 2 用例截图（2400×3200） |
