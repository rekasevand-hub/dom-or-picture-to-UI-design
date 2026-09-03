# UI 自动还原 Agent

从截图自动提取 UI 组件，并生成可导入 Figma 或 SVG 的设计原型。

## 快速开始

```bash
# 安装依赖
pip install -r requirements.txt

# 运行（SVG 输出，无需 Figma 插件）
python -m src.main --image uploads/test_02.png --tool svg --direct-render

# 运行（输出到 Figma，需先启动桥接服务器和 Figma 插件）
python -m src.main --image uploads/test_02.png --tool figma --direct-render
```

## 项目结构

见项目根目录 `README.md` 和 `PLAN.md`。
