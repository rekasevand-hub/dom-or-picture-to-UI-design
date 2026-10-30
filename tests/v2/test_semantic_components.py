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
