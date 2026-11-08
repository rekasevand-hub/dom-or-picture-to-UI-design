# HANDOFF - Grounding v2 双门与 Native Text 优化

**日期：** 2026-11-07  
**分支：** `feature/precise-agent-router`  
**工作树状态：** 大量前序改动仍未提交，本轮改动叠加在同一工作树中  
**当前结论：** v2 chrome gate 已通过；critical native-text gate 仍失败  
**下一目标：** 继续降低 critical native-text blocker，使最新 live high v2 acceptance 通过

---

## 1. 当前可声明的结论

- `image-figma-mvp-product/1.0` 保持冻结，原始 raw-region 判定未被改写。
- `image-figma-mvp-product/2.0` 已实现为显式 opt-in。
- v2 将视觉质量拆成：
  - `chrome_visual`：排除 native text ink 后的 region bad-pixel gate。
  - `native_text_visual`：critical native-text owner 的位置、尺寸、coverage、edge-F1 gate。
- v2 中旧 raw-region 指标仍会测量，并作为
  `legacy_raw_region_visual / mode=informational` 保留。
- 最新真实 Figma 导出中：
  - critical text 内容为 `24/24`。
  - chrome gate 为 `9/9` 通过。
  - native-text gate 为 `9/33`，通过率 `27.27%`。
  - 因此 v2 总体仍为 `fail`。
- 最新完整 live high-fidelity run 已生成正式 v2 acceptance：
  - critical text：`24/24`
  - fidelity / asset / edit：全部通过
  - chrome gate：`pass`
  - native-text gate：`9/32`，通过率 `28.125%`
  - within30：`96.553%`
  - page bad-pixel：`3.447%`
  - 总体仍为 `blocked-fail`
- baseline 仍为 `not-evaluated`，没有从截图伪造 baseline 证据。

不能声明：

- 不能声明 v2 已通过。
- 不能把本次 `probe-v2-gate` 当成完整的正式 acceptance。
- 不能修改或回填 r11 的冻结结果来制造通过。
- 不能把 chrome 通过解释成 native text 也已通过。

---

## 2. 本轮新增实现

### 2.1 v2 policy

新增：

```text
IMAGE_MVP_POLICY_V2
policy_id = image-figma-mvp-product/2.0
```

关键字段：

```text
region_visual_mode = native-text-and-chrome
chrome_bad_pixel_ratio_max = 0.05
native_text_position_px_max = 1
native_text_ink_coverage_min = 0.90
native_text_ink_coverage_max = 1.10
native_text_edge_f1_min = 0.95
native_text_baseline_required = false
legacy_raw_region_visual_informational = true
```

关键位置：

- `src/app/services/evidence/image_figma_acceptance.py:37`

### 2.2 Native text gate

`build_native_text_quality` 现在支持可选的 `gate_policy`：

```python
build_native_text_quality(
    ...,
    gate_policy=IMAGE_MVP_POLICY_V2,
    critical_texts=truth["critical_texts"],
)
```

开启 gate 后输出：

```text
schema_version = grounding-native-text-quality/2.0
acceptance_effect = native-text-and-chrome-gate
gate.nativeText
gate.chrome
gate.criticalText
gate.baseline
gate.blockers
```

统计字段包括：

```text
ownerCount
ownerPassCount
ownerPassRatio
matchedCount
missing
```

关键位置：

- `src/app/services/evidence/native_text_quality.py:145`

### 2.3 Acceptance 分流

v1：

```text
dimensions.region_visual
```

v2：

```text
dimensions.native_text_visual
dimensions.chrome_visual
dimensions.legacy_raw_region_visual
```

v2 只有 chrome 和 native text 都通过时，视觉维度才通过。native-text
失败不会被 chrome 通过抵消。

关键位置：

- `src/app/services/evidence/image_figma_acceptance.py:217`
- `src/app/services/evidence/image_figma_acceptance.py:469`

### 2.4 CLI opt-in

默认仍是 `1.0`：

```text
python scripts/image_figma_mvp.py ... --acceptance-policy 1.0
```

显式启用 v2：

```text
python scripts/image_figma_mvp.py ... --acceptance-policy 2.0
```

只有 `2.0` 会向 native quality 传入 gate policy 和 critical texts。

关键位置：

- `scripts/image_figma_mvp.py:79`
- `scripts/image_figma_mvp.py:186`

### 2.5 Form over-ink 校准

新增 `calibrate_form_text_weight_from_render`：

- 只处理 form bounds 内的原生 TEXT。
- 排除 table header owner。
- 深色文字 rendered/reference ink coverage 超过 `1.18` 时切换到 Light。

当前 r11 真实导出会命中 7 个 owner：

```text
执行时间
禁用
下次执行时间
托管
以auto用户身份执行
执行
备注
```

批量真实 A/B 中，critical native owner 通过数从 `9/33` 提升到 `11/33`，
没有引入新的相关 critical blocker。该规则已接入 pipeline。

最新 live high run 中实际命中 6 个 owner：

```text
禁用
托管
以auto用户身份执行
执行
备注
任务执行历史:
```

关键位置：

- `src/app/services/structure/fidelity/text_calibration.py:559`

---

## 3. 同一工作树中已完成的相关修复

以下修复已在上一阶段完成，后续不得回退：

### 3.1 Textarea text bbox

- 旧 bbox：`[442,372,1407,20]`
- 修复后：`[447,352,335,16]`
- 备注文字不再低 23px。

位置：

- `src/app/services/structure/fidelity/fixed_canvas_compiler.py:65`

### 3.2 Source chrome 与 native control 双壳

- form 区拥有 source-pixel chrome 时，input/button 保留透明 shell 节点。
- native TEXT 仍绘制在最上层。
- main-content 真实探针从 `5.155%` 降到约 `3.47%`。

位置：

- `src/app/services/structure/fidelity/fixed_canvas_compiler.py:569`
- `src/app/services/rendering/adapter_base.py:351`

### 3.3 Textarea 字号策略

- textarea 不再使用整串 ink 宽度直接放大字号。
- 实测 `15.25 -> 17.25` 会增加残差，因此该类型跳过 form-font
  width scaling。

位置：

- `src/app/services/structure/fidelity/text_calibration.py:506`

### 3.4 Font weight 协议

- Python 不再发送 `fontWeightValue: null`。
- JS 使用：

```javascript
params.fontWeightValue ?? params.fontWeight
```

真实 Figma readback 已验证：

```text
300 -> Noto Sans SC Light
500 -> Noto Sans SC Medium
```

位置：

- `src/app/services/rendering/adapter_base.py:493`
- `figma_bridge/code.js`

### 3.5 表格重复 OCR owner

最新 live high-fidelity grounding 额外生成了 3 个位于表格前两行的 OCR 文本：

```text
text:588481e38e3a86e0  "31649"
text:844b279d22cc8b0c  "2026-10-31 03:30:00"
text:0af82315816686f3  "31374"
```

它们与 table cell 文本重叠。原因是 `10_content_inventory.json` 中 table bbox
错误地从 `y=672` 开始，而 geometry bbox 正确为 `[308,549,1579,270]`。
旧仲裁逻辑使用 inventory bbox，因此误判这 3 个节点不在表格内。

修复：

- table 去重判断改用 geometry bbox 作为权威。
- 3 个节点全部以 `table-cell-owner-authoritative` 被抑制。
- ScenePlan 从 117 个节点降到 114 个节点。
- 修复后真实 Figma 导出中前两行重影消失。

位置：

- `src/app/services/structure/fidelity/scene_plan.py:591`
- `tests/v2/test_grounding_scene_plan.py:286`

修复前后指标：

```text
page bad-pixel:  3.447% -> 3.418%
table bad-pixel: 5.472% -> 5.363%
```

table 仍高于 5%，但剩余原因是字形 coverage/edge 和宽度，不再是重复文本层。

### 3.6 低对比度 CJK OCR 二次识别

侧栏搜索框 placeholder `输入关键字过滤菜单` 在最新 live run 中完全缺失。

原因：

- 文字颜色与深色侧栏背景对比度低。
- EasyOCR 原始召回只有 `关键字过滤菜单`，缺少开头的“输入”。
- 原始置信度仅 `0.0867`，被 `_merge_ocr_line_observations` 的 `0.4` 门槛过滤。
- 因此 inventory、ScenePlan、DesignSpec 和 Figma readback 中都没有这段文字。

修复：

- 对低置信度、至少包含 2 个 CJK 字符的观察执行局部二次 OCR。
- 扩展 observation bbox，放大 3-4 倍并增强对比度。
- 只有置信度显著提升、文本长度不退化和文本相似度合格时才替换。
- 不降低全局 OCR 阈值。

真实图片验证：

```text
raw text:       关键字过滤菜单
raw confidence: 0.0867
text:           输入关键字过滤菜单
bbox:           [30,100,144,21]
confidence:     0.7643
engine:         easyocr-enhanced
```

位置：

- `src/app/services/structure/image_contract.py:165`

真实 live 验证目录：

```text
output/_grounding_manual_20261107_high_v2_ocrfix/
```

验证结果：

- `输入关键字过滤菜单` 已进入 inventory、ScenePlan、DesignSpec 和 Figma readback。
- 最终导出中 placeholder 已可见。
- 本次随机 grounding 同时漏掉了另一个关键文本“禁用”，critical text 为 `23/24`。
- 因此该目录只用于验证 OCR 修复，不替换
  `IMG-FLEXWEAVER-ADMIN-r11-final-i` 或上一份 `24/24` 的正式基线。
- native gate 对该 placeholder 报告 `failed-missing-rendered-ink`，这是低对比度
  contrast mask 的诊断限制；视觉导出中文字实际存在。

### 3.7 VLM grounding 随机退化与旧导出的可比性

`probe-compiler-fixes-combined-2/export.png` 不是一次完整 live
image-to-Figma 重跑。它的输入是：

```text
r11 已稳定的 grounding graph + 已校准 DesignSpec
        ↓
叠加当时的 textarea/source-chrome 编译器修复
        ↓
直接写 Figma 并导出
```

因此该探针没有重新调用 VLM，不会包含本次 live grounding 随机产生的错误标签位置。

`high_v2_ocrfix` 则是完整的 live 流程：

```text
重新调用 qwen3-vl-plus
        ↓
重新生成 grounding graph
        ↓
OCR、ScenePlan、Compiler、Figma 校准
```

三次运行的模型和 cache key 完全一致：

```text
model:      qwen3-vl-plus
cache key:  dec6077c685d0d40
cache:      miss
```

但模型输出不同：

| 运行 | elements | containers | completion tokens | 结果 |
|---|---:|---:|---:|---|
| r11 | 42 | 7 | 6673 | 旧稳定结构 |
| high_v2 OCR 修复前 | 44 | 5 | 3420 | 无本次 form 标签重影 |
| high_v2_ocrfix | 43 | 5 | 4569 | 出现错误位置标签 |

ocrfix 中的错误文本在 ScenePlan 之前就已经出现在 grounding graph：

```text
禁用：
  本次 VLM 只生成在 [453,232]
  高置信度 OCR 正确位置约为 [380,194]

额外“执行者”：
  source_ref = graph.elements[24]
  bbox = [768,232]

额外“以auto用户身份执行”：
  source_ref = graph.elements[43]
  bbox = [1682,360]
```

因此可以明确区分：

- 旧 combined-2：好 grounding 输入 + 当前渲染修复。
- 新 ocrfix：随机新 grounding 输入 + 当前渲染修复。

这不是旧修复被回退，也不是工作树切换到了冻结版本。当前问题是：

- Grounding reliability cache 仅为进程内缓存。
- 默认 TTL 只有 `300s`，进程退出后缓存丢失。
- 请求使用 `temperature=0.1`，不是严格确定性。
- cache key 只包含模型名称，不包含供应商实际模型 revision。
- 当前没有跨进程 grounding artifact pinning，也没有输出语义回归门禁。

尚不能确认供应商是否在相同 `qwen3-vl-plus` alias 下更新了实际模型 revision；
相同模型字符串和 cache key 不能证明服务端是同一份权重。

后续复现实验应优先冻结一份高质量 grounding graph/artifact，再在冻结输入上运行当前
OCR、ScenePlan、Compiler 和 Figma 校准，而不是每次重新采样 VLM。

---

## 4. 最新真实证据

最新完整 live high-fidelity 正式运行：

```text
output/_grounding_manual_20261107_high_v2/
```

关键文件：

- `acceptance.json`
- `region_quality.json`
- `native_text_quality.json`
- `font_calibration.json`
- `figma_form_calibrated_2/export.png`

本次运行必须显式启用：

```powershell
$env:GROUNDING_FIDELITY_MODE='high'
$env:IMAGE_ENRICHMENT_MODE='apply'
```

如果只设置 `--route grounding`，当前默认会走 legacy
`image-mvp-direct`，不会生成 ScenePlan，也不属于高保真验收。

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
```

修复表格重复 owner 后的 direct Figma probe：

```text
output/_grounding_manual_20261107_high_v2/probe-table-dedupe-fix/
```

修复后的真实导出：

```text
probe-table-dedupe-fix/export.png
```

该 probe 不是正式 acceptance，只用于验证重复 owner 修复。

上一轮 r11 对照目录：

```text
output/_grounding_high_fidelity_2026-11-05/
  IMG-FLEXWEAVER-ADMIN-r11-final-i/
    probe-v2-gate/
```

关键文件：

- `export.png`
- `readback.json`
- `figma_design.json`
- `native_text_quality_v2.json`
- `form_text_weight.json`
- `summary.json`

r11 对照 chrome gate：

```text
page                    0.901%
sidebar                 1.053%
header                  2.143%
main-content            0.757%
form-section            0.113%
table-section           0.066%
table-header-controls   3.364%
table                   0.067%
table-header            0.000%
```

全部低于 `5%`。

r11 对照 native-text gate：

```text
critical texts matched: 24/24
critical owners:        33
owners passed:          9
owner pass ratio:       27.27%
status:                 fail
```

r11 该结果来自真实 Figma export，但只是 direct probe，不是完整 formal
acceptance。最新 live high run 已单独生成正式 acceptance。

注意：r11 `probe-v2-gate` 与最新 live high run 不是同一份 grounding 输出。
r11 没有那 3 个重复 table OCR owner；最新 live run 有。比较时必须先确认
ScenePlan 和 DesignSpec 是否同源。

---

## 5. 当前主要 native-text blocker

### 5.1 Form 标签

主要问题：

- coverage 普遍在 `1.20-1.38`，说明 rendered ink 过粗。
- r11 对照导出中 over-ink 校准会命中 7 个 owner。
- 最新 live high run 中实际命中 6 个 owner。
- 最新 native-text gate 仍为 `9/32`，说明该规则只解决了部分 coverage blocker。

### 5.2 5 行 JSON 结果

当前稳定残差：

```text
reference width: 308
rendered width:  299
width delta:     -9
edge F1:        约 0.839
coverage:       约 1.00
```

说明问题主要是宽度和字形边界，不是整体粗细。下一步应联合调整：

```text
fontSize + letterSpacing
```

不要只增加 fontSize，否则高度和 coverage 会一起恶化。

### 5.3 Table header

两个剩余 header：

```text
持续时长
启动时间
```

特征：

```text
width delta:  0 / -1
height delta: +1
coverage:     0.884 / 0.819
edge F1:      0.976 / 0.992
```

形状和位置已经接近，主要差在 ink coverage 偏少。下一步应做表头组级
face/weight/size 校准，而不是单个字符平移。

### 5.4 Toolbar

```text
暂停自动刷新: edge F1 约 0.937
复制:         coverage 约 0.881
```

`复制` 当前从 Light 的 `0.881` 到 Regular 的约 `1.26`，越过理想区间。
最值得验证的是中间 face：

```text
Noto Sans SC / DemiLight
```

如果引入 `350` 档，需要：

1. 在 `WEIGHT_LADDER` 中映射 `DemiLight`。
2. 重新加载 Figma 开发插件。
3. 用真实 readback 确认实际 face。
4. 重新跑 native gate。

### 5.5 Textarea

当前：

```text
width delta: -29
height delta: -2
edge F1:     约 0.725
```

下一步应联合：

```text
略增 fontSize 补高度
负 letterSpacing 收宽度
```

单独增大字号已经验证会退化。

### 5.6 表格重复 owner

最新 live high run 中前两行的 3 个 OCR 重影已经修复：

```text
31649
2026-10-31 03:30:00
31374
```

后续如果再次看到表格重复文字，应先检查 inventory 与 geometry 的 table bbox，
不要先调整字体或位置。

---

## 6. 测试与验证

本轮最后完整测试：

```text
1236 passed in 80.57s
```

最终聚焦测试：

```text
31 passed
```

同时通过：

```text
py_compile
node --check figma_bridge/code.js
git diff --check
```

测试环境：

```text
C:\Users\lzq\.conda\envs\omni\python.exe
```

不要使用 base `D:\LLM_condas\python.exe` 跑全套测试；base 缺少
`openai` 和 `playwright`，会在 collection 阶段失败。

---

## 7. Figma Bridge 已知风险

- 修改 `figma_bridge/code.js` 后必须关闭并重新运行开发插件。
- 较早的正式 v2 acceptance 尝试曾多次遇到：

```text
Attempted to invoke callback with invalid id
```

- 最新 live high run 已完整生成 `acceptance.json`，说明该问题不是稳定阻塞。
- 如果再次出现，应重新加载插件并使用唯一输出目录重试。
- 插件可能留下部分 Frame；不要把失败尝试的中间 Frame 计入正式证据。

---

## 8. Git 工作树约束

当前分支存在大量未提交改动。不得回退与当前任务无关的前序内容，尤其是：

- production admission；
- bridge fencing / security / soak；
- observability；
- Grounding reliability；
- 外部资料和未跟踪历史文件。

根目录仍有历史未跟踪项：

```text
2'
Figma'
```

不要无条件删除或覆盖。

---

## 9. 推荐下一轮执行顺序

1. 冻结一份结构质量较好的 grounding graph/artifact。优先使用
   `output/_grounding_manual_20261107_high_v2/pipeline/10_pagegraph.json`
   作为下游校准输入，不再让每次参数实验重新采样 VLM。
2. 在冻结 grounding 输入上运行当前 OCR、ScenePlan、Compiler 和 Figma
   校准；不要直接把 `high_v2_ocrfix` 当成新基线，因为该 live run 随机生成了错误
   form-label 位置并漏掉“禁用”。
3. 实现 table JSON 的 joint calibration：

```text
fontSize target = reference ink height
letterSpacing correction = remaining width delta / gaps
```

4. 对 table header 做组级 coverage 校准。
5. 验证 `DemiLight / 350`，优先修复“复制”。
6. 对 textarea 做 size + negative spacing 联合校准。
7. 每轮只改一个 owner 类型，并重新跑 v2 gate。
8. 每轮继续生成正式 v2 acceptance；若 bridge 再次出现回调错误，保留失败证据、
   重新加载插件并使用新目录重试，不得用 direct probe 冒充正式 acceptance。
9. 不通过时不要放宽 `0.90-1.10 coverage` 或 `0.95 edge-F1` 来制造通过。
10. 表格 bbox 已改为 geometry 权威，后续如再出现重复行文字，先检查
   `10_content_inventory.json` 和 `10_geometry_manifest.json` 的 table bbox
   是否再次不一致，不要先调字号。

---

## 10. 完成标准

下一轮只有同时满足以下条件，才能声明 v2 通过：

- `image-figma-mvp-product/2.0` 明确启用；
- `chrome_visual` 所有 region 通过；
- `native_text_visual` 所有 critical native owner 通过；
- baseline 若仍无证据，必须继续标记 `not-evaluated`；
- 文本保持 native Figma TEXT，没有整段或控件文字栅格化；
- 生成完整 `acceptance.json`，包含真实 readback、export、text probe、asset probe；
- 旧 `image-figma-mvp-product/1.0` 结果没有改写。

