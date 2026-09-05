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
| `--route` | `auto` / `dom` / `grounding` / `cv`；显式路线失败直接报错，不静默换路 |
| `--fast` | （实验）DOM 路线退回 computed style 几何直出 DesignSpec，跳过 VLM 语义生成 |
| `--enrich` | 视觉补充开关（默认关） |
| `--storage-state` | Playwright 登录态 JSON：URL 抓取时复用已登录 cookie/localStorage（登录保护页面用） |
| `--login-state` | 交互导出登录态：打开有头浏览器登录 `--url`，回车后保存为 JSON（只导出，不跑管线） |

- `--route auto` 回退链：`--url` 且拿到 DOM 时为 `dom → grounding → cv`；图片输入为 `grounding → cv`（未配置 VISION_API_KEY 时仅 cv），逐条写入 `provenance.fallbacks`。
- 前置条件：URL 输入需要 Playwright Chromium，先执行 `python -m playwright install chromium`。

```bash
python -m src.main --url https://example.com --route auto --tool svg
python -m src.main --image uploads/shot.png --route cv --tool svg --enrich
python -m src.main --url https://example.com --route dom --fast --tool svg   # 实验：computed style 几何直出
```

产物（`output_dir` 下）：`10_pagegraph.json`、`11_som.png`、`11_som.json`、`12_design.json`、`prototype.svg`、`manifest.json`。

### DOM 路线设计生成（默认 Interpreter / 可选 --fast 直出）

DOM 抓取时 `DOM_JS` 直接采集每个节点的 computed style（`bg` / `color` / `fontSize` / `fontWeight` / `borderRadius` / `borderColor` / `borderWidth` / `position` / `zIndex`），随结构写入 SoM JSON 的 `style`，作为 Interpreter 的参考输入。

- **默认（`DOM_DIRECT_DESIGN=false`）**：DOM 路线走 **Interpreter（VLM 语义生成）**，DesignSpec 由模型统一产出，不做规则直出。
- **可选 `--fast`（或 `DOM_DIRECT_DESIGN=true`）**：仅 DOM 路线（`dom`，或 `auto` 落到 dom）退回 **computed style 规则直出**，不调用多模态模型、无语义推断，耗时从“每批数分钟”降到秒级：
  - 容器只要“有非透明背景色”或“带真实边框（color+width 成对）”就画出；既透明又无边框才跳过（数量计入 `_meta.skipped_transparent_containers`）。透明底 + 描边的卡片/控件输出 `fillColor: "transparent"` 只画边框，不再被丢弃或垫成灰块；
  - 无自身背景且无真实边框的 button/input 用白底保守默认；有边框时保留透明背景 + 描边；
  - `image`/`avatar` 元素按 SoM bbox 从整页截图 1:1 裁真实像素，写入元素级 `imageBase64`（数量计入 `_meta.image_backfilled`），不再是一排 `#cccccc` 占位灰块；
  - DOM 路线的叶子文本会先剥离图标字体私有区字形（`E000-F8FF` 与补充私有区 `F0000-FFFFD` / `100000-10FFFD`），纯图标叶子（如 `<i class="iconfont">`）不生成正文元素，掺杂文本只剥离图标保留可读正文——避免还原稿出现乱码/豆腐块；
  - DOM 的容器/元素 bbox 一律裁剪到截图画布内：横向滚动容器里当前不可见的溢出列（截图里不存在的像素）会被丢弃，跨界节点按可视部分 clamp——诊断图越界框从 219 降到 0；
  - DOM 的 `fixed/sticky` 与 `absolute`（负 z-index 除外）且与“文档序在前”的兄弟内容发生像素级重叠（≥1500px² 且宽≥30/高≥15）的定位层会被标记为 `overlay`（如 antd 固定“操作”列——absolute z=1 的整列 wrapper，或单元格级 sticky 列）；其子元素沿文档序继承该标记与 `zIndex`，字段贯穿 PageGraph → SoM JSON → DesignSpec（`_meta.overlays` 计数）；
  - 透明无边框的 overlay 容器（fixed wrapper）直出时按 SoM bbox 从整页截图裁真实像素作底（`imageBase64`，同框克隆去重），避免被盖住的内容从透明层里“透出来”；
  - 渲染绘制序分两段：普通内容先画，`overlay` 元素顺延到最后并按 `zIndex` 升序绘制，让浮层真正盖在被它覆盖的列/内容之上，而不是平铺穿插（对 SVG 与 Figma 适配器同时生效）；
- 若样式覆盖度过低（<50%），`--fast` 直出自动回退到下方“分批生成”VLM 流程；
- `--fast` 直出时 `manifest.json` 的 `design.mode` 为 `dom-direct`，产物里没有 `13_vlm_raw/`；默认走 VLM 时无 `dom-direct` 模式（为 `batch` / `single`）。

### 登录保护页面（storage_state）

目标站需要登录时，先导出登录态，再用 `--storage-state` 复用（无需每次手动登录）：

```bash
# 1) 打开有头浏览器让你登录（完成后回终端按回车），登录态写入 login_state.json
python -m src.main --url http://your-site/index --login-state login_state.json

# 2) 复用该登录态跑还原（cookie/localStorage 会自动带上）
python -m src.main --url http://your-site/index --storage-state login_state.json --route auto --tool svg
```

- `--login-state` 与 `--storage-state` 分两步使用，不要同时传。
- 也可直接用环境变量 `PLAYWRIGHT_STORAGE_STATE=/abs/path/state.json` 代替 `--storage-state`。
- 抓取后若日志出现“疑似仍停在登录页”告警，说明登录态失效，请重跑第 1 步。

### 模型网关

新流程视觉与文本模型共用 acctoken OpenAI 兼容网关，默认 `https://www.acctoken.com/v1`，对应 `.env` 变量：

| 变量 | 默认 | 说明 |
|---|---|---|
| `VISION_BASE_URL` | `https://www.acctoken.com/v1` | 视觉模型网关 |
| `VISION_API_KEY` | 空 | 视觉模型 key（与 `TEXT_API_KEY` 同一把，只写 `.env`） |
| `VISION_MODEL` | `qwen3-vl-plus` | 视觉模型 |
| `VISION_MAX_TOKENS` | `16000` | 视觉模型单次输出上限（大页面不够时调大或分批生成） |
| `VISION_TIMEOUT` | `120` | 视觉模型调用超时（秒） |
| `TEXT_BASE_URL` | `https://www.acctoken.com/v1` | 文本模型网关 |
| `TEXT_API_KEY` | 空 | 文本模型 key（只写 `.env`） |
| `TEXT_MODEL` | `deepseek-v4-flash` | 文本模型 |
| `TEXT_MAX_TOKENS` | `16000` | 文本模型单次输出上限 |
| `TEXT_TIMEOUT` | `120` | 文本模型调用超时（秒） |
| `SOM_BATCH_ENABLED` | `true` | SoM→DesignSpec 是否分批生成（`false` 退回单发整表） |
| `SOM_BATCH_SIZE` | `80` | 每批 id 数（长页面建议 60–100） |
| `SOM_BATCH_MAX_ROUNDS` | `3` | 覆盖度自检最大轮数（含首轮） |
| `SOM_BATCH_MIN_COVERAGE` | `0.9` | 多轮后覆盖率低于该值直接报错，不产出残缺 SVG |
| `SOM_COLOR_BACKFILL` | `false` | 像素级颜色校正（预留开关，尚未实现） |
| `DOM_DIRECT_DESIGN` | `false` | DOM 路线默认走 Interpreter（VLM 语义生成）；为 `true` 时（或 CLI `--fast`）退回 computed style 规则直出 DesignSpec（不调 VLM、无语义推断） |

> 说明：`LLM_BASE_URL` / `LLM_API_KEY` / `LLM_MODEL` / `LLM_TEMPERATURE` / `LLM_MAX_TOKENS` / `LLM_TIMEOUT` 仅旧流程 `ReconstructAgent`（`call_vision_llm`）使用；新流程 `PreciseAgent` 的视觉调用读 `VISION_*`、文本调用读 `TEXT_*`（含各自的 `MAX_TOKENS` / `TIMEOUT`），不再复用 `LLM_*`。

### SoM→DesignSpec 分批生成与覆盖度自检

长页面（数百个 SoM 组件）单发输出会撞上视觉模型 `max_tokens` 上限（qwen3-vl-plus 最大 32768），此前会出现“JSON 解析失败 → json_repair 兜底 → 只剩少量元素”的残缺现象。默认下所有路线（DOM 走 Interpreter）的 DesignSpec 都经**分批生成**产出（仅 `--fast` 直出不调模型）：

- 按 id 分批（默认 `SOM_BATCH_SIZE=80`/批），**整张 SoM 标注图每批重复传入**，不裁图、不按区域分批；
- 每批提示词只允许模型输出本批分配的 id，返回后**按 id 机械合并**（不做模型拼接），并按 SoM 原 bbox 对齐坐标（4px 网格），不信任模型的平移/缩放；
- 每轮结束后做覆盖度自检：缺失的 id 下一轮只**定向补发缺失部分**，最多 `SOM_BATCH_MAX_ROUNDS` 轮；
- 多轮后覆盖率仍低于 `SOM_BATCH_MIN_COVERAGE`（默认 90%）会**报错退出**，并把部分结果写入 `12_design_partial.json`，不再静默产出残缺 SVG；
- 每次 VLM 原始返回保存在 `output_dir/13_vlm_raw/r<轮次>_b<批次>.txt`；合并结果带 `_meta`（calls/rounds/coverage/missing/duplicates/foreign/cross_batch），并汇总进 `manifest.json` 的 `design` 字段；
- 排序条目携带 DOM computed style（DOM 路线时）：模型输出合并后按 SoM style 做确定性回填
  （fillColor/textColor/fontSize/fontWeight/borderRadius/borderWidth/borderColor 凡 SoM 有记录的字段以浏览器计算值为准），避免 VLM 从标注图“猜色”把白字蓝底反写成蓝字白底、绿色状态列被写成黑字；
  回填数记入 `_meta.som_style_overrides`；
- 需要和旧的“单发整表”A/B 对比时，设 `SOM_BATCH_ENABLED=false` 即可退回单发。

### PreciseAgent Python API

```python
from dataclasses import replace
from pathlib import Path

from src.app.agents.precise_agent import PreciseAgent
from src.config import load_config

cfg = replace(load_config(), output_dir=Path("output/precise"))
graph = PreciseAgent(cfg).run(
    url="https://example.com",   # 或 image="uploads/shot.png"
    route="auto",                # auto | dom | grounding | cv
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


### 交互式选择入口

```bash
python -m src.main --interactive
```

引导依次选择：1) URL / 本地截图 → 2) 路线 auto / dom / grounding / cv → 3) 工具 svg / figma / jsdesign / mockingbot；回车取 `[默认]`。等价非交互参数：

```bash
python -m src.main --url https://example.com --route dom --tool svg
python -m src.main --image uploads/shot.png --route cv --tool svg
```

- URL 输入可选全部路线；本地截图仅 `auto/grounding/cv`（未配置 `VISION_API_KEY` 时去掉 `grounding`）。
- 未显式传 `--route` 时默认路线取 `ROUTE` 环境变量（默认 `auto`），`config.route_default` 已由 `main` 消费。
- 无参数且不加 `--interactive` 时仍按 argparse 报错退出（不会静默进入向导）。
