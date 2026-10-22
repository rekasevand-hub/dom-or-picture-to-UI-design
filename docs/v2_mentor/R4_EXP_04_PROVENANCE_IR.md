# R4-EXP-04 · 只读、版本化的字段级 provenance IR（回放实验）

> 状态：`completed-for-current-scope`（2026-10-18），不是 `verified`。  
> 范围：把 `R4-EXP-01` 的 24 个融合字段、`R4-EXP-02` 的 13 个 OCR 用例、`R4-EXP-03` 的 11 次捕获 / 7 个状态 / 55 个状态对回放为一份只读 IR；共 34 个节点、77 个字段、181 条证据、22 项检查、11 个非法变异拒绝测试。  
> 证据：`output/_r4_experiments/r4_provenance_ir.json`、`output/_r4_experiments/r4_provenance_artifacts/design_ir.json`、`schema.json`、`replay_manifest.json`，以及 `r4_ir_flow.png`、`r4_ir_coverage.png`、`r4_ir_replay.png`。  
> 边界：IR 是设计产物，不是生产融合 API；未修改 `src/`、`figma_bridge/`，未执行 Figma 写入。来源仍是三个受控/合成实验，不覆盖真实站点、跨 DPR、实时状态识别或 OCR 精度。

## 1. 目的与边界

本实验回答五个问题：

1. 前三个 R4 实验的决策能否在不丢失来源、状态和拒绝理由的前提下回放为一份版本化 IR。
2. 每个字段能否同时给出权威、状态、选中值（或显式 `null`）、provenance 与保留观测。
3. 冲突字段能否保持双侧观测且不产生 winner，`unknown` 能否保留 absent observation 而不发明值。
4. OCR 能否只提升 `text-content`，而 `editability / role / asset_source` 永不从截图候选升级。
5. 非法 provenance、伪晋升、瞬态强制比较和悬空引用能否被 schema 校验稳定拒绝。

实验验证的是**IR 表达力、只读回放与拒绝边界**，不是融合算法准确率，也不是生产 schema 的最终形态。

## 2. 环境与可复现性

| 项目 | 值 |
|---|---|
| 操作系统 | Windows 11（`10.0.26300`） |
| Python | 3.12.0（`C:\Users\lzq\.conda\envs\omni\python.exe`） |
| Pillow | 12.2.0 |
| 运行时间 | 约 0.44 秒 |
| IR 版本 | `design-ir/0.1-exp` |
| 文档 ID | `r4-exp-04-read-only-replay` |

重跑命令：

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe output/_r4_experiments/r4_provenance_ir.py
```

脚本只读取三个来源 JSON、11 张捕获 PNG 与 14 张裁片，重建 IR、三张图和回放清单。来源哈希如下：

| 来源 | SHA-256（前 16 位） |
|---|---|
| `r4_fusion_contract.json` | `c5d5cc1ef5b86db9` |
| `r4_ocr_candidates.json` | `d571c4ae431e95dc` |
| `r4_state_gate.json` | `3222646f5f2b82a8` |

## 3. IR 合同

### 3.1 顶层结构

IR 顶层固定为：

```text
ir_version / document_id / schema_hash / generated_at / scope / contract /
sources / states / captures / state_pairs / nodes / evidence / counts / content_hash
```

- `schema_hash` 是规范化 schema JSON 的 SHA-256；schema 同时写入 `schema.json`。
- `content_hash` 是对除自身以外全部 IR 内容的规范化 JSON 哈希。
- `contract.read_only=true`、`source_mutation=false`、`figma_write=false`。
- 顶层和记录级必需键由 schema 声明，22 项检查逐项验证。

### 3.2 节点与字段

节点只有两个通道：

- `fusion:<element>`：来自 `R4-EXP-01`，21 个节点、24 个字段。
- `ocr:<case_id>`：来自 `R4-EXP-02`，13 个节点、53 个字段。

每个字段固定记录：

```text
field_id / name / authority / status / stage / selected / selected_source /
reason / observed_states / provenance / retained_observations / source_case_ref
```

字段权威直接复用 `R4-EXP-01` 的 `field_policy`：

| 权威 | 字段 |
|---|---|
| DOM | `text / font / color / role / editability / asset_source` |
| 截图 | `visible_state / occlusion / z_order / rendered_effect` |
| 交叉核对 | `content_hash / pairing` |
| 几何 | `bbox` |

OCR 节点的 `text` 字段权威为 `screenshot-candidate`；`editability / role / asset_source` 仍是显式边界字段，值分别为 `unverified / not-inferred / not-inferred`。O13 额外记录 `pairing=ambiguous`。

### 3.3 冲突与未知

- `external-conflict`、`state-mismatch`、`ambiguous`、`unknown` 以及 OCR 的 `ambiguous-candidate / occluded-candidate` 均不允许 winner。
- 融合冲突必须保留 DOM 与截图两侧观测；`unknown` 必须保留 `present=false, value=null` 的 absent observation。
- OCR 文本只有在双引擎 exact、最小置信度 ≥ 0.85、跨引擎 bbox IoU ≥ 0.50 时才允许 `selected`；未晋升用例的 `selected=null`。
- `editability / role / asset_source` 的 provenance 规则分别为 `never-promote-editability / never-infer-role / never-infer-asset-source`。

### 3.4 状态与证据

- `states`：7 个状态签名，来自捕获的 `state_key` 哈希。
- `captures`：11 次捕获，记录路径、PNG 哈希、像素尺寸、DPR、稳定性、瞬态标记与 probe 数。
- `state_pairs`：55 个状态对；只有 `comparable` 对携带 `field_result`，被阻断对只保留 gate 理由与诊断像素差。
- `evidence`：181 条去重证据，按 `evidence_id` 索引；字段、状态、捕获和状态对的所有引用都必须可解析。

### 3.5 计数口径

本次回放的计数由脚本遍历计算，不硬编码：

| 计数 | 值 | 说明 |
|---|---:|---|
| 节点 | 34 | 21 fusion + 13 OCR |
| 字段 | 77 | 24 fusion + 53 OCR |
| provenance | 86 | 21 融合选中 + 25 OCR 候选 + 39 OCR 边界 + 1 pairing |
| retained_observations | 32 | 融合用例保留观测；其中 14 条带裁片 |
| provenance + retained | 118 | 字段级来源记录总量 |
| evidence | 181 | 43 fusion + 25 OCR 候选 + 40 OCR gate + 11 捕获 + 7 状态 + 55 状态对 |
| states / captures / state_pairs | 7 / 11 / 55 | 来自 R4-EXP-03 |
| comparable / blocked | 4 / 51 | 32 异态 + 19 瞬态 |
| replayed_records | 103 | 24 字段 + 13 OCR 用例 + 11 捕获 + 55 状态对 |

## 4. 回放结果

### 4.1 22/22 检查

| 组 | 检查 | 结果 |
|---|---|---|
| 结构 | `schema-hash`、`ir-version`、`contract-shape`、`node-ids`、`field-ids`、`evidence-ids`、`state-capture-pair-ids`、`required-keys` | 8/8 |
| 权威与选择 | `fusion-authority`、`conflict-no-winner`、`selection-provenance`、`unknown-no-invention` | 4/4 |
| OCR 边界 | `ocr-unpromoted-no-selected`、`ocr-promotion-scope`、`ocr-boundaries` | 3/3 |
| 状态门 | `transient-pairs-blocked`、`blocked-no-field-result` | 2/2 |
| 完整性 | `evidence-refs`、`source-hashes`、`replay-decisions`、`roundtrip-content-hash`、`counts-match` | 5/5 |

关键明细：

- 34 个节点 ID、77 个字段 ID、181 个证据 ID、7 个状态 ID、11 个捕获 ID、55 个状态对 ID 全部唯一。
- 422 个证据/状态引用全部可解析；28 个来源文件哈希一致（3 个 JSON + 11 张捕获 PNG + 14 张裁片）。
- `replay-decisions` 的 `103` 条记录全部与来源一致：24 个融合字段、13 个 OCR 用例、11 个捕获、55 个状态对。
- `roundtrip-content-hash` 在 JSON 序列化/反序列化后保持对象相等且哈希一致。

### 4.2 11/11 非法变异被拒绝

每个变异在应用后重新计算 `content_hash`，以免仅靠哈希不一致就被拒绝；下表的 `triggered_checks` 是语义检查实际触发的结果。

| 变异 | 预期检查 | 实际触发 |
|---|---|---|
| 删除选中字段 provenance | `selection-provenance` | `selection-provenance`、`counts-match` |
| 伪造 OCR 晋升 | `ocr-unpromoted-no-selected` | `selection-provenance`、`ocr-unpromoted-no-selected`、`replay-decisions` |
| 把 OCR editability 改成原生文本 | `ocr-boundaries` | `selection-provenance`、`ocr-boundaries`、`replay-decisions` |
| 强制瞬态对可比较 | `transient-pairs-blocked` | `transient-pairs-blocked`、`replay-decisions`、`counts-match` |
| 给 bbox 冲突发明 winner | `conflict-no-winner` | `conflict-no-winner`、`selection-provenance`、`replay-decisions` |
| 给 unknown 发明值 | `unknown-no-invention` | `conflict-no-winner`、`selection-provenance`、`unknown-no-invention`、`replay-decisions` |
| 交换字段权威 | `fusion-authority` | `fusion-authority`、`replay-decisions` |
| 指向不存在的 state_ref | `evidence-refs` | `evidence-refs` |
| 删除冲突双侧观测 | `conflict-no-winner` | `conflict-no-winner`、`counts-match` |
| 给被阻断对附加 field_result | `blocked-no-field-result` | `blocked-no-field-result`、`replay-decisions` |
| 使用不支持的 IR 版本 | `ir-version` | `ir-version` |

### 4.3 状态对回放

4 个 `comparable` 对均为同态重复，字段差异全部为 `0`，像素差全部为 `0.0`：

- `S00_top` vs `S00_top_repeat`
- `S01_scroll900` vs `S01_scroll900_repeat`
- `S02_scroll1400` vs `S02_scroll1400_repeat`
- `S05_scroll1950` vs `S05_scroll1950_repeat`

其余 51 对全部阻断：32 对 `state-mismatch`、19 对 `transient-state`。被阻断对不携带 `field_result`，只保留 gate 理由和诊断像素差。与瞬态捕获相关的 19 个唯一状态对全部不可比较。

## 5. 关键案例

### 5.1 融合冲突

- `C04 sidebar bbox`：DOM `[920, 250, 240, 420]` 与截图 `[980, 250, 240, 420]` 的绝对差为 60 px，超过 2 px 容差；IR 记录 `external-conflict`、`selected=null`，两侧观测与截图裁片均保留。
- `C13 carousel-title text`：DOM 状态 S0 与截图状态 S1 不同，文本也不同；在字段比较前返回 `state-mismatch`。
- `C14 article-title text`：两侧文本相同，但状态为 S0 vs S2（滚动位置不同），仍不得进入字段比较。
- `C17 duplicate-card pairing`：两个 DOM 候选对两个截图候选，没有唯一配对证据；返回 `ambiguous`，不强制配对。
- `C18 article content_hash`：两侧规范化文本哈希不同；返回 `external-conflict`，没有权威可以选边。
- `C22 drawer-title text`：两侧都未观测；保留 `present=false, value=null` 的 absent observation，不发明标题。

### 5.2 OCR 晋升与重复歧义

- `O06` 的“低对比度辅助说明”由 EasyOCR 与 Tesseract 双引擎 exact 命中，最小置信度 0.9143、跨引擎 bbox IoU 0.802；只提升 `text-content`，两条选中 provenance 分别指向两个引擎。
- `O11` 的“十像素小字测试”同样双引擎命中，最小置信度 0.9248、IoU 0.8274；`editability` 仍为 `unverified`。
- `O13` 的重复块返回 3 条候选、2 个唯一文本，`pairing=ambiguous`；文本不晋升，配对字段显式记录歧义。
- 其余 11 个 OCR 用例的文本 `selected=null`，候选只以 `selected=false` 的 provenance 保留；`role / asset_source` 全部为 `not-inferred`。

### 5.3 状态门

状态门先于字段比较：异态对和瞬态对即使像素或字段存在差异，也不产生缺陷结论。IR 明确区分 `comparable` 与 `blocked`，而不是把阻断对写成“零差异”。

## 6. 限制

1. 只回放三个受控/合成实验，不构成真实站点、跨 DPR、跨字体或跨语言的融合准确率。
2. IR 未接入 `src/` 或 `figma_bridge/`，不是生产 API、存储层或写入协议。
3. 字段权威映射来自 `R4-EXP-01` 的实验合同，尚未做跨环境标定。
4. 状态命名空间来自 `R4-EXP-03` 的单个合成页面与 7 个签名，不是通用状态识别器。
5. OCR 阈值 `0.85 / 0.50 / 0.30` 是实验合同值，不构成生产接受率。
6. 裁片只证明平面像素来源，不证明原始资产、原生可编辑性或 DOM 身份。
7. 来源与裁片哈希证明文件身份，不证明夹具语义或政策本身正确；IR 的 22 项检查是合同自洽性检查，不是外部真值验证。

## 7. 结论

`R4-EXP-04` 完成当前范围：三个 R4 实验可以被回放为一份只读、版本化的字段级 provenance IR；34 个节点、77 个字段、181 条证据和 103 条决策全部自洽，22/22 检查通过，11/11 非法变异被拒绝。

可以写入设计规格的内容：

1. IR 版本、顶层结构、只读合同与内容哈希。
2. 每字段必须记录权威、状态、选中值、选择来源、理由、provenance 与保留观测。
3. 冲突保持双侧观测且 winner 为 `null`；`unknown` 只保留 absent observation。
4. OCR 只允许提升 `text-content`；`editability / role / asset_source` 永不从截图候选升级。
5. 被阻断的状态对不得携带 `field_result`，瞬态捕获相关对不得比较。
6. 非法 provenance、伪晋升、权威交换和悬空引用必须被 schema 检查拒绝。

不能宣称：生产融合 API、真实站点 IR、通用 OCR/状态/几何阈值、原生可编辑性、资产来源或 Figma 写入能力。状态为 `completed-for-current-scope`，不是 `verified`。
