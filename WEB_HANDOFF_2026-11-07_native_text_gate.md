# Grounding v2 Native-Text Gate 网页审阅包

**日期：** 2026-11-07  
**任务：** 审阅 native-text gate 失败原因，并给出下一阶段修复方案  
**当前结论：** v2 未通过，不能声明通过

---

## 1. 本轮只需要做什么

请基于本文件和随附截图/JSON，回答：

1. 23 个 critical owner 失败的共同原因是什么；
2. native-text gate 的 coverage / edgeF1 是否可能测量失真；
3. 单字符表格被放大到 24px 的规则缺陷是否成立；
4. 给出不超过 5 个按优先级排序的修复方案；
5. 指出哪些结论必须重新跑真实 Figma acceptance 才能确认。

本轮不要重新调用 VLM，不要直接建议继续扫字号，不要声称 v2 已通过。

---

## 2. 当前确认结果

正式运行结果：

```text
status:             blocked-fail
critical text:      24/24
fidelity:           pass
asset:              pass
edit:               pass
chrome gate:        pass
native-text gate:   9/32
native pass ratio:  28.125%
within30:           96.553%
page bad-pixel:     3.447%
baseline:           not-evaluated
```

详细 owner 指标：

- native-text ownerCount：`32`
- ownerPassCount：`9`
- failed owners：`23`
- 含 `edgeF1 < 0.95` 的失败 owner：`21/23`
- position fail：`8`
- size fail：`10`
- coverage high：`8`
- coverage low：`5`
- edgeF1 fail：`21`

gate 阈值：

```text
position max:          1 px
ink coverage:          0.90 - 1.10
edge F1 min:           0.95
chrome bad-pixel max:  5%
```

---

## 3. 23 个失败 owner

| owner 文本 | 类型 | ΔX | ΔY | ΔW | ΔH | coverage | edgeF1 | 失败项 |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| 导出 | button | -2 | 0 | -1 | +1 | 1.08 | 0.59 | edge, position |
| 复制 | button | +1 | 0 | -2 | +1 | 1.26 | 0.94 | coverage, edge |
| 刷新 | button | 0 | -2 | -2 | 0 | 0.82 | 0.78 | coverage, edge, position |
| 暂停自动刷新 | button | -2 | -2 | +1 | 0 | 1.23 | 0.78 | coverage, edge, position |
| 2023年12月16日：修改成凌晨3：30执行备份 | input | 0 | 0 | -5 | -5 | 0.72 | 0.63 | coverage, edge, size |
| {"error":"SUCCESS","message":"SUCCESS"} ×5 | text | 0 | 0 | -9 | -1 | 1.00 | 0.84 | edge, size |
| 备注 | text | -2 | 0 | -1 | -1 | 1.07 | 0.79 | edge, position |
| 表内搜索 | text | -2 | 0 | +3 | +2 | 1.27 | 0.88 | all |
| 持续时长 | text | 0 | 0 | 0 | +1 | 0.88 | 0.98 | coverage |
| 禁用 | text | -2 | 0 | 0 | +1 | 1.01 | 0.82 | edge, position |
| 名称 | text | -2 | -1 | -1 | +1 | 1.11 | 0.75 | coverage, edge, position |
| 启动时间 | text | 0 | -1 | -1 | +1 | 0.82 | 0.99 | coverage |
| 任务执行历史: | text | -2 | 0 | +3 | +1 | 0.94 | 0.86 | edge, position, size |
| 托管 | text | -1 | 0 | -1 | +1 | 0.98 | 0.93 | edge |
| 下次执行时间 | text | -1 | -1 | +5 | +1 | 1.29 | 0.85 | coverage, edge, size |
| 显示名称 | text | -1 | -1 | 0 | +1 | 1.19 | 0.82 | coverage, edge |
| 以auto用户身份执行 | text | 0 | 0 | +2 | 0 | 0.87 | 0.75 | coverage, edge |
| 执行时间 | text | 0 | 0 | +3 | +1 | 1.28 | 0.87 | coverage, edge, size |
| 执行者 | text | 0 | -1 | 0 | +1 | 1.28 | 0.93 | coverage, edge |

JSON 文本有 5 个表格行 owner，指标完全相同，因此表中合并为一行。

---

## 4. 关键代码问题

### 4.1 Gate coverage 可能混入非文字区域

当前 `native_text_quality.py` 先对完整 `source_bbox` 做 contrast mask：

```python
x, y, box_width, box_height = source_bbox
source_region = rendered[y:y + box_height, x:x + box_width]
reference_region = reference[y:y + box_height, x:x + box_width]

rendered_mask = _contrast_mask(source_region)
reference_mask = _contrast_mask(reference_region)

reference_pixels = int(reference_mask.sum())
rendered_pixels = int(rendered_mask.sum())
coverage = rendered_pixels / reference_pixels
```

风险：

- 表格线、控件边框或邻近图形可能被计入文字 ink；
- 某些 owner 的 `source_bbox` 明显大于 `ink_bbox`；
- 低对比度 placeholder 曾出现 `failed-missing-rendered-ink`，但导出图中文字实际可见；
- 如果测量目标错误，后续字重和字号优化会追错目标。

需要审阅的问题：

- coverage 是否应只限制在 reference text ink ROI 或受控 halo；
- 是否应使用 `foreground/background` 已知颜色构造 mask；
- 是否应把 `failed-missing-rendered-ink` 单独区分“真缺失”和“mask 失效”；
- 不能通过放宽 gate 阈值来绕过。

### 4.2 单字符表格 owner 被按宽度过度放大

当前 `text_calibration.py` 会按 reference/rendered ink width 单独缩放字号。
长度不足 4 的 table cell 会进入 `individual_items`。

实际输出：

```text
table cell "1" -> fontSize 19.25
table cell "2/3/4/5" -> fontSize 24.0
height delta: +6
coverage:     2.67-2.76
edgeF1:       0.40-0.54
```

这说明单字符宽度样本很小，`3px -> 8px` 之类的比值不应直接映射到整体字号。

需要审阅的问题：

- 1-2 字符 owner 是否应该只继承 table body group size；
- 剩余宽度是否应该只通过受控 letter spacing 调整；
- 是否需要将单字符和长文本的校准策略分开。

### 4.3 Face / glyph edge 是主要残差

23 个失败 owner 中 21 个含 edgeF1 失败。即使 width 接近，glyph edge 仍可能明显
不重合，原因可能是：

- 实际 Figma face 与参考图不同；
- Light / Regular / Medium / DemiLight 选错；
- 同一 family 下 glyph outline 不同；
- source 与 Figma 的 rasterization / antialiasing 不同。

不能只通过移动文字或调整 letter spacing 解决。

### 4.4 中间字重缺失

`figma_bridge/code.js` 的 350 档已有 `Semilight` / `Semi Light`，但没有
`DemiLight`。如果 Noto Sans SC 的实际 face 是 `DemiLight`，当前规则不会命中。

已观察：

```text
复制 Light:     coverage 约 0.881
复制 Regular:   coverage 约 1.26
```

需要验证 350 / DemiLight 的真实 Figma readback。

---

## 5. 推荐修复顺序

### P0：先验证测量

对 JSON、table header、textarea、低对比 placeholder 各选一个 owner，输出：

- source crop；
- reference ink crop；
- rendered ink crop；
- contrast masks；
- coverage；
- edgeF1。

先确认 gate 没有把表格线和边框算进文字。

### P0：修复单字符表格缩放

禁止 1-2 字符 table owner 使用独立宽度比例放大字号，优先继承 body group size。

### P1：JSON face/glyph 联合校准

只对 5 个 JSON owner 做 A/B，联合验证：

```text
fontFamily
face / weight
fontSize
letterSpacing
```

目标是同时满足 width/height、coverage 和 edgeF1。

### P1：Toolbar 350 / DemiLight

增加 `DemiLight` 别名，重新加载 Figma 插件，并用 font probe 确认真实 face。

### P1：Table header coverage

对 `持续时长`、`启动时间` 做组级 face/size 校准，优先补 coverage，
不要先做单字平移。

### P2：Textarea

联合调整 fontSize 和 negative letterSpacing，不单独放大字号。

---

## 6. 不可违反的约束

- 不修改 v1 / r11 的冻结结果。
- 不把 chrome gate 通过解释成 native-text gate 通过。
- 不使用 direct probe 冒充 formal acceptance。
- 不降低 coverage 或 edgeF1 门槛。
- 不整段或控件文字栅格化。
- baseline 无证据时保持 `not-evaluated`。
- 不用重新采样 VLM 的结果做字体 A/B。

---

## 7. 随附文件

建议网页上传以下 6 个文件：

```text
WEB_HANDOFF_2026-11-07_native_text_gate.md
IMG-FLEXWEAVER-ADMIN.png
export.png
native_text_quality.json
font_calibration.json
acceptance.json
```

其中：

- `IMG-FLEXWEAVER-ADMIN.png` 是参考图；
- `export.png` 是当前 Figma 导出；
- 三个 JSON 提供完整 owner、校准和 acceptance 证据。

最后请以“审阅报告”形式回答，不要修改代码或声称已经验证通过。
