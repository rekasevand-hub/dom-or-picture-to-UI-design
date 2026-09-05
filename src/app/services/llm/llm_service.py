"""视觉理解层：Prompt 构建、LLM 调用、JSON 解析。"""
from __future__ import annotations

import importlib
import json
import logging
import re
from typing import Any
from pathlib import Path

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
                           timeout=cfg.vision_timeout)
    resp = client.chat.completions.create(model=cfg.vision_model, messages=messages,
                                          temperature=0.1, max_tokens=cfg.vision_max_tokens)
    return resp.choices[0].message.content or ""


def call_text_llm(messages: list[dict], cfg) -> str:
    """用 TEXT_* 配置调用纯文本模型（可选任务用）。"""
    if not cfg.text_api_key:
        raise ValueError("TEXT_API_KEY 未配置")
    import openai
    client = openai.OpenAI(base_url=cfg.text_base_url, api_key=cfg.text_api_key,
                           timeout=cfg.text_timeout)
    resp = client.chat.completions.create(model=cfg.text_model, messages=messages,
                                          temperature=0.2, max_tokens=cfg.text_max_tokens)
    return resp.choices[0].message.content or ""


# ---------------------------------------------------------------------------
# SoM -> DesignSpec 分批生成：按 id 分批 + 覆盖度自检（防长页面单发截断）
# ---------------------------------------------------------------------------

_DESIGN_SCHEMA_JSON = (
    "{\"canvas\": {\"width\": int, \"height\": int}, \"elements\": ["
    "{\"id\": str, \"type\": \"rectangle|text|button|input|image|avatar|divider|container\","
    " \"x\": int, \"y\": int, \"width\": int, \"height\": int, \"text\": str,"
    " \"style\": {\"fillColor\": \"#RRGGBB\", \"textColor\": \"#RRGGBB\", \"fontSize\": int,"
    " \"fontWeight\": str, \"borderRadius\": int, \"borderWidth\": int,"
    " \"borderColor\": \"#RRGGBB\"}}]}"
)

_SOM_BATCH_SYSTEM = (
    "你是 UI 还原专家。输入为整张 Set-of-Mark（SoM）标注图与本批待还原条目列表："
    "图中的每个容器/元素都有编号描边框与角标，列表给出同一 id 的 bbox/类型/文字。"
    "任务：为本批列表中的每个 id 输出且只输出一条 DesignSpec element；容器（id 形如 C1）"
    "输出 type=container，其余元素参照画面内容修正 type 与 style/text。\n"
    "规则：\n"
    "1) 只输出合法 JSON，不要解释、不要 markdown 代码块、不要额外文字；\n"
    "2) 每条 element 的 id 必须原样等于列表 id（字符串）；只允许本批列表内的 id；"
    "禁止合并、拆分、重复、丢弃；\n"
    "3) 坐标与尺寸以列表 bbox 为准（最终按 SoM bbox 落盘，禁止平移缩放）；\n"
    "4) text 优先使用列表中的 text，列表为空时才从截图识别；\n"
    "5) style 的 fillColor/textColor/fontSize/fontWeight/borderRadius/borderWidth/"
    "borderColor 参照标注图推断，尽量贴近真实观感。\n"
    "输出 schema：\n" + _DESIGN_SCHEMA_JSON
)


def _snap4(value: int) -> int:
    """数值就近取整到 4px 网格。"""
    return int(round(float(value) / 4.0) * 4)


def _som_entries(som_json: dict) -> list[dict]:
    """把 SoM 的容器/元素归一成有序待还原条目（容器在前、元素在后，id 统一字符串）。"""
    entries: list[dict] = []
    for c in som_json.get("containers", []):
        entry = {"id": str(c["id"]), "group": "container", "bbox": [int(v) for v in c["bbox"]]}
        if c.get("depth") is not None:
            entry["depth"] = int(c["depth"])
        if c.get("parent"):
            entry["parent"] = str(c["parent"])
        entries.append(entry)
    for e in som_json.get("elements", []):
        entry = {"id": str(e["id"]), "group": "element",
                 "bbox": [int(v) for v in e["bbox"]], "type": e.get("type", "rectangle")}
        if e.get("text"):
            entry["text"] = str(e["text"])
        if e.get("container"):
            entry["container"] = str(e["container"])
        if e.get("ariaLabel"):
            entry["ariaLabel"] = str(e["ariaLabel"])
        if e.get("title"):
            entry["title"] = str(e["title"])
        entries.append(entry)
    return entries


def _chunk_ids(ids: list[str], size: int) -> list[list[str]]:
    """把 id 列表切成 size 一组的子批。"""
    return [ids[i:i + size] for i in range(0, max(1, len(ids)), size)]


def build_som_batch_prompt(som_json: dict, image_b64: str, ids: list[str]) -> list[dict]:
    """构建某批 SoM id 的还原提示词：整张标注图 + 仅本批条目。"""
    entry_by_id = {e["id"]: e for e in _som_entries(som_json)}
    entries = [entry_by_id[i] for i in ids if i in entry_by_id]
    w, h = som_json.get("size", [0, 0])[:2]
    item_lines = "\n".join(json.dumps(e, ensure_ascii=False) for e in entries)
    user_content = [
        {"type": "text",
         "text": (
             "画布尺寸 %dx%d。\n"
             "本批待还原 items（每行一条，id/bbox 即 SoM 依据）：\n%s\n"
             "请只还原上述 items 对应的 id（每个 id 恰好输出一条 element），输出 DesignSpec JSON。")
         % (w, h, item_lines)},
        {"type": "image_url",
         "image_url": {"url": "data:image/png;base64," + image_b64}},
    ]
    return [{"role": "system", "content": _SOM_BATCH_SYSTEM},
            {"role": "user", "content": user_content}]


def _normalize_design_element(el: dict, entry: dict) -> dict:
    """按 SoM 条目机械对齐 model 输出：id/bbox 以 SoM 为准，可见文本以条目为准，防模型移位/改写。"""
    out = dict(el)
    x, y, w, h = entry["bbox"]
    out["id"] = entry["id"]
    out["x"] = max(0, _snap4(x))
    out["y"] = max(0, _snap4(y))
    out["width"] = max(1, _snap4(w))
    out["height"] = max(1, _snap4(h))
    if entry.get("text"):
        out["text"] = entry["text"]          # DOM 可见文本为准，防模型改写
    if entry["group"] == "container":
        out["type"] = "container"
    elif not out.get("type"):
        out["type"] = entry.get("type", "rectangle")
    return out


def _assemble_som_design(canvas: dict, entries: list[dict], found: dict, meta: dict) -> dict:
    """把各批收集到的 element 按 SoM 顺序合成为 DesignSpec。"""
    design = {"canvas": canvas,
              "elements": [found[e["id"]] for e in entries if e["id"] in found]}
    design["_meta"] = meta
    return design


def generate_som_design(
    som_json: dict,
    image_b64: str,
    cfg,
    output_dir: str | Path | None = None,
    batch_size: int | None = None,
    max_rounds: int | None = None,
    min_coverage: float | None = None,
) -> dict:
    """把 SoM 标注转成 DesignSpec。

    默认（cfg.som_batch_enabled=True）按 id 分批生成：整张标注图每批重复传入，
    每批只允许模型输出本批 id，按 id 机械合并；随后覆盖度自检——缺失 id 定向补发，
    多轮后覆盖仍低于阈值即报错（不静默产出残缺 SVG）。cfg.som_batch_enabled=False
    时退回单发整表提示词，便于 A/B 对比。
    """
    if not cfg.som_batch_enabled:
        return parse_design_json(call_vlm(build_som_prompt(som_json, image_b64), cfg))

    size = som_json.get("size") or [0, 0]
    canvas = {"width": int(size[0]), "height": int(size[1])}
    batch_size = max(1, int(batch_size or cfg.som_batch_size))
    max_rounds = max(1, int(max_rounds or cfg.som_batch_max_rounds))
    min_coverage = float(cfg.som_batch_min_coverage if min_coverage is None else min_coverage)
    entries = _som_entries(som_json)
    expected = [e["id"] for e in entries]
    if not expected:
        return {"canvas": canvas, "elements": []}

    entry_by_id = {e["id"]: e for e in entries}
    found: dict[str, dict] = {}
    stats = {"calls": 0, "rounds": 0, "duplicates": 0, "foreign": 0, "cross_batch": 0}
    out_base = Path(output_dir) if output_dir else (Path(cfg.output_dir) if getattr(cfg, "output_dir", None) else None)
    raw_root = out_base / "13_vlm_raw" if out_base else None
    pool = list(expected)
    while pool and stats["rounds"] < max_rounds:
        stats["rounds"] += 1
        for batch_index, batch in enumerate(_chunk_ids(pool, batch_size), 1):
            stats["calls"] += 1
            raw = call_vlm(build_som_batch_prompt(som_json, image_b64, batch), cfg)
            if raw_root is not None and cfg.save_intermediate:
                raw_root.mkdir(parents=True, exist_ok=True)
                (raw_root / f"r{stats['rounds']}_b{batch_index}.txt").write_text(
                    raw, encoding="utf-8")
            try:
                parsed = parse_design_json(raw)
            except Exception as exc:
                logger.warning("SoM 分批第 %d 轮第 %d 批 JSON 解析失败：%s（该批计入缺失，下轮补发）",
                               stats["rounds"], batch_index, exc)
                continue
            batch_set = set(batch)
            for el in parsed.get("elements", []):
                eid = el.get("id")
                eid = "" if eid is None else str(eid)
                if eid not in batch_set:
                    if eid in expected:
                        stats["cross_batch"] += 1
                    else:
                        stats["foreign"] += 1
                    continue
                if eid in found:
                    stats["duplicates"] += 1
                    continue
                found[eid] = _normalize_design_element(el, entry_by_id[eid])
        pool = [i for i in expected if i not in found]

    missing = [i for i in expected if i not in found]
    coverage = len(found) / len(expected)
    meta = {"mode": "batch", "batch_size": batch_size, "calls": stats["calls"],
            "rounds": stats["rounds"], "expected": len(expected),
            "returned": len(found), "coverage": round(coverage, 4),
            "duplicates": stats["duplicates"], "foreign": stats["foreign"],
            "cross_batch": stats["cross_batch"], "missing": missing}
    design = _assemble_som_design(canvas, entries, found, meta)
    if coverage < min_coverage:
        partial_hint = ""
        if out_base is not None:
            (out_base / "12_design_partial.json").write_text(
                json.dumps(design, ensure_ascii=False, indent=1), encoding="utf-8")
            partial_hint = "，部分结果已写入 12_design_partial.json"
        preview = ", ".join(missing[:20])
        raise ValueError(
            "SoM 覆盖度不足：%.0f%% < %.0f%%，缺失 %d/%d 个 id（如 %s）%s。"
            % (coverage * 100, min_coverage * 100, len(missing), len(expected),
               preview or "(全部)", partial_hint))
    if missing:
        logger.warning("SoM 分批后仍缺失 %d/%d 个 id（首 20 个：%s），请在 12_design.json/_meta 中查看完整列表",
                       len(missing), len(expected), ", ".join(missing[:20]))
    if cfg.som_color_backfill and som_json.get("image"):
        design = backfill_colors_from_screenshot(design, som_json["image"], som_json)
    return design


def backfill_colors_from_screenshot(design: dict, image_path: str, som_json: dict) -> dict:
    """像素级颜色校正（预留接口，尚未实现）。

    计划：读取 image_path，按 SoM 各 id 的 bbox 在截图上采样颜色，
    当 model 未给出可信 style（fillColor/textColor/borderColor）时做兜底填充。
    启用方式：.env 设 SOM_COLOR_BACKFILL=true。
    """
    logger.info("SOM_COLOR_BACKFILL 已开启，但像素级颜色校正仍为预留接口，当前原样返回 DesignSpec")
    return design
