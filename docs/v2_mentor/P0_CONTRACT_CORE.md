# P0-CONTRACT-CORE · 纯合同核心

> 状态：`implemented-current-scope`（2026-10-19），不是生产接入或 `verified`。  
> 范围：新增纯确定性 `contracts` 包与 20 个标准库单测；不接 Figma、不改变默认渲染路径。  
> 依据：`R5_CURRENT_SCOPE_AUDIT.md`、`R5_PRODUCTION_BACKLOG.md`。

## 1. 目标

把 R5 已验证的字段、coverage、验收、IR、迁移与 replay 合同落成可复用 Python 库，先解决：

- 状态和字段权威不可混用；
- unknown/deleted/not-applicable 不能都用 null；
- coverage 与 release 逻辑可确定性复算；
- runtime IR 与 ordered audit bundle 分层；
- replay 语义不混用。

本切片不负责真实采集、Figma 写入、报告 Frame、生产存储、TTL worker 或 detector 标定。

## 2. 模块

```text
src/app/services/contracts/
  acceptance.py   four-dimensional gate and release decision
  authority.py    field-level authority / OCR promotion guards
  coverage.py     union area, four coverage units, fixed denominator
  enums.py        versioned status enums
  ir.py           audit projection from runtime IR
  migration.py    v1 -> v2 migration and preservation checks
  models.py       immutable dataclasses and JSON-safe projection
  replay.py       audit / materialize / recapture / resume
  schema.py       runtime-ir and audit-bundle JSON schemas
  validation.py   fail-closed validators
```

## 3. 主要 API

| API | 作用 |
|---|---|
| `FieldDecision` / `FieldRecord` | 观测、状态、权威、候选和 semantic guard |
| `text_decision_from_ocr()` | 只产生 text candidate 或 DOM+screenshot selected |
| `validate_runtime_ir()` | enum、winner、evidence、reference、DAG、retention 校验 |
| `CoverageInput` / `build_page_coverage()` | area/object/text/critical 四维覆盖 |
| `rect_union_area()` | 重叠区域按并集 |
| `fixed_denominator_diff()` | mask 后保持原分母 |
| `AcceptanceCheck` / `evaluate_release()` | critical closure、complete/partial/reference-only |
| `build_audit_bundle()` | 无 runtime graph 的 ordered audit 投影 |
| `migrate_runtime_ir()` | v1 → v2 并检查 tombstone/authority/order/unknown 保留 |
| `ReplayInput` / replay functions | audit/materialize/recapture/resume 分离 |
| `runtime_ir_json_schema()` | portable runtime IR schema |
| `audit_bundle_json_schema()` | ordered audit bundle schema |

## 4. 当前验证

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe -m unittest discover -s tests\v2 -p "test_*.py" -v
```

结果：

- 20/20 unittest 通过；
- JSON schema 对 golden runtime IR / audit bundle 通过；
- unknown enum 失败关闭；
- screenshot 不能拥有 semantic field；
- OCR text 必须保留 `role / editability / asset-source` 禁升逻辑；
- unknown 不能携带 winner；
- coverage 使用并集；
- mask 后 denominator 必须守恒；
- visual pass 不能抵消 edit fail；
- critical fail/unknown/no-ground-truth/未允许 partial 阻断；
- noncritical 可隔离缺口只能产生 `deliverable-partial`；
- reference-only 不等于 complete；
- runtime DAG cycle 失败关闭；
- migration 保留 tombstone、authority、order 与 unknown；
- audit bundle 不携带 runtime graph；
- TTL evidence 只能 summary audit，materialize 阻断；
- recapture 必须新 capture/revision；
- resume 重复副作用阻断。

## 5. 默认路径隔离

当前生产主链仍为：

```text
capture -> direct_design -> RenderingController -> PrototypeAdapter
```

`contracts` 包尚未被 `PreciseAgent`、`RenderingController`、`FigmaBridgeAdapter` 引用。

已验证：

- `PreciseAgent` 可正常导入；
- `FigmaBridgeAdapter` 可正常导入；
- 新包只使用标准库；
- 未修改 `figma_bridge/code.js`；
- 未执行 Figma 写入。

## 6. 下一步

P1-EVIDENCE-ADAPTER 的 shadow 实现已完成当前范围，见 `P1_EVIDENCE_ADAPTER.md`。后续仍需：

- Chromium 14/14、WebKit 7/7 受控与 7/7 真实 page-state/marker 已通过；受控 strict/content 状态门均 7/7，真实 strict 1/7、content 5/7；OCR 剔除可疑合并框后最大残差 8px，但 2px 内只有 41/57（Chromium）和 37/57（WebKit）；继续补严格真实页面对齐、字符框局部残差、iframe 子文档作用域与生产对象存储；
- 端到端资产哈希与本地字节保留；
- 真实样本验收后再决定是否进入 P2。

## 7. 不得宣称

- 不得写 P0 已接入生产或已 `verified`。
- 不得写 JSON schema 已覆盖所有未来 optional 字段。
- 不得把 20/20 单测写成真实页面准确率。
- 不得因 P0 完成就把 P1–P5 标为 ready。
- 不得在 P3 bridge 能力缺失时接真实写入。
