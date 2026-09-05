# -*- coding: utf-8 -*-
"""SoM 分批生成离线测试：按 id 分批、机械合并、覆盖度自检（mock call_vlm，不发网络）。"""
from __future__ import annotations

import json
from dataclasses import replace

import pytest

from src.app.services.llm import llm_service
from src.app.services.llm.llm_service import build_som_batch_prompt, generate_som_design
from src.config import load_config


def _som(n_containers: int = 2, n_elements: int = 3, w: int = 400, h: int = 200) -> dict:
    containers = [
        {"id": f"C{i}", "bbox": [0, (i - 1) * 60, 100, 50], "depth": i - 1,
         "parent": None,
         "elements": list(range(1, n_elements + 1)) if i == 1 else []}
        for i in range(1, n_containers + 1)
    ]
    elements = [
        {"id": n, "bbox": [10, n * 20, 20, 10], "text": f"文本{n}",
         "type": "text", "container": "C1", "interactable": False}
        for n in range(1, n_elements + 1)
    ]
    return {"image": "a.png", "size": [w, h], "containers": containers,
            "elements": elements, "provenance": {"route": "dom"}}


def _requested_ids(messages) -> list[str]:
    text = messages[1]["content"][0]["text"]
    ids = []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("{"):
            ids.append(json.loads(line)["id"])
    return ids


def _echo(ids, drop=(), extra=()) -> str:
    elements = []
    for i in ids:
        if i in drop:
            continue
        elements.append({"id": i,
                         "type": "container" if i.startswith("C") else "text",
                         "x": 3, "y": 3, "width": 33, "height": 22})
    for eid in extra:
        elements.append({"id": eid, "type": "text",
                         "x": 0, "y": 0, "width": 1, "height": 1})
    return json.dumps({"canvas": {"width": 400, "height": 200},
                       "elements": elements}, ensure_ascii=False)


def _cfg(tmp_path, **kw):
    return replace(load_config(), output_dir=tmp_path, **kw)


def test_batch_happy_path(tmp_path, monkeypatch):
    som = _som()
    calls = []

    def fake(messages, cfg):
        ids = _requested_ids(messages)
        calls.append(ids)
        return _echo(ids)

    monkeypatch.setattr(llm_service, "call_vlm", fake)
    design = generate_som_design(som, "BASE64==", _cfg(tmp_path), batch_size=2)

    assert [e["id"] for e in design["elements"]] == ["C1", "C2", "1", "2", "3"]
    assert design["_meta"]["calls"] == 3
    assert design["_meta"]["rounds"] == 1
    assert design["_meta"]["coverage"] == 1.0
    assert design["_meta"]["missing"] == []

    # 模型输出被机械对齐到 SoM bbox（4px 网格），且 id 缺 text 时回填 SoM 文本
    el1 = {e["id"]: e for e in design["elements"]}["1"]
    assert el1["x"] == 8 and el1["width"] == 20 and el1["height"] == 8
    el3 = {e["id"]: e for e in design["elements"]}["3"]
    assert el3["text"] == "文本3"
    assert {e["id"]: e for e in design["elements"]}["C1"]["type"] == "container"

    raw_files = list((tmp_path / "13_vlm_raw").glob("*.txt"))
    assert len(raw_files) == 3


def test_batch_retry_only_missing_ids(tmp_path, monkeypatch):
    som = _som()
    calls = []
    dropped = {"done": False}

    def fake(messages, cfg):
        ids = _requested_ids(messages)
        calls.append(ids)
        drop = {"2"} if (not dropped["done"] and "2" in ids) else set()
        if drop:
            dropped["done"] = True
        return _echo(ids, drop=drop)

    monkeypatch.setattr(llm_service, "call_vlm", fake)
    design = generate_som_design(som, "B==", _cfg(tmp_path), batch_size=10, max_rounds=3)

    assert design["_meta"]["rounds"] == 2
    assert design["_meta"]["calls"] == 2
    assert calls[1] == ["2"]  # 第二轮只定向补发缺失的 id
    assert design["_meta"]["missing"] == []
    assert len(design["elements"]) == 5


def test_batch_raises_on_low_coverage(tmp_path, monkeypatch):
    som = _som()

    def fake(messages, cfg):
        return _echo(_requested_ids(messages), drop={"2"})

    monkeypatch.setattr(llm_service, "call_vlm", fake)
    with pytest.raises(ValueError, match="覆盖度不足"):
        generate_som_design(som, "B==", _cfg(tmp_path, som_batch_min_coverage=0.9),
                            batch_size=10, max_rounds=2)
    assert (tmp_path / "12_design_partial.json").exists()


def test_batch_drops_foreign_and_duplicates(tmp_path, monkeypatch):
    som = _som(n_containers=1, n_elements=2)

    def fake(messages, cfg):
        ids = _requested_ids(messages)
        parsed = json.loads(_echo(ids, extra=("999",)))
        elems = parsed["elements"]
        if elems:
            elems.insert(0, dict(elems[0]))  # 第一个 id 故意重复输出
        return json.dumps({"canvas": parsed["canvas"], "elements": elems},
                          ensure_ascii=False)

    monkeypatch.setattr(llm_service, "call_vlm", fake)
    design = generate_som_design(som, "B==", _cfg(tmp_path), batch_size=10)

    assert design["_meta"]["duplicates"] == 1
    assert design["_meta"]["foreign"] == 1
    assert [e["id"] for e in design["elements"]] == ["C1", "1", "2"]


def test_batch_rejects_cross_batch_ids(tmp_path, monkeypatch):
    som = _som(n_containers=2, n_elements=2)  # ids: C1, C2, 1, 2
    all_ids = ["C1", "C2", "1", "2"]
    first = {"done": False}

    def fake(messages, cfg):
        if not first["done"]:
            first["done"] = True
            return _echo(all_ids)  # 第一批发超范围 id，本应属于第二批
        return _echo(_requested_ids(messages))

    monkeypatch.setattr(llm_service, "call_vlm", fake)
    design = generate_som_design(som, "B==", _cfg(tmp_path), batch_size=3, max_rounds=3)

    assert design["_meta"]["cross_batch"] == 1
    assert design["_meta"]["coverage"] == 1.0
    assert len(design["elements"]) == 4


def test_single_shot_when_batch_disabled(tmp_path, monkeypatch):
    som = _som()
    calls = []

    def fake_call_vlm(messages, cfg):
        calls.append(1)
        return '{"canvas": {"width": 400, "height": 200}, "elements": []}'

    monkeypatch.setattr(llm_service, "call_vlm", fake_call_vlm)
    design = generate_som_design(som, "B==",
                                 _cfg(tmp_path, som_batch_enabled=False))
    assert len(calls) == 1
    assert design["elements"] == []


def test_build_som_batch_prompt_only_includes_given_ids():
    som = _som()
    msgs = build_som_batch_prompt(som, "B64==", ["C1", "3"])
    parts = msgs[1]["content"]
    text = parts[0]["text"]
    assert '"id": "C1"' in text and '"id": "3"' in text
    assert '"id": "C2"' not in text and '"id": "1"' not in text
    assert any(p["type"] == "image_url" and "B64==" in p["image_url"]["url"]
               for p in parts)


def test_batch_empty_som(tmp_path, monkeypatch):
    som = _som(n_containers=0, n_elements=0)

    def fake(messages, cfg):
        raise AssertionError("空 SoM 不应调用 VLM")

    monkeypatch.setattr(llm_service, "call_vlm", fake)
    design = generate_som_design(som, "B==", _cfg(tmp_path))
    assert design["elements"] == []
    assert design["canvas"] == {"width": 400, "height": 200}


def _som_with_styles() -> dict:
    """DOM 路线 SoM：容器/文本带浏览器 computed style，模拟页面真实配色。"""
    return {
        "image": "a.png", "size": [400, 200], "provenance": {"route": "dom"},
        "containers": [
            {"id": "C1", "bbox": [0, 0, 100, 40], "depth": 0,
             "style": {"fillColor": "#1890ff", "textColor": "#ffffff",
                       "borderRadius": 4, "borderColor": "#1890ff",
                       "borderWidth": 1}},
            {"id": "C2", "bbox": [0, 60, 100, 40], "depth": 0,
             "style": {"fillColor": "#fafafa"}},
        ],
        "elements": [
            {"id": 1, "bbox": [10, 8, 28, 20], "type": "text", "text": "\u641c\u7d22",
             "container": "C1",
             "style": {"textColor": "#ffffff", "fontSize": 14}},
            {"id": 2, "bbox": [10, 68, 28, 20], "type": "text", "text": "\u666e\u901a",
             "container": "C2", "style": {}},
        ],
    }


def _styled_echo(ids) -> str:
    """VLM \u5e38\u89c1\u8bef\u8bfb\uff1a\u767d\u5b57\u84dd\u5e95\u88ab\u53cd\u5199\u6210\u84dd\u5b57\u767d\u5e95\u3002"""
    style = {
        "C1": {"fillColor": "#FFFFFF", "textColor": "#1890ff",
               "borderRadius": 0, "borderWidth": 1, "borderColor": "#000000"},
        "C2": {"fillColor": "#F5F5F5", "textColor": "#000000"},
        "1": {"fillColor": "#FFFFFF", "textColor": "#1890ff", "fontSize": 12},
        "2": {"fillColor": "#FFFFFF", "textColor": "#333333", "fontSize": 14},
    }
    geo = {"C1": (0, 0, 100, 40), "C2": (0, 60, 100, 40),
           "1": (10, 8, 28, 20), "2": (10, 68, 28, 20)}
    elements = []
    for i in ids:
        x, y, w, h = geo[i]
        elements.append({"id": i,
                         "type": "container" if i.startswith("C") else "text",
                         "x": x, "y": y, "width": w, "height": h,
                         "text": "" if i.startswith("C") else "\u641c\u7d22",
                         "style": style[i]})
    return json.dumps({"canvas": {"width": 400, "height": 200}, "elements": elements},
                      ensure_ascii=False)


def test_reconcile_som_styles_pins_dom_computed_colors(tmp_path, monkeypatch):
    """DOM \u8def\u7ebf\uff1aSoM \u5df2\u6709\u7684 computed style \u8986\u76d6\u6a21\u578b\u731c\u8272\uff0c
    \u672a\u8bb0\u5f55\u7684\u5b57\u6bb5\u4fdd\u7559\u6a21\u578b\u8f93\u51fa\u3002"""
    som = _som_with_styles()

    def fake(messages, cfg):
        return _styled_echo(_requested_ids(messages))

    monkeypatch.setattr(llm_service, "call_vlm", fake)
    design = generate_som_design(som, "B==", _cfg(tmp_path), batch_size=10)
    by_id = {e["id"]: e for e in design["elements"]}

    # C1/文本 1 \u88ab\u6a21\u578b\u53cd\u8f6c\u6210\u84dd\u5b57\u767d\u5e95\uff0c\u5e94\u56de\u586b\u767d\u5b57\u84dd\u5e95
    assert by_id["C1"]["style"]["fillColor"] == "#1890ff"
    assert by_id["C1"]["style"]["borderColor"] == "#1890ff"
    assert by_id["1"]["style"]["textColor"] == "#ffffff"
    assert by_id["1"]["style"]["fontSize"] == 14
    # SoM \u65e0 textColor/fontSize \u8bb0\u5f55\u7684\u5143\u7d20 2 \u4fdd\u7559\u6a21\u578b\u8f93\u51fa
    assert by_id["2"]["style"]["textColor"] == "#333333"
    assert by_id["C2"]["style"]["fillColor"] == "#fafafa"
    assert design["_meta"]["som_style_overrides"] > 0


def test_som_batch_prompt_carries_computed_style():
    som = _som_with_styles()
    msgs = build_som_batch_prompt(som, "B64==", ["C1", "1"])
    text = msgs[1]["content"][0]["text"]
    assert '"style"' in text and "#1890ff" in text and "#ffffff" in text
