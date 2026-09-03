"""视觉理解层：Prompt 构建、LLM 调用、JSON 解析。"""
from __future__ import annotations

import importlib
import json
import logging
import re
from typing import Any

from src.config import Config

logger = logging.getLogger(__name__)


def _system_prompt() -> str:
    """返回给 LLM 的系统提示词，明确输出 Schema 和约束。"""
    return """你是一名 UI 还原专家。你的任务是根据用户上传的界面截图和 OpenCV 提取的候选组件信息，输出一份标准化的设计描述 JSON（DesignSpec）。

要求：
1. 只输出合法 JSON，不要任何解释、markdown 代码块标记或额外文字。
2. 基于截图和候选组件，修正/补全组件类型、文字、颜色、圆角、边框等属性。
3. 坐标系使用原图尺寸，x/y 为左上角，width/height 为宽高。
4. 元素之间保持独立，不要建立 Auto Layout、Frame 嵌套、约束或组件变体。
5. 必须保留 OpenCV 提取的绝大多数候选组件，不要合并、不要丢弃。
6. 对于表格/列表：每一行、每一列、每个单元格内的文字都要单独输出元素。
7. 不要把同一区域内的多个独立文字合并成一段文字。
8. 宁可多画不要漏画。
9. 保持 OpenCV 检测到的组件坐标和相对位置，不要随意移动元素。
10. 所有坐标和尺寸按 4px 网格输出。

输出 Schema：
{
  "canvas": {"width": int, "height": int},
  "elements": [
    {
      "id": "string",
      "type": "rectangle|text|button|input|image|avatar|divider|container",
      "x": int,
      "y": int,
      "width": int,
      "height": int,
      "text": "string or empty",
      "style": {
        "fillColor": "#RRGGBB",
        "textColor": "#RRGGBB",
        "fontSize": int,
        "fontWeight": "normal|bold",
        "borderRadius": int,
        "borderWidth": int,
        "borderColor": "#RRGGBB"
      }
    }
  ]
}
"""


def build_prompt(
    image_b64: str,
    features: dict[str, Any],
    image_w: int,
    image_h: int,
) -> list[dict[str, Any]]:
    """构建 OpenAI 兼容的多模态 Chat Messages。"""
    feature_text = json.dumps(features, ensure_ascii=False, indent=2)

    user_content = [
        {
            "type": "text",
            "text": f"原图尺寸: {image_w}x{image_h}\n\nOpenCV 提取的候选组件如下:\n{feature_text}\n\n请输出 DesignSpec JSON。",
        },
        {
            "type": "image_url",
            "image_url": {"url": f"data:image/png;base64,{image_b64}"},
        },
    ]

    return [
        {"role": "system", "content": _system_prompt()},
        {"role": "user", "content": user_content},
    ]


def call_vision_llm(messages: list[dict[str, Any]], config: Config) -> str:
    """调用多模态 LLM，返回原始文本。"""
    if not config.llm_api_key:
        raise ValueError("LLM_API_KEY 未配置")

    try:
        import openai
    except ImportError as exc:
        raise ImportError("openai 包未安装，请执行 pip install openai") from exc

    client = openai.OpenAI(
        base_url=config.llm_base_url,
        api_key=config.llm_api_key,
        timeout=config.llm_timeout,
    )

    try:
        response = client.chat.completions.create(
            model=config.llm_model,
            messages=messages,
            temperature=config.llm_temperature,
            max_tokens=config.llm_max_tokens,
        )
        content = response.choices[0].message.content
        if not content:
            raise ValueError("LLM 返回内容为空")
        return content
    except Exception as exc:
        logger.error(f"LLM 调用失败: {exc}")
        raise


def _extract_json_block(text: str) -> str:
    """从可能包含 markdown 代码块的文本中提取 JSON 字符串。"""
    match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if match:
        return match.group(1).strip()

    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return text[start : end + 1]

    return text.strip()


def parse_design_json(raw: str) -> dict[str, Any]:
    """解析 LLM 返回的原始文本为 DesignSpec JSON。"""
    text = _extract_json_block(raw)

    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        logger.warning(f"直接 JSON 解析失败: {exc}")

    try:
        json_repair = importlib.import_module("json_repair")
        repaired = json_repair.repair_json(text)
        return json.loads(repaired)
    except ImportError:
        logger.warning("json_repair 未安装，跳过兜底修复")
    except Exception as exc:
        logger.warning(f"json_repair 修复失败: {exc}")

    raise ValueError(f"无法解析 LLM 输出为 JSON: {raw[:200]}")
