from __future__ import annotations

from collections import Counter
from pathlib import Path

from playwright.sync_api import sync_playwright

from src.app.services.structure.capture import DOM_JS
from src.app.services.structure.layer_tree import build_layer_tree
from src.app.services.structure.semantic_components import (
    classify_semantic_components,
)


FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "dom_semantics"
    / "semantic_fixture.html"
)


def _capture_fixture() -> list[dict]:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={"width": 1440, "height": 1200})
            page.goto(FIXTURE.resolve().as_uri(), wait_until="domcontentloaded")
            return page.evaluate(DOM_JS)
        finally:
            browser.close()


def test_semantic_roles_have_evidence_bounds_and_explicit_capture_hints() -> None:
    nodes = _capture_fixture()
    result = classify_semantic_components(
        nodes,
        layer_tree=build_layer_tree(nodes),
    )
    roles = Counter(item["role"] for item in result["components"])

    assert result["schema_version"] == "dom-semantic-components/1.0"
    assert roles["navigation"] == 2
    assert roles["list"] == 2
    assert roles["card"] == 6
    assert roles["button"] == 3
    assert roles["link"] == 1
    assert result["unknownCount"] == 0

    for item in result["components"]:
        assert item["evidence"]
        assert 0.0 <= item["confidence"] <= 1.0
        assert item["sourceDomIndices"]
        assert item["bbox"][2] > 0 and item["bbox"][3] > 0

    nav = next(node for node in nodes if node.get("tag") == "nav")
    role_nav = next(
        node
        for node in nodes
        if node.get("tag") == "div" and node.get("role") == "navigation"
    )
    card_list = next(node for node in nodes if node.get("tag") == "ul")
    assert nav["semanticHints"]["landmark"] == "nav"
    assert nav["semanticHints"]["ariaLabel"] == "Primary"
    assert role_nav["semanticHints"]["ariaRole"] == "navigation"
    assert card_list["semanticHints"]["listType"] == "unordered"


def test_table_cells_never_classify_as_cards() -> None:
    nodes = _capture_fixture()
    result = classify_semantic_components(nodes)
    table_indices = {
        index
        for index, node in enumerate(nodes)
        if str(node.get("tag") or "").lower() in {"table", "thead", "tbody", "tfoot", "tr", "td", "th"}
    }

    for item in result["components"]:
        if item["role"] != "card":
            continue
        assert not set(item["sourceDomIndices"]) & table_indices


def _node(tag: str, index: int, *, parent: int | None = None, **values) -> dict:
    node = {
        "tag": tag,
        "x": index * 20,
        "y": 0,
        "w": 100,
        "h": 40,
        "interactive": tag in {"a", "button", "input"},
    }
    if parent is not None:
        node["pIdx"] = parent
    node.update(values)
    return node


def test_table_links_and_icon_list_items_do_not_become_navigation_or_cards() -> None:
    nodes = [
        _node("table", 0, w=600, h=200),
        _node("tr", 1, parent=0, w=600, h=40),
        _node("td", 2, parent=1, w=200, h=40),
        _node("a", 3, parent=2, text="One"),
        _node("td", 4, parent=1, x=200, w=200, h=40),
        _node("a", 5, parent=4, text="Two"),
        _node("td", 6, parent=1, x=400, w=200, h=40),
        _node("a", 7, parent=6, text="Three"),
        _node("ul", 8, y=100, w=600, h=120, clsAll="nav-menu"),
        _node("li", 9, parent=8, y=100, w=600, h=40),
        _node("img", 10, parent=9, x=10, y=110, w=64, h=64),
        _node("span", 11, parent=9, x=40, y=112, w=80, h=20, text="Icon label"),
    ]

    result = classify_semantic_components(nodes)
    roles = Counter(item["role"] for item in result["components"])

    assert roles["navigation"] == 0
    assert roles["card"] == 0


def test_button_link_row_is_not_inferred_as_navigation() -> None:
    nodes = [_node("div", 0, w=700, h=60)]
    for index in range(1, 4):
        nodes.append(
            _node(
                "a",
                index,
                parent=0,
                x=(index - 1) * 220,
                y=10,
                w=200,
                h=40,
                text=f"CTA {index}",
                bg="rgb(31, 102, 239)",
                borderTopWidth=1,
                borderLeftWidth=1,
            )
        )

    result = classify_semantic_components(nodes)

    assert not any(item["role"] == "navigation" for item in result["components"])
    assert sum(item["role"] == "button" for item in result["components"]) == 3


def test_wrapper_around_explicit_nav_does_not_add_duplicate_navigation() -> None:
    nodes = [_node("div", 0, w=700, h=60), _node("nav", 1, parent=0, w=700, h=60)]
    for index in range(2, 5):
        nodes.append(
            _node(
                "a",
                index,
                parent=1,
                x=(index - 2) * 160,
                y=10,
                w=140,
                h=24,
                text=f"Nav {index}",
            )
        )

    result = classify_semantic_components(nodes)

    assert sum(item["role"] == "navigation" for item in result["components"]) == 1
