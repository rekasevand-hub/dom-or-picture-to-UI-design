# Benchmark Families（四族回归基准）

image → Figma 流水线的泛化回归基准。每族各有一个**冻结的 Figma Make 黄金稿**作为答案键，一个冻结的源图与 truth。

| 目录 | 族 | 参考图 | 黄金稿 frame | 缩放 |
|---|---|---|---|---|
| `light-form/` | 浅色表单（FlexWeaver, 1920×826, 1x） | c0180587 | `12:1223`（原 `2:523`，2026-11-10 重导出） | 1:1 |
| `light-table/` | 浅色密集表格（工时确认, 2544×1336, 2x） | e0eefc67 | `77:42771`（原 `32:2520`，2026-11-10 换代） | 1:1 |
| `dark-card-grid/` | 深色卡网格（ACCTOKEN 模型广场, 2544×1336, 2x） | 674d733f | `35:2909` | 1:1 |
| `content-review/` | 内容审核页（1920×1008, 1x） | b4df0d75 | `129:8737`（金稿 2544×1336） | **0.7547** |

> `content-review` 于 2026-11-13 由 **holdout #4 转正**：它此前只有 within30 / critical / native 三门，
> 因为没有金稿也就没有 `ink_ratio`。转正后审计 20/20 框落墨、20/20 字符串与 readback 一致、`ink_ratio=1.0(n=20)`。
> 代价写在这里：它已被七轮迭代碰过，从此是**回归基线**，不再是"没被看过的考卷"；新考卷要靠新族（见 `tests/fixtures/holdout5_pending/`）。

> `light-table` 于 2026-11-10 **整族换代**：基准图换成 8 行/1 页签的当前状态（`e0eefc67`），金稿换成原生 2544×1336 的 `77:42771`。旧金稿 `32:2520` 是 1920×1008 的重建稿，**39% 的框落在空白上、47% 的文本被改写**（`项目代码`→`项目编号` 之类），肉眼在 Figma 里看不出来。换代后 100% 框落在文字上、文本一致率 93.9%。
> 换金稿前先跑 `scripts/audit_gold_tree.py`，验收线：框落在文字上 ≥80%、文本一致率 ≥80%。

> `light-form` 的黄金稿于 2026-11-10 从实时帧 `12:1223` 重新导出：原 `2:523` 已从文档删除。
> 同一份 79 条文本与字重分布，答案键指标仅 `font_ratio 1.0 → 1.016`；重导出前后 `within30` / `critical` 不变。
> 细节见 `docs/v2_mentor/20261110_font_weight_evidence.md` §4.5。

## 用法

```bash
# 跑流水线（环境已封装）：
bash scripts/run_image_pipeline.sh --image tests/fixtures/benchmark_families/light-table/reference.png \
  --truth tests/fixtures/benchmark_families/light-table/truth.json --out output/<run_dir> --acceptance-policy 2.0

# 更新 family.json 的 pipeline_run 指向新 run 目录后，跑门禁：
C:/Users/lzq/.conda/envs/omni/python.exe scripts/check_benchmark_families.py
# 首次/重置基线：
C:/Users/lzq/.conda/envs/omni/python.exe scripts/check_benchmark_families.py --register

# 只补/刷新字号基线（墨迹比），其余基线不动：
C:/Users/lzq/.conda/envs/omni/python.exe scripts/check_benchmark_families.py \
  --rerun --register-ink --policy 2.1
```

## pipeline_run 指哪儿

`pipeline_run` 必须指向一次**完整运行**：目录里同时有 `pipeline/`（冻结感知，`--rerun` 从这里复制）和
`figma*/readback.json`（普通模式从这里取渲染结果）。

只有 `pipeline/` 的目录会让普通模式把整族**跳过**：报告里少一行、退出码 1，但屏幕上只是句
`[skip] … no readback/export`，很容易被当成"跑完了"。`light-form` 在 2026-11-13 之前正是这种情况
（指向 `_20261110_split`，一个只剩 `pipeline/` 的目录），现已改指 `output/_image_figma_flexweaver_20261113`。

## 字号指标口径（2026-11-10 变更）

| 指标 | 定义 | 角色 |
|---|---|---|
| `ink_ratio_median` | 渲染墨迹高度 / 源图墨迹高度，**两者同一金稿框** | **主指标**，门禁判定用它（容差 `\|x-1\|` 漂移 ≤ 0.05） |
| `font_ratio_median` | 流水线 fontSize / 金稿 fontSize | **仅诊断**，漂移只写 note，不判回归 |

原因：`font_ratio` 除的是两个**声明**字号。当流水线与金稿用的不是同一套字体时，商里混着字体度量差（实测 1.5–2.4%，dark 更大），追它会把像素改坏——两次收紧 `ink-convergence` 参数都以 light-table 回归告终（`docs/v2_mentor/20261110_font_weight_evidence.md` §5.2）。

`light-table` 声明 `size_metrics.evaluable: false`：它的金稿框大半落在空白上（`ink_fraction 0.364`），91 条文本只有 11 条能同时测到源/渲染墨迹，`corr(size, ink) = -0.52`。该族的两个字号指标都不参与门禁；`within30` 等像素指标照常判定。

## 规则（铁律 2 的执行体）

- 任一族回归（within30 下降 / 墨迹高度比偏离 1.0 更远 / dy 变差 / critical 命中减少 / 位图增多 / 层级变浅）→ 退出码 1，修复合入打回。
- 黄金稿是**测试夹具**：只做裁判，永不进入运行时链路（不蒸馏、不回填参数）。
- 新版式族 = 新目录 + 一张 Figma Make 黄金稿（每族一次，不是每图一次）。

## 产出

- 报告：`output/_benchmark_families/report.json`
- 答案键明细（历史存档）：`output/_bridge_inspect/*_answer_key_diff.json`
