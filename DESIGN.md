# UI 自动还原 Agent — 架构设计与实现建议

> 本文档按 `AGENTS.md` 的协作规范编写：只给设计、骨架、理由和深层知识点，不填充可直接运行的完整业务代码。

## 1. 总体流程

```
用户上传图片
   │
   ▼
image_loader.load_image() → OpenCV BGR ndarray
   │
   ▼
图像预处理 + OpenCV 特征提取 ──→ 结构化视觉特征（组件位置/尺寸/颜色/文本/层级）
   │
   ▼
base64 PNG + 特征 JSON ──→ 多模态 LLM
   │
   ▼
标准化设计描述 JSON（DesignSpec）
   │
   ▼
原型工具适配器 ──→ Figma Plugin / 即时设计 / 墨刀 / SVG 兜底
```

## 2. 分层职责与数据契约

### 2.1 Image Loader 层（image_loader.py）

**职责**：读取用户上传的图片文件或二进制数据，统一输出为 OpenCV BGR 格式。

**核心函数签名建议**：

```python
def load_image(source: str | Path | bytes | BinaryIO) -> np.ndarray: ...
def encode_image_base64(frame: np.ndarray) -> str: ...
```

**关键决策**：

- **优先使用 `cv2.imdecode`，fallback 到 `PIL.Image.open()`**
  - 理由：`cv2.imdecode` 直接处理字节流，支持 JPG/PNG/BMP/WebP 等常见格式，且输出天然是 BGR；PIL 作为兜底可处理一些 OpenCV 不支持的格式。
  - 深层知识：OpenCV 的解码器基于 `imgcodecs` 模块，对损坏或特殊编码的图片可能失败；PIL 的格式支持更广，但默认输出 RGB，需要 `COLOR_RGB2BGR` 转换。
  - 备选：如果输入源是 URL，可先用 `requests` 下载为 bytes 后再调用 `load_image`。

- **统一输出 OpenCV BGR 格式**
  - 理由：与 OpenCV 后续处理无缝衔接，避免反复颜色空间转换。
  - 注意：发给 LLM 或保存预览时需转成 RGB/PNG。

### 2.2 Extraction 层（src/app/services/detection/ + src/app/services/ocr/）

**职责**：把 600 万像素降维成几十个带语义的组件描述。

**核心数据结构建议**：

```python
@dataclass
class Component:
    id: int
    bbox: tuple[int, int, int, int]   # x, y, w, h
    comp_type: str                    # button | text | input | image | container | ...
    shape: str
    color: tuple[int, int, int]       # BGR
    color_hex: str
    text: str
    level: int                        # 层级深度
    parent_id: int | None
    confidence: float
```

**核心函数签名建议**：

```python
def detect_components(frame: np.ndarray, ...) -> list[Component]: ...
def dominant_color(roi: np.ndarray) -> tuple[int, int, int]: ...
def extract_text_with_ocr(frame: np.ndarray, components: list[Component], engine: str) -> None: ...
def layout_rows(components: list[Component], y_tolerance: float = 0.25) -> list[list[int]]: ...
def draw_debug_overlay(frame: np.ndarray, components: list[Component]) -> np.ndarray: ...
```

**关键决策与知识点**：

1. **检测策略：轮廓检测 + 边缘检测双通道**
   - 理由：单一方法容易漏。自适应阈值擅长抓实心块（按钮、输入框），Canny 擅长抓细边缘（分割线、文字区域）。二者 `bitwise_or` 互补。
   - 深层知识：`cv2.findContours` 的 `RETR_TREE` 返回层级信息，可判断组件嵌套关系；`CHAIN_APPROX_SIMPLE` 压缩轮廓点，节省内存。

2. **滤波用双边滤波而非高斯模糊**
   - 理由：双边滤波在降噪的同时保留边缘，对 UI 截图这种强边缘场景更友好。
   - 备选：若性能吃紧，可换 `cv2.GaussianBlur` 或降采样后处理。

3. **颜色提取用 K-Means 而非简单平均**
   - 理由：UI 元素内部常有文字、图标、渐变，直接取平均会偏灰；K-Means 找主色更能代表背景色。
   - 注意：ROI 缩放到 64x64 再聚类，可显著降低计算量。

4. **形状分类**
   - 建议：`approxPolyDP` 顶点数 + 最小外接矩形宽高比。
   - 圆角矩形很难直接从轮廓判断，可先用 `rectangle` 兜底，后续由 LLM 根据视觉语义推断 `borderRadius`。

5. **OCR 策略**
   - 建议：对 `text/button/input/unknown` 类型区域跑 OCR。
   - `easyocr` 中文效果好但体积大；`pytesseract` 轻量但需要本机安装 Tesseract-OCR 引擎。

6. **布局行信息**
   - 建议：按垂直中心点做简单行聚类，结果只作为 LLM 的参考，不用于在原型工具里建组。

### 2.3 LLM 层（src/app/services/llm/）

**职责**：把图像 + 结构化特征翻译成机器可读的设计描述。

**核心函数签名建议**：

```python
def build_prompt(image_b64: str, features: dict, image_w: int, image_h: int) -> list[dict]: ...
def call_vision_llm(messages: list[dict], config: Config) -> str: ...
def parse_design_json(raw: str) -> dict: ...
```

**关键决策与知识点**：

1. **传图方式：base64 PNG**
   - 理由：OpenAI 兼容接口的标准格式；PNG 无损，保留文字和边缘。
   - 注意：大图建议先按 1024/1600 长边缩放，否则 token 和推理成本会显著增加。

2. **Prompt 结构建议**
   - System：角色 + 输出 Schema + 约束（不解释、不臆测、只输出 JSON）。
   - User：
     - 原始截图（base64 image_url）
     - 已提取的组件列表（坐标、颜色、OCR 文本）
     - 明确的问题：“请根据截图和这些候选组件，输出标准化的 DesignSpec JSON。”

3. **Schema 设计建议**

```json
{
  "canvas": {"width": 1920, "height": 1080},
  "elements": [
    {
      "id": "el-1",
      "type": "rectangle|text|button|image|input|divider|container",
      "x": 100, "y": 200, "width": 120, "height": 40,
      "text": "登录",
      "style": {
        "fillColor": "#1877F2",
        "textColor": "#FFFFFF",
        "fontSize": 14,
        "borderRadius": 4,
        "borderWidth": 0,
        "borderColor": "#000000"
      }
    }
  ]
}
```

4. **JSON 解析容错**
   - 建议：先用 `json.loads`，失败则正则提取 ```json ... ``` 代码块，再做一次解析。
   - 备选：引入 `json_repair` 做最后兜底。

5. **模型选择**
   - 建议：GPT-4o / Claude 3.5 Sonnet / 国内兼容多模态接口。
   - 理由：这些模型在细粒度空间关系和文字识别上更稳定；小模型容易把按钮和输入框混淆。

### 2.4 Prototype 层（src/app/services/rendering/）

**职责**：把 DesignSpec 映射到具体原型工具 API。

**设计模式：适配器模式**

```python
class PrototypeAdapter(ABC):
    def connect(self) -> None: ...
    def create_frame(self, spec: dict) -> str: ...
    def create_rectangle(self, spec: dict) -> str: ...
    def create_text(self, spec: dict) -> str: ...
    def create_image(self, spec: dict) -> str: ...
    def apply_style(self, node_id: str, style: dict) -> None: ...
    def flush(self) -> None: ...
```

**关键决策与知识点**：

1. **Figma 写入必须通过 Plugin API 桥接**
   - 理由：Figma REST API 只读（读文件/评论/导出），不能创建或修改图层。必须写 Figma 插件，在 Figma 沙箱内调用 `figma.createRectangle()` 等。
   - 桥接方案：本地起一个 WebSocket 服务器，Figma 插件的 UI 线程连接它，Python 端发命令，插件端执行后返回结果。
   - 安全：插件主线程与 UI 线程隔离，所有 DOM 操作必须在 `code.js` 中进行；UI 线程只负责网络收发和 `parent.postMessage`。

2. **元素保持独立（遵循 AGENTS.md）**
   - 在 Figma 中只把元素 `appendChild` 到当前 Page，不创建 Auto Layout、Frame 嵌套、组件实例或约束。
   - 理由：当前阶段目标是先把“位置、尺寸、颜色、文字”四要素画对，绑定关系会引入累积误差。

3. **即时设计 / 墨刀**
   - 二者都提供插件 API，调用方式与 Figma 插件 API 高度相似；但接口名称、认证方式、坐标系细节有差异。
   - 建议先抽象出 `PrototypeAdapter`，再各自实现一个 `JSDesignAdapter` 和 `MockingBotAdapter` 的桩，等拿到官方 Token/文档后补全。

4. **SVG 兜底适配器**
   - 理由：在没有 Figma/即时设计/墨刀环境时，可立即验证 LLM 输出是否正确。
   - 可生成 `.svg` 文件，用浏览器打开即可看到还原效果。

### 2.5 Orchestration 层（src/main.py + src/app/agents/）

**职责**：把上述模块串联起来，提供 CLI 入口。

**核心流程建议**：

```python
def run():
    config = load_config()
    frame = capture_screen(...)
    components = detect_components(frame)
    extract_text_with_ocr(frame, components, config.ocr_engine)
    features = build_feature_payload(components, frame)
    b64 = encode_image_base64(frame)
    messages = build_prompt(b64, features, w, h)
    raw = call_vision_llm(messages, config)
    design = parse_design_json(raw)
    adapter = build_adapter(config.prototype_tool)
    adapter.connect()
    render_design(design, adapter)
    adapter.flush()
```

**错误处理建议**：

- 截图失败：降级到 `pyautogui`。
- LLM 返回非 JSON：重试 + JSON 修复。
- 原型工具连接失败：降级到 SVG 适配器。
- 每个阶段保存中间产物（截图、特征 JSON、LLM 原始输出、SVG 预览），方便调试。

## 3. 精度从 60% 提升到 80% 的策略

### 3.1 字体

- **问题**：OpenCV 无法准确识别字体族、字重、行高。
- **策略**：
  1. LLM 根据视觉推断常见字体（如苹方、思源黑体、Inter、Roboto）。
  2. 在原型工具端使用默认字体兜底（Figma 用 Inter），并在 DesignSpec 中标注 `fontFamily`、`fontWeight`、`lineHeight`。
  3. 后续可接入字体识别模型或本地字体库比对。

### 3.2 间距

- **问题**：轮廓检测会给出绝对坐标，但设计稿通常按 4/8px 网格对齐。
- **策略**：
  1. 后处理把坐标/尺寸按 4px 或 8px 取整。
  2. 用行聚类计算平均行高，统一同一行内基线。
  3. LLM Prompt 里明确说明“请按 8pt 网格对齐元素”。

### 3.3 交互状态

- **问题**：截图是静态的，无法直接看到 hover/pressed/disabled。
- **策略**：
  1. LLM 根据颜色深浅推断主按钮、禁用按钮、链接状态。
  2. 在 DesignSpec 中输出 `states` 字段（如 `default`/`hover`/`disabled`），适配器只绘制默认状态，状态数据保留供后续扩展。
  3. 未来可采集多张截图（鼠标悬停前后）做状态对齐。

### 3.4 迭代增强

- 第一轮：粗检测 + LLM 生成 DesignSpec。
- 第二轮：把生成的 SVG/草稿与原图做像素级 diff，让 LLM 指出错位/漏检区域，再修正坐标和漏掉的元素。
- 第三轮：字体/间距/圆角后处理。

## 4. Figma 接入指南（概要）

1. **创建 Personal Access Token**：Figma Settings → Security → Personal access tokens。
2. **开发插件**：
   - `manifest.json`：声明 `name`、`id`、`api`、`main`、`editorType`、`networkAccess`。
   - `code.js`：调用 `figma.showUI()` 打开隐藏 UI，监听 `figma.ui.onmessage`。
   - `ui.html`：连接本地 WebSocket，接收命令并转发给主线程。
3. **启动本地桥接服务器**：Python `websockets` 库监听 `ws://localhost:8765`。
4. **通信流程**：
   - Python 端发送 `{"type": "create_rectangle", "params": {...}}`。
   - WebSocket 服务器转发给 Figma 插件 UI。
   - UI 通过 `parent.postMessage({ pluginMessage: ... })` 发给 `code.js`。
   - `code.js` 调用 `figma.createRectangle()` / `figma.createText()` 等。
   - 结果反向传回 Python。
5. **限制**：插件需在 Figma 桌面端或浏览器中打开并运行；每次只能操作当前打开的文件。

## 5. 即时设计 / 墨刀接入指南（概要）

- **即时设计**：提供插件 API，模型与 Figma 类似，需注册开发者账号并申请插件权限。建议先实现 HTTP/插件适配接口桩，拿到具体文档后补全签名。
- **墨刀**：提供 REST API 用于项目管理，但创建矢量组件通常也需要通过插件或 SDK。建议先阅读官方 OpenAPI 文档，确认是否支持直接创建组件；若不支持，可考虑生成墨刀可导入的 JSON/图片方案。

## 6. 文件清单

```
src/
├── main.py                           # CLI 入口
├── app/
│   ├── agents/
│   │   └── reconstruct_agent.py      # 工作流编排
│   ├── controllers/
│   │   ├── extraction_controller.py  # 特征提取控制
│   │   └── rendering_controller.py   # 渲染控制
│   ├── models/
│   │   ├── component.py              # Component 数据模型
│   │   └── design.py                 # DesignSpec 模型
│   ├── services/
│   │   ├── detection/                # 红框/容器/组件检测
│   │   ├── ocr/                      # OCR 引擎
│   │   ├── rendering/                # 原型工具适配器
│   │   ├── llm/                      # LLM 调用
│   │   ├── omniparser/               # OmniParser HTTP 包装服务
│   │   └── bridge_server.py          # Figma WebSocket 桥接服务端
│   └── utils/                        # 图像/颜色/几何/日志工具
├── config/
│   └── settings.py                   # 配置读取

figma_bridge/
├── manifest.json
├── code.js
└── ui.html

tests/                   # 测试
docs/                    # 文档
scripts/                 # 可执行脚本
.env.example
requirements.txt
requirements-easyocr.txt
setup.py
README.md
PLAN.md
DESIGN.md                # 本文档
```
