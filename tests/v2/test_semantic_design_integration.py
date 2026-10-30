from __future__ import annotations

import copy
import json
from pathlib import Path

from PIL import Image

from src.app.services.rendering.adapter_base import (
    PrototypeAdapter,
    paint_order,
)
from src.app.services.rendering.semantic_groups import apply_semantic_groups
from src.app.services.som.direct_design import build_direct_design
from src.config.settings import Config


def _geometry_hash(design: dict) -> str:
    rows = []
    for element in design["elements"]:
        rows.append(
            {
                key: copy.deepcopy(element.get(key))
                for key in (
                    "id",
                    "type",
                    "x",
                    "y",
                    "width",
                    "height",
                    "clip",
                    "textEmBox",
                    "textBox",
                    "layoutChildren",
                )
            }
        )
    return json.dumps(rows, ensure_ascii=False, sort_keys=True)


def _style_hash(design: dict) -> str:
    return json.dumps(
        [copy.deepcopy(element.get("style") or {}) for element in design["elements"]],
        ensure_ascii=False,
        sort_keys=True,
    )


def _semantic(
    role: str,
    source: int,
    *,
    group_id: str = "",
    group_role: str = "",
    member_index: int | None = None,
    member_count: int | None = None,
) -> dict:
    value = {
        "id": f"semantic-{source}",
        "role": role,
        "confidence": 0.94,
        "sourceDomIndices": [source],
        "bbox": [0, 0, 100, 40],
        "evidence": [{"kind": "tag", "value": role, "weight": 1.0}],
    }
    if group_id:
        value["groupId"] = group_id
        value["groupRole"] = group_role
    if member_index is not None:
        value["memberIndex"] = member_index
    if member_count is not None:
        value["memberCount"] = member_count
    return value


def _baseline_design() -> dict:
    return {
        "canvas": {"width": 800, "height": 600, "background": "#ffffff"},
        "elements": [
            {
                "id": "nav",
                "type": "container",
                "x": 0,
                "y": 0,
                "width": 800,
                "height": 64,
                "text": "",
                "name": "header",
                "style": {"fillColor": "#f4f7fb"},
                "domIndex": 0,
            },
            {
                "id": "list",
                "type": "container",
                "x": 20,
                "y": 80,
                "width": 760,
                "height": 240,
                "text": "",
                "name": "section",
                "style": {"fillColor": "transparent"},
                "domIndex": 1,
            },
            {
                "id": "card",
                "type": "container",
                "x": 20,
                "y": 80,
                "width": 220,
                "height": 220,
                "text": "",
                "name": "article",
                "style": {"fillColor": "#ffffff"},
                "domIndex": 2,
            },
            {
                "id": "button",
                "type": "button",
                "x": 620,
                "y": 20,
                "width": 120,
                "height": 40,
                "text": "Search",
                "name": "button",
                "style": {"fillColor": "#1f66ef", "textColor": "#ffffff"},
                "domIndex": 3,
            },
            {
                "id": "link",
                "type": "text",
                "x": 20,
                "y": 340,
                "width": 120,
                "height": 24,
                "text": "Methodology",
                "name": "a",
                "style": {"textColor": "#1557d6"},
                "domIndex": 4,
            },
        ],
    }


def test_semantic_groups_preserve_geometry_style_and_paint_order() -> None:
    baseline = _baseline_design()
    semantics = {
        "schema_version": "dom-semantic-merge/1.0",
        "components": [
            _semantic("navigation", 0),
            _semantic(
                "list",
                1,
                group_id="list-0",
                group_role="list",
                member_count=3,
            ),
            _semantic(
                "card",
                2,
                group_id="card-set-0",
                group_role="card",
                member_index=0,
                member_count=3,
            ),
            _semantic("button", 3, group_id="button-set-0", group_role="button", member_index=0, member_count=2),
            _semantic("link", 4),
        ],
    }

    semantic = apply_semantic_groups(copy.deepcopy(baseline), semantics)

    assert _geometry_hash(semantic) == _geometry_hash(baseline)
    assert _style_hash(semantic) == _style_hash(baseline)
    assert [item["id"] for _index, item in paint_order(semantic["elements"])] == [
        item["id"] for _index, item in paint_order(baseline["elements"])
    ]
    assert len(semantic["elements"]) == len(baseline["elements"])

    by_id = {item["id"]: item for item in semantic["elements"]}
    assert by_id["nav"]["semanticRole"] == "navigation"
    assert by_id["nav"]["name"] == "Nav / Primary"
    assert by_id["list"]["name"] == "List / Article grid"
    assert by_id["card"]["name"] == "Card / Article 1"
    assert by_id["button"]["name"] == "Button / Search"
    assert by_id["link"]["name"] == "Link / Methodology"
    assert by_id["card"]["semanticGroupId"] == "card-set-0"


def test_semantic_fields_are_disabled_by_default_and_read_only_when_enabled(
    tmp_path,
    monkeypatch,
) -> None:
    screenshot = tmp_path / "page.png"
    Image.new("RGB", (320, 180), "white").save(screenshot)
    dom_nodes = [
        {"tag": "body", "x": 0, "y": 0, "w": 320, "h": 180},
        {
            "tag": "button",
            "x": 20,
            "y": 20,
            "w": 120,
            "h": 40,
            "pIdx": 0,
            "text": "Search",
            "interactive": True,
        },
    ]
    som = {
        "image": str(screenshot),
        "size": [320, 180],
        "containers": [
            {
                "id": "C1",
                "bbox": [0, 0, 320, 180],
                "style": {"fillColor": "#ffffff"},
                "domIndex": 0,
            }
        ],
        "elements": [
            {
                "id": 1,
                "bbox": [20, 20, 120, 40],
                "type": "button",
                "text": "Search",
                "domIndex": 1,
                "style": {
                    "fillColor": "#1f66ef",
                    "textColor": "#ffffff",
                    "fontSize": 16,
                    "fontWeight": "400",
                    "fontFamily": "Arial",
                },
            }
        ],
        "provenance": {
            "route": "dom",
            "capture": {
                "viewport": {"width": 320, "height": 180},
                "canvas_size": [320, 180],
                "device_scale_factor": 1,
            },
        },
    }
    semantic_path = tmp_path / "20_semantic_components.json"
    semantic_path.write_text("{invalid", encoding="utf-8")
    monkeypatch.delenv("DOM_SEMANTIC_COMPONENTS", raising=False)

    assert Config().dom_semantic_components is False
    baseline = build_direct_design(som, dom_nodes=dom_nodes)
    assert all("semanticRole" not in item for item in baseline["elements"])

    semantic_path.write_text(
        json.dumps(
            {
                "schema_version": "dom-semantic-merge/1.0",
                "components": [_semantic("button", 1)],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("DOM_SEMANTIC_COMPONENTS", "true")
    semantic = build_direct_design(som, dom_nodes=dom_nodes)

    assert _geometry_hash(semantic) == _geometry_hash(baseline)
    assert _style_hash(semantic) == _style_hash(baseline)
    button = next(item for item in semantic["elements"] if item.get("domIndex") == 1)
    assert button["semanticRole"] == "button"


class _RecordingAdapter(PrototypeAdapter):
    supports_clip_frames = False

    def __init__(self) -> None:
        self.calls = []

    def connect(self) -> None:
        pass

    def disconnect(self) -> None:
        pass

    def create_frame(self, spec):
        self.calls.append(("create_frame", dict(spec)))
        return "frame"

    def create_rectangle(self, spec, parent_id=None):
        self.calls.append(("create_rectangle", dict(spec), parent_id))
        return "rect"

    def create_ellipse(self, spec, parent_id=None):
        self.calls.append(("create_ellipse", dict(spec), parent_id))
        return "ellipse"

    def create_text(self, spec, parent_id=None):
        self.calls.append(("create_text", dict(spec), parent_id))
        return "text"

    def create_image(self, spec, parent_id=None):
        self.calls.append(("create_image", dict(spec), parent_id))
        return "image"

    def flush(self) -> None:
        pass


def test_adapter_propagates_semantic_metadata_as_plugin_data() -> None:
    semantics = {
        "schema_version": "dom-semantic-merge/1.0",
        "components": [_semantic("button", 0)],
    }
    design = apply_semantic_groups(
        {
            "canvas": {"width": 320, "height": 180, "background": "#ffffff"},
            "elements": [
                {
                    "id": "text",
                    "type": "text",
                    "x": 20,
                    "y": 20,
                    "width": 120,
                    "height": 24,
                    "text": "Search",
                    "name": "button",
                    "style": {"textColor": "#111111"},
                    "domIndex": 0,
                }
            ],
        },
        semantics,
    )
    adapter = _RecordingAdapter()

    adapter.render_design(design)

    text_params = next(
        params
        for action, params, *_rest in adapter.calls
        if action == "create_text"
    )
    assert text_params["pluginData"]["figma_auto_agent.semantic_role"] == "button"
    assert (
        text_params["pluginData"]["figma_auto_agent.semantic_confidence"]
        == "0.94"
    )
