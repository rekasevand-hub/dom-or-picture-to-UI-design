from __future__ import annotations

from src.app.services.structure.layer_tree import build_layer_tree


def test_build_layer_tree_preserves_parent_child_order():
    tree = build_layer_tree(
        [
            {"tag": "body", "x": 0, "y": 0, "w": 100, "h": 100},
            {"tag": "div", "pIdx": 0, "x": 0, "y": 0, "w": 100, "h": 40},
            {"tag": "span", "pIdx": 1, "x": 4, "y": 4, "w": 30, "h": 20},
        ]
    )
    assert tree["roots"] == ["n0"]
    assert tree["nodes"]["n0"]["children"] == ["n1"]
    assert tree["nodes"]["n1"]["children"] == ["n2"]
    assert tree["nodes"]["n2"]["sourceIndex"] == 2


def test_build_layer_tree_keeps_roots_separate_and_compact():
    nodes = [
        {"tag": "main", "x": 0, "y": 0, "w": 100, "h": 100, "text": "large"},
        {"tag": "aside", "x": 110, "y": 0, "w": 40, "h": 100},
    ]
    tree = build_layer_tree(nodes)
    assert tree["schema_version"] == "dom-layer-tree/1.0"
    assert tree["roots"] == ["n0", "n1"]
    assert tree["nodes"]["n0"]["bbox"] == [0, 0, 100, 100]
    assert "text" not in tree["nodes"]["n0"]
