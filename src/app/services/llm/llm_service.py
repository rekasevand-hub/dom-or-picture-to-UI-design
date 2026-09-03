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


def build_som_prompt(som_json: dict, image_b64: str) -> list[dict]:
    """把 SoM 标注图 + SoM JSON 一起交给 VLM，要求输出现有 DesignSpec schema。"""
    system = (
        "你是 UI 还原专家。输入是 Set-of-Mark 标注图与配套 JSON：容器 id 形如 C1，"
        "元素 id 为整数，JSON 已给出每个 id 的 bbox/type/text。任务：输出 DesignSpec JSON。"
        "规则：1) 只输出合法 JSON；2) 元素保持独立、不许合并与丢组件；3) 容器画成背景矩形"
        "(type=container)；4) 坐标尺寸基于 JSON 的 bbox 且按 4px 网格取整，不得随意移动；"
        "5) 颜色/字号/圆角参照标注图推断。schema："
        '{"canvas": {"width": int, "height": int}, "elements": ['
        '{"id": str, "type": "rectangle|text|button|input|image|avatar|divider|container",'
        ' "x": int, "y": int, "width": int, "height": int, "text": str,'
        ' "style": {"fillColor": "#RRGGBB", "textColor": "#RRGGBB", "fontSize": int,'
        ' "fontWeight": str, "borderRadius": int, "borderWidth": int, "borderColor": "#RRGGBB"}}]}'
    )
    import json as _json
    user = [
        {"type": "text",
         "text": "画布尺寸 %dx%d。\nSoM JSON：\n%s\n请输出 DesignSpec JSON。" % (
             som_json["size"][0], som_json["size"][1],
             _json.dumps(som_json, ensure_ascii=False, indent=1))},
        {"type": "image_url",
         "image_url": {"url": "data:image/png;base64," + image_b64}},
    ]
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def call_vlm(messages: list[dict], cfg) -> str:
    """用 VISION_* 配置调用多模态模型。cfg 为 src.config.Config。"""
    if not cfg.vision_api_key:
        raise ValueError("VISION_API_KEY 未配置，无法调用多模态模型")
    import openai
    client = openai.OpenAI(base_url=cfg.vision_base_url, api_key=cfg.vision_api_key,
                           timeout=cfg.llm_timeout)
    resp = client.chat.completions.create(model=cfg.vision_model, messages=messages,
                                          temperature=0.1, max_tokens=cfg.llm_max_tokens)
    return resp.choices[0].message.content or ""


def call_text_llm(messages: list[dict], cfg) -> str:
    """用 TEXT_* 配置调用纯文本模型（可选任务用）。"""
    if not cfg.text_api_key:
        raise ValueError("TEXT_API_KEY 未配置")
    import openai
    client = openai.OpenAI(base_url=cfg.text_base_url, api_key=cfg.text_api_key,
                           timeout=cfg.llm_timeout)
    resp = client.chat.completions.create(model=cfg.text_model, messages=messages,
                                          temperature=0.2, max_tokens=cfg.llm_max_tokens)
    return resp.choices[0].message.content or ""
