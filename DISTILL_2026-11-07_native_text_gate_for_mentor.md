# Grounding v2 Native-Text Gate 蒸馏包

**日期：** 2026-11-07  
**接收者：** 下一阶段实施 Agent  
**仓库：** `D:\LLM-Data\Figma_auto_agent`  
**分支：** `feature/precise-agent-router`  
**目标：** 在冻结 grounding artifact 上降低 native-text blocker，并最终生成真实 Figma v2 formal acceptance

---

## 1. 一句话任务

保持 `image-figma-mvp-product/1.0` 冻结，继续完成显式启用的
`image-figma-mvp-product/2.0` native-text gate；当前总体结果是
`blocked-fail`，不能声明通过。

---

## 2. 已确认状态

### 通过项

- critical text 内容匹配：`24/24`
- chrome gate：`pass`
- fidelity：`pass`
- asset：`pass`
- edit：`pass`
- within30：`96.553%`
- page bad-pixel：`3.447%`

### 未通过项

- native-text gate：`9/32` owners passed
- owner pass ratio：`28.125%`
- 32 个 critical owners 中 23 个失败
- 23 个失败中 21 个包含 `edgeF1 < 0.95`
- 总体 acceptance：`blocked-fail`
- baseline：`not-evaluated`，不得从截图补造 baseline evidence

### 当前正式运行

目录：

```text
output/_grounding_manual_20261107_high_v2/
```

关键文件：

```text
acceptance.json
native_text_quality.json
region_quality.json
font_calibration.json
figma_design.json
figma_form_calibrated_2/export.png
pipeline/10_pagegraph.json
```

Artifact hashes：

```text
10_pagegraph.json
702941D20362D88B85EFC8C15B79014472CEFDF66B5EA4738FD28B90DF959334

acceptance.json
71F3EC138AEC2502E1F44C635988DEA0A0487D19AC84E0B7F0F746B56EB57669

native_text_quality.json
2F9188D2510525A78E3181D9F2E86767F1C22FA05AFEFF31DEF6DFACF7D4E4A7
```

### 最新 direct probe

表格重复 OCR owner 修复后：

```text
output/_grounding_manual_20261107_high_v2/probe-table-dedupe-fix/
```

结果仍是 native-text `9/32`；page bad-pixel 降到 `3.418%`，table bad-pixel
降到 `5.363%`。

该 probe 只能证明重复 owner 修复，不是 formal acceptance。

### 当前验证代差

最新表格去重代码在该 formal acceptance 之后修改，目前只有 direct probe。
因此不能把现有 `acceptance.json` 当成“最新工作树代码的完整正式验收”。

---

## 3. Native-Text 失败分类

### 3.1 5 行 JSON 结果

文本：

```text
{"error":"SUCCESS","message":"SUCCESS"}
```

5 个 critical owner 均表现为：

```text
width delta:  -9
height delta: -1
coverage:      1.00
edge F1:       0.84
```

这说明宽度和 glyph edge 同时有残差。当前第一优先级是 table JSON joint
calibration，但不能只调 `letterSpacing`；需要联合验证：

```text
fontFamily
font face / weight
fontSize
letterSpacing
```

### 3.2 Toolbar

```text
暂停自动刷新: coverage 1.23, edge 0.78
复制:         coverage 1.26, edge 0.94
刷新:         coverage 0.82, edge 0.78
导出:         coverage 1.08, edge 0.59
```

`复制` 在 Light 下约 `0.881`，Regular 下约 `1.26`，中间字重缺失。

### 3.3 Table header

```text
持续时长: height +1, coverage 0.88, edge 0.98
启动时间: deltaY -1, height +1, coverage 0.82, edge 0.99
```

几何和 edge 已接近，主要缺口是 ink coverage。适合组级 face/size 校准，
不要先做单字平移。

### 3.4 Textarea

```text
width delta:   -5
height delta:  -5
coverage:      0.72
edge F1:       0.63
```

单独增加字号已证实会退化，需要联合调整 size 和 negative letter spacing。

### 3.5 Form / sidebar 文本

11 个 critical text owner 仍有 blocker，edge F1 主要分布在约
`0.75-0.93`，部分同时存在 `1px-2px` 位置偏差和 `0.87-1.29` coverage。

代表项：

```text
执行时间:       width +3, height +1, coverage 1.28, edge 0.87
显示名称:       width 0, height +1, coverage 1.19, edge 0.82
下次执行时间:   width +5, height +1, coverage 1.29, edge 0.85
以auto用户身份执行: width +2, coverage 0.87, edge 0.75
表内搜索:       width +3, height +2, coverage 1.27, edge 0.88
```

---

## 4. 关键卡点

### P0. VLM grounding 不可复现

同一个 cache key 在 live run 中产生过不同 grounding graph。当前缓存是进程内
缓存，TTL 默认 `300s`，没有持久化 artifact pinning，cache key 也不包含供应商
实际模型 revision。

后果：

- 每次 live VLM 重跑都会混入 grounding 随机漂移；
- 字体 A/B 结果无法归因；
- 不能把 direct probe 和 formal acceptance 当成同源比较。

处置：

- 固定使用：

```text
output/_grounding_manual_20261107_high_v2/pipeline/10_pagegraph.json
```

- 先验证 hash，再在冻结输入上运行 OCR、ScenePlan、Compiler 和 Figma 校准；
- 字体参数实验不得重新采样 VLM。

### P0. Native-text gate 测量有效性

`src/app/services/evidence/native_text_quality.py` 当前对整个
`source_bbox` 计算 contrast mask，而不是严格限制在 reference text ink ROI。

已观察到的风险：

- 低对比度 placeholder `输入关键字过滤菜单` 曾被报为
  `failed-missing-rendered-ink`，但导出视觉中文字实际存在；
- 表格 cell 的 `source_bbox` 可以包含明显大于文字 ink 的区域，存在把表格线或
  邻近图形计入 coverage 的风险；
- 如果 gate 测量失真，字体校准会优化错误目标。

处置：

- 在调字体前先增加 ROI 对照测试；
- 比较 `source_bbox` coverage 与 `reference ink + controlled padding`
  coverage；
- 保留严格阈值，不得通过放宽 `0.90-1.10` 或 `0.95 edge-F1` 制造通过；
- 修复测量时应保留 before/after owner 指标。

### P0. 单字符表格 owner 被按宽度过度放大

位置：

```text
src/app/services/structure/fidelity/text_calibration.py
```

当前 table font calibration 会把 1-2 字符 owner 放入 `individual_items`，再按
reference/rendered ink width 单独放大字号。

实际结果：

```text
单字符 "1" -> fontSize 19.25
单字符 "2/3/4/5" -> fontSize 24.0
height delta: +6
coverage:     2.67-2.76
```

这是明确的校准规则缺陷。下一步应禁止 1-2 字符 owner 使用独立宽度缩放，
优先继承表格 body group size；剩余宽度用受控 letter spacing 处理。

### P1. Face / glyph edge 是主要 blocker

23 个 critical 失败中，21 个包含 `edgeF1 < 0.95`。因此问题不只是位置或
letter spacing，而是最终 Figma face 和 glyph outline/rasterization 仍与参考图
不完全一致。

联合搜索必须覆盖：

```text
fontFamily
face/weight
fontSize
letterSpacing
```

仅匹配 ink bbox 不能证明 glyph edge 通过。

### P1. 350 / DemiLight 未覆盖

`figma_bridge/code.js` 的 `WEIGHT_LADDER` 已有 350 档，但别名中没有
`DemiLight`。Noto Sans SC 若实际提供 `DemiLight`，当前不会命中这个中间 face。

处置：

- 在 350 档增加 `DemiLight` 别名；
- 关闭并重新运行 Figma 开发插件；
- 用 `font_probe` / `font_strict_probe` 确认真实 face；
- 只有真实 readback 命中后，才重新评估 `复制` 等 owner。

### P1. Figma bridge 运行态

修改 `figma_bridge/code.js` 后必须重新加载开发插件。历史上出现过：

```text
Attempted to invoke callback with invalid id
```

如果出现，保留失败 evidence，重新加载插件并使用唯一新输出目录重试。
不要把失败尝试产生的部分 Frame 计入正式结果。

---

## 5. 不可违反的约束

- 不得修改或回填 v1 / r11 的冻结结果。
- v2 必须显式启用。
- 不得把 chrome gate 通过解释成 native-text gate 通过。
- 不得用 direct probe 冒充 formal acceptance。
- 不得整段或控件文字栅格化。
- 文本必须保持 native Figma TEXT。
- baseline 没有证据时必须保持 `not-evaluated`。
- 不得无条件执行 `git reset`、`git clean` 或覆盖历史未跟踪文件。
- 当前工作树包含大量前序未提交改动，修复必须增量进行。

---

## 6. 推荐执行顺序

### Step 0：冻结和复核

1. 校验 `10_pagegraph.json` hash。
2. 确认使用 `GROUNDING_FIDELITY_MODE=high` 和
   `IMAGE_ENRICHMENT_MODE=apply`。
3. 确认 acceptance policy 显式为 `2.0`。
4. 记录代码 revision、输入 hash、输出目录。

### Step 1：验证 gate 测量

1. 对 JSON、table header、textarea、低对比 placeholder 各选一个 owner。
2. 输出 source crop、reference ink crop、rendered ink crop、mask 和 coverage。
3. 检查 table line / control border 是否污染 coverage。
4. 为 `failed-missing-rendered-ink` 增加低对比回归测试。
5. 保持阈值不变。

没有完成本步，不建议继续大规模字重调参。

### Step 2：修复短表格文本缩放

1. 1-2 字符 table owner 禁止按独立宽度比例放大字号。
2. 单字符优先继承 table body group size。
3. 增加回归测试，覆盖 `1/2/3/4/5` 和 `#`。
4. 在冻结 artifact 上跑真实 Figma 渲染，检查 height/coverage 是否回落。

### Step 3：Table JSON joint calibration

1. 固定其余 owner，只对 5 个 JSON owner 做候选搜索。
2. 联合评估 fontFamily、label、fontSize、letterSpacing。
3. 不以 ink width 单项最优作为结束条件。
4. 每个候选必须记录：

```text
position
width/height delta
coverage
edgeF1
actual resolved face
```

5. 目标必须同时满足现有 v2 gate。

### Step 4：Toolbar 350 / DemiLight

1. 增加 `DemiLight` 别名。
2. 重新加载 Figma 插件。
3. 用 font probe 确认 350 的实际 face。
4. 对 `复制` 先做 Light / DemiLight / Regular A/B。
5. 再处理 `暂停自动刷新`、`刷新`、`导出`。

### Step 5：Table header 组级 coverage

1. 以 `持续时长`、`启动时间` 为第一组。
2. 调整组级 face/size/weight，不做单字平移。
3. 保持 edge F1，优先把 coverage 拉回 `0.90-1.10`。

### Step 6：Textarea

1. 联合调整 fontSize 与 negative letterSpacing。
2. 每次只改 textarea 类型。
3. 以 height、width、edge F1 三项共同评估。

### Step 7：Form / sidebar 文本

在表格、toolbar、textarea 稳定后，再按相同 face 分组批量校准。

### Step 8：完整 formal acceptance

每轮关键修复后都生成完整 formal run；最终必须重新生成：

```text
acceptance.json
readback
export.png
text probe
asset probe
native_text_quality.json
region_quality.json
```

---

## 7. 验证环境与命令

Python：

```text
C:\Users\lzq\.conda\envs\omni\python.exe
```

不要使用 base：

```text
D:\LLM_condas\python.exe
```

base 缺少 `openai` 和 `playwright`，会在 collection 阶段失败。

聚焦测试：

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe -m pytest `
  tests/v2/test_native_text_quality.py `
  tests/v2/test_image_figma_acceptance.py `
  tests/v2/test_grounding_text_calibration.py -q
```

静态检查：

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe -m py_compile `
  src/app/services/evidence/native_text_quality.py `
  src/app/services/evidence/image_figma_acceptance.py `
  src/app/services/structure/fidelity/text_calibration.py

node --check figma_bridge/code.js
git diff --check
```

上一轮完整测试基线：

```text
1236 passed in 80.57s
```

---

## 8. 完成标准

只有同时满足以下条件，下一 Agent 才能声明 v2 通过：

- `image-figma-mvp-product/2.0` 明确启用；
- chrome 所有 region 通过；
- native-text 所有 critical owners 通过；
- critical text 保持完整；
- baseline 无证据时仍为 `not-evaluated`；
- 文本保持 native Figma TEXT；
- formal acceptance 包含真实 readback、export、text probe、asset probe；
- v1 原始结果未改写；
- 报告包含代码 revision、输入 hash、输出目录和 before/after owner 指标。

---

## 9. 给接收 Agent 的第一个动作

先不要重新采样 VLM，也不要继续扫字号。

先复现并审计 [native_text_quality.json](output/_grounding_manual_20261107_high_v2/native_text_quality.json)
中 23 个失败 owner，确认 gate 的 coverage/edge 测量没有被 source bbox
污染，然后修复单字符 table owner 的过度放大问题。完成这两项后，再在冻结的
[10_pagegraph.json](output/_grounding_manual_20261107_high_v2/pipeline/10_pagegraph.json)
上做 table JSON 的 face/glyph 联合校准。
