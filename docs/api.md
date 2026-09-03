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
