# API 文档

## CLI 入口

`python -m src.main [选项]`

### 参数

- `--image`: 输入图片路径（必填）
- `--tool`: 原型工具，可选 `svg` | `figma` | `jsdesign` | `mockingbot`
- `--ocr-engine`: OCR 引擎，可选 `none` | `easyocr` | `tesseract`
- `--output-dir`: 中间产物输出目录
- `--direct-render`: 跳过 LLM，直接渲染检测组件
- `--debug`: 打印更多日志

## Python API

```python
from src.app.agents import ReconstructAgent
from src.config import load_config

config = load_config()
agent = ReconstructAgent(config)
agent.run(
    image_path="uploads/test_02.png",
    tool="svg",
    ocr_engine="easyocr",
    direct_render=True,
)
```

## 新流程：PreciseAgent（多路线结构提取）

### CLI 参数

`--url` / `--route` 存在时，`src/main.py` 走 `PreciseAgent` 新流程；否则保持旧流程（`ReconstructAgent`）不变。

| 参数 | 说明 |
|---|---|
| `--url` | 网页 URL（Playwright 截图后走结构提取） |
| `--route` | `auto` / `dom` / `a11y` / `grounding` / `cv`；显式路线失败直接报错，不静默换路 |
| `--enrich` | 视觉补充开关（默认关） |

- `--route auto` 回退链：`--url` 且拿到 DOM 时为 `dom → grounding → cv`；图片输入为 `grounding → cv`（未配置 VISION_API_KEY 时仅 cv），逐条写入 `provenance.fallbacks`。
- 前置条件：URL 输入需要 Playwright Chromium，先执行 `python -m playwright install chromium`。

```bash
python -m src.main --url https://example.com --route auto --tool svg
python -m src.main --image uploads/shot.png --route cv --tool svg --enrich
```

产物（`output_dir` 下）：`10_pagegraph.json`、`11_som.png`、`11_som.json`、`12_design.json`、`prototype.svg`、`manifest.json`。

### 模型网关

新流程视觉与文本模型共用 acctoken OpenAI 兼容网关，默认 `https://www.acctoken.com/v1`，对应 `.env` 变量：

| 变量 | 默认 | 说明 |
|---|---|---|
| `VISION_BASE_URL` | `https://www.acctoken.com/v1` | 视觉模型网关 |
| `VISION_API_KEY` | 空 | 视觉模型 key（与 `TEXT_API_KEY` 同一把，只写 `.env`） |
| `VISION_MODEL` | `qwen3-vl-plus` | 视觉模型 |
| `TEXT_BASE_URL` | `https://www.acctoken.com/v1` | 文本模型网关 |
| `TEXT_API_KEY` | 空 | 文本模型 key（只写 `.env`） |
| `TEXT_MODEL` | `deepseek-v4-flash` | 文本模型 |

### PreciseAgent Python API

```python
from dataclasses import replace
from pathlib import Path

from src.app.agents.precise_agent import PreciseAgent
from src.config import load_config

cfg = replace(load_config(), output_dir=Path("output/precise"))
graph = PreciseAgent(cfg).run(
    url="https://example.com",   # 或 image="uploads/shot.png"
    route="auto",                # auto | dom | a11y | grounding | cv
    tool="svg",                  # svg | figma | jsdesign | mockingbot
    enrich=False,
)
# 返回 PageGraph dict，并写入 output_dir/10_pagegraph.json
```

### 三路对比工具

同一 URL / 截图分别跑多条路线，两两对比：

```bash
python scripts/compare_routes.py --url https://example.com --routes dom,grounding,cv
python scripts/compare_routes.py --image uploads/shot.png --routes grounding,cv --base-out output/compare
```

- `--routes`：逗号分隔路线，默认 `dom,grounding,cv`。
- `--base-out`：输出根目录（默认 `output/compare`），每条路线写入 `base-out/<route>/`，两两 `metrics.summarize` 结果写入 `base-out/summary.json`。
