# HANDOFF - Native Text 搜索校准与 ACCTOKEN 高保真重跑

**日期：** 2026-11-08  
**分支：** `feature/precise-agent-router`  
**工作树：** 大量前序改动仍未提交，禁止 reset / clean / checkout 覆盖用户改动  
**当前主线基线：** `output/_grounding_manual_20261107_full_vl_search_fix/`  
**当前最优结果：** FlexWeaver native gate `14/32`，chrome pass，总体仍为 `blocked-fail`  
**下一步优先项：** 只处理“暂停自动刷新”的 glyph/raster 边缘残差

---

## 1. 当前结论

项目已经回退到 2026-11-07 22:48 对应的稳定版本，并在该基线上完成
“表内搜索”的低对比文本后校准。

当前 FlexWeaver 正式 live high-fidelity 结果：

```yaml
status:           blocked-fail
critical text:    24/24
fidelity:         pass
chrome gate:      pass
native-text gate: 14/32
within30:         96.7662%
page bad-pixel:   3.2338%
blockers:         18
```

相比回退基线：

```text
native-text gate: 13/32 -> 14/32
page bad-pixel:   3.2352% -> 3.2338%
within30:         96.7648% -> 96.7662%
blockers:         19 -> 18
```

不能声明：

- 不能声明 v2 overall pass；仍有 18 个 native-text blockers。
- 不能把 chrome pass 当成 native text pass。
- 不能修改冻结 acceptance 或回填指标。
- 不能把 direct probe 当成正式 Figma acceptance。
- 不能声称 ACCTOKEN 派生 truth 运行等价于历史冻结 holdout。

---

## 2. 回退状态与不可覆盖资产

目标正式运行：

```text
output/_grounding_manual_20261107_full_vl_search_fix/
```

回退前完整备份：

```text
output/_rollback_20261107_2248_backup/after_2248.tracked.patch
output/_rollback_20261107_2248_backup/current_core.zip
```

回退重建预览与删除清单：

```text
output/_rollback_20261107_2248_preview/
output/_rollback_20261107_2248_preview/_deleted_files.json
```

注意：

- 不要删除上述备份。
- 不要让 `output/_rollback_20261107_2248_preview/tests` 干扰 pytest 收集。
- 测试时应使用 `--ignore=output`。
- 当前 22:48 快照实际收集到 `1249` 个测试；更早记录中的 `1251 passed`
  不是该 22:48 快照的精确测试集合。

---

## 3. 表内搜索修复

### 3.1 最终算法

实现：

```text
src/app/services/structure/fidelity/text_calibration.py
```

关键函数：

```text
calibrate_search_control_from_render
```

规则只命中：

- `button` / `input`
- 低对比 evidence
- 文本或控件标签带 `搜索` / `search` 语义

校准方式：

```text
位置：只修正到 ±1px 容差边界，不追求 bbox 完全重合
宽度：textBox 宽度保持不变；通过受控 letterSpacing 修正实际 glyph 宽度
外壳：绝不移动搜索框 shell
上限：单次有界校准
```

本次实际命中：

```yaml
previousTextBox: [1727, 511, 62, 20]
updatedTextBox:  [1728, 511, 62, 20]
positionCorrectionX: 1
positionCorrectionY: 0
widthCorrectionPx: -1
letterSpacing: -0.25
```

### 3.2 已验证被否决的方案

不要重新尝试“完整 bbox 对齐 + 缩小 textBox 宽度”。

失败实验：

```text
output/_grounding_manual_20261108_search_textbox_fix/
```

结果：

```yaml
deltaX: 0
deltaY: 0
widthDelta: 3
edgeF1: 0.8519
native gate: 13/32
```

原因：

- Figma 的实际字形宽度不随 textBox 宽度 shrink 自动缩小。
- 将 x/y 推到 ink bbox 完全重合后，栅格相位反而使 edgeF1 明显退化。
- 正确做法是把误差收进容差，并只对实际 glyph 宽度做有限字距修正。

### 3.3 搜索 owner 最终指标

```yaml
dx:       -1
dy:       -1
width:    +2
height:   +2
coverage: 0.9963
edgeF1:   0.9756
status:   pass
```

关键位置：

- `src/app/services/structure/fidelity/text_calibration.py:688`
- `scripts/image_figma_mvp.py:592`
- `tests/v2/test_grounding_text_calibration.py:636`

---

## 4. FlexWeaver 当前 formal acceptance

正式结果：

```text
output/_grounding_manual_20261108_search_control_post/
```

最终导出：

```text
output/_grounding_manual_20261108_search_control_post/figma_search_control/export.png
```

导出 SHA-256：

```text
972049b6dfc9c0ad2377784ed06c8e8623104d794792ca46f8edab51eec4088c
```

运行模式：

```yaml
route: grounding
fidelity_mode: high
image_enrichment: apply
acceptance_policy: 2.0
```

本次 FlexWeaver 运行复用了冻结 prepared pipeline，没有再调用 VLM；
它验证的是当前源码下的 ScenePlan/Compiler/Figma 校准和 formal gate。

---

## 5. ACCTOKEN 高保真全量重跑

### 5.1 输入来源

用户附件已固化：

```text
output/_image_figma_acctoken_models_20261108_rerun_full_high/input.png
```

附件：

```yaml
size: [2544, 1336]
sha256: 674d733f3bbdda5d201b6c78b76ddb94d6d818c980f33e86a107781b8b011641
```

从回退备份恢复的原图：

```text
output/_recovered_acctoken_models_20261108/tests/fixtures/image_to_slice_benchmark_2026-11-02/IMG-ACCTOKEN-MODELS-20261108.png
```

原图 SHA-256：

```text
a09ee049265105c2868114b4cc3a2ad4f5ca122eff30f3ab312e79c3949ecd59
```

附件与原图的差异：

```yaml
changed_pixels: 16479
changed_ratio: 0.4848%
bbox: [1328, 1100, 220, 80]
max_channel_delta: 21
```

因此本次没有冒用旧 truth 的图片哈希，而是建立了明确的派生 truth：

```text
output/_image_figma_acctoken_models_20261108_rerun_full_high/derived.truth.json
```

派生 truth：

- 保留原 truth 的 27 个 critical texts。
- 保留 `image-figma-mvp-product/2.0` policy。
- 只更新附件图片 SHA、size 和来源说明。
- 不是历史原始 manifest，不能冒充冻结 holdout。

恢复的原 truth：

```text
output/_recovered_acctoken_models_20261108/tests/fixtures/image_to_slice_benchmark_2026-11-02/IMG-ACCTOKEN-MODELS-20261108.truth.json
```

### 5.2 运行方式

本次是真正的全量重跑：

- 没有使用 `--reuse-prepared`
- 重新调用 `qwen3-vl-plus`
- 重新执行 OCR / image enrichment
- 重新生成 grounding graph、ScenePlan、Compiler 和 DesignSpec
- 重新写入 Figma、校准、回读和导出

### 5.3 结果

```yaml
status:           blocked-fail
fidelity mode:    high
fidelity:         pass
critical text:    24/27
native-text gate: 0/19
chrome gate:      fail
within30:         94.1469%
page bad-pixel:   5.8531%
scene nodes:      62
blockers:         31
```

关键失败：

1. `critical_text` 为 `24/27`。
2. native gate 中 19 个 critical owner 全部失败。
3. `banner` chrome region 为 `8.6799%`，超过 `5%`。
4. 结构维度失败，主要与 critical/native text owner 缺失和文本结构不完整相关。

critical text 行中明确缺失：

```text
5.8折
查看详情
8.8折
```

native gate 报告的 9 个缺失文本：

```text
价目牌 · 82 个模型 · 11 月 8 日更新
5.8折
输入 · 峰时
输出 · 峰时
查看详情
复制模型 ID
Seedance 特惠款
8.8折
去画布试
```

这说明：

- 不能只修字体 metrics。
- 先要区分“截图里确实可见，但 pipeline 没生成 native owner”与“matcher/owner scope 丢失”。
- 在该差异解决前，font calibration 只能优化已经存在的 owner，不能恢复缺失内容。

ACCTOKEN 正式产物：

```text
output/_image_figma_acctoken_models_20261108_rerun_full_high/acceptance.json
output/_image_figma_acctoken_models_20261108_rerun_full_high/native_text_quality.json
output/_image_figma_acctoken_models_20261108_rerun_full_high/figma_font_calibrated/export.png
```

导出 SHA-256：

```text
b0e432e83b6cac4e194710dae57b9e0025e00dbffc65b28b182fa23d1b4cde2b
```

---

## 6. 当前 FlexWeaver blockers

### 6.1 暂停自动刷新

```yaml
deltaX: -1
deltaY: 1
widthDelta: 0
heightDelta: -1
coverage: 1.0777
edgeF1: 0.9420
```

除 edgeF1 外全部通过，距离阈值只差 `0.008016`。

建议：

- 只做一次有界 glyph/raster 边缘校准。
- 不改变内容、位置和尺寸。
- 不为了 edgeF1 放宽 `0.95` 阈值。

### 6.2 复制

```yaml
coverage: 1.2340
edgeF1: 0.9409
position: pass
size: pass
```

问题是 rendered ink 明显过粗，同时边缘仍差。

建议先验证 `Noto Sans SC / DemiLight` 或 `350` 中间字重是否真实可用；
不要继续在 Light 与 Regular 之间来回扫。

### 6.3 导出

```yaml
coverage: 1.1146
edgeF1: 0.9683
position: pass
size: pass
```

只超出 coverage 上限 `0.0146`。应做轻微减重，不应继续移动文字盒。

### 6.4 5 行 JSON

五个结果 owner 完全一致：

```yaml
deltaX: 0
deltaY: 0
widthDelta: 0
heightDelta: -1
coverage: 0.9571
edgeF1: 0.9073
```

这是当前最高杠杆的组级问题。位置、尺寸和 coverage 都已通过，
只能从 face/glyph 轮廓或抗锯齿层面联合校准。

### 6.5 Form 标签

当前仍失败：

```text
名称
显示名称
禁用
下次执行时间
托管
执行成功
以auto用户身份执行
备注
任务执行历史:
```

应继续按 owner 分组，不要整组统一改字号。

### 6.6 Textarea

备注 textarea：

```yaml
widthDelta: -5
heightDelta: -5
coverage: 0.8669
edgeF1: 0.5912
```

这是独立问题，不能和普通标签一起调。

---

## 7. 测试与静态验证

本轮完整项目测试：

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe -m pytest -q --ignore=output
```

结果：

```text
1249 passed in 70.55s
```

静态检查：

```text
Ruff: pass
node --check figma_bridge/code.js: pass
git diff --check: pass
```

相关聚焦测试：

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe -m pytest -q tests\v2\test_grounding_text_calibration.py
```

结果：

```text
25 passed
```

---

## 8. 推荐下一步顺序

### P0

保持当前 FlexWeaver 14/32 基线，不回退搜索修复。

### P1

搜索阶段已经完成：

```text
13/32 -> 14/32 已确认完成
```

下一轮只实现“暂停自动刷新”的单次边缘校准，目标：

```text
14/32 -> 15/32
chrome 继续保持 pass
page bad-pixel 不显著上升
```

完成判据：

- edgeF1 >= 0.95
- 其他三项不退化
- 必须使用真实 Figma export 重算

### P2

按收益处理：

1. `复制`：中间字重/DemiLight 验证
2. `导出`：轻微减重
3. 5 行 JSON：face/glyph 组级校准
4. form labels
5. textarea

### P3

ACCTOKEN holdout：

1. 先核对 9 个 native missing 是真的没生成，还是 owner/matcher 丢失。
2. 再处理 banner chrome。
3. 最后才做 ACCTOKEN 字体 metrics 校准。

不要用 ACCTOKEN 的派生 truth 结果覆盖 FlexWeaver 正式基线。

---

## 9. 可复现命令

### FlexWeaver formal acceptance

```powershell
$env:VISION_MODEL='qwen3-vl-plus'
$env:GROUNDING_FIDELITY_MODE='high'
$env:IMAGE_ENRICHMENT_MODE='apply'

C:\Users\lzq\.conda\envs\omni\python.exe scripts/image_figma_mvp.py `
  --image tests/fixtures/image_to_slice_benchmark_2026-11-02/IMG-FLEXWEAVER-ADMIN.png `
  --truth tests/fixtures/image_to_slice_benchmark_2026-11-02/truth/IMG-FLEXWEAVER-ADMIN.truth.json `
  --out output/_grounding_manual_20261108_search_control_post `
  --route grounding `
  --acceptance-policy 2.0 `
  --reuse-prepared
```

### ACCTOKEN full rerun

```powershell
$env:VISION_MODEL='qwen3-vl-plus'
$env:GROUNDING_FIDELITY_MODE='high'
$env:IMAGE_ENRICHMENT_MODE='apply'

C:\Users\lzq\.conda\envs\omni\python.exe scripts/image_figma_mvp.py `
  --image output/_image_figma_acctoken_models_20261108_rerun_full_high/input.png `
  --truth output/_image_figma_acctoken_models_20261108_rerun_full_high/derived.truth.json `
  --out output/_image_figma_acctoken_models_20261108_rerun_full_high `
  --route grounding `
  --acceptance-policy 2.0
```

注意：同一输出目录已经有文件，不能直接覆盖；复现时请使用新的 `--out`。

---

## 10. 交接时必须保留的判断

- FlexWeaver 当前是 `14/32`，不是 pass。
- ACCTOKEN 当前是派生 truth 的 `blocked-fail`，不是历史冻结 holdout pass/fail。
- 搜索修复的最优形式是“容差内位置 + 有限字距”，不是 bbox 完全重合。
- 不要按单个特例继续扩大硬编码；优先使用低对比、search 语义和统一容差规则。
- 任何“通过”声明都必须来自真实 Figma export 和当前 formal acceptance。
