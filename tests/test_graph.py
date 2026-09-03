import json
from src.app.services.structure.graph import (new_graph, add_container, add_element,
                                              assign_ids, assign_parent_depth, contains, iou,
                                              save_graph, load_graph)

def _sample():
    g = new_graph("shot.png", 100, 100, "dom")
    add_container(g, [0, 0, 100, 50], role="banner", source="dom:header")   # C
    add_container(g, [10, 10, 40, 30], role="card", source="dom:div")        # 内层容器
    add_element(g, [12, 12, 30, 20], type_="button", text="hi")              # 中心(27,22) 在内层容器
    add_element(g, [60, 10, 30, 20], type_="text", text="t")                 # 只在外层
    return g

def test_assign_ids_and_containment():
    g = _sample()
    assign_ids(g)
    assign_parent_depth(g)
    ids = [c["id"] for c in g["containers"]]
    assert ids == ["C1", "C2"]
    c_outer = g["containers"][0]
    c_inner = g["containers"][1]
    assert c_inner["parent"] == "C1" and c_inner["depth"] == 1 and c_outer["depth"] == 0
    by_id = {c["id"]: c for c in g["containers"]}
    # 阅读序编号（上→下、左→右）：文本(y=10,id1) 只挂外层，按钮(y=12,id2) 挂最小内层容器
    assert by_id["C1"]["elements"] == [1]      # 外层只列直接子元素(文本1)
    assert by_id["C2"]["elements"] == [2]      # 按钮(2)挂内层容器
    assert g["elements"][0]["container"] == "C1"
    assert g["elements"][1]["container"] == "C2"

def test_iou_and_contains():
    assert iou([0, 0, 10, 10], [5, 5, 10, 10]) == 25.0 / 175.0
    assert contains({"bbox": [0, 0, 100, 50]}, {"bbox": [10, 10, 40, 30]}) is True
    assert contains({"bbox": [10, 10, 40, 30]}, {"bbox": [0, 0, 100, 50]}) is False

def test_save_load_roundtrip(tmp_path):
    g = _sample()
    assign_ids(g)
    p = str(tmp_path / "g.json")
    save_graph(g, p)
    g2 = load_graph(p)
    assert g2["image"] == "shot.png" and len(g2["containers"]) == 2

