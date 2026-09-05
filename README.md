# UI 自动还原 Agent

基于屏幕截图/用户上传图片，自动提取视觉特征并调用多模态 LLM，生成结构化设计描述，最终驱动 Figma / 即时设计 / 墨刀 / SVG 还原出 UI 原型。

> 当前目标：先把“位置、尺寸、颜色、文字”四要素画对，元素之间保持独立，暂不建立 Auto Layout、Frame 嵌套或组件变体。

## 目录结构

```
.
├── src/                          # 项目源码
│   ├── main.py                   # CLI 入口
│   ├── app/
│   │   ├── agents/               # 工作流编排
│   │   ├── controllers/          # 提取/渲染控制器
│   │   ├── models/               # Component、DesignSpec 模型
│   │   ├── services/
│   │   │   ├── detection/        # 红框/容器/组件检测 + OmniParser 客户端
│   │   │   ├── ocr/              # EasyOCR / Tesseract OCR 引擎
│   │   │   ├── rendering/        # Figma / SVG / 即时设计 / 墨刀适配器
│   │   │   ├── llm/              # 多模态 LLM 调用
│   │   │   └── omniparser/       # OmniParser HTTP 包装服务
│   │   └── utils/                # 图像、颜色、几何、日志工具
│   └── config/                   # 配置读取
├── figma_bridge/                 # Figma 插件
├── tests/                        # 测试
├── docs/                         # 文档
├── scripts/                      # 可执行脚本
├── .env.example                  # 环境变量模板
├── requirements.txt              # 核心依赖
├── requirements-easyocr.txt      # 可选 OCR 依赖
├── DESIGN.md                     # 架构设计
└── PLAN.md                       # 优化计划
```

## 安装

```bash
# 1. 创建并激活 conda 环境（Python 3.11 推荐）
conda create -n omni python=3.11 -y
conda activate omni

# 2. 安装核心依赖
pip install -r requirements.txt

# 3. 如需使用 EasyOCR（高精度中文 OCR）
pip install -r requirements-easyocr.txt

# 4. 如需使用 Tesseract OCR，需额外安装 Tesseract-OCR 引擎
# Windows 下载地址：https://github.com/UB-Mannheim/tesseract/wiki
```

## 配置

复制 `.env.example` 为 `.env`，填入你的配置：

```bash
cp .env.example .env
```

关键配置项：

| 变量 | 说明 |
|---|---|
| `LLM_BASE_URL` | OpenAI 兼容接口地址 |
| `LLM_API_KEY` | API Key |
| `LLM_MODEL` | 模型名，如 `gpt-4o` |
| `OCR_ENGINE` | `none` / `tesseract` / `easyocr` |
| `TESSERACT_CMD` | Tesseract 可执行文件路径 |
| `PROTOTYPE_TOOL` | `svg` / `figma` / `jsdesign` / `mockingbot` |

## 使用

### SVG 兜底渲染（无需 LLM 以外的外部工具）

```bash
python -m src.main \
  --image uploads/your_screenshot.png \
  --tool svg \
  --ocr-engine easyocr \
  --output-dir ./output
```

运行后 `output/` 会生成：

- `01_original.png`：原始图片
- `02_overlay.png`：检测框可视化
- `03_features.json`：提取的结构化特征
- `04_llm_raw.json`：LLM 原始输出
- `05_design.json`：解析后的 DesignSpec
- `prototype.svg`：最终还原的 SVG

### Figma 自动绘制

1. 启动桥接服务器：

```bash
python -m src.app.services.bridge_server
```

2. 在 Figma 中导入开发插件 `figma_bridge/`：
   - Figma 桌面端 → Plugins → Development → Import plugin from manifest
   - 选择 `figma_bridge/manifest.json`
   - 运行插件

3. 运行 Agent：

```bash
python -m src.main \
  --image uploads/your_screenshot.png \
  --tool figma \
  --ocr-engine easyocr
```

### OmniParser 本地服务（可选）

如需使用 OmniParser 作为检测后端：

```bash
python -m src.app.services.omniparser.omniparser_server \
  --omniparser-root OmniParser/OmniParser-master \
  --som-model-path OmniParser/OmniParser-master/weights/icon_detect/model.pt \
  --caption-model-path OmniParser/OmniParser-master/weights/icon_caption_florence \
  --device cuda
```

然后在 `.env` 中启用：

```env
OMNIPARSER_ENABLED=true
OMNIPARSER_URL=http://127.0.0.1:8000
```

### 红框标注图片区（可选）

如果你希望某些区域被当作图片保留、不参与 OpenCV 组件提取，可以在上传前用**红色矩形框**圈出这些区域：

- 框线建议用纯红（`#FF0000`）、线宽 2px 以上；
- 被红框圈住的区域会生成一个 `type: "image"` 的组件；
- 红框内部不再进行轮廓/颜色/文本检测，避免把图片内容拆碎；
- 通过环境变量控制灵敏度，详见 `.env.example` 中 `RED_BOX_*` 配置。

```bash
python -m src.main \
  --image uploads/screenshot_with_red_boxes.png \
  --tool svg
```

## 架构流程

```
用户上传图片
   │
   ▼
image_utils.load_image() → OpenCV BGR ndarray
   │
   ▼
detection.detect_components() → 组件位置/尺寸/颜色/形状/层级
ocr.extract_text_with_ocr() → 文字识别
   │
   ▼
llm.build_prompt() → base64 图片 + 特征 JSON
llm.call_vision_llm() → 原始文本
llm.parse_design_json() → DesignSpec JSON
   │
   ▼
rendering.build_adapter() → Figma / SVG / 即时设计 / 墨刀
adapter.render_design() → 自动绘制
```

## 精度优化方向

1. **字体**：当前使用默认字体（Figma 用 Inter），后续可接入字体识别或本地字体库比对。
2. **间距**：后处理把坐标/尺寸按 4px/8px 网格取整，减少错位。
3. **交互状态**：LLM 可根据颜色深浅推断 hover/disabled，输出 `states` 字段保留数据。
4. **嵌套合并**：合并同色同类型的嵌套轮廓，减少误检的 `container`。

## 各原型工具接入状态

| 工具 | 状态 | 说明 |
|---|---|---|
| SVG | ✅ 可用 | 无需外部工具，用于快速验证 |
| Figma | ✅ 可用 | 需启动 bridge_server 并导入插件 |
| 即时设计 | 🦴 桩 | 待接入官方 Plugin/REST API |
| 墨刀 | 🦴 桩 | 待接入官方 API/SDK |

## 注意事项

- LLM 调用会产生费用，测试前请确认 API Key 和模型选择。
- Figma 插件必须在 Figma 桌面端或浏览器中保持运行状态。
- 截图功能为可选，当前主流程基于用户上传图片。

## 新流程：PreciseAgent 多路线结构提取

新流程以 `src/main.py` 的 `--url` / `--route` 分支进入 `PreciseAgent`：网页截图或上传图片 → 结构提供器产出 PageGraph → SoM 标注 → VLM 生成 DesignSpec → 渲染到原型工具。旧流程（`ReconstructAgent` + `--direct-render`）不受影响。

### 前置条件

`--url` 走 Playwright 截图，需要先安装 Chromium：

```bash
python -m playwright install chromium
```

### 视觉 / 文本模型网关

新流程视觉与文本模型共用 acctoken OpenAI 兼容网关，默认地址 `https://www.acctoken.com/v1`。在 `.env` 中配置：

```env
VISION_BASE_URL=https://www.acctoken.com/v1
VISION_API_KEY=
VISION_MODEL=qwen3-vl-plus
TEXT_BASE_URL=https://www.acctoken.com/v1
TEXT_API_KEY=
TEXT_MODEL=deepseek-v4-flash
```

- 视觉模型默认 `qwen3-vl-plus`（`VISION_MODEL`），负责 grounding / CV 结构提取与 DesignSpec 生成。
- 文本模型默认 `deepseek-v4-flash`（`TEXT_MODEL`），负责纯文本侧调用。
- 两者使用同一网关、同一 `api_key`（`VISION_API_KEY` 与 `TEXT_API_KEY` 填同一个值即可；key 只写入 `.env`，不入库）。

### CLI 参数

```bash
python -m src.main --url https://example.com --route auto --tool svg
python -m src.main --image uploads/shot.png --route cv --tool svg --enrich
```

| 参数 | 说明 |
|---|---|
| `--url` | 网页 URL（新流程入口，配合 `--route` 使用） |
| `--route` | 结构来源路线：`auto` / `dom` / `a11y` / `grounding` / `cv`。显式路线失败会直接报错，不静默换路 |
| `--enrich` | 视觉补充开关，默认关闭 |

- `--route auto`：`--url` 且拿到 DOM 时回退链为 `dom → grounding → cv`；图片输入为 `grounding → cv`（未配置 VISION_API_KEY 时仅 cv），逐条记录在 `provenance.fallbacks`。
- 产物写入输出目录：`10_pagegraph.json`、`11_som.png`、`11_som.json`、`12_design.json`、`prototype.svg`、`manifest.json`。

### PreciseAgent Python API

```python
from dataclasses import replace
from pathlib import Path

from src.app.agents.precise_agent import PreciseAgent
from src.config import load_config

cfg = replace(load_config(), output_dir=Path("output/precise"))
graph = PreciseAgent(cfg).run(
    url="https://example.com",
    route="auto",      # 或 dom / a11y / grounding / cv
    tool="svg",        # svg | figma | jsdesign | mockingbot
    enrich=False,      # 视觉补充，默认关
)
# graph 为 PageGraph dict；10_pagegraph.json 已写入 output_dir
```

### 三路对比工具

同一 URL / 截图分别跑多条结构路线，并输出两两对比小结：

```bash
python scripts/compare_routes.py \
  --url https://example.com \
  --routes dom,grounding,cv \
  --base-out output/compare

# 图片输入同理：
python scripts/compare_routes.py \
  --image uploads/shot.png \
  --routes grounding,cv \
  --base-out output/compare
```

- 每条路线在 `base-out/<route>/` 下独立产出全套中间产物。
- 两两路线调用 `metrics.summarize`，结果写入 `base-out/summary.json`（容器 IoU 矩阵、文本包含率、容器两两平均最佳 IoU）。

### 交互式选择入口

不想记参数时，用引导式向导选择输入来源与处理路线：

```bash
python -m src.main --interactive
```

依次选择：1) 输入来源（网页 URL / 本地截图）→ 2) 处理路线（auto / dom / a11y / grounding / cv，按输入来源过滤）→ 3) 输出工具（svg / figma / jsdesign / mockingbot）。直接回车使用 `[默认]` 项。

非交互等价参数（与向导同一套配置）：

```bash
# URL 输入
python -m src.main --url https://example.com --route a11y --tool svg

# 本地截图输入（截图只提供 auto/grounding/cv）
python -m src.main --image uploads/shot.png --route cv --tool svg
```

- URL 输入可选全部路线；本地截图仅 `auto/grounding/cv`，且未配置 `VISION_API_KEY` 时不提供 `grounding`。
- `ROUTE` 环境变量（默认 `auto`）为 CLI 未显式指定 `--route` 时的默认路线；`config.route_default` 已由 `main` 消费。
- 无任何参数且不加 `--interactive` 时仍按 argparse 报错退出（不会静默进入向导）。

## 许可证

MIT

## URL权限获取
- python -m src.main --url 'http://flexweaver.rtdsoft.com:6016/index#/production/microflow/mfg_order/data/mfg_order_query@ui?title=%E7%94%9F%E4%BA%A7%E8%AE%A2%E5%8D%95' --login-state D:\LLM-Data\Figma_auto_agent\login_state.json
