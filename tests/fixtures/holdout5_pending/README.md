# 第 5 族（待登记）

`atomgit-home.jpg` —— 1920×1008，sha256 `8a1f4961d204e402049f3e04550d1f58260dfb974f5ad129000e300e83aeb610`。

用户提供的第 5 族考卷（AtomGit 首页）。**尚未登记为 fixture**：`family.json` 一落盘就会进入
所有 `check_benchmark_families` 运行，所以最后一步才写。

## 进度

| # | 产物 | 状态 |
|---|---|---|
| 1 | `reference.png` | ✅ 由 jpg 无损转 PNG，sha256 `7b2ecb0a…edb5e`，1920×1008 |
| 2 | `truth.json` | ✅ 28 条 critical_texts（对冻结感知命中 26/28，两条已知 OCR 缺陷见文件内说明）；`expected_asset_count=39` |
| 3 | 冻结感知 | ✅ `output/_holdout5_atomgit_prepare/pipeline`（120 元素 / 67 文本 / 39 图标；perception contract 全过） |
| 4 | `gold_tree.json` | ❌ **卡在这里**：需要在 Figma Make 里重建一版 1920×1008 金稿 |
| 5 | `family.json` | ❌ 依赖第 4 步的 `frame_id` |

## 为什么第 4 步是硬阻塞

`scripts/check_benchmark_families.py` 的 `measure_family()` 会**无条件**读 `gold_tree.json`，
没有 `is_file()` 判断，也没有 `try/except`——缺失时整个门禁运行会 traceback 中止，不是跳过这一族。

两条路：

- **A. 建真金稿**：与三个已登记族同标准，五类指标全开（within30 / ink_ratio / dy / critical / structure）。
- **B. 降级登记**：`gold_tree.json` 写 `{}`，`family.json` 声明 `size_metrics.evaluable: false`。
  结果只有 within30 / critical / structure 三门生效，ink 与 dy **永久静默**（基线首次运行即固化为 null）。

登记之前它**不参与任何门禁**，也不要拿它调参——第 4 族就是这么被烧掉的。

## 复现第 3 步

```bash
PY="C:/Users/lzq/.conda/envs/omni/python.exe"
GROUNDING_FIDELITY_MODE=high IMAGE_ENRICHMENT_MODE=apply \
$PY scripts/image_figma_mvp.py \
  --image tests/fixtures/holdout5_pending/reference.png \
  --truth tests/fixtures/holdout5_pending/truth.json \
  --out output/_holdout5_atomgit_prepare --prepare-only --acceptance-policy 2.1
```

不需要 Figma 插件：`--prepare-only` 在写画布之前就返回。
