# Benchmark Families（三族回归基准）

image → Figma 流水线的泛化回归基准。三族各有一个**冻结的 Figma Make 黄金稿**作为答案键，一个冻结的源图与 truth。

| 目录 | 族 | 参考图 | 黄金稿 frame | 缩放 |
|---|---|---|---|---|
| `light-form/` | 浅色表单（FlexWeaver, 1920×826, 1x） | c0180587 | `2:523` | 1:1 |
| `light-table/` | 浅色密集表格（工时确认, 2544×1336, 2x） | ece8effc | `32:2520` | ×1.325 |
| `dark-card-grid/` | 深色卡网格（ACCTOKEN 模型广场, 2544×1336, 2x） | 674d733f | `35:2909` | 1:1 |

## 用法

```bash
# 跑流水线（环境已封装）：
bash scripts/run_image_pipeline.sh --image tests/fixtures/benchmark_families/light-table/reference.png \
  --truth tests/fixtures/benchmark_families/light-table/truth.json --out output/<run_dir> --acceptance-policy 2.0

# 更新 family.json 的 pipeline_run 指向新 run 目录后，跑门禁：
C:/Users/lzq/.conda/envs/omni/python.exe scripts/check_benchmark_families.py

# 首次/重置基线：
C:/Users/lzq/.conda/envs/omni/python.exe scripts/check_benchmark_families.py --register
```

## 规则（铁律 2 的执行体）

- 任一族回归（within30 下降 / 字号比偏离 1.0 更远 / critical 命中减少 / 位图增多 / 层级变浅）→ 退出码 1，修复合入打回。
- 黄金稿是**测试夹具**：只做裁判，永不进入运行时链路（不蒸馏、不回填参数）。
- 新版式族 = 新目录 + 一张 Figma Make 黄金稿（每族一次，不是每图一次）。

## 产出

- 报告：`output/_benchmark_families/report.json`
- 答案键明细（历史存档）：`output/_bridge_inspect/*_answer_key_diff.json`
