# 精准复刻 Agent：按用户选择路由的三源结构还原设计

- 日期：2026-09-03
- 状态：设计已评审通过（brainstorming），待写实施计划
- 目标仓库：`D:\LLM-Data\Figma_auto_agent`

## 1. 背景与目标

输入一张网页/App 截图（或直接一个网页 URL），自动产出 **Set-of-Mark 标注图 + 配套结构化 JSON**，供多模态大模型理解页面的**布局容器结构**与**可交互元素**并引用精确坐标，最终**驱动原型工具产出还原的 UI 原型**（精准复刻 agent）。

本设计的核心新增点：把"容器/元素结构从哪里来"做成**三种可插拔来源 + 自动路由**：

1. **真实结构**：网页 DOM（几何 + 样式）或 a11y 树（语义角色 + bounds）
2. **Grounding 多模态模型**：直接看截图输出容器/元素 bbox（`qwen3-vl-plus`，JSON 模式；预留原生 `<|box_start|>` 模式）
3. **现有 CV 管线**：`container_pipeline`（v2.4 掩膜容器 + 格式塔 + OmniParser GPU + easyocr），作为拿不到结构时的兜底

三路输出统一收敛到同一份中间结构 `PageGraph`，其后 SoM 标注、多模态模型生成 DesignSpec、**经 `figma_bridge` 产出最终原型**只写一遍。`figma_bridge`（WebSocket 桥接 + Figma 插件）已实现，直接复用，不新建 Figma 基础设施。

## 2. 输入/输出契约（CLI）

扩展现有 `src/main.py`，新旧两条流程共存：有 `--url` 或 `--route` 走新流程（PreciseAgent），否则保持旧 ReconstructAgent 流程。

### 2.1 参数

| 参数 | 说明 |
|---|---|
| `--url` | 网页地址（新）；与 `--image` 二选一 |
| `--image` | 本地截图（沿用） |
| `--route` | `auto`(默认) / `dom` / `a11y` / `grounding` / `cv` |
| `--tool` | `figma`(最终原型) / `svg`(离线验证) / `jsdesign` / `mockingbot`（沿用现有适配器） |
| `--enrich` | 可选视觉补充开关（默认关） |
| `--output-dir` | 输出目录（沿用） |
| `--debug` | 沿用 |

### 2.2 示例

```powershell
# URL + 自动路由，最终产物画进 Figma（需先起 bridge_server 并在 Figma 里运行 figma_bridge 插件）
python -m src.main --url https://example.com --route auto --tool figma

# URL + 指定 DOM 路线，先 SVG 离线验证
python -m src.main --url https://example.com --route dom --tool svg

# 纯截图 + grounding / cv（没有 DOM 数据源）
python -m src.main --image shot.png --route grounding --tool svg
python -m src.main --image shot.png --route cv --tool figma
```

- `--tool figma` 的前置条件沿用 README：先 `python -m src.app.services.bridge_server` 起桥接服务，再在 Figma 里运行 `figma_bridge/` 插件（manifest 已写好）。连接失败则报错退出，不静默降级。

### 2.3 运行中间产物（一个 output-dir 内，调试/对比检查点）

```
00_screenshot.png          # URL 抓取截图（或 --image 的拷贝）
00_dom.json                # dom/a11y 路线：原始 DOM/AX 数据缓存（调试/对比用）
10_pagegraph_<route>.json  # 规范化结构（PageGraph）
11_som.png                 # Set-of-Mark 双编号标注图
11_som.json                # SoM 配套 JSON（ID↔坐标/类型/文本）
12_design.json             # MLLM 生成的 DesignSpec
prototype.svg              # 仅 --tool svg 时生成（离线验证）
manifest.json              # 本 run 的路由、回退、耗时、阶段产物清单、最终产物去向
```

**最终产物不是某个文件**：`--tool figma` 时，多模态模型产出 DesignSpec 后由 `RenderingController` → `FigmaBridgeAdapter` → `bridge_server` → `figma_bridge` 插件在 Figma 当前文件中直接创建 Frame/矩形/文本/图片，产物以 Figma 画布上的图层为准；`--tool svg` 才把同一份 DesignSpec 落成 `prototype.svg`。中间文件只用于调试、对比与断点续查。

## 3. 统一中间结构 PageGraph

唯一数据契约。容器与元素均保留 `source` 便于回溯与路线对比。

```jsonc
{
  "image": "00_screenshot.png",
  "image_w": 1440, "image_h": 900,
  "route": "dom",
  "containers": [
    {"id": "C1", "bbox": [0, 0, 1440, 80], "role": "banner",
     "depth": 0, "parent": null, "confidence": 1.0, "source": "dom:header"}
  ],
  "elements": [
    {"id": 1, "bbox": [1180, 20, 120, 40], "type": "button", "text": "登录",
     "role": "button", "container": "C2", "confidence": 1.0, "source": "dom"}
  ],
  "provenance": {"route": "dom", "fallbacks": [], "warnings": []}
}
```

- `containers[].id` = `C1..`；`elements[].id` = `1..`；`container` 字段挂元素所属容器 id。
- 坐标一律原图像素整数，左上原点（`x,y,w,h`）。
- `source` 记录产出节点：`dom:<tag>` / `a11y:<role>` / `grounding` / `cv:v2.4` / `cv:gestalt` / `cv:omniparser` / `cv:ocr` / `visual`（enrichment）。
- 该 schema 对齐 HANDOFF_SetOfMark.md 4.4 的 SoM JSON 形态。

## 4. 总体流程与路由

```
URL ──┐
      ├─(1) capture: Playwright 截图 + (按需) DOM/AX 原始数据
image ┘
(2) 路由决策 → (3) provider → PageGraph
(4) [可选] enrichment → (5) SoM 标注器 → 11_som.png + 11_som.json
(6) VLM: build_som_prompt → DesignSpec
(7) RenderingController → --tool figma: figma_bridge 画进 Figma / --tool svg: prototype.svg
```

### 4.1 路由决策（router.py）

规则表（输入形态 × 所选 route）：

| 输入 | `dom`/`a11y` | `grounding`/`cv` | `auto` |
|---|---|---|---|
| URL | 允许（DOM 已抓到） | 允许（用截图） | 先 `dom`；失败→`grounding`；再失败→`cv` |
| 纯图 | **报错**（无 DOM 数据源，给出原因） | 允许 | 先 `grounding`（不可用→`cv`） |

- 显式指定路线：路线与输入不匹配或运行失败 → 直接报错并给出原因，**不静默换路**。
- `auto`：每次回退都记入 `provenance.fallbacks`，最终产物/日志明确实际走的路线。
- capture 失败（网络/无 Chromium）→ 直接终止报错，不做路线级回退。
- 渲染失败：`--tool figma` 连不上桥接 → 报错退出（产物保留 12_design.json 便于手工续接）。

### 4.2 错误处理总则

- 每个 provider 允许返回"部分结果 + warnings"，但图片加载失败/尺寸非法视为硬错误。
- LLM JSON 解析复用现有 `parse_design_json` 的修复链（json_repair 兜底）。

## 5. 三路提供器规格

统一接口（provider 形态）：`class BaseProvider: name; def run(ctx) -> PageGraph`。ctx 含截图路径、可选 DOM/AX 原始数据、配置。

### 5.1 `dom`（DomProvider）

- 同一 Playwright 会话：固定 viewport（默认 1440×900）、`device_scale_factor=1`（CSS 像素=截图像素）、等待 `networkidle`、关动画。
- 页面内 evaluate 遍历所有可见元素：过滤 `display:none/visibility:hidden/零尺寸`；记录 `rect`(取整)、`tag`、`role`、叶子文本、样式子集（`bgColor/color/fontSize/fontWeight/borderRadius`）。
- **容器判定**（几何+语义）：与页面底色不同的可见背景块；大区块（面积/占屏阈值）；`role` ∈ `header/nav/main/aside/footer/section/form`。
- **元素判定**：交互标签 `a/button/input/select/textarea`、叶子文本、`img/svg`；按 tag+role 映射 `button/input/text/link/image`。
- **层级**：bbox 包含关系建树（最小包含者为 parent）。
- 特性：结构细、带样式，是"复刻"主力；是 `grounding/cv` 的参照物。

### 5.2 `a11y`（A11yProvider）

- 同会话经 CDP `Accessibility.getFullAXTree` 取 AX 树（properties 内含 `bounds`）。
- 过滤 `ignored` 节点，只留带 bounds 的；文本取 `name`。
- 容器角色白名单：`banner/navigation/main/region/complementary/contentinfo/group/list/tablist` 等。
- 元素角色：`button/link/textbox/text/heading/image/listitem` 等。
- 层级按 bounds 包含关系建树。特性：语义+坐标一步到位、自动滤装饰；粒度通常比 DOM 粗，与 `dom` 构成对比组。

### 5.3 `grounding`（GroundingProvider，可插拔）

- 后端抽象 `GroundingBackend`：输入截图 → `{containers:[bbox..], elements:[bbox+type+text..]}`。
- v1 默认后端 `GroundingVLM`（OpenAI 兼容协议）：`base_url=https://www.acctoken.com/v1`、`model=qwen3-vl-plus`，以截图 b64 + schema prompt 输出**绝对像素坐标** JSON，强制 `response_format=json_object`（若网关支持）；结果做 clamp、类型白名单校验。
- 原生 grounding 模式（qwen3-vl 的 `<|box_start|>` token）作为后续可插拔后端预留（配置位 `VLM_NATIVE_GROUNDING=false`），v1 不实现解析。
- `VISION_*` 配置缺失 → 该路线"不可用"，`auto` 落到 `cv`，显式选择则报错。

### 5.4 `cv`（CVProvider，复用冻结管线、零改动核心文件）

- 在新项目内**进程内编排**复用 `container_pipeline/` 的四个模块：`container_borders_v2_4`（掩膜容器）、`gestalt_group`（格式塔补全/精修/建层级）、`pipeline_utils`（`_install_paddleocr_stub`、直线段）、OmniParser GPU 元素 + easyocr 文本。
- 复刻 `run_pipeline.py` 的 5 步顺序但把 elements/文本一并收进 PageGraph（原 `run_pipeline.py` 只落盘容器，**不改动**）。
- 路径解析沿用 run_pipeline 的回退逻辑：先找 `container_pipeline/OmniParser/OmniParser-master`，找不到再找父级 `View_fill/OmniParser/OmniParser-master`（子文件夹场景）。
- 说明：该编排约 30-50 行薄胶水，换取冻结文件零改动；easyocr+OmniParser 同进程 GPU 内存压力与现管线一致。

### 5.5 可选 enrichment（默认关，`--enrich` 开启）

- 对任意路线的 PageGraph 再跑 OmniParser/OCR，把缺失的图标/文字以 `source="visual"` 并入。
- v1 默认关闭：先保证三路纯结果可比、比完再决定是否默认开。

## 6. SoM 标注器（som_annotate.py）

- 输入 PageGraph + 截图，输出 `11_som.png` + `11_som.json`。
- 双编号：容器 `C1..`（粗框，颜色按深度渐变），元素 `1..`（细框）；编号按视觉阅读序（上→下、左→右）。
- 元素编号标签放框左上角外侧，深色小底块 + 白字（仿 OmniParser 输出风格），保证可读。
- JSON 结构对齐 HANDOFF 4.4：

```jsonc
{
  "image": "00_screenshot.png",
  "size": [1440, 900],
  "containers": [
    {"id": "C1", "bbox": [0,0,1440,80], "depth": 0, "parent": null,
     "elements": [1, 2]}
  ],
  "elements": [
    {"id": 1, "bbox": [1180,20,120,40], "text": "登录",
     "type": "button", "interactable": true, "container": "C1"}
  ],
  "provenance": {"route": "dom", "fallbacks": [], "warnings": []}
}
```

## 7. DesignSpec 生成与最终产物（figma_bridge / SVG）

- `llm_service` 新增 `build_som_prompt(som_image_b64, som_json, size)`：把 SoM 图 + SoM JSON 一起发给**多模态模型 `qwen3-vl-plus`**；系统提示要求基于 ID/坐标输出现有 DesignSpec schema（`canvas/elements`+style）；规则：4px 网格、不许合并、不许丢组件、容器画成背景矩形、坐标尺寸不随意移动。
- 纯文本任务（对比小结、DesignSpec 校验/修复等）使用 `deepseek-v4-flash`（`TEXT_*` 配置），v1 不强依赖。
- 复用 `call_vision_llm` 与 `parse_design_json`（两者改为消费 `VISION_*` / `TEXT_*` 配置）。
- **最终产物**经现有渲染链路产出，不做新造轮子：
  - `--tool figma`：`RenderingController` → `FigmaBridgeAdapter`（WebSocket）→ `bridge_server.py` → `figma_bridge/code.js`，在 Figma 当前文件中创建 Frame + 元素（`create_frame/create_rectangle/create_text/create_image` 均已实现）。连接失败报错退出，`12_design.json` 保留供续接。
  - `--tool svg`：同一 DesignSpec 落成 `prototype.svg`，供无 Figma 环境的离线验证。
- v1 渲染口径与现有 DESIGN.md 一致：元素独立平铺、父容器以背景矩形表达，不建 Auto Layout / Frame 嵌套（后续可让 VLM 依据 PageGraph 的 parent/depth 增量支持嵌套，不在本次范围）。
- 旧 `--direct-render` 链路与 `ReconstructAgent` 保留，供 CV 老用法兼容。

## 8. 三路对比工具（scripts/compare_routes.py）

- 用法：`python scripts/compare_routes.py --url <u> --routes dom,grounding,cv`
- 每路产物各放独立 output 子目录；最后产出对比小结：
  - 容器/元素数量；
  - 文本覆盖率（DOM 文本叶落在容器内的比例，以 dom 路线为参照）；
  - 容器两两 IoU 表；
  - 三张 SoM 叠图 + 原图拼贴（montage）。
- 每 run 写 `manifest.json`（route、耗时、计数、fallbacks）。
- 对比小结可选用 `deepseek-v4-flash`（`TEXT_*`）生成自然语言结论，文本模型不可用则跳过。

## 9. 文件布局

```
src/app/services/structure/
  graph.py            # PageGraph 数据类 + 建层级 + 读写
  capture.py          # Playwright：截图 + DOM json + a11y（原始数据缓存）
  router.py           # 输入形态 × route 决策
  providers/dom.py / a11y.py / grounding.py / cv.py
  backends/grounding_base.py / grounding_vlm.py
src/app/services/som/annotate.py
src/app/services/llm/llm_service.py    # + build_som_prompt；消费 VISION_*/TEXT_* 配置
src/app/agents/precise_agent.py        # 新编排器（PreciseAgent）
src/main.py                            # + --url / --route / --enrich
src/config/settings.py                 # 新增配置项
requirements.txt                       # + playwright
scripts/compare_routes.py
docs/superpowers/specs/                # 本文档
```

渲染复用现有：`src/app/controllers/rendering_controller.py`、`src/app/services/rendering/figma_adapter.py`、`src/app/services/bridge_server.py`、`figma_bridge/`（不改动或仅必要小改）。

## 10. 新增配置项（.env / settings）

模型分两档，均为 `https://www.acctoken.com/v1` 的 OpenAI 兼容网关；**明文密钥只放 `.env`，spec/代码不放**。

| key | 默认 | 说明 |
|---|---|---|
| `VISION_BASE_URL` | `https://www.acctoken.com/v1` | 多模态模型网关 |
| `VISION_API_KEY` | （.env） | 与 TEXT 共用同一 key |
| `VISION_MODEL` | `qwen3-vl-plus` | grounding 与 SoM→DesignSpec 共用 |
| `VISION_NATIVE_GROUNDING` | `false` | 预留原生 `<\|box_start\|>` 模式 |
| `TEXT_BASE_URL` | `https://www.acctoken.com/v1` | 纯文本模型网关 |
| `TEXT_API_KEY` | （.env） | |
| `TEXT_MODEL` | `deepseek-v4-flash` | 对比小结/校验修复等文本任务 |
| `ROUTE` | `auto` | CLI 未显式指定时的路线 |
| `PLAYWRIGHT_VIEWPORT_WIDTH` / `_HEIGHT` | 1440 / 900 | capture viewport |
| `PLAYWRIGHT_HEADLESS` | true | |
| `DEVICE_SCALE_FACTOR` | 1 | CSS 像素=截图像素 |
| `ENRICH_VISUAL` | false | 对应 `--enrich` |
| `WAIT_NETWORKIDLE_TIMEOUT` | 30000(ms) | |

旧 `LLM_*` / `OMNIPARSER_*` / `OCR_*` / `RED_BOX_*` 配置继续保留给旧 ReconstructAgent 流程，不被新流程删除或复用（新流程只读 `VISION_*` / `TEXT_*` / `PLAYWRIGHT_*`）。

## 11. 依赖与运行约束

- `pip install playwright` + `python -m playwright install chromium`（dom/a11y 路线必需，需网络）。
- `grounding` 与 DesignSpec 阶段需 `acctoken` 网关可达。
- `cv` 路线需现有 omni conda 环境（torch CUDA、OmniParser weights，路径回退见 5.4）。
- `--tool figma` 需起 `bridge_server` 并在 Figma 中运行 `figma_bridge` 插件（README 已有步骤）。
- 三路均以 `device_scale_factor=1` 截图，保证所有坐标在同一像素坐标系。

## 12. 测试策略

- 离线单测（不依赖网络）：`router` 决策表、PageGraph 建树/读写、SoM 画图（用 fixture 截图 + 构造 PageGraph）。
- `cv` 冒烟：用仓库现有截图（`user_test*.png` 一类）。
- `dom/a11y/grounding/DesignSpec` 标 integration（需网络/Chromium/模型端点），`conftest.py` 中 skip 条件判断。
- Figma 渲染以手工验收为准（起 bridge + 插件后跑 `--tool figma`，确认画布上出现 Frame 与元素）。
- 验收 demo：选一个真实网页 URL，`compare_routes.py` 跑 `dom,grounding,cv` 三路，人工看拼贴图 + 指标，确认路由与回退逻辑符合 4.1 规则。

## 13. 原型里程碑

1. PageGraph + router + capture（Playwright）落地
2. dom / a11y 两路 provider
3. grounding provider（qwen3-vl-plus 默认后端）+ cv provider 编排
4. SoM 标注器 + build_som_prompt → DesignSpec 闭环（先 --tool svg 离线验证）
5. --tool figma 经 figma_bridge 产出最终原型（手工验收）+ compare_routes 工具
