# -*- coding: utf-8 -*-
"""dom/a11y 样式直出 DesignSpec 离线测试：style 透传、SoM 带样式、规则拼装、路由门控。"""
from __future__ import annotations

import json
from dataclasses import replace

from src.app.services.som.annotate import annotate_som
from src.app.services.som.direct_design import (build_direct_design,
                                                try_build_direct_design)
from src.app.services.structure.graph import add_container, add_element, new_graph
from src.app.services.structure.providers.a11y import A11yProvider
from src.app.services.structure.providers.base import ProviderContext
from src.app.services.structure.providers.dom import DomProvider
from src.app.services.rendering.adapter_base import PrototypeAdapter
from src.config import load_config


def _dom_nodes():
    return [
        {"tag": "header", "role": "header", "ariaLabel": "", "text": "",
         "x": 0, "y": 0, "w": 800, "h": 60, "interactive": False,
         "bg": "rgb(20, 30, 40)", "pageBg": "rgb(255, 255, 255)",
         "color": "rgb(0, 0, 0)", "fontSize": "14px", "fontWeight": "400",
         "borderRadius": "0px"},
        {"tag": "div", "role": "", "ariaLabel": "", "text": "首页",
         "x": 8, "y": 10, "w": 60, "h": 20, "interactive": False,
         "bg": "rgba(0, 0, 0, 0)", "pageBg": "rgb(255, 255, 255)",
         "color": "rgb(255, 255, 255)", "fontSize": "16px", "fontWeight": "700",
         "borderRadius": "4px"},
    ]


def _ax_nodes():
    return [
        {"ignored": False, "backendDOMNodeId": 1, "role": {"value": "banner"},
         "name": {"value": ""},
         "properties": [
             {"name": "bounds",
              "value": {"value": {"x": 0, "y": 0, "width": 800, "height": 60}}},
             {"name": "style", "value": {"value": {
                 "bg": "rgb(20, 30, 40)", "pageBg": "rgb(255, 255, 255)",
                 "color": "rgb(0, 0, 0)", "fontSize": "14px",
                 "fontWeight": "400", "borderRadius": "0px"}}}]},
        {"ignored": False, "backendDOMNodeId": 2, "role": {"value": "heading"},
         "name": {"value": "首页"},
         "properties": [
             {"name": "bounds",
              "value": {"value": {"x": 8, "y": 10, "width": 60, "height": 20}}},
             {"name": "style", "value": {"value": {
                 "bg": "rgba(0, 0, 0, 0)", "pageBg": "rgb(255, 255, 255)",
                 "color": "rgb(255, 255, 255)", "fontSize": "16px",
                 "fontWeight": "700", "borderRadius": "4px"}}}]},
    ]


class _RecordingAdapter(PrototypeAdapter):
    """记录 create_* 调用顺序的测试桩，用于验证渲染绘制序。"""

    def __init__(self):
        self.calls = []

    def connect(self):
        pass

    def disconnect(self):
        pass

    def create_frame(self, spec, parent_id=None):
        self.calls.append(("frame", spec))
        return "F"

    def create_rectangle(self, spec, parent_id=None):
        self.calls.append(("rect", spec))
        return "R"

    def create_ellipse(self, spec, parent_id=None):
        self.calls.append(("ellipse", spec))
        return "E"

    def create_text(self, spec, parent_id=None):
        self.calls.append(("text", spec))
        return "T"

    def create_image(self, spec, parent_id=None):
        self.calls.append(("image", spec))
        return "I"

    def flush(self):
        pass


def test_dom_provider_passthrough_style(tmp_path):
    dom_p = tmp_path / "dom.json"
    dom_p.write_text(json.dumps(_dom_nodes()), encoding="utf-8")
    ctx = ProviderContext(image_path=str(tmp_path / "shot.png"), image_w=800,
                          image_h=600, route="dom", output_dir=str(tmp_path),
                          dom_path=str(dom_p), ax_path=None)
    g = DomProvider().run(ctx)

    assert any(c.get("style", {}).get("fillColor") == "#141e28"
               for c in g["containers"])
    texts = [e for e in g["elements"] if e.get("text") == "首页"]
    assert texts
    st = texts[0]["style"]
    assert st["textColor"] == "#ffffff"
    assert st["fontSize"] == 16
    assert st["fontWeight"] == "bold"
    assert st["borderRadius"] == 4
    assert "fillColor" not in st  # 透明背景不写 fill


def test_a11y_provider_passthrough_style(tmp_path):
    ax_p = tmp_path / "ax.json"
    ax_p.write_text(json.dumps(_ax_nodes()), encoding="utf-8")
    ctx = ProviderContext(image_path=str(tmp_path / "shot.png"), image_w=800,
                          image_h=600, route="a11y", output_dir=str(tmp_path),
                          dom_path=None, ax_path=str(ax_p))
    g = A11yProvider().run(ctx)

    assert any(c.get("style", {}).get("fillColor") == "#141e28"
               for c in g["containers"])
    heads = [e for e in g["elements"] if e.get("text") == "首页"]
    assert heads
    st = heads[0]["style"]
    assert st["textColor"] == "#ffffff"
    assert st["fontSize"] == 16
    assert st["fontWeight"] == "bold"
    assert st["borderRadius"] == 4
    assert "fillColor" not in st


def test_annotate_som_carries_style(tmp_path):
    import cv2
    import numpy as np
    cv2.imwrite(str(tmp_path / "shot.png"),
                np.zeros((600, 800, 3), dtype=np.uint8))
    g = new_graph(str(tmp_path / "shot.png"), 800, 600, "dom")
    add_container(g, [0, 0, 800, 60], role="header",
                  style={"fillColor": "#141e28", "borderRadius": 0})
    add_element(g, [8, 10, 60, 20], type_="text", text="首页",
                style={"textColor": "#ffffff", "fontSize": 16,
                       "fontWeight": "bold", "borderRadius": 4})
    som = annotate_som(g, str(tmp_path))

    assert som["containers"][0]["style"]["fillColor"] == "#141e28"
    elem = som["elements"][0]
    assert elem["text"] == "首页"
    assert elem["style"]["fontSize"] == 16
    assert elem["style"]["textColor"] == "#ffffff"
    disk = json.loads((tmp_path / "11_som.json").read_text(encoding="utf-8"))
    assert disk["elements"][0]["style"] == elem["style"]


def _direct_som(route="dom"):
    return {
        "image": "x.png", "size": [800, 600],
        "containers": [
            {"id": "C1", "bbox": [0, 0, 800, 60], "depth": 0, "parent": None,
             "style": {"fillColor": "#141e28"}},
            {"id": "C2", "bbox": [0, 60, 800, 540], "depth": 1, "parent": "C1",
             "style": {}},
        ],
        "elements": [
            {"id": 1, "bbox": [8, 10, 60, 20], "type": "text", "text": "首页",
             "container": "C1",
             "style": {"textColor": "#ffffff", "fontSize": 16,
                       "fontWeight": "bold", "borderRadius": 4}},
            {"id": 2, "bbox": [10, 80, 120, 32], "type": "input", "text": "",
             "container": "C2", "style": {}},
        ],
        "provenance": {"route": route, "fallbacks": []},
    }


def test_build_direct_design_rule():
    d = build_direct_design(_direct_som())
    by_id = {e["id"]: e for e in d["elements"]}

    assert "C1" in by_id and "C2" not in by_id  # 透明容器不凭空画框
    assert by_id["C1"]["type"] == "container"
    assert by_id["C1"]["style"]["fillColor"] == "#141e28"

    text = by_id["1"]
    assert text["x"] == 8 and text["width"] == 60
    assert text["text"] == "首页"
    assert text["style"]["textColor"] == "#ffffff"
    assert text["style"]["fontWeight"] == "bold"

    inp = by_id["2"]
    assert inp["type"] == "input"
    assert inp["style"]["fillColor"] == "#FFFFFF"  # 无背景控件的保守默认
    assert d["_meta"]["mode"] == "dom-direct"
    assert d["_meta"]["skipped_transparent_containers"] == 1


def test_try_direct_design_route_gate():
    dom_cfg = replace(load_config(), dom_direct_design=True)
    assert try_build_direct_design(_direct_som("dom"), dom_cfg) is not None
    assert try_build_direct_design(_direct_som("a11y"), dom_cfg) is not None

    non_style_route = {**_direct_som(), "provenance": {"route": "grounding"}}
    assert try_build_direct_design(non_style_route, dom_cfg) is None

    off = replace(load_config(), dom_direct_design=False)
    assert try_build_direct_design(_direct_som("dom"), off) is None

    sparse = _direct_som()
    sparse["containers"] = [{"id": "C1", "bbox": [0, 0, 800, 60], "depth": 0,
                             "parent": None, "style": {}}]
    sparse["elements"] = [{"id": 1, "bbox": [8, 10, 60, 20], "type": "text",
                           "text": "首页", "container": "C1", "style": {}}]
    assert try_build_direct_design(sparse, dom_cfg) is None


def test_build_direct_design_a11y_mode():
    d = build_direct_design(_direct_som("a11y"))
    assert d["_meta"]["mode"] == "a11y-direct"
    assert {e["id"] for e in d["elements"]} >= {"C1", "1", "2"}


def test_build_style_border_fields():
    """build_style：borderColor/borderWidth 成对有效才写入 style。"""
    from src.app.utils.style_utils import build_style
    st = build_style(bg="rgb(255,255,255)", page_bg="rgb(240,240,240)",
                     borderColor="rgb(221, 221, 221)", borderWidth="1px")
    assert st["fillColor"] == "#ffffff"
    assert st["borderColor"] == "#dddddd"
    assert st["borderWidth"] == 1
    # width=0px 或颜色透明 → 边框字段整体不写
    assert "borderColor" not in build_style(borderColor="rgb(221, 221, 221)",
                                            borderWidth="0px")
    assert "borderColor" not in build_style(borderColor="rgba(0, 0, 0, 0)",
                                            borderWidth="1px")


def test_dom_provider_passes_border(tmp_path):
    """DOM 采集的 borderColor/borderWidth 必须透传到 PageGraph 容器/元素 style。"""
    nodes = _dom_nodes()
    nodes[0]["borderColor"] = "rgb(221, 221, 221)"
    nodes[0]["borderWidth"] = "1px"
    dom_p = tmp_path / "dom.json"
    dom_p.write_text(json.dumps(nodes), encoding="utf-8")
    ctx = ProviderContext(image_path=str(tmp_path / "shot.png"), image_w=800,
                          image_h=600, route="dom", output_dir=str(tmp_path),
                          dom_path=str(dom_p), ax_path=None)
    g = DomProvider().run(ctx)
    cont = next(c for c in g["containers"])
    assert cont["style"]["borderColor"] == "#dddddd"
    assert cont["style"]["borderWidth"] == 1


def test_dom_provider_filters_icon_glyph_text(tmp_path):
    """DOM 路线：私有区图标字形叶子不生成正文元素；掺杂文本只剥离图标保留正文。"""
    nodes = _dom_nodes()
    nodes.append({"tag": "i", "role": "", "ariaLabel": "", "text": "\ue090\ue090",
                  "x": 100, "y": 200, "w": 20, "h": 20, "interactive": False,
                  "bg": "rgba(0, 0, 0, 0)", "pageBg": "rgb(255, 255, 255)",
                  "color": "rgb(0, 0, 0)", "fontSize": "14px",
                  "fontWeight": "400", "borderRadius": "0px"})
    nodes.append({"tag": "span", "role": "", "ariaLabel": "", "text": "运行\uf107成功",
                  "x": 100, "y": 230, "w": 80, "h": 20, "interactive": False,
                  "bg": "rgba(0, 0, 0, 0)", "pageBg": "rgb(255, 255, 255)",
                  "color": "rgb(0, 0, 0)", "fontSize": "14px",
                  "fontWeight": "400", "borderRadius": "0px"})
    dom_p = tmp_path / "dom.json"
    dom_p.write_text(json.dumps(nodes), encoding="utf-8")
    ctx = ProviderContext(image_path=str(tmp_path / "shot.png"), image_w=800,
                          image_h=600, route="dom", output_dir=str(tmp_path),
                          dom_path=str(dom_p), ax_path=None)
    g = DomProvider().run(ctx)
    texts = [e["text"] for e in g["elements"] if e.get("text")]
    assert "首页" in texts
    assert "运行成功" in texts           # 掺杂文本剥离图标字形
    assert not any("\ue090" in t for t in texts)
    assert not any("\uf107" in t for t in texts)


def test_dom_provider_clips_to_canvas(tmp_path):
    """DOM 视口裁剪：画布外(横向溢出)节点不生成，跨界节点 clamp 到画布内。"""
    nodes = _dom_nodes()
    nodes.append({"tag": "header", "role": "header", "ariaLabel": "", "text": "",
                  "x": 900, "y": 0, "w": 200, "h": 60, "interactive": False,
                  "bg": "rgb(20, 30, 40)", "pageBg": "rgb(255, 255, 255)",
                  "color": "rgb(0, 0, 0)", "fontSize": "14px",
                  "fontWeight": "400", "borderRadius": "0px"})
    nodes.append({"tag": "span", "role": "", "ariaLabel": "", "text": "跨界",
                  "x": 760, "y": 300, "w": 80, "h": 20, "interactive": False,
                  "bg": "rgba(0, 0, 0, 0)", "pageBg": "rgb(255, 255, 255)",
                  "color": "rgb(0, 0, 0)", "fontSize": "14px",
                  "fontWeight": "400", "borderRadius": "0px"})
    nodes.append({"tag": "span", "role": "", "ariaLabel": "", "text": "画布外",
                  "x": 850, "y": 400, "w": 60, "h": 20, "interactive": False,
                  "bg": "rgba(0, 0, 0, 0)", "pageBg": "rgb(255, 255, 255)",
                  "color": "rgb(0, 0, 0)", "fontSize": "14px",
                  "fontWeight": "400", "borderRadius": "0px"})
    dom_p = tmp_path / "dom.json"
    dom_p.write_text(json.dumps(nodes), encoding="utf-8")
    ctx = ProviderContext(image_path=str(tmp_path / "shot.png"), image_w=800,
                          image_h=600, route="dom", output_dir=str(tmp_path),
                          dom_path=str(dom_p), ax_path=None)
    g = DomProvider().run(ctx)

    assert not any(c.get("bbox") == [900, 0, 200, 60] for c in g["containers"])
    clipped = [e for e in g["elements"] if e.get("text") == "跨界"]
    assert clipped and clipped[0]["bbox"] == [760, 300, 40, 20]
    assert not any(e.get("text") == "画布外" for e in g["elements"])


def test_build_direct_design_bordered_container_and_image_backfill(tmp_path):
    """透明+边框容器不再被跳过；无背景有边框控件保留描边；image 回填真实像素。"""
    import base64
    import io
    import cv2
    import numpy as np
    from PIL import Image

    shot = tmp_path / "shot.png"
    frame = np.full((600, 800, 3), 255, dtype=np.uint8)
    frame[100:140, 50:150] = (0, 0, 255)      # BGR 红色块 = 图片元素真实内容
    cv2.imwrite(str(shot), frame)

    som = {
        "image": str(shot), "size": [800, 600],
        "containers": [
            {"id": "C1", "bbox": [0, 0, 800, 60], "depth": 0, "parent": None,
             "style": {"fillColor": "#141e28"}},
            {"id": "C2", "bbox": [10, 60, 780, 300], "depth": 1, "parent": "C1",
             "style": {"borderColor": "#dddddd", "borderWidth": 1}},
        ],
        "elements": [
            {"id": 1, "bbox": [50, 100, 100, 40], "type": "image", "text": "",
             "container": "C2", "style": {}},
            {"id": 2, "bbox": [300, 200, 120, 32], "type": "button", "text": "",
             "container": "C2", "style": {"borderColor": "#888888",
                                          "borderWidth": 1}},
        ],
        "provenance": {"route": "dom", "fallbacks": []},
    }
    d = build_direct_design(som)
    by_id = {e["id"]: e for e in d["elements"]}

    assert "C2" in by_id                       # 有边框的透明容器不再被丢弃
    assert by_id["C2"]["style"]["fillColor"] == "transparent"
    assert by_id["C2"]["style"]["borderColor"] == "#dddddd"
    assert by_id["C2"]["style"]["borderWidth"] == 1
    assert by_id["2"]["style"]["fillColor"] == "transparent"  # 描边控件不垫白底
    assert by_id["2"]["style"]["borderColor"] == "#888888"

    img = by_id["1"]
    assert img["imageBase64"]
    crop = Image.open(io.BytesIO(base64.b64decode(img["imageBase64"])))
    rgb = np.asarray(crop)
    assert rgb[..., 0].mean() > 150 and rgb[..., 2].mean() < 100
    assert d["_meta"]["image_backfilled"] == 1
    assert d["_meta"]["skipped_transparent_containers"] == 0


def test_dom_provider_marks_fixed_column_overlay(tmp_path):
    """sticky 固定列：定位单元格本身不发射，但其子按钮继承 overlay+zIndex；
    被它盖住的滚动文本保持普通层。"""
    base = {"role": "", "ariaLabel": "", "bg": "rgba(0, 0, 0, 0)",
            "pageBg": "rgb(255, 255, 255)", "color": "rgb(0, 0, 0)",
            "fontSize": "14px", "fontWeight": "400", "borderRadius": "0px"}
    nodes = [
        {**base, "tag": "span", "text": "工艺路线值", "x": 330, "y": 100,
         "w": 120, "h": 40, "interactive": False,
         "position": "static", "zIndex": "0"},
        {**base, "tag": "td", "text": "", "x": 260, "y": 100, "w": 140, "h": 45,
         "interactive": False, "position": "sticky", "zIndex": "30"},
        {**base, "tag": "a", "text": "", "x": 270, "y": 105, "w": 30, "h": 20,
         "interactive": True, "position": "static", "zIndex": "0"},
    ]
    dom_p = tmp_path / "dom.json"
    dom_p.write_text(json.dumps(nodes), encoding="utf-8")
    ctx = ProviderContext(image_path=str(tmp_path / "shot.png"), image_w=800,
                          image_h=600, route="dom", output_dir=str(tmp_path),
                          dom_path=str(dom_p), ax_path=None)
    g = DomProvider().run(ctx)

    overlays = [e for e in g["elements"] if e.get("overlay")]
    assert len(overlays) == 1
    assert overlays[0]["type"] == "button"
    assert overlays[0]["zIndex"] == 30
    covered = [e for e in g["elements"] if e.get("text") == "工艺路线值"]
    assert covered and not covered[0]["overlay"] and covered[0]["zIndex"] == 0


def test_dom_provider_no_false_overlay_for_isolated_absolute(tmp_path):
    """absolute+z 但没有与兄弟内容重叠（如页面局部装饰）不应被判浮层。"""
    base = {"role": "", "ariaLabel": "", "bg": "rgba(0, 0, 0, 0)",
            "pageBg": "rgb(255, 255, 255)", "color": "rgb(0, 0, 0)",
            "fontSize": "14px", "fontWeight": "400", "borderRadius": "0px"}
    nodes = [
        {**base, "tag": "div", "text": "", "x": 500, "y": 200, "w": 200, "h": 100,
         "interactive": False, "position": "absolute", "zIndex": "5"},
        {**base, "tag": "a", "text": "", "x": 505, "y": 210, "w": 40, "h": 20,
         "interactive": True, "position": "static", "zIndex": "0"},
        {**base, "tag": "span", "text": "独立文案", "x": 10, "y": 300, "w": 60,
         "h": 20, "interactive": False, "position": "static", "zIndex": "0"},
    ]
    dom_p = tmp_path / "dom.json"
    dom_p.write_text(json.dumps(nodes), encoding="utf-8")
    ctx = ProviderContext(image_path=str(tmp_path / "shot.png"), image_w=800,
                          image_h=600, route="dom", output_dir=str(tmp_path),
                          dom_path=str(dom_p), ax_path=None)
    g = DomProvider().run(ctx)

    assert not any(e.get("overlay") for e in g["elements"])


def test_overlay_fields_flow_to_som_and_design(tmp_path):
    """PageGraph 的 overlay/zIndex 需贯穿 SoM JSON 与直出 DesignSpec。"""
    import cv2
    import numpy as np
    cv2.imwrite(str(tmp_path / "shot.png"),
                np.zeros((600, 800, 3), dtype=np.uint8))
    g = new_graph(str(tmp_path / "shot.png"), 800, 600, "dom")
    add_container(g, [0, 0, 800, 60], role="header", overlay=True, z_index=5,
                  style={"fillColor": "#141e28"})
    add_element(g, [8, 10, 60, 20], type_="text", text="首页",
                overlay=True, z_index=5,
                style={"textColor": "#ffffff", "fontSize": 16})
    add_element(g, [300, 300, 120, 32], type_="button", text="普通按钮")
    som = annotate_som(g, str(tmp_path))

    assert som["containers"][0]["overlay"] is True
    assert som["containers"][0]["zIndex"] == 5
    assert som["elements"][0]["overlay"] is True
    assert som["elements"][0]["zIndex"] == 5
    assert som["elements"][1]["overlay"] is False

    design = build_direct_design(som)
    by_id = {e["id"]: e for e in design["elements"]}
    assert by_id["C1"]["overlay"] is True and by_id["C1"]["zIndex"] == 5
    assert by_id["1"]["overlay"] is True and by_id["1"]["zIndex"] == 5
    assert design["_meta"]["overlays"] == 2


def test_render_design_paints_overlay_last():
    """渲染绘制序：普通内容先画，overlay 顺延到最后并按 zIndex 升序。"""
    design = {
        "canvas": {"width": 800, "height": 600},
        "elements": [
            {"id": "t1", "type": "text", "x": 40, "y": 40, "width": 60,
             "height": 20, "text": "被盖内容", "overlay": False, "zIndex": 0,
             "style": {"textColor": "#000000", "fontSize": 14}},
            {"id": "b9", "type": "container", "x": 30, "y": 30, "width": 80,
             "height": 40, "overlay": True, "zIndex": 9,
             "style": {"fillColor": "#ffffff"}},
            {"id": "b1", "type": "container", "x": 30, "y": 30, "width": 80,
             "height": 40, "overlay": True, "zIndex": 1,
             "style": {"fillColor": "#ffffff"}},
            {"id": "i1", "type": "text", "x": 35, "y": 35, "width": 16,
             "height": 16, "text": "图标", "overlay": True, "zIndex": 1,
             "style": {"textColor": "#000000", "fontSize": 12}},
        ],
    }
    adapter = _RecordingAdapter()
    adapter.render_design(design)

    ids = [call[1].get("id") for call in adapter.calls]
    assert ids == [None, "t1", "b1", "i1", "b9"]
