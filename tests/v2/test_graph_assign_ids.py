from __future__ import annotations

from src.app.services.structure.graph import assign_ids, new_graph


def _element(x: int, y: int, w: int, h: int, text: str) -> dict:
    return {"bbox": [x, y, w, h], "text": text, "kind": "text"}


def test_element_outside_every_container_does_not_abort() -> None:
    """A headline above the card has no container; id assignment must survive.

    The old code only wrote ``container`` when a containing box existed, then
    indexed the key unconditionally -- an unseen layout with one orphan element
    raised ``KeyError: 'container'`` and the whole run died before any render.
    """
    graph = new_graph("page.png", 200, 200, "grounding")
    graph["containers"] = [
        {"bbox": [20, 50, 160, 140], "role": "card"},
    ]
    graph["elements"] = [
        _element(20, 10, 160, 30, "标题"),      # above the card
        _element(30, 60, 100, 20, "正文"),      # inside the card
        _element(20, 195, 160, 5, "页脚"),      # below the card
    ]

    assign_ids(graph)

    assert [e["id"] for e in graph["elements"]] == [1, 2, 3]
    assert graph["elements"][0]["container"] is None
    assert graph["elements"][1]["container"] == "C1"
    assert graph["elements"][2]["container"] is None
    assert graph["containers"][0]["elements"] == [2]
