# Image → Figma 跨样本泛化问题：架构诊断与修复

**日期：** 2026-11-08
**范围：** `image → Figma` grounding 高保真链路
**结论级别：** 架构诊断 + 已实施的第一层修复；**不声明 overall pass**
**不改动：** 冻结的 `acceptance-policy 2.0` 门禁、冻结 truth、R5-P3 生产准入结论

---

## 1. 问题陈述

同一套命令、同一个模型（`qwen3-vl-plus`）、同一个 `--acceptance-policy 2.0`：

| 样本 | 尺寸 | 主题 | 用户观感 | 正式结果 |
| --- | --- | --- | --- | --- |
| FlexWeaver Admin | 1920×826 | 浅色表单 | 约 95% 精准复刻 | `blocked-fail`，native gate `14/32`，chrome pass，within30 `96.7662%` |
| ACCTOKEN Models | 2544×1336 | 深色卡片网格 | 换图即崩 | `blocked-fail`，native gate `0/19`，chrome fail，within30 `94.1469%` |

两张结果就是当前 Figma 页面中的
`Fixed canvas image-sha256:c01805877d…`（`28:15696`）与
`Fixed canvas image-sha256:674d733f3b…`（`28:15929`）。

---

## 2. 根因链（按贡献排序）

### 2.1 主因：VLM 坐标系契约缺失，`y_scale` 被硬编码为 1

`src/app/services/structure/backends/grounding_vlm.py::parse_vlm_json`：

```python
x_scale = image_w / 1000.0 if image_w > 1000 and max(raw_x_values) <= 1000 else 1.0
y_scale = 1.0     # <-- 从未按 image_h 归一化
```

VLM 返回的 bbox 落在 0–1000 归一化空间。x 轴被猜出来并乘以 `image_w/1000`，
**y 轴没有**。纵向误差随 y 线性增长：

- ACCTOKEN 高 1336 → `1000/1336 = 0.7485`
- 实测 32 组「VLM 文本 ↔ OCR 同一文本」的 `y_vlm / y_ocr` 中位数 = **0.7563**
- `Seedance 特惠款`：VLM y=484，OCR y=638（484/638 = 0.759）
- `输入·峰时`：VLM y=624，OCR y=829（0.753）
- `看详情 →`：VLM y=835，OCR y=1121（0.745）

页面顶部误差只有几像素，底部误差可达 300px，因此**下半屏文本 bbox 全部落在空白背景上**。
FlexWeaver 高 826（<1000），误差相对小，且它的正式运行使用冻结 prepared pipeline，
掩盖了这个缺陷。

### 2.2 次因：感知证据丢失被静默降级，而不是被拦截

`src/app/services/structure/fidelity/style_resolver.py::resolve_text_style`：
固定阈值 `distance >= 24`、以 crop 边框中位数估计背景。深色主题低对比文字或错位 bbox
导致 `ink_count < 2`，函数返回 `status: low-confidence / reason: text-ink-not-found`，
**不写 `ink_bbox`**。

下游连锁反应：

- `evidence/native_text_quality.py:379-392` 只把同时具备 `source_bbox` 和 `ink_bbox`
  的文本登记为 native owner；缺 `ink_bbox` 的元素被静默丢弃
  → 门禁把"Figma 里其实存在的文字"报成 `native-text:missing:<text>`
- `fidelity/text_calibration.py` 的 15 个校准阶段全部依赖 `ink_bbox`，对这些文本跳过
- `fixed_canvas_compiler.py` 无法用 ink_bbox 做遮罩
- 回退样式硬编码 `#555555` 灰字 + `fontSize = 0.75 * box_height`，在深色主题上必错

量化：

| 样本 | 文本元素 | 缺 `ink_bbox` | 比例 | `font_calibration.adjusted_count` |
| --- | --- | --- | --- | --- |
| FlexWeaver | 75 | 1 | 1.3% | 176 |
| ACCTOKEN | 49 | 12 | **24.5%** | 7 |

12 个失效 bbox 的参考图裁剪 `dist.max() == 0`（完全空白），确认是坐标错位而非对比度问题。

### 2.3 感知阶段文本召回断点（逐阶段证据）

| 阶段 | FlexWeaver | ACCTOKEN |
| --- | --- | --- |
| VLM enrichment | 0/24 | 2/27 |
| OCR supplement | 22/24 | 16/27 |
| content inventory | 24/24 | 24/27 |
| scene plan → design → Figma | 24/24 | 24/27 |

`5.8折` / `8.8折` 在 VLM enrichment 里被判为 raster 徽标资产；`查看详情` 在任何阶段都未出现
（截图实际是 `看详情 →`，**truth 清单写错**）。

### 2.4 校准阶梯是针对单一样本调出来的，不是通用优化器

`scripts/image_figma_mvp.py:292-667` 是 15 个顺序硬编码阶段：
`control fonts → table fonts → form text positions → table positions → table letter spacing →
form fonts → form weight → form shape → form positions ×2 → placeholder →
toolbar spacing → toolbar weight → toolbar respacing → search control`。

- 阶段名绑定 FlexWeaver 的 `form / table / toolbar / search` 布局角色
- FlexWeaver：`adjusted_count = 176`；ACCTOKEN：`7`，且 `form_*` 阶段多数 `not-needed`
- 没有通用的「按残差选策略」循环，也没有跨样本能力画像

HANDOFF 第 559 行已明确警告「不要按单个特例继续扩大硬编码」，本诊断给出其量化代价。

### 2.5 大面积源像素底图让第一张图的 95% 失真

`src/app/services/structure/fidelity/fixed_canvas_compiler.py::_source_form_background`
只在同时存在 `form-section` 与 `table-section` 角色时触发，把**原截图裁剪**贴回设计
（文字区域被涂掉以便叠原生文字）：

| 样本 | raster 面积占比 | overall bad | native-only bad | raster 区 bad |
| --- | --- | --- | --- | --- |
| FlexWeaver | **47.41%** | 3.2338% | 4.0482% | 2.3306% |
| ACCTOKEN | 1.97% | 5.8531% | 5.9384% | 1.6069% |

即第一张的 `within30 = 96.77%` 有约一半画布是原图位图在兜底；
剔除底图后的真实原生误差 `4.05%` 与第二张 `5.94%` 差距远没有"95% vs 崩"那么夸张。
**真正断崖式下降的是 native-text 结构质量（14/32 → 0/19），不是像素相似度。**

### 2.6 没有 truth-independent 的自检与双样本回归护栏

验收依赖每张图自带的 `critical_texts` manifest；流水线在运行期不知道自己漏了文字，
只有写进 Figma 之后才由门禁发现。此前也没有任何命令能同时检查两个样本。

---

## 3. 目标架构

```text
Input image
  └─ CoordinateSpaceContract      单一坐标空间；VLM 输出统一做可验证的逆变换
     └─ PerceptionLayer           VLM + OCR + 自适应墨迹检测（亮/暗主题通用）
        └─ PerceptionContract     每个文本 bbox 必须在参考图中有墨迹证据
           │                      否则：逆变换重定位 → OCR 重定位 → 显式 quarantine
           └─ ScenePlan / Compiler  所有文本都带 styleEvidence.ink_bbox
              └─ CalibrationLoop   声明式策略 + 残差驱动选择（替代 15 段硬编码阶梯）
                 └─ Figma render
                    └─ Frozen acceptance  +  NativeFidelity 诊断（剔除位图底图）
                       └─ GeneralizationGuard  双样本回归门禁
```

关键不变量：

1. **只修复被像素证据证明为坏的 bbox**；已验证元素永不改写 → 已校准样本不可能退化。
2. **漂移判定看结构性特征**（同一个逆坐标变换解释多数坏框），而不是拍一个全局比例阈值。
3. **诊断与验收分离**：新指标只写 `perception_coverage.json`，不进冻结门禁。

---

## 4. 本次已实施

| 文件 | 变更 |
| --- | --- |
| `src/app/services/structure/fidelity/perception_contract.py` | 新增。自适应 Otsu 对比度、文本形态校验、逆坐标变换候选、OCR 重定位、`run_perception_contract`、`evaluate_native_fidelity` |
| `scripts/image_figma_mvp.py` | 新增 `--perception-contract {off,report,adaptive}`（默认 adaptive）、`--perception-drift-threshold`、`--strict-perception`；写出 `perception_coverage.json` / `figma_design_unrepaired.json`；末尾追加 native fidelity 诊断 |
| `scripts/check_image_generalization.py` | 新增双样本泛化护栏 CLI |
| `tests/v2/test_perception_contract.py` | 新增 5 个单测（暗色低对比、归一化 y、零回归、系统性漂移、剔除位图） |

默认命令无需改动，新样本会自动走 `adaptive`：
`perceptionDefectRatio > 0.20` 或检测到系统性坐标漂移时才触发修复。

---

## 5. 真实 Figma 验证（`--reuse-prepared` + 真实 export）

两次运行均使用冻结 prepared pipeline、真实 Figma 写入/回读/导出与当前 formal acceptance。

### ACCTOKEN（本次修复目标）

| 指标 | 修复前 | 修复后 |
| --- | --- | --- |
| 运行目录 | `_image_figma_acctoken_models_20261108_rerun_full_high` | `_image_figma_acctoken_perception_contract_20261108_r1` |
| perception `broken / unverified` | 13 / — | 13 / **0** |
| 系统性坐标漂移 | 未检测 | **`y+height-1000` 命中 10 个** |
| criticalText matched | **18/27** | **24/27** |
| criticalText missing | 9 项 | **3 项**（`5.8折`, `查看详情`, `8.8折`） |
| native ownerCount | 19 | **26** |
| acceptance status | `blocked-fail` | `blocked-fail`（未改变结论级别） |
| acceptance blockers | 31 | 32（6 个假 missing 变成 7 个真实 owner blocker） |
| native gate ownerPassCount | 0/19 | 0/26 |
| overall / native-only bad pixel | 5.8531% / 5.9384% | 5.8789% / 5.9737% |

13 个错位文本全部重定位到 OCR 验证过的位置（例如 `Seedance 特惠款` y 484→647、
`输入·峰时` y 624→834、`看详情 →` y 837→1118）。

**解读**：本次修复解决的是「文本是否存在、是否在正确位置」，不是 glyph 级字体保真度。
因此 `criticalText` 与 owner 覆盖显著改善，但 native gate 的 edgeF1/coverage 仍为 `0/26`，
像素指标基本持平——这两项属于 §7 的 P1（通用校准循环）。没有把 blocker 数量下降说成通过。

### FlexWeaver（回归护栏，逐字节一致）

运行目录 `_grounding_flexweaver_perception_contract_20261108_r1`：

| 指标 | 基线 | 带新契约重跑 |
| --- | --- | --- |
| perception status / applyRepair | — | `verified` / `false` |
| 设计元素被改写 | — | **0 / 143** |
| `figma_design.json` elements | 143 | **完全相同（逐元素相等）** |
| `figma_search_control/export.png` SHA-256 | `972049b6…4088c` | **`972049b6…4088c`** |
| critical text | 24/24 | 24/24 |
| native gate | 14/32 | 14/32 |
| chrome / blockers | pass / 18 | pass / 18 |

即：新默认配置对第一张图**零改动、零回归**，正式导出与交接基线逐字节一致。

### 测试与静态检查

```text
pytest tests/v2/test_perception_contract.py tests/v2/test_image_enrichment_tiling_runtime.py
    → 14 passed
pytest -q --ignore=output（全量）
    → 1253 passed, 1 failed
      失败项：tests/v2/test_capture_browser_engine.py::test_non_rendered_svg_clip_geometry_is_not_captured
      原因：本机缺少 WebKit 可执行文件
            C:\Users\lzq\AppData\Local\ms-playwright\webkit-2336\Playwright.exe
      → 环境依赖缺失，与本次改动无关；需 `playwright install webkit` 后复跑
ruff check <4 files>                              → All checks passed
git diff --check                                  → pass
node --check figma_bridge/code.js                 → pass
check_image_generalization.py --baseline ... --holdout ...
    → status: pass（baseline_not_regressed / holdout_recoverable / drift_signal_present 全 true）
```

交接基线为 `1249 passed`；本次新增 5 个单测后为 `1253 passed + 1 环境失败`。

---

## 6. 剩余 3 个缺失关键文本：定性，不回填指标

放大原图确认：

- `5.8折` / `8.8折`：徽标内是**上下两行**（`5.8` 与 `折`），pipeline 只生成了 `5.8` 原生文本，
  其余进 raster 资产。这是**逻辑标签聚合**缺失，不是感知失败。
- `查看详情`：截图实际是 `看详情 →`（VLM、OCR、放大图三者一致）。
  **派生 truth 的 critical_texts 与截图不符**，属于数据错误，不应通过放宽 matcher 来"修好"。

按交接约束，本次没有改 truth、没有改门禁阈值、没有回填指标。

---

## 7. 仍为 `blocked-fail` 的部分与下一步

| 优先级 | 事项 | 依据 |
| --- | --- | --- |
| P1 | 把坐标系契约前移到 `parse_vlm_json` / provider 边界，用「像素墨迹支持」取代 `x_scale` 猜测，并让 `y_scale` 对称 | 本次在编译后修复有效，但上游仍会产出坏 bbox，浪费一次编译 |
| P1 | 把 15 段校准阶梯重构为声明式策略注册表 + 残差驱动选择器（position / size / coverage / edgeF1 四类残差 → 策略 → 有界迭代） | FlexWeaver 176 次 vs ACCTOKEN 7 次；native gate 修复后仍 `0/26` |
| P2 | 引入 `LogicalTextAggregation`：把相邻多行 OCR/VLM token 聚成逻辑标签，给 owner 增加 `logicalText` | `5.8折` / `8.8折` |
| P2 | 通用背景重建（渐变/纹理）替代 `_source_form_background` 的 `form-section`+`table-section` 硬编码 | banner chrome `8.68% > 5%`；FlexWeaver 47.4% 位图兜底 |
| P3 | 修正派生 truth 的 `查看详情`，并把它标为 derived、不得冒充冻结 holdout | 放大图证据 |
| P3 | 把 `check_image_generalization.py` 接入 CI，并扩充到 ≥3 个不同主题/DPR/版式样本 | 目前只有 2 样本护栏 |

**保持的判断**：R5-P3 仍是 `production-not-admitted`；本工作只改善
image 高保真链路的跨样本泛化，不改变生产准入结论。
任何"通过"声明必须来自真实 Figma export 与当前 formal acceptance。

---

## 8. 全量重跑验证（不使用 `--reuse-prepared`）

按用户要求对两张图各做一次真正全量重跑：重新调用 `qwen3-vl-plus`、OCR、
image enrichment、ScenePlan/Compiler、Figma 写入/回读/导出与 formal acceptance。
两张图串行执行（共用一个 bridge 与 Figma 页面），输出均为全新目录。

```text
FlexWeaver: output/_image_figma_fullrerun_20261108_flexweaver        (4m55s)
ACCTOKEN:   output/_image_figma_fullrerun_20261108_acctoken          (1m34s)
对照实验:   output/_image_figma_fullrerun_20261108_flexweaver_repairprobe (2m34s)
```

### 8.1 两次全量结果

| 指标 | FlexWeaver 冻结基线（reuse-prepared） | FlexWeaver 全量（新） | ACCTOKEN 全量基线（修复前） | ACCTOKEN 全量（新） |
| --- | --- | --- | --- | --- |
| status | `blocked-fail` | `blocked-fail` | `blocked-fail` | `blocked-fail` |
| critical text | 24/24 | 24/24 | **18/27** | **24/27** |
| missing | 0 | 0 | 9 项 | **3 项** |
| native gate | 14/32 | 11/33 | 0/19 | 0/25 |
| chrome | pass | pass | fail(banner) | fail(banner) |
| within30 | 96.7662% | 96.2210% | 94.1469% | **94.1966%** |
| bad pixel | 3.2338% | 3.7790% | 5.8531% | **5.8034%** |
| blockers | 18 | 22 | 31 | 31 |
| perception | — | `verified`（不修复） | — | `repaired` |
| 感知坏框 / 不可恢复 | — | 16 / 7 | — | 11 / **0** |
| 系统性坐标漂移 | — | False | — | **True**（`y+height-1000` ×9） |
| 契约改写元素 | — | **0** | — | 11 |
| font calibration | 176 | 185 | 7 | 9 |

### 8.2 ACCTOKEN：修复在独立 VLM 调用上稳定复现

这是本次最关键的验证。`_image_figma_acctoken_models_20261108_rerun_full_high`
本身就是修复前的全量重跑，口径完全一致；新的全量重跑是**另一次独立 VLM 采样**：

- critical text `18/27 → 24/27`，missing `9 → 3`，与 prepared-pipeline 结果一致
- 9 个文本由同一个 `y+height-1000` 逆变换解释，系统性漂移再次命中
- 11 个坏框全部恢复、`unverified = 0`
- within30 与 bad-pixel 略改善（+0.05pp / −0.05pp），没有出现"结构变好但画面变差"

即修复不依赖某一次 VLM 的偶然输出。

### 8.3 FlexWeaver：全量退化不是感知契约造成的

`applyRepair = false`、**设计 0 个元素被契约改写**，所以 `14/32 → 11/33`、
`96.7662% → 96.2210%` 完全来自 VLM 重新采样与冻结 prepared pipeline 的差异：

- 全量感知输出有 16/84（19.05%）坏框，冻结 prepared 只有 8/75（10.67%）
- 这些坏框主要是表格小数字 `"2"` 和 JSON 片段的**畸形 2px 高 bbox**
  （如 `[422, 824, 231, 2]`），不是坐标空间错误
- `transformCounts = {x-axis-1000: 1, xywh-1000: 2, y+height-1000: 0, y-axis-1000: 0}`，
  没有统一变换，`systematicCoordinateDrift = False` 判定正确

### 8.4 对照实验：不要靠调低阈值硬修

用 `--reuse-prepared --perception-drift-threshold 0.15` 复用同一份全量 pipeline，
强制触发修复（9 个元素）：

| 指标 | 默认 0.20（不修复） | 强制 0.15（修复 9 个） |
| --- | --- | --- |
| native gate | 11/33 | 11/37（通过数不变，多 4 个失败 owner） |
| blockers | 22 | **26** |
| within30 | 96.2210% | 96.3491% |
| critical | 24/24 | 24/24 |

结论：强行修复只让 4 个本就测不准的 owner 进入门禁，**净增 4 个 blocker**，
不能改善 native gate。默认「只在系统性坐标漂移时修复」的策略保持不变，
不因为单张图的指标去调阈值（那正是本项目此前过拟合的模式）。

### 8.5 本次全量重跑暴露的下一步

1. **P1（新）**：表格/JSON 区域的 2px 畸形 bbox 属于上游结构解析缺陷，
   应在 `table_scene.py` / `image_contract.py` 增加「最小文本 bbox 高度」约束与
   OCR 行合并，而不是交给感知契约事后猜位置。
2. **P1**：VLM 重采样不稳定性需要固定 seed / 温度或缓存感知产物，
   否则同一张图两次全量重跑会得到不同结构，正式基线不可复现。
3. 保持 §7 的 P1：15 段校准阶梯改为残差驱动循环（native gate 仍 0/25）。

可视化对比：`output/_image_generalization_20261108/full_rerun_comparison.png`
（2×3 总览）、`full_rerun_acctoken_detail.png`（ACCTOKEN 大图），
机器可读汇总：`full_rerun_summary.json`。

---

## 9. 架构级改造 A + D 已实施（2026-11-08 12:00）

按 §3 目标架构，落地了前两项：**A 坐标系契约前移**、**D 感知产物可复现性契约**。
§7 的 B（校准闭环）与 C（底图策略化）仍未实施。

### 9.1 改动清单

| 文件 | 作用 |
| --- | --- |
| `src/app/services/structure/coordinate_space.py`（新） | 证据驱动的坐标空间判定：`infer_coordinate_space` 枚举 identity / x-1000 / y-1000 / xywh-1000 四种逆变换，用参考图像素墨迹支持打分；`resolve_bbox` 逐元素处理混合坐标空间（越界优先、ink 次优）；`legacy_axis_scales` 仅保留给无图像的 parse-only 调用 |
| `src/app/services/structure/backends/grounding_vlm.py` | `parse_vlm_json` 删除证据路径上的 `x_scale` 猜测与 `y_scale=1.0`，改为 `image_path` 注入 + decision；输出 `coordinateSpace` 顶层决策与逐元素 provenance；`ground` / `ground_with_prompt` 传入 `image_path` |
| `src/app/services/structure/providers/grounding.py` | `_collect_report` 把 `coordinate_space` 决策写入 `09_evidence_bundle.json` 的 `grounding_reliability`，使 provenance 可追溯 |
| `src/app/services/structure/perception_fingerprint.py`（新） | `vision_request_contract`（请求契约，含坐标契约版本）、`build_perception_fingerprint`（规范化 artifact 哈希 + manifest 指纹） |
| `src/app/services/structure/backends/grounding_reliability.py` | `request_contract` 纳入 cache key；新增跨进程持久化内容寻址缓存 `.vision_cache/`（无 TTL，key 已覆盖全部参数） |
| `src/config/settings.py` / `.env.example` / `.gitignore` | 新增 `VISION_TEMPERATURE` / `VISION_SEED` / `VISION_SEND_SEED` / `VISION_PERSISTENT_CACHE*`；缓存目录不入库 |
| `src/app/agents/precise_agent.py` | 单图链路 `manifest.json` 写入 `perception_fingerprint`，并落盘 `pipeline/perception_fingerprint.json` |
| `tests/v2/test_coordinate_space_contract.py`（新） | 10 个单测：逆变换选中、逐元素越界保护、legacy 兼容、请求契约进 key、持久缓存跨实例、指纹排除执行状态 |

### 9.2 关键设计决策（含一次回退）

1. **可复现性由缓存保证，不改请求分布**。初版把 `temperature` 改成 `0.0` 并新增发送 `max_tokens=16000`，结果 VLM 少输出 `本期好价` 等文本，critical 从 `24/27` 掉到 `21/27`。已回退为历史的 `temperature=0.1`（本来就是固定值）、不发送 `max_tokens`；`seed` 只作为本地契约语义记录，默认不发送（多数 OpenAI 兼容网关不接受）。**缓存才是跨运行一致性的来源**。
2. **契约版本进入 cache key**。A 的逻辑调整后把 `COORDINATE_CONTRACT_VERSION` 升到 `1.1`，旧缓存自动失效，避免回放旧解析结果。R3 因此重新调用 VLM。
3. **逐元素 override 收紧**。ink 判据从「identity 略优即 override」改为「需显著更优（1.5×+0.02）」，避免邻近内容把本该缩放的文本留在旧 y。
4. **指纹规范化**。artifact 哈希剔除运行目录绝对路径与执行状态（`cache_status` / `latency` / `token_usage` / `observability`），否则一次缓存命中也会让指纹变化。
5. **legacy 兼容分支保留**：不提供 `image_path` 的 parse-only 调用（单测、离线工具）行为逐字节不变，27 个既有解析/可靠性测试全绿。

### 9.3 真实全量验证（ACCTOKEN，4 次运行）

| | R1（初版） | R2（R1 缓存命中） | R3（修正版） | R4（R3 缓存命中） |
| --- | --- | --- | --- | --- |
| 运行目录 | `_archAD_..._r1` | `_r2` | `_r3` | `_r4` |
| 耗时 | 1m34s | **29s** | 1m38s | **29s** |
| cache_status / attempts | miss / 1 | **hit / 0** | miss / 1 | **hit / 0** |
| 坐标决策 provenance | 未传播 | — | **`xywh-1000`（47/47 像素支持）** | 同 R3 |
| 感知契约 | verified，坏框 3/44 | — | **verified，坏框 3/42、unverified 0、未触发修复** | 同 R3 |
| critical text | 21/27 | 21/27 | 22/27 | **22/27** |
| within30 | 95.1478% | 95.1478% | **95.1632%** | **95.1632%** |
| blockers | 31 | 31 | 30 | **30** |
| 规范化感知指纹 | — | 与 R1 一致 | `f1102942…` | **`f1102942…`（一致）** |

R3/R4 的 `10_content_inventory.json`、`11_scene_plan.json`、`12_design.json` **逐字节一致**，验收指标完全一致。

### 9.4 达成的与未达成的

**A 达成**：`y_scale=1.0` 从真实链路移除；`xywh-1000` 由 47/47 像素证据选中并写入 `09_evidence_bundle.json`；编译后感知契约从「必须补救 11 个框」降级为「校验即可，坏框 3 个、0 未恢复」；within30 相对改动前全量基线 `94.1966% → 95.1632%`（+0.97pp）。这正是「契约前置」相对「后置补救」的架构收益。

**D 达成**：跨进程持久缓存命中（`attempts=0`、耗时 94s→29s），感知产物与规范化指纹逐字节一致；契约版本变更自动失效旧缓存；`manifest.json` 可追溯请求契约、输入 sha、artifact 哈希与坐标决策。

**未达成 / 需如实记录**：R3/R4 的 critical text 是 `22/27`，低于改动前全量基线的 `24/27`。根因不是坐标：VLM 本次输出少了 `本期好价`、`复制模型 ID` 两个文本 owner（temperature 0.1 仍是非确定性采样，首次结果被缓存固化）。也就是说 **D 让这个新输出稳定可复现，但没有让它变好**。这是后续要处理的感知召回问题，不是 A 的回归。

### 9.5 验证与检查

```text
pytest tests/v2/test_coordinate_space_contract.py + 解析/可靠性/契约测试  → 37 passed
pytest -q --ignore=output（全量）                                        → 1263 passed, 1 failed
    唯一失败：test_capture_browser_engine.py 缺 WebKit 可执行文件（环境依赖，与本次改动无关）
ruff check <本次 12 个改动文件>                                          → All checks passed
    全仓 `ruff check src scripts tests` 仍有 142 条历史遗留告警（如 axure_proto_gen.py 未用 import），非本次引入
check_image_generalization.py（冻结基线 + 修复前全量 holdout）              → status: pass
git diff --check                                                        → pass
```

### 9.6 A+D 之后的下一步

1. **P1（新，最高）**：VLM 文本召回稳定性 —— 对同一图像做多次独立采样取并集，或用 OCR 行作为 owner 下界，解决 `本期好价` / `复制模型 ID` 这类漏输出。D 的缓存已提供稳定基线，这项工作现在可以可靠评估。
2. **P1**：把 `coordinateSpace` provenance 继续传播到 `11_som.json` / `12_design.json` 元素（当前只到 `09_evidence_bundle.json`）。
3. **P1**：持久缓存目前只覆盖 grounding VLM 调用；image generation / enrichment 的其他调用不在契约内。
4. **P1**：§7 的 B（残差驱动校准闭环）与 C（底图策略化 / 指标口径）仍未动，native gate 仍 `0/22`。

**保持不变**：`acceptance-policy 2.0` 冻结门禁未改、truth 未改、指标未回填；
所有运行仍为 `blocked-fail`；R5-P3 仍是 `production-not-admitted`。

---

## 10. 「先测不先改」：三层感知召回基线（2026-11-08 13:30）

按 §9.6 的起点开始 **P0 建基准 + P1 第一步**，本轮**只测量、不改生产链路**：
新增只读诊断 `scripts/measure_perception_recall.py`，并跑一张从未参与任何常量选择的
新 holdout 图。**结论修正了上一轮的改造判断。**

### 10.1 为什么要分三层

一个笼统的 "perception recall" 会把丢失位置藏起来。OCR 看到的文字可能：
进了内容清单却没发射成 native TEXT；或发射了 TEXT 却没注册成 gate owner。
这是三种不同缺陷，必须分别报，不能合并成一个分数：

```text
R  参考截图  --(独立OCR观测, 高置信度下界)-->  I  内容清单
I  内容清单  --(ScenePlan / Compiler 发射)-->   N  native TEXT 图元
N  native TEXT --(native_text_quality 注册)-->  G  gate owner
```

- `R→I` / `R→N` 用 `pipeline/ocr_supplement.json` 的 `observations`（easyocr/tesseract，
  独立于 VLM 生成路径）作为**召回下界**，只用 confidence ≥ 0.60 的观测。
- `I→N` 以 `10_content_inventory.json` 中 `text/control/table-cell` 为参照。
- `N→G` 以 `native_text_quality.json` 的 `owners[].text` 为参照。
- 归一化只做全半角、空白与常见标点变体（`·`/`・`/`•`/`．`→`.`，`，：`→`,:`等），
  **不做内容替换**（不猜 `半`→`¥`），避免制造假匹配。
- 明确局限：OCR 是下界不是真值，它同样会漏读且与生成路径共享原图；匹配是字符串
  相似度而非 glyph/位置验证；四层 recall 不得相乘或合成总分。

### 10.2 六个运行目录的基线

| 运行 | R→I | I→N | R→N | N→G | critical |
| --- | ---: | ---: | ---: | ---: | --- |
| holdout3 `flexweaver_submitted` | 95.5% | **100.0%** | 95.5% | 90.7% | 24/29 |
| holdout3 `acctoken_models` | 94.9% | 96.6% | 92.3% | 89.8% | 19/27 |
| holdout3 `deepseek_keys` | **100.0%** | 92.5% | 97.1% | **87.8%** | 20/23 |
| 全量基线（A+D 前，带契约修复） | 94.9% | 94.4% | 92.3% | **100.0%** | 24/27 |
| R3（A+D 后） | 94.9% | **88.2%** | **87.2%** | 97.6% | 22/27 |
| **新 holdout `IMG-ACCTOKEN-API`** | **100.0%** | **88.9%** | 93.5% | 93.3% | 40/48 |

跨样本范围：`R→I` 94.9–100%（中位数 95.2%）、`I→N` 88.2–100%（93.4%）、
`R→N` 87.2–97.1%（92.9%）、`N→G` 87.8–100%（92.0%）。

### 10.3 关键发现：上一轮的归因错了

上一轮把 R3 的 critical `24/27 → 22/27` 归因为「VLM 少输出两个文本 owner」，
并据此把 P1 定为「补独立感知召回门禁」。**测量否定了这个判断**：

- `本期好价`：OCR ✓、inventory ✓、**native ✗** → 丢在 `I→N`，不是 `R→I`
- `复制模型 ID`：OCR ✓、inventory ✓、native ✓、**gate owner ✗** → 丢在 `N→G`
- R3 的 `I→N` missing 共 6 项，其中 `¥4.64`、`¥8.00`、`大厂直供`、`三方供应`
  在 inventory 里是 `kind=text`、`reference_only` 未设置、`authority=grounding`，
  即**本应发射却没发射**；另 2 项是 OCR 噪声（`11月 &日更新`、`半20.24  起`）
- `R→I` 在 6 个目录里最低仍有 94.9% —— **独立召回下界不是瓶颈**

新 holdout 进一步坐实：它的 `R→I = 100%`，但 `I→N = 88.9%`，且
`I→N` 的 missing 与 critical missing 直接重合——
`不限额度`、`数据看板`、`钱包`，以及空格写法的 `9 月 3 日创建` ↔ `9月3日创建`。
也就是说 **critical 文本缺失主要发生在「清单→图元发射」，不是「截图没看清」**。

### 10.4 新 holdout 的真实验收（未参与任何常量选择）

输入 `IMG-ACCTOKEN-API.png`，2544×1336，
sha256 `7c61218a…f404`，与冻结 truth 完全匹配；
版式为深色 dashboard + 表格 + badges + 掩码凭据，与前两张（浅色表单 / 卡片市场）不同。
输出 `output/_image_figma_holdout_20261108_acctoken_api`（新目录，未覆盖）。

```text
status            blocked-fail
critical text     40/48，missing: 数据看板 / 钱包 / 推荐官 / 我的等级 / 过期 /
                  9月3日创建 / 不限额度 / ICP备2026030291号-1
native gate       0/44
chrome            fail (chrome-visual:table-header)
within30          95.6062%   bad-pixel 4.3938%
blockers          55
坐标契约          xywh-1000（53/62 像素支持），A 在新图上仍生效
感知契约          verified，7 个坏框全部恢复、unverified 0，未触发修复
缓存 / 指纹        miss / f424dc34…
```

注意 within30 95.6% 高于两张旧样本，但 native gate 仍 0/44、chrome fail ——
再次印证「整体像素相似度不能替代内容/结构验收」。

### 10.5 修正后的路线（替换 §9.6 第 1 条）

| 原计划 | 修正后 |
| --- | --- |
| P1 先补独立 OCR 召回门禁 | **降级**：`R→I` 已 94.9–100%，补它的边际收益最小；保留为长期下界监控，不是第一刀 |
| — | **P1（新，最高）**：`InventoryEmissionContract` —— ScenePlan/Compiler 必须为每个非抑制的 `text/control/table-cell` 清单项发射恰好一个 native owner，未发射即 blocker；同时修 `N→G` 的 owner 注册（`复制模型 ID` 型：文字在但 owner 未登记） |
| — | **P1（新）**：逻辑标签聚合仍要做，但优先级排在发射契约之后；`折`×2 与 `9 月 3 日创建` 的空白/标点是归一化问题，不应算内容缺失 |
| P2 校准闭环 | 保持不变，但必须在发射契约之后 —— 否则仍在漏的地基上优化字形 |

**制度不变**：单样本改善不算完成（任何新策略需 ≥2 样本验证）、分轨报告、旧失败不追认、
约定必须落成代码 + 单测 + 真实 formal acceptance、`R5-P3 production-not-admitted` 不变。
本轮新增的 `perception_recall_baseline.json` 与 `measure_perception_recall.py` 均为**只读诊断**，
不进冻结门禁、不改任何设计或验收结果。

---

## 11. InventoryEmissionContract：第一刀落地（2026-11-08）

### 11.1 身份对齐再次修正了上一章的归因

第 10 章用**归一化文本相似度**测 `I→N`，得到 88.2–100%，并把缺口解释为
「清单项未发射」。改用 `contentRef` 做**身份对齐**后，结论被推翻：

| 检查 | 六个运行目录的结果 |
| --- | --- |
| inventory 项无 plan 节点、**且无 suppressed 记录** | **0** |
| plan 文本节点无 design 元素 | **0** |
| design 中同一 `contentRef` 发射两次 | **0** |

即 `inventory → scene plan → design` 三层是按身份严格一一对应的；
`Compiler._meta.coverage = 1.0` 虽是硬编码，但它对每个 plan node 确实发射了元素。
上一章报出的 `I→N` 缺口，相当一部分是**合法抑制**被文本匹配误判为丢失
（例如 `table-cell-owner-authoritative` 把同名表头合并到表格 owner）。

真正的丢失只有两处，都在身份链的两端：

1. **抑制替代不校验文本等价**（`fidelity/scene_plan.py::_suppress_overlapping_text_owners`）。
   旧判据明确要求 `normalize_match_text(existing) != normalize_match_text(node)`，
   再仅凭 bbox `_overlap_over_smaller >= 0.45` 就删掉后者 —— 等于把**几何重叠当成内容重复**。
   实测被删掉的是完全不同的可见标签：
   `本期好价` → `折扣都按官方价实时算`、`¥4.64` → `DeepSeek V4.1 Flash`、
   `数据看板` → `API 密钥`、`钱包` → `推荐官`。
   VLM bbox 越大、越容易重叠，这个 bug 就越致命 —— 它天然对其他版式更不友好。
2. **native gate 静默跳过 owner**（`evidence/native_text_quality.py::build_native_text_quality`）。
   元素缺 `styleEvidence.evidence` 或缺 `ink_bbox` 时直接 `continue`，
   而 `criticalText.matchedCount` 只在 `owners` 列表里匹配。于是
   **Figma 里存在、readback 里是 native TEXT 的文字，被门禁报成 `missing`**。
   实测 `复制模型 ID`、`看详情`、`概览`、`状态`、`原型绘制`、`过期`、`推荐官`、`我的等级` 均属此类。

### 11.2 已实施（改动均在 `D:/LLM-Data/Figma_auto_agent`）

| 文件 | 内容 |
| --- | --- |
| `fidelity/emission_contract.py`（新增） | `suppression_allowed()` 作为 planner 与审计共用的**单一判据源**；`audit_emission()` 按 `contentRef` 审计 5 条不变量（身份唯一 / 抑制有记录 / 抑制等价 / plan-design 对齐 / native owner 已注册）；`register_unmeasured_owners()` 产出诊断副本；`critical_missing_overlap()` |
| `fidelity/scene_plan.py` | 重叠抑制改为调用同一判据：仅当**文本等价**，或**被抑制项是 `authority=ocr` 的噪声变体**（相似度 ≥0.80）时才允许替代。两个 grounded 标签不再因重叠被合并。`SCENE_PLAN_LEGACY_OVERLAP_SUPPRESSION=1` 可完整回退旧行为做 A/B |
| `evidence/native_text_quality.py` | 新增 `register_unmeasured_owners` 可选参数（**默认 False**）：不可测元素登记为 `status=unmeasurable-missing-evidence`，`nativeText` 由 readback 判定，不带 `checks`、永不 `pass`、不重算 gate |
| `scripts/image_figma_mvp.py` | `--emission-contract {off,report,repair}`（默认 `report`，零行为变更）、`--strict-emission`（默认关），产出 `emission_contract.json` |
| `tests/v2/test_inventory_emission_contract.py`（新增） | 30 个单测：等价判据、五类违规、诊断副本不重算 gate、planner 保留独立标签 / 吸收 OCR 变体 / legacy 回退、输入不可变 |

判据必须保留 OCR 例外：既有测试明确要求吸收 `执行#间`（`执行时间` 变体）与
`Wauto用户身份执行`（`auto用户身份执行` 变体）。**只用严格相等会破坏历史行为**，
这是第一次实现被 2 个既有测试拦下后修正的。

### 11.3 六样本离线契约基线

`output/_image_generalization_20261108/emission_contract_baseline.json`：

| 运行 | 违规数 | unequivalent-suppression | unregistered-owner | replacement-missing | 与 critical missing 重合 |
| --- | ---: | ---: | ---: | ---: | --- |
| holdout3 flexweaver | 34 | 21 | 12 | 1 | 创建时间 / 填报日期 / 当天总投入工时 / 操作 |
| holdout3 acctoken_models | 12 | 2 | 10 | 0 | ¥1.16 / 复制模型 ID / 输入·峰时 / 输出·峰时 |
| holdout3 deepseek_keys | 13 | 5 | 8 | 0 | 2026-08-05 / 产品定价 / 网页版免费对话 |
| 全量基线（A+D 前） | 6 | 6 | 0 | 0 | — |
| R3（A+D 后） | 8 | 6 | 2 | 0 | 复制模型 ID |
| **新 holdout ACCTOKEN-API** | **16** | **8** | **6** | **2** | 数据看板 / 钱包 / 推荐官 / 我的等级 / 过期 / 9 月 3 日创建 / 不限额度 |

契约的价值在于**点名**：以前这些文本只是 `criticalText.missing` 里的字符串，
现在能指出它是被哪个 `replacement_ref` 顶替、或哪个 `contentRef` 没注册 owner。

### 11.4 三样本真实全量重跑 + 严格 A/B

三样本全量（不带 `--reuse-prepared`，新目录，串行共用一个 Figma 页面）：
`output/_image_figma_emission_20261108_{acctoken_api,acctoken_models,flexweaver}`。
再用 `SCENE_PLAN_LEGACY_OVERLAP_SUPPRESSION=1` 在**同一份感知输入**下各跑一次 legacy 对照
（`..._emission_legacy_20261108_*`）。同感知判据：`10_content_inventory.json` 与
`ocr_supplement.json` **逐字节一致**（`11_scene_plan.json` 因判据本身不同而不同，属预期）。

| 同感知 A/B | critical | within30 | blockers | plan 节点 | emission 违规 |
| --- | --- | --- | --- | --- | --- |
| ACCTOKEN-API legacy | 40/48 | 95.6062% | 55 | 79 | 16 |
| **ACCTOKEN-API 新判据** | **44/48** | 95.5289% | 58 | 85 | **7** |
| FlexWeaver legacy | 24/24 | 91.3220% | 35 | 119 | 17 |
| **FlexWeaver 新判据** | 24/24 | **91.3354%** | 37 | 128 | **8** |

- 新判据在**未参与常量选择的验证集**上 +4 critical（`数据看板`、`钱包`、
  `9月3日创建`、`不限额度` 恢复），within30 仅 −0.08pp，`overlapping-text-owner`
  抑制 7→1，emission 违规 16→7。
- FlexWeaver 在同感知对照下 within30 **+0.013pp**，判据几乎无影响，
  critical 仍 24/24；emission 违规 17→8。

**必须说明的绝对退化**：把 `output/_image_figma_emission_20261108_flexweaver`
与历史全量基线 `_image_figma_fullrerun_20261108_flexweaver` 直接比，
within30 `96.2210% → 91.3354%`、chrome `pass → fail`、blockers `22 → 37`。
但这个对比**不是同感知**：历史基线是 A+D 之前的老运行（无坐标契约、
inventory 157 项），本次是 143 项且 `xywh-1000` 首次生效；legacy 对照在
同一份新感知输入下同样是 91.322%，证明退化来自**感知输入变化**，不是本轮判据。
跨全量重跑仍不可复现，是独立待办（见 §11.6）。

ACCTOKEN models 全量：critical 仍 `22/27`（未改善），但 emission 违规 `8 → 2`
（`unequivalent-suppression` 清零），剩余 2 项均为 owner 未注册。
`本期好价` 恢复到 design 后仍未被 gate 匹配，说明 `N→G` 是独立的下一层。

### 11.5 owner 注册修复：修正计量，不是放宽门禁

用 `_image_figma_emission_20261108_acctoken_api` 的真实 design / readback / export
离线调用 `build_native_text_quality`（不写 Figma、不进 acceptance）：

| | owners | critical | native pass | gate blockers | gate status |
| --- | ---: | --- | --- | ---: | --- |
| 默认（report） | 60 | 44/48 | 0/50 | 55 | fail |
| `repair`（注册补全） | 66 | **47/48** | **0/56** | **58** | **fail** |

补进来的 6 个 owner（`概览`、`状态`、`原型绘制`、`过期`、`推荐官`、`我的等级`）
readback 确认是 native TEXT，但状态全部是 `unmeasurable-missing-evidence`，
**没有一个被算作通过**，blocker 反而 +3。因此这是把「内容不存在」的错误计量
改成「内容存在但不可测」，不是回填指标、不是追认通过。`repair` 默认关闭。

### 11.6 未解决与下一步（按优先级）

1. **P0｜感知产物可复现性仍有缺口**：`perception_fingerprint.py` 的 `ARTIFACTS`
   包含 `11_scene_plan.json` 等**规划产物**，导致「同一份感知 + 不同规划」被判成不同基线；
   且 `image_ir.json` 在 cache=hit 时仍出现 `counts.nodes 57 vs 61` 的非确定性。
   需要把「感知核心指纹」与「pipeline 指纹」分开，并定位 image_ir 的写入时序。
   在此之前，同感知 A/B 应以 `content_inventory + ocr_supplement` 逐字节一致为准。
2. **P1｜`N→G` 注册修复的正式接线**：`--emission-contract repair` 已实现并离线验证，
   但尚未在冻结验收中启用；是否将其设为默认需单独拍板（会改变 critical 数字口径）。
3. **P1｜剩余 critical**：`ICP备2026030291号-1` 是唯一修复后仍 missing 的项；
   `5.8折` / `8.8折` 仍需逻辑标签聚合；`查看详情` 是派生 truth 写错（原图 `看详情 →`）。
4. **P2｜native gate 仍 `0/50`**：字形保真度未动，仍是 §7 的 15 段阶梯 → 残差驱动闭环（B）。
5. **P2｜`_source_form_background` 位图兜底**（C）与分轨指标口径，尚未决策。
6. `--strict-emission` 目前只是可选退出码，未纳入任何正式验收；
   `emission_contract.json` 与 `perception_coverage.json` 一样只做诊断。

### 11.7 口径与检查

- 冻结 `acceptance-policy 2.0`、**truth、门禁阈值、指标回填规则均未改**；
  所有 7 次真实运行（3 新判据 + 2 legacy A/B + 2 历史对照）仍为 `blocked-fail`。
- 检查：新增 30 单测全过；相关 118 passed；全量 `1293 passed / 1 failed`
  （唯一失败是本机缺 WebKit 可执行文件，与改动无关）；改动文件 Ruff 全干净；
  `git diff --check` / `node --check figma_bridge/code.js` / 双样本护栏 `status: pass`。
  工作区中 `test_grounding_scene_plan.py`、`test_native_text_quality.py` 的 `M`
  是项目原有未提交改动，本轮未编辑。
- `R5-P3` 仍是 `production-not-admitted`；本轮只增加**可观测性与身份不变量**，
  不宣称任何样本通过、不宣称泛化问题已解决。

产物：`emission_contract_baseline.json`（6 样本离线）、`emission_contract_fullrun.json`
（3 样本前后）、`emission_ab.json`（严格 A/B）、各运行目录的 `emission_contract.json`。

---

## 12. 感知指纹分层：P0 归因修正与收口（2026-11-08 14:50）

### 12.1 先修正第 11 章的判断

第 11 章把「`image_ir.json` 在 cache=hit 时仍非确定」列为 P0。逐产物核对后，
**这个判断不准确**。在两组严格 A/B 上，用规范化哈希逐个比对 8 个 artifact：

| artifact | FlexWeaver A/B | ACCTOKEN-API A/B | 层次 |
| --- | --- | --- | --- |
| `image_reference.json` | 一致 | 一致 | 感知 |
| `image_enrichment.json` | 一致 | 一致 | 感知 |
| `ocr_supplement.json` | 一致（逐字节） | 一致（逐字节） | 感知 |
| `10_content_inventory.json` | 一致（逐字节） | 一致（逐字节） | 感知 |
| `10_geometry_manifest.json` | 一致 | 一致 | 感知 |
| `11_scene_plan.json` | **不同** | **不同** | 规划派生 |
| `11_som.json` | **不同** | **不同** | 规划派生 |
| `image_ir.json` | **不同** | **不同** | 规划派生 |

`image_ir.json` 由 `image_contract.py::build_image_ir(som_json, design, ...)`
从 **SoM / design** 构建，是字段级候选 IR，不是 VLM 响应快照。strict 运行多出的
4 个节点是 `authority=ocr-candidate` 的页脚观测
（`鄂1CP备2026030291号-1`、`用户协议`、`隐私政策`、`联系邮箱`），
而 `ocr_supplement.json` 两次完全相同。也就是说：**它随规划变化是预期行为，
不是缓存失效或随机抖动**。

真正的缺陷是概念性的：`perception_fingerprint.py` 的 `ARTIFACTS` 把两层混在一个
名为 "perception fingerprint" 的摘要里，导致「同一份感知 + 不同规划」被判成
不同基线，A/B 只能退而求其次用「清单 + OCR 逐字节一致」来举证。

### 12.2 实施：分层摘要（纯增量）

`src/app/services/structure/perception_fingerprint.py`：

- 新增 `PERCEPTION_CORE_ARTIFACTS`（5 个感知产物）与
  `PIPELINE_DERIVED_ARTIFACTS`（3 个派生产物），是 `ARTIFACTS` 的无交集划分。
- 新增 `perception_core_sha256`：只含请求契约、输入 sha/size、坐标决策、5 个感知摘要。
- 新增 `pipeline_derived_sha256`：只含 3 个派生摘要与坐标空间统计。
- 新增 `artifact_layers` 字段；`limitations` 写明三者用途。
- **`ARTIFACTS` 元组与 `material` 完全不动，`PERCEPTION_FINGERPRINT_VERSION` 也不升**
  —— 版本号是 `material` 的一部分，升版本会让所有历史 `fingerprint_sha256` 失效。
  历史摘要因此逐字节保持可比。

`tests/v2/test_perception_core_fingerprint.py` 5 个单测覆盖：分层划分、
规划变化不改核心、感知输入变化改核心、执行状态（hit/miss/latency）不改核心、
持久化与确定性。

### 12.3 真实运行目录验证（只读）

`output/_image_generalization_20261108/perception_layer_baseline.json`：

| 对比 | core | derived | full | 历史 full 与记录值 |
| --- | --- | --- | --- | --- |
| FlexWeaver legacy | `a5fe6518…` | `7b2511d2…` | `4ad08631…` | 一致 |
| FlexWeaver strict | **`a5fe6518…`** | `b23cb918…` | `582c1a40…` | 一致 |
| ACCTOKEN-API legacy | `1b5ddaf0…` | `2c711c47…` | `f424dc34…` | 一致 |
| ACCTOKEN-API strict | **`1b5ddaf0…`** | `63033c05…` | `dd8fcb01…` | 一致 |
| R3 / R4（A+D 复现实验） | `713f3483…` | — | `f1102942…` | 一致 |
| 新 holdout 原始基线 | **`1b5ddaf0…`** | — | `f424dc34…` | 一致 |

三个结论：

1. 两对 A/B 的 **core 完全一致**、derived 与 full 都不同 —— 分层判据按设计工作。
2. 历史 `fingerprint_sha256` 与运行目录里已落盘的记录**逐字节一致**，新字段没有
   篡改任何历史基线（R3/R4 仍是 `f1102942…`）。
3. **新 holdout 原始基线、legacy 对照、strict 运行三者 core 相同**（`1b5ddaf0…`），
   从指纹层面坐实了第 11 章 A/B 的「同感知输入」前提，不再需要靠文件逐字节比对论证。

### 12.4 检查

新增 5 单测 + 既有 10 个坐标/指纹单测共 15 passed；改动文件 Ruff 干净；
`git diff --check`、`node --check` 通过；未启动任何 Figma 写入（本轮纯离线，
bridge server 已按用户要求停止）。

### 12.5 待办更新

| 状态 | 项目 |
| --- | --- |
| **P0 关闭** | 感知/规划指纹分层已落地；「image_ir 非确定性」更正为派生层预期差异 |
| 保留 P1 | `--emission-contract repair` 是否设为默认（改变 critical 数字口径，需拍板） |
| 保留 P1 | 逻辑标签聚合（`5.8折` / `8.8折`）、派生 truth 的 `查看详情` 错字、剩余 `ICP备2026030291号-1` |
| 保留 P2 | native gate 仍 `0/50`；15 段校准阶梯 → 残差驱动闭环（B） |
| 保留 P2 | `_source_form_background` 位图兜底与分轨指标口径（C） |
| 保留 P2 | 缓存覆盖 enrichment 的其他调用；provenance 继续传播到 som/design |

### 12.6 口径

冻结 `acceptance-policy 2.0`、truth、阈值、指标回填规则仍未改；没有新的
Figma 写入或 formal acceptance 运行，因此**不产生新的通过/失败结论**。
所有历史 `blocked-fail` 判定不变，`R5-P3 production-not-admitted` 不变。
本轮只修正「如何判断两次运行看到的是不是同一份感知」这件事。
