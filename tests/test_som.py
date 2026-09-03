from src.app.services.structure.graph import new_graph, add_container, add_element
from src.app.services.som.annotate import annotate_som

def _mk_graph(tmp_path, shot):
    import cv2
    cv2.imwrite(str(tmp_path / "shot.png"), __import__("numpy").zeros((80, 100, 3), dtype="uint8"))
    g = new_graph(str(tmp_path / "shot.png"), 100, 80, "dom")
    add_container(g, [0, 0, 100, 80], role="banner")
    add_container(g, [0, 0, 100, 20], role="header")
    add_element(g, [10, 4, 20, 12], type_="button", text="登录")
    return g

def test_annotate_som_writes_files(tmp_path):
    g = _mk_graph(tmp_path, None)
    som = annotate_som(g, str(tmp_path))
    assert (tmp_path / "11_som.png").exists()
    assert (tmp_path / "11_som.json").exists()
    assert som["elements"][0]["id"] == 1
    assert som["containers"][0]["id"] == "C1"
    cids = {c["id"] for c in som["containers"]}
    assert som["elements"][0]["container"] in cids
