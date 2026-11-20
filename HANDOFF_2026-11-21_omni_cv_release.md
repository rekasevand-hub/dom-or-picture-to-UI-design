# 交接：omni-cv 封版交付（2026-11-21）

**一句话**：`omni-cv`（截图 → 纯 CV 物理感知 → Figma / Axure）已封版并快进合入 `main`，
代码、文档、回归基线全部落地，下一轮从 `origin/main` 开分支继续。

---

## 1. 仓库现状

| 项 | 值 |
|---|---|
| 当前分支 | `main`，已跟踪 `origin/main`，**0 ahead / 0 behind** |
| HEAD | `3ad4331 release: omni-cv v1.0.0-omni-cv (route naming, IR gate, offline QA inspector)` |
| 封版 tag | `v1.0.0-omni-cv`（annotated，已推远端，指向 `3ad4331`） |
| `feat/visual-fidelity-pass` | 与 `main` 同点，未被任何 worktree 检出，可删可留 |
| 本 worktree | `C:/Users/lzq/WorkBuddy/Worktrees/Figma_auto_agent/feature-precise-agent-router-496e1371`，**已 `git switch main`**（此前那条"仍绑在 feat 分支"的记录已过时） |
| 工作区 | clean |

开新分支的标准动作：

```bash
git fetch origin && git switch -c feat/<name> origin/main
```

---

## 2. 封版基线（回归时必须原地不动）

七页冷启（`--route omni-cv --tool figma`，`arbiter=off`，口径 `figma/export.png`）：

| 页面 | 帧 | within30 | within15 | mean |
|---|---|---|---|---|
| AtomGit | 9 | 91.43 | 87.73 | 10.334 |
| FluxWeaver | 7 | 95.30 | 93.97 | 5.331 |
| inventory | 7 | 94.14 | 93.31 | 8.332 |
| inventory2 | 13 | 94.91 | 92.83 | 7.449 |
| marketplace | 6 | 95.12 | 93.87 | 6.653 |
| review | 5 | 93.31 | 82.88 | 8.689 |
| wecom-modal | 1 | 96.15 | 94.97 | 6.211 |
| **均值** | — | **94.34** | **91.37** | **7.571** |

- **冻结红线**（`replay_pagegraph.py` 在已存 pagegraph 上重编译，硬约束）：
  `AtomGit 13 / FluxWeaver 6 / inventory 10 / inventory2 14 / marketplace 9 / review 3 / wecom-modal 6`
  = **13/6/10/14/9/3/6**；
- 冷启帧 `9/7/7/13/6/5/1` 是**另一套口径**（随感知变化），不是回归指标；
- 全量单测 **1729 passed / 8 skipped**；单页端到端 **~27~28s**；
- Axure 双页（`--tool axure --generate-twice`）：FluxWeaver `461aad1a…`（119 控件 / 13 资源）、
  marketplace `9182833d…`（68 / 2），`self_check` / `integrity` / `comparison` / 逐字节一致全绿。

两条验收命令：

```bash
python scripts/replay_pagegraph.py --out-suffix _gate --fresh   # 必须 13/6/10/14/9/3/6
python -m pytest tests/ -q                                       # 必须 0 failed
```

---

## 3. 必读文档

| 文件 | 用途 |
|---|---|
| `docs/omni_cv_route.md` | **对外唯一说明书**：数据流、环境、启动命令、全部参数默认值、产物字段、排障 |
| `NOTES_2026-11-16_dom_to_figma_swarm_reuse.md` **§25** | 字号三件套公式与"锁帧后才许动字号"铁律 |
| `REPORT_2026-11-21_ir_gate_and_qa_inspector.md` | IR 闸门 / Axure 逐字节 / QA 四桶巡检 |
| `REPORT_2026-11-21_p0_type_and_emission.md` | "发射端截断"证伪、字号 25% 根因与四种改法实测 |
| `REPORT_2026-11-20_phase3_closeout_phase4_ab.md` | ink 回环关闭决策、OCR 丢字根因、chip 遮挡修复 |

---

## 4. 下一轮候选（按 ROI）

1. **`font_metrics` 按 `fontFamily` 取字体文件** —— 现在一律用 Noto 量、Figma 排 Open Sans，
   一档差 15%；这条不做，后面所有字号/字距估算都会系统偏。
2. **字号三件套**（`size = ink_h / 墨高比`、`letterSpacing = (ink_w − advance)/(n−1)`、
   `y -= (ascent − cap)·size`）—— 三件一起改，只改一件会把一类误差换成三类。
3. **`13_degradations` 按页汇总**：多页 axure 目前只汇总到合并稿。
4. **QA 巡检多轮点名**：单次上限 3 处（`SWEEP_MAX_DEFECTS`），缺陷多的页要跑多次。
5. **`arbiter` 的 `target-*` 探针并入闭环**：让"设计有、导出没有"能在闭环里被发现并修。
6. `vlm_arbiter` 继续 `opt-in`：+0.007 分 / 40~50s，暂不值得开默认。

---

## 5. 工程约定

- **分支**：一切新工作从 `origin/main` 开 `feat/xxx`，不要在旧本地分支上继续；
- **解释器**：`C:/Users/lzq/.conda/envs/omni/python.exe`；shell 封装认 `OMNI_PYTHON`；
- **前置服务**：OmniParser `:8000`（`python -m src.app.services.omniparser.omniparser_server`）、
  Figma Bridge `:8765`（`python -m src.app.services.bridge_server`）；
  **Axure 路线完全离手，不需要这两个**；
- **不入库**：`output/`、`.workbuddy/`；金标在 `samples/image_screenshots/`；
- **度量**：只用 `figma/export.png`，不要混 `figma_ink_converged/`；
- **路由名**：对外 `--route omni-cv`（或 `--omni-cv`）；`physical` 是会打弃用提示的隐藏别名。

---

## 6. 已知坑（都是踩过的）

1. **动字号必须落在 `_keep_renderable_frames` 之后**：提前到 `style_resolver` 会让
   marketplace 9→8 帧（字变大 → 行内 y 重排 → 帧成员落进隔壁容器）。
2. **通道顺序**：`_image()` 读的是 RGB。给 `cv2.imwrite` 写 RGB 缓冲会整页 R/B 对调
   （`qa_overlay` 修过一次）；画图落盘统一用 `save_overlay`（PIL）。
3. **RapidOCR 漏字**不是阈值问题：检测框在、识别退化，靠"低分框逐张重读"修；
   调 `box_thresh` / 缩放只会让结果在 3~6 行之间跳。
4. **`--strict-ir` 退出码 3**（四个入口一致，axure strict 自检失败也是 3），
   违规细节看 `13_degradations.json.issues[]`，`image_figma_mvp` 另落 `ir_gate.json`。
5. **Figma 插件 `Attempted to invoke callback with invalid id`** = 插件被重载过，
   Reload plugin 后重跑发射，Python 服务不用重启。
6. **`13_degradations` 的 `auto-layout` 条目不是 bug**：物理帧在 RP8 里就是固定坐标，
   `can_claim_complete=false` 是如实记账。
