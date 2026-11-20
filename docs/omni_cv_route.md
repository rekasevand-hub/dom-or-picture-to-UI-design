# omni-cv 路线：截图 → 纯 CV 物理感知 → Figma / Axure

**封版版本：`v1.0.0-omni-cv`（2026-11-21）**
**对外唯一路由名：`--route omni-cv`**

本文档是这条路线唯一的对外说明书。文中每条命令、每个参数、每个默认值都对照源码
核对过（入口脚本的 `_build_parser()`、`src/config/settings.py` 的 `field(default_factory=...)`
与各模块顶层的 `os.environ.get(...)`），不含凭记忆写下的"大概"。

---

## 1. 路线概述与定位

omni-cv 是一条**不调用 VLM 的确定性还原链**：给一张界面截图，用本地 OCR + 目标检测
拿到文字与图标，用 OpenCV 拿到容器与线条，再用固定画布编译器把三者合成一份坐标
锁死的设计稿，最后投影成 `design-ir/2.0` 契约、发射到 Figma（实时）或 Axure RP8
（离线 `.rp`），并可用只读工具离线巡检。

### 1.1 端到端数据流

```text
截图输入 (.png/.jpg)
   │
   ├─ RapidOCR ──────────── 文字 + 紧框 + 置信度（缺失时自动回退 EasyOCR）
   ├─ OmniParser (:8000) ── 图标框 + 语义标签
   └─ OpenCV ────────────── 容器、分隔线、行带、列簇、底色
   │
   ▼  build_physical_plan()            src/app/services/structure/physical_perception.py
10_pagegraph.json（三路分权感知结果，route = omni-cv）
   │
   ▼  compile_scene_plan_to_design()   src/app/services/structure/fidelity/fixed_canvas_compiler.py
12_design.json / figma_design.json（固定画布：锁帧 → 行带成表 → 字号与基线校准）
   │
   ▼  design-ir/2.0 生产闸门           src/app/services/contracts/production_gate.py
13_design_ir.json（后端中立投影） + 13_degradations.json（能力降级账本）
   │
   ├─ --tool figma → Figma Bridge (:8765) → 画板 → figma/export.png + readback.json
   └─ --tool axure → AxureRPAdapter → prototype.rp → evidence.py 只读回读自检
   │
   ▼  scripts/vlm_qa_inspect.py（独立、只读）
qa_report.json / qa_report.md / qa_overlay.png（四类归因分桶）
```

### 1.2 核心能力

| 能力 | 说明 |
|---|---|
| 文字 | RapidOCR 紧框；检测到但识别退化的框会**逐张重读**（批内宽度归一导致的退化，见 §7） |
| 图标 | OmniParser（YOLO 图标检测 + Florence caption），仅取几何与标签，不把标签当正文 |
| 容器/表格 | OpenCV 连通域 + 行带聚类；行带升格成表后**整表共用一个字号比值** |
| 布局 | 固定画布编译器；帧锁定后只允许改 `fontSize`（铁律，见 §7 NOTES §25.3） |
| 契约 | `design-ir/2.0`：`project_for_output` + `validate_output_ir`，降级显式记账 |
| 发射 | Figma 实时写入 + 回读 + 导出；Axure RP8 离线写 `.rp`（逐字节确定） |
| 巡检 | 只读 QA，四桶归因（感知漏检 / 发射漂移 / 计划内降级 / 样式偏差） |

### 1.3 封版实测基线

七页冷启（`--route omni-cv`、`arbiter=off`、首轮导出口径 `figma/export.png`）：

| 页面 | 帧 | within30 | within15 | mean | ink |
|---|---|---|---|---|---|
| AtomGit | 9 | 91.43 | 87.73 | 10.334 | 88.55 |
| FluxWeaver | 7 | 95.30 | 93.97 | 5.331 | 11.03 |
| inventory | 7 | 94.14 | 93.31 | 8.332 | 21.95 |
| inventory2 | 13 | 94.91 | 92.83 | 7.449 | 16.55 |
| marketplace | 6 | 95.12 | 93.87 | 6.653 | 4.26 |
| review | 5 | 93.31 | 82.88 | 8.689 | 73.75 |
| wecom-modal | 1 | 96.15 | 94.97 | 6.211 | 5.68 |
| **均值** | — | **94.34** | **91.37** | **7.571** | — |

- **端到端单页 ~27s**（FluxWeaver 两次实测 27.3s / 28.2s，其中感知 21.7s）；
- **冻结基准红线**（`replay_pagegraph.py` 在已存 pagegraph 上重编译的帧数）：
  `AtomGit 13 / FluxWeaver 6 / inventory 10 / inventory2 14 / marketplace 9 / review 3 / wecom-modal 6`
  → **13/6/10/14/9/3/6**，任何编译器改动都必须原地不动；
- 冷启帧数（9/7/7/13/6/5/1）与红线是**两套口径**，前者随感知结果变化，不是回归指标；
- **Axure 双页**（`--tool axure --generate-twice`）：FluxWeaver 1 页 / 119 控件 / 13 资源，
  marketplace 1 页 / 68 控件 / 2 资源；`self_check`、`integrity`、`comparison`、两次渲染
  逐字节一致全部通过（sha256 `461aad1a…` / `9182833d…`）；
- **全量单测 1729 passed / 8 skipped / 0 failed**。

### 1.4 路线边界与已知限制

1. **适用面**：25~30s 内完成高保真静态还原，最擅长密集后台表单、数据表格、中后台列表页；
   对强动态内容（视频、3D、实时图表）只能还原静态帧。
2. **不调用 VLM**：不认语义，只认像素几何。文案错字、图标语义错误不会被发现（这是
   `vlm_qa_inspect.py` 存在的原因，它只报告、不改图）。
3. **Axure RP8 降级**：扁平 1 层，无 auto-layout，7 个物理帧在 Axure 侧被排成固定坐标；
   `13_degradations.json` 会显式记 `auto-layout → fixed-coordinate` 与受影响节点 id，
   `can_claim_complete=false`。无裁切/旋转等 RP8 缺失能力同样走这本账。
4. **VLM 在线微调闭环默认关闭**（`opt-in`）：`ARBITER_MAX_ROUNDS` 默认 1；实测 +0.007 分
   换来 40~50s，且 ROI 收益不稳定，故只在评测脚本（`replay_pagegraph.py --arbiter`、
   `scripts/arbiter_ab.py`）里按需开启。生产管线从不调用它。
5. **字号系统性偏小 25% 未修**：根因已定位（`fontSize = ink_height * 0.95` 把墨高当 em，
   数字墨高/em 只有 0.755），但单改尺寸会让七页均值从 95.45 掉到 95.11——量尺（Noto）
   与渲染（Open Sans）不是同一款字。正确改法是"字体族 + 尺寸 + 字距 + 基线上浮"四件一起，
   方案与实测代价归档在
   `NOTES_2026-11-16_dom_to_figma_swarm_reuse.md` **§25「字号三件套」**。
   **铁律：任何动字号的改动必须落在 `_keep_renderable_frames` 之后**（提前到 `style_resolver`
   会让 marketplace 9→8 帧）。
6. **图中的 `route` 字段**：`10_pagegraph.json` / `presentation` 写的是规范名 `omni-cv`；
   感知结果自身的 schema 名仍是 `physical-perception/1.0`（数据格式名，不是路线名）。

---

## 2. 运行环境与前置服务启动

### 2.1 Python 与依赖

| 项 | 值 |
|---|---|
| Python | 3.10+（本机实测 3.11） |
| 主环境 | 任意装了 `requirements.txt` 的 venv/conda |
| omni 环境 | 本机 `C:/Users/lzq/.conda/envs/omni/python.exe`（`OMNI_PYTHON` 可覆盖） |
| 系统 | Windows 10/11 实测；Linux/macOS 未做封版验证 |

```bash
conda create -n omni python=3.11 -y
conda activate omni
pip install -r requirements.txt
pip install rapidocr-onnxruntime        # 推荐：默认 OCR 后端
pip install -r requirements-easyocr.txt # 可选：回退后端（会带 torch）
```

**OCR 后端与回退**（`src/app/services/structure/image_contract.py`）：

- `OCR_BACKEND` 默认 `rapidocr`；`extract_ocr_observations()` 先试配置值，再试另一个；
- `rapidocr` 导入失败 → 自动走 `easyocr`；两个都不可用 → 返回空列表（不抛错，链路继续）；
- 两者差异：RapidOCR 紧框、快（整页 1.3~1.8s）、对 12px 长串偶发识别退化（已用逐张重读
  修掉）；EasyOCR 框更松、慢（整页 20s+），会把相邻字吞进同一框；
- **OpenCV**：`requirements.txt` 声明 `opencv-python>=4.8.0`。4.x 的轮廓/线段返回
  `(N, 1, 4)`、5.x 返回 `(N, 4)`，代码里用 `reshape(-1)[:4]` 两种都吃
  （`line_rulers.py`、`physical_perception.py`）；封版实测环境是 **4.10.0**。

### 2.2 OmniParser（`:8000`）

```bash
python -m src.app.services.omniparser.omniparser_server \
  --omniparser-root OmniParser/OmniParser-master \
  --som-model-path OmniParser/OmniParser-master/weights/icon_detect/model.pt \
  --caption-model-path OmniParser/OmniParser-master/weights/icon_caption_florence \
  --box-threshold 0.05
# 无 CUDA 时追加：--device cpu
```

参数默认值（源码实测）：`--host 127.0.0.1`、`--port 8000`、`--device cuda`、
`--caption-model-name florence2`、`--box-threshold 0.05`。

健康检查（Windows PowerShell）：

```powershell
Test-NetConnection 127.0.0.1 -Port 8000
```

```bash
# Git Bash / Linux
netstat -ano | grep ":8000"
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8000/
```

**服务不在线会怎样**：`omni-cv` 是 strict 路线，物理感知失败直接抛错（不会静默退回旧链路）；
`auto` 才会退回 legacy。客户端地址取 `OMNIPARSER_URL`（默认 `http://127.0.0.1:8000`）；
单次请求超时是 `omniparser_icons()` 的固定默认值 **120s**（不是环境变量）。

### 2.3 Figma Bridge（`:8765`）与插件

```bash
python -m src.app.services.bridge_server
```

- 端口与客户端地址来自 `figma_bridge.config.json`（`client.url = ws://localhost:8765`、
  `port = 8765`）；允许环境覆盖时可用 `FIGMA_BRIDGE_URL` 改地址。
- 这是一个 **WebSocket 服务**，没有 `/health` HTTP 端点；判活看端口监听：

```powershell
Test-NetConnection 127.0.0.1 -Port 8765
```

插件加载 / 重载：

1. Figma 桌面端 → 菜单 **Plugins → Development → Import plugin from manifest…**，
   选 `figma_bridge/manifest.json`（只需一次）；
2. 每次开新画板：**Plugins → Development → 该插件 → Run**；
3. 桥接报 `Attempted to invoke callback with invalid id` 时：**Plugins → Development →
   Reload plugin**（或关掉插件面板重新 Run），再重跑发射；不需要重启 Python 服务。

### 2.4 Axure 路线完全离线

`--tool axure` **不连接 Figma Bridge，也不需要打开 Axure 客户端**：适配器直接写
`.rp` 二进制（`AxureRPAdapter`），校验用 `evidence.py` 只读回读 + `--generate-twice`
两次渲染逐字节比对。只有需要人眼验收时才用 Axure RP8 打开 `.rp`。

---

## 3. 常用启动命令速查

> 所有命令在仓库根目录执行。`bash scripts/run_image_pipeline.sh` 只是环境封装：
> 设好 `OMNI_PYTHON`、`cd` 到仓库根、默认注入 `--route omni-cv`；
> 若你在 `"$@"` 里已经给了 `--route` / `--omni-cv`，它不会再补。

### 3.1 纯 CV → Figma

```bash
# 单页冷启（封版路线）
bash scripts/run_image_pipeline.sh \
  --image output/_fresh_prep/FluxWeaver.png \
  --truth output/_fresh_prep/FluxWeaver.truth.json \
  --out   output/run_FluxWeaver \
  --route omni-cv --tool figma
```

```bash
# 七页批量（一页一目录，日志各自落盘）
for name in AtomGit FluxWeaver inventory inventory2 marketplace review wecom-modal; do
  ext=png; [ -f "output/_fresh_prep/$name.png" ] || ext=jpg
  bash scripts/run_image_pipeline.sh \
    --image "output/_fresh_prep/$name.$ext" \
    --truth "output/_fresh_prep/$name.truth.json" \
    --out   "output/run_$name" \
    --route omni-cv --tool figma > "output/run_$name.log" 2>&1
  grep -E "^\[route\]|^\[score\]" "output/run_$name.log"
done
```

```bash
# 可选：导出后再跑一次墨迹回环校准（默认关闭，实测在 RapidOCR 紧框下是负收益）
bash scripts/run_image_pipeline.sh ... --ink-roundtrip
```

```bash
# 可选：VLM 在线闭环（默认关闭，仅用于评测；生产管线不调用）
ARBITER_MAX_ROUNDS=2 python scripts/replay_pagegraph.py FluxWeaver --arbiter --fresh
ARBITER_MAX_ROUNDS=2 python scripts/arbiter_ab.py FluxWeaver --mode B --rounds 2 \
  --emit --run output/run_FluxWeaver --out output/abB_FluxWeaver
```

### 3.2 纯 CV → Axure `.rp`

```bash
# 单页 + 两次渲染逐字节校验
bash scripts/run_image_pipeline.sh \
  --image output/_fresh_prep/FluxWeaver.png \
  --truth output/_fresh_prep/FluxWeaver.truth.json \
  --out   output/ax_FluxWeaver \
  --route omni-cv --tool axure --generate-twice
```

```bash
# 单页 + 契约违规即阻断（exit 3）
bash scripts/run_image_pipeline.sh ... --tool axure --strict-ir

# 多页（重复 --image / --url，每输入一页；目前仅 axure 支持多页）
python -m src.main \
  --image output/_fresh_prep/FluxWeaver.png \
  --image output/_fresh_prep/marketplace.png \
  --route omni-cv --tool axure \
  --output-dir output/ax_multi --strict-ir
```

```bash
# 已有 DesignSpec 单独补一份 Axure 证据（不重新感知）
python scripts/axure_dom_output.py \
  --design output/run_FluxWeaver/figma_design.json \
  --ir     output/run_FluxWeaver/13_design_ir.json \
  --out    output/ax_evidence_FluxWeaver \
  --source-kind image --generate-twice
```

### 3.3 独立离线只读 QA 巡检

```bash
python scripts/vlm_qa_inspect.py \
  --ref         output/_fresh_prep/FluxWeaver.png \
  --rendered    output/run_FluxWeaver/figma/export.png \
  --design      output/run_FluxWeaver/figma_design.json \
  --ir          output/run_FluxWeaver/13_design_ir.json \
  --degradations output/run_FluxWeaver/13_degradations.json \
  --readback    output/run_FluxWeaver/figma/readback.json \
  --out         output/qa_FluxWeaver
```

```bash
# 无模型冒烟（只写空报告与 overlay，用于验通路）
python scripts/vlm_qa_inspect.py ... --no-vlm

# 一次最多点名 3 处（默认）
python scripts/vlm_qa_inspect.py ... --max-defects 3
```

只读保证：脚本只写 `--out` 下的 `qa_report.json` / `qa_report.md` / `qa_overlay.png`，
设计稿与渲染图一个字节都不改（单测里直接比对字节）。

### 3.4 回归验证

```bash
# 七页冻结红线：必须仍是 13/6/10/14/9/3/6
python scripts/replay_pagegraph.py --out-suffix _gate --fresh

# 全量单测
python -m pytest tests/ -q
```

---

## 4. 全量可选参数与环境变量速查

### 4.1 `src/main.py`（生产总入口）

| 参数 | 类型 / 可选值 | 默认 | 作用 |
|---|---|---|---|
| `--image PATH` | 可重复 | — | 截图输入；N 张 = N 页（多页仅 axure 支持） |
| `--url URL` | 可重复 | — | 网页输入；N 个 = N 页 |
| `--route` | `auto` \| `dom` \| `omni-cv` | `None`（回退 `ROUTE`，再回退 `auto`） | 实现层策略；`omni-cv` 为封版路线 |
| `--omni-cv` | flag | 关 | 等价 `--route omni-cv`；与冲突的 `--route` 同时出现报错（exit 2） |
| `--tool` | `svg` \| `figma` \| `jsdesign` \| `mockingbot` \| `axure` | `None`（回退 `PROTOTYPE_TOOL`，默认 `svg`） | 输出目标 |
| `--ocr-engine` | `none` \| `easyocr` \| `tesseract` | `None`（回退配置） | DOM 路线的 OCR 引擎；omni-cv 用 `OCR_BACKEND` |
| `--output-dir` | 路径 | `None`（回退 `OUTPUT_DIR=./output`） | 中间产物目录 |
| `--strict-ir` | flag | 关 | `design-ir/2.0` 违规时非零退出、阻断发射 |
| `--pick-crops` | flag | 关 | 采集后弹框选，写 `manual_crops.json`（omni-cv 用） |
| `--interactive` | flag | 关 | 交互式选输入与路线（一次只处理一个输入） |
| `--storage-state` | 路径 | `None` | Playwright 登录态 JSON |
| `--user-data-dir` | 路径 | `None` | 持久化浏览器目录 |
| `--headed-fallback` / `--no-headed-fallback` | flag | 开 | 无头被拦时用有头重试 |
| `--login-state` | 路径 | `None` | 只导出登录态，不跑管线 |
| `--direct-render` | flag | 关 | 旧 ReconstructAgent 路径：跳过 LLM 直接渲染 |
| `--fast` / `--enrich` | flag | 关 | **已废弃**，参数被忽略，仅兼容旧脚本 |
| `--debug` | flag | 关 | DEBUG 日志 + traceback |

### 4.2 `scripts/image_figma_mvp.py`（图片管线，`run_image_pipeline.sh` 的实体）

| 参数 | 类型 / 可选值 | 默认 | 作用 |
|---|---|---|---|
| `--image` | 路径 | **必填** | 输入截图 |
| `--truth` | 路径 | **必填** | 冻结真值清单（校验 sha256 / size） |
| `--out` | 路径 | **必填** | 输出目录 |
| `--route` | `auto` \| `omni-cv` | `None` → `auto` | `omni-cv` = 物理感知且不回退 |
| `--omni-cv` | flag | 关 | 等价 `--route omni-cv` |
| `--tool` | `figma` \| `axure` | `figma` | 发射目标（两者都过 IR 闸门） |
| `--strict-ir` | flag | 关 | 契约违规 → exit 3 |
| `--generate-twice` | flag | 关 | 仅 axure：两次渲染要求逐字节一致 |
| `--ink-roundtrip` | flag | 关 | 导出后二次墨迹回环校准（`figma_ink_converged/`） |
| `--prepare-only` | flag | 关 | 只跑感知与编译，停在 `prepared.json` |
| `--reuse-prepared` | flag | 关 | 复用已冻结的 pipeline 目录，不重新感知 |
| `--origin-x` | float | `22000` | 画板在 Figma 画布上的 X 原点 |
| `--origin-y` | float | `0` | 画板 Y 原点 |
| `--readback-depth` | int | `8` | 回读树深度 |
| `--acceptance-policy` | `1.0` \| `2.0` \| `2.1` | `1.0` | 验收口径（冻结原区域 / 拆分原生文本 / 2.1） |
| `--calibration-mode` | `legacy` \| `residual` | `residual` | 校准策略选择（残差画像 vs 历史十五级顺序） |
| `--perception-contract` | `off` \| `report` \| `adaptive` | `adaptive` | 文本框与原图像素的一致性合同 |
| `--perception-drift-threshold` | float | `0.20` | 未证实比例超过它才触发自适应修复 |
| `--strict-perception` | flag | 关 | 仍有未证实文本归属时中止（exit 2） |
| `--emission-contract` | `off` \| `report` \| `repair` | `repair` | 清单→计划→设计→闸门的归属审计 |
| `--strict-emission` | flag | 关 | 发射违规时 exit 3（不改变冻结验收） |

退出码：`0` 验收通过；`2` 验收未通过 / 捕获失败 / 校准渲染失败 / 感知被阻断；
`3` `--strict-ir` 契约违规、`--strict-emission` 违规、或 axure 证据自检失败（strict 时）。

### 4.3 `scripts/axure_dom_output.py`（既有设计稿补 Axure 证据）

| 参数 | 类型 | 默认 | 作用 |
|---|---|---|---|
| `--design` | 路径 | **必填** | `12_design.json` / `figma_design.json` |
| `--ir` | 路径 | `""` | 可选 `13_design_ir.json`（不传则现算） |
| `--out` | 路径 | **必填** | 证据输出目录（同时落 `13_design_ir/13_degradations`） |
| `--source-kind` | 字符串 | `dom` | `dom` / `image`，写进路由与账本 |
| `--generate-twice` | flag | 关 | 两次渲染逐字节校验 |
| `--page-name` | 可重复 | `[]` | 每个帧一个页名 |

### 4.4 `scripts/vlm_qa_inspect.py`（只读巡检）

| 参数 | 类型 | 默认 | 作用 |
|---|---|---|---|
| `--ref` | 路径 | **必填** | 原图（参考） |
| `--rendered` | 路径 | **必填** | 导出图（尺寸必须与 ref 一致） |
| `--design` | 路径 | **必填** | 设计稿，用于把缺陷吸附到节点 |
| `--ir` | 路径 | `""` | `13_design_ir.json` |
| `--degradations` | 路径 | `""` | `13_degradations.json`（判 `planned-degradation`） |
| `--readback` | 路径 | `""` | Figma 回读树 / Axure `inspect_rp` 结果 |
| `--out` | 路径 | **必填** | 报告目录 |
| `--max-defects` | int | `3` | 一次点名的上限（`SWEEP_MAX_DEFECTS`） |
| `--no-vlm` | flag | 关 | 不调模型，只写空报告 + overlay |

### 4.5 回归 / 评测脚本

| 脚本 | 关键参数 | 说明 |
|---|---|---|
| `scripts/replay_pagegraph.py` | `tags...`、`--out-suffix`（默认 `_replay`）、`--fresh`、`--no-patches`、`--no-calibrate`、`--arbiter` | 在已存 pagegraph 上重编译；红线口径 |
| `scripts/arbiter_ab.py` | `tag`、`--mode A\|B`、`--rounds 2`、`--emit`、`--run`、`--design-name`、`--out` | VLM 闭环 A/B，A 组不带 arbiter |

### 4.6 环境变量

| 变量 | 默认 | 作用 |
|---|---|---|
| `OCR_BACKEND` | `rapidocr` | `rapidocr` \| `easyocr`；缺失自动回退另一个 |
| `OMNIPARSER_URL` | `http://127.0.0.1:8000` | 物理感知的图标检测服务地址（超时固定 120s） |
| `ARBITER_MAX_ROUNDS` | `1` | `>1` 才启用 VLM 闭环；生产管线不读它 |
| `VISION_API_KEY` | 空 | VLM 密钥（grounding / arbiter / QA 巡检需要；omni-cv 主链不需要） |
| `VISION_BASE_URL` | `https://www.acctoken.com/v1` | 单端点 |
| `VISION_BASE_URLS` | 空 | 多端点（逗号分隔），优先于 `VISION_BASE_URL` |
| `VISION_MODEL` | `qwen3-vl-plus` | 视觉模型名 |
| `VISION_TIMEOUT` | `120` | VLM 请求超时（秒） |
| `ROUTE` | `auto` | `src/main.py` 未传 `--route` 时的默认路线 |
| `IMAGE_ROUTE` | `omni-cv` | `run_image_pipeline.sh` 注入的路线 |
| `OMNI_PYTHON` | 本机 omni 环境 python | `run_image_pipeline.sh` 用的解释器 |
| `FIGMA_BRIDGE_URL` | `ws://localhost:8765` | 桥接地址（`figma_bridge.config.json` 允许覆盖时生效） |
| `OUTPUT_DIR` | `./output` | 默认输出根 |
| `PROTOTYPE_TOOL` | `svg` | 未传 `--tool` 时的默认输出目标 |

---

## 5. 输出目录与关键产物

```text
output/<run>/
├── 13_design_ir.json            # design-ir/2.0 投影（后端中立）
├── 13_degradations.json         # 能力降级账本（本稿要降级的 + 后端一共缺什么）
├── acceptance.json              # 验收判定（visual / critical_text / structure / asset ...）
├── emission_contract.json       # 清单→计划→设计→闸门的归属审计
├── perception_coverage.json     # 文本归属覆盖与未证实比例
├── native_text_quality.json     # 原生文本质量探针
├── font_calibration.json        # 校准组与跳过组（ink-roundtrip 关时含 skipped_groups）
├── figma_design.json            # 最终发射稿（元素扁平表 + layoutChildren 帧成员）
├── pipeline/
│   ├── 10_pagegraph.json        # 三路分权感知结果（route=omni-cv）
│   ├── 11_som.json / .png       # 元素池与可视化
│   ├── 12_design.json           # 编译产物（锁帧后）
│   ├── manifest.json            # route / requested_route / seconds / counts / design
│   └── image_reference.json     # 输入指纹（sha256 / size / path）
├── figma/                       # 仅 --tool figma
│   ├── export.png               # **唯一度量粒度**
│   ├── readback.json            # Figma 回读树
│   ├── summary.json             # 发射摘要（calls / artifacts / frame_id）
│   └── (figma_ink_converged/)   # 仅 --ink-roundtrip 时出现，不参与度量
├── prototype.rp                 # 仅 --tool axure：RP8 产物
├── prototype.repeat.rp          # 仅 --generate-twice：第二遍，用于逐字节比对
├── artifact_report.json         # 仅 --tool axure：自检 + 完整性 + 比对 + 确定性
├── axure_design.json            # 仅 --tool axure：路由后的设计稿
├── route.json                   # 仅 --tool axure：路由/投影/降级/资源渲染摘要
└── (axure_evidence.json)        # precise_agent 走 axure 时的只读回读摘要
```

`output/qa_<page>/`（`scripts/vlm_qa_inspect.py --out`）：

```text
qa_report.json     # summary（四桶计数、dismissed、unjudgeable）+ 逐条 defects
qa_report.md       # 同一份结论的表格版
qa_overlay.png     # 渲染图 + 按桶着色的编号框 + 左上角带底框的图例
```

### 5.1 关键文件字段要点

- **`12_design.json`**：`elements[]`，每个元素 `id / type / role / x / y / width / height /
  style / text / layoutChildren`。帧的成员只存在于 `layoutChildren`（不是嵌套对象），
  这是"帧锁定"与 Figma 成员关系的唯一来源。
- **`13_design_ir.json`**：`schema_version=design-ir/2.0`，`frames[]`（`frame_id / name / canvas /
  nodes[]`），节点分 `geometry / content / style / layout / constraints / required_features`；
  `source` 记输入指纹，`limitations` 记路线级声明，`assets[]` 记资源绑定。
- **`13_degradations.json`**：`status`（`pass` / `invalid`）、`target`、`counts`
  （`frames / nodes / degraded_features / affected_nodes`）、`degradations[]`
  （`feature / fallback / source_node_ids`）、`target_gaps[]`（后端一共缺哪些能力，与本稿无关也列）、
  `can_claim_complete`、`acceptance_scope`。
- **`artifact_report.json`**：`artifact{name,size,sha256}`、`self_check`、`integrity`、
  `comparison{widget_count,ok}`、`determinism{enabled,repeat_sha256,identical}`、
  `inspection{page_count,asset_count,member_count}`、`projection`、`degradations`。
- **`qa_report.json`**：`summary{buckets{4},dismissed,unjudgeable,styleMismatch}`；
  每条 `defects[]` 带 `bucket / kind / bbox / node / evidence{source_ink,rendered_ink,
  ink_share,ink_state,still_missing} / detail`。

---

## 6. 质量验收与常见排障

### 6.1 每次改动后的最小验收

```bash
python scripts/replay_pagegraph.py --out-suffix _gate --fresh   # 必须 13/6/10/14/9/3/6
python -m pytest tests/ -q                                       # 必须 0 failed
```

### 6.2 Figma 插件报 `Attempted to invoke callback with invalid id`

- **原因**：插件被重载/关闭过，桥接里记录的 `callback id` 已失效（常见于长时间空闲后
  再次发射，或手工 Reload 插件之前发起的请求）。
- **处理**：Figma → **Plugins → Development → Reload plugin**（或关掉面板重新 Run），
  然后重跑发射命令。Python 侧 `bridge_server` **不需要重启**。
- 若整页写入中途失败，产物目录里会留下部分图层的画板；清掉画板或换 `--origin-x`
  重跑即可，不要复用同一原点。

### 6.3 RapidOCR 缺失 → EasyOCR 回退

- 现象：`pipeline/ocr_supplement.json` 里 `source` 变成 `ocr-supplement:easyocr`
  （每条 observation 的 `engine` 也是 `easyocr`），单页耗时从 ~2s 涨到 20s+，
  框更松（相邻两列可能被吞进同一个框），表格列偶发错位。
- 处理：`pip install rapidocr-onnxruntime`，或显式 `OCR_BACKEND=rapidocr`；
  确认装好后跑一次 `--prepare-only`，看 `ocr_supplement.added_count` 是否回到正常量级。
- 不要用降阈值/改缩放去"救"识别：RapidOCR 的漏字是**识别阶段批内宽度归一**导致，
  代码已用"低分框逐张重读"修掉（`OCR_RETRY_BELOW=0.5`、`OCR_RETRY_ACCEPT=0.6`、
  最多 24 个框、斜排跳过）。

### 6.4 `--strict-ir` 退出码 3

```bash
echo $?        # 3 = 契约违规被阻断（四个入口一致）
cat output/<run>/13_degradations.json   # {"status":"invalid","issues":[...]}
cat output/<run>/ir_gate.json           # image_figma_mvp 另外落的阻断快照（可选）
```

- 默认（不加 `--strict-ir`）只记账不阻断：`13_*` 照常落盘（`status=invalid` + `issues[]`），
  发射继续；
- 退出码 3 时**两个账本已先写盘**，直接看 `13_degradations.json.issues[]` 定位是哪个节点
  违反了哪条契约（常见：缺少 `required_features` 声明、节点几何非有限数、帧成员缺失）；
- `scripts/image_figma_mvp.py` 会额外写 `ir_gate.json`（`status=blocked-ir`）作为阻断快照；
  `src/main.py` 与 `precise_agent` 只保证 `13_*` 与退出码 3。

### 6.5 Axure 自检失败

| 症状 | 先看 | 常见原因 |
|---|---|---|
| `self_check.ok=false` | `artifact_report.json.self_check` | `.rp` 内页/控件数与设计不符；多为 `--page-name` 数量与帧数不一致 |
| `integrity.ok=false` | `.integrity` | 部件流哈希不匹配（手工改过 `.rp`，或两次写入交错） |
| `comparison.ok=false` | `.comparison` | 控件文本/坐标与设计稿不一致；先确认传的是**路由后**的 `axure_design.json` |
| `determinism.identical=false` | `.determinism` | 两次渲染字节不同；通常是时间戳/随机 id 泄漏，属回归，需查 writer |
| `blocked-axure-evidence` | 退出码 3 | `--strict-ir` 下自检未过；去掉 strict 先看报告 |

### 6.6 度量口径

- 只用 `figma/export.png`；`figma_ink_converged/` 是回环校准产物，**不得混用**；
- 三通道平均误差：`max` 通道 ≤30 / ≤15 判命中；`mean` 为全页平均绝对差；
- 冻结页分数波动必须 ≤0.03，超过就说明编译器行为被改了。

---

## 7. 封版版本记录（Release Notes）

### 7.1 本封版里程碑

| 项 | 内容 |
|---|---|
| 路由命名 | `--route omni-cv` 成为唯一对外名；`--omni-cv` 快捷参数；`physical` 降为隐藏别名（可用、带弃用提示、不进 `--help`）；`cv`/`grounding` 退出公开帮助 |
| 感知 | RapidOCR 紧框 + 低分框逐张重读（修掉表格整列丢字）；缺依赖自动回退 EasyOCR |
| 编译 | 行带升格成表、整表共用一个字号比值；chip-outline 装饰层插进帧成员，修掉遮挡文字 |
| 契约 | `design-ir/2.0` 生产闸门接入四个入口，落 `13_design_ir.json` + `13_degradations.json`；`--strict-ir` 可阻断；axure 账本首次非空（auto-layout → fixed-coordinate） |
| 发射 | Figma 首轮导出定为唯一口径（`--ink-roundtrip` 默认关）；Axure 生产分支复用 `plan_axure_route` + `evidence.py` + `--generate-twice` |
| 巡检 | `scripts/vlm_qa_inspect.py` 只读离线；四桶归因；`still_missing` 像素证实 + 墨点密度门槛挡掉"缩略图看不清 → 报缺字"的假阳性；overlay 修 RGB 通道与图例底框 |
| 线上闭环 | `vlm_arbiter` 保持 `opt-in`（`ARBITER_MAX_ROUNDS=2` + 评测脚本）；新增 `setText`/`textColor`/`fillColor`/`zIndex` 四工具，各配确定性前置门 |

### 7.2 历史报告与笔记索引

| 文件 | 内容 |
|---|---|
| `HANDOFF_2026-11-20_phase3_physical_route.md` | 阶段三收官：physical 路线转正、七页 94.35/91.38、两套帧数口径 |
| `REPORT_2026-11-20_phase3_closeout_phase4_ab.md` | ink 回环关闭决策、OCR 丢字根因、chip 遮挡修复、三页 A/B |
| `REPORT_2026-11-21_p0_type_and_emission.md` | "发射端截断"证伪、字号 25% 根因与四种改法实测、`still_missing` 落地 |
| `REPORT_2026-11-21_ir_gate_and_qa_inspector.md` | IR 闸门接入、Axure 逐字节验证、QA 巡检四桶与三页实测 |
| `NOTES_2026-11-16_dom_to_figma_swarm_reuse.md` **§25** | 字号三件套（`size = ink_h/墨高比`、`letterSpacing`、基线上浮）与"锁帧后才许动字号"铁律 |
| `docs/omni_cv_route.md` | 本文（对外说明书） |

### 7.3 下一版建议（不在本封版范围）

1. `font_metrics` 按 `fontFamily` 取字体文件 → 再谈字号三件套（否则量尺与渲染不是一款字）；
2. `13_degradations` 支持按页汇总（现在多页只汇总到合并稿）；
3. QA 巡检支持多轮点名（单次最多 3 处，缺陷多的页需要跑多次）；
4. `arbiter` 把 `target-*` 探针并入闭环，让"设计有、导出没有"能在闭环里被修。
