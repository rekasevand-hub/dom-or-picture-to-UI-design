from __future__ import annotations

from pathlib import Path

from playwright.sync_api import sync_playwright

from src.app.services.structure.capture import DOM_JS
from src.app.services.structure.component_patterns import (
    infer_component_patterns,
)
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


def _component(role: str, index: int, *, confidence: float = 0.9) -> dict:
    return {
        "id": f"semantic-n{index}",
        "role": role,
        "confidence": confidence,
        "sourceDomIndices": [index],
        "bbox": [0, 0, 1, 1],
        "evidence": [{"kind": "test", "value": role, "weight": 1.0}],
    }


def _list_case(*, gaps: tuple[int, int] = (24, 24), positions: tuple[str, ...] = ("static", "static", "static")) -> tuple[list[dict], dict]:
    nodes = [
        {
            "tag": "section",
            "x": 0,
            "y": 0,
            "w": 620,
            "h": 220,
            "role": "list",
        }
    ]
    x = 0
    for index, gap in enumerate(gaps, start=1):
        nodes.append(
            {
                "tag": "article",
                "x": x,
                "y": 10,
                "w": 180,
                "h": 190,
                "pIdx": 0,
                "position": positions[index - 1],
            }
        )
        x += 180 + gap
    nodes.extend(
        [
            {"tag": "img", "x": 0, "y": 0, "w": 80, "h": 50, "pIdx": 1},
            {"tag": "h2", "x": 0, "y": 60, "w": 160, "h": 24, "pIdx": 1, "text": "A"},
            {"tag": "p", "x": 0, "y": 90, "w": 160, "h": 20, "pIdx": 1, "text": "A body"},
            {"tag": "a", "x": 0, "y": 120, "w": 80, "h": 20, "pIdx": 1, "text": "More", "interactive": True},
            {"tag": "img", "x": 0, "y": 0, "w": 80, "h": 50, "pIdx": 2},
            {"tag": "h2", "x": 0, "y": 60, "w": 160, "h": 24, "pIdx": 2, "text": "B"},
            {"tag": "p", "x": 0, "y": 90, "w": 160, "h": 20, "pIdx": 2, "text": "B body"},
            {"tag": "a", "x": 0, "y": 120, "w": 80, "h": 20, "pIdx": 2, "text": "More", "interactive": True},
            {"tag": "img", "x": 0, "y": 0, "w": 80, "h": 50, "pIdx": 3},
            {"tag": "h2", "x": 0, "y": 60, "w": 160, "h": 24, "pIdx": 3, "text": "C"},
            {"tag": "p", "x": 0, "y": 90, "w": 160, "h": 20, "pIdx": 3, "text": "C body"},
            {"tag": "a", "x": 0, "y": 120, "w": 80, "h": 20, "pIdx": 3, "text": "More", "interactive": True},
        ]
    )
    semantic = {
        "schema_version": "dom-semantic-components/1.0",
        "components": [
            _component("list", 0, confidence=0.98),
            _component("card", 1),
            _component("card", 2),
            _component("card", 3),
        ],
        "roleCounts": {"list": 1, "card": 3},
        "unknownCount": 0,
    }
    return nodes, semantic


def test_infers_repeated_list_card_and_button_groups() -> None:
    nodes = _capture_fixture()
    semantic = classify_semantic_components(nodes)

    patterns = infer_component_patterns(nodes, semantic)

    assert patterns["schema_version"] == "dom-component-patterns/1.0"
    list_group = patterns["groups"]["list-0"]
    assert list_group["role"] == "list"
    assert len(list_group["members"]) == 3
    assert list_group["axis"] == "x"
    assert list_group["gap"] == 24

    card_group = patterns["groups"]["card-set-0"]
    assert len(card_group["members"]) == 3
    assert card_group["structuralSignature"] == "visual:1|text:2|interactive:1"

    button_group = patterns["groups"]["button-set-0"]
    assert len(button_group["members"]) == 2

    cards = [
        item
        for item in patterns["components"]
        if item["role"] == "card"
        and item["sourceDomIndices"] == card_group["members"][:1]
    ][0]
    assert cards["groupId"] == "card-set-0"
    assert cards["groupRole"] == "card"
    assert cards["memberIndex"] == 0
    assert cards["memberCount"] == 3
    assert cards["structuralSignature"] == "visual:1|text:2|interactive:1"


def test_rejects_inconsistent_spacing_and_position_modes() -> None:
    nodes, semantic = _list_case(gaps=(24, 28))
    uneven = infer_component_patterns(nodes, semantic)
    assert "list-0" not in uneven["groups"]
    assert "card-set-0" not in uneven["groups"]

    nodes, semantic = _list_case(positions=("static", "absolute", "static"))
    mixed_position = infer_component_patterns(nodes, semantic)
    assert "list-0" not in mixed_position["groups"]


def test_rejects_mixed_roles_and_only_two_generic_boxes() -> None:
    nodes, semantic = _list_case()
    semantic["components"][2]["role"] = "button"
    mixed_roles = infer_component_patterns(nodes, semantic)
    assert "list-0" not in mixed_roles["groups"]
    assert "card-set-0" not in mixed_roles["groups"]

    generic_nodes = [
        {"tag": "div", "x": 0, "y": 0, "w": 100, "h": 40},
        {"tag": "div", "x": 124, "y": 0, "w": 100, "h": 40},
    ]
    generic_semantic = {
        "schema_version": "dom-semantic-components/1.0",
        "components": [_component("unknown", 0), _component("unknown", 1)],
        "roleCounts": {"unknown": 2},
        "unknownCount": 2,
    }
    generic = infer_component_patterns(generic_nodes, generic_semantic)
    assert generic["groups"] == {}


def test_duplicate_bounds_keep_the_strongest_explicit_semantic_evidence() -> None:
    nodes = [
        {"tag": "a", "x": 20, "y": 20, "w": 120, "h": 40},
    ]
    semantic = {
        "schema_version": "dom-semantic-components/1.0",
        "components": [
            {
                **_component("link", 0),
                "evidence": [{"kind": "tag", "value": "a", "weight": 0.4}],
            },
            {
                **_component("button", 0, confidence=0.96),
                "evidence": [{"kind": "tag", "value": "button", "weight": 1.0}],
            },
        ],
        "roleCounts": {"link": 1, "button": 1},
        "unknownCount": 0,
    }

    patterns = infer_component_patterns(nodes, semantic)

    assert len(patterns["components"]) == 1
    assert patterns["components"][0]["role"] == "button"


def test_repeated_controls_allow_width_variation_with_cross_axis_overlap() -> None:
    nodes = [
        {"tag": "div", "x": 0, "y": 0, "w": 500, "h": 80},
        {"tag": "button", "x": 0, "y": 20, "w": 100, "h": 40, "pIdx": 0, "text": "A"},
        {"tag": "button", "x": 124, "y": 20, "w": 140, "h": 40, "pIdx": 0, "text": "B"},
        {"tag": "button", "x": 288, "y": 20, "w": 110, "h": 40, "pIdx": 0, "text": "C"},
    ]
    semantic = {
        "schema_version": "dom-semantic-components/1.0",
        "components": [
            {**_component("button", 1), "bbox": [0, 20, 100, 40]},
            {**_component("button", 2), "bbox": [124, 20, 140, 40]},
            {**_component("button", 3), "bbox": [288, 20, 110, 40]},
        ],
        "roleCounts": {"button": 3},
        "unknownCount": 0,
    }

    patterns = infer_component_patterns(nodes, semantic)

    assert len(patterns["groups"]["button-set-0"]["members"]) == 3


def test_repeated_controls_reject_low_cross_axis_overlap() -> None:
    nodes = [
        {"tag": "div", "x": 0, "y": 0, "w": 500, "h": 100},
        {"tag": "button", "x": 0, "y": 0, "w": 100, "h": 40, "pIdx": 0, "text": "A"},
        {"tag": "button", "x": 124, "y": 30, "w": 100, "h": 40, "pIdx": 0, "text": "B"},
        {"tag": "button", "x": 248, "y": 0, "w": 100, "h": 40, "pIdx": 0, "text": "C"},
    ]
    semantic = {
        "schema_version": "dom-semantic-components/1.0",
        "components": [
            {**_component("button", 1), "bbox": [0, 0, 100, 40]},
            {**_component("button", 2), "bbox": [124, 30, 100, 40]},
            {**_component("button", 3), "bbox": [248, 0, 100, 40]},
        ],
        "roleCounts": {"button": 3},
        "unknownCount": 0,
    }

    patterns = infer_component_patterns(nodes, semantic)

    assert "button-set-0" not in patterns["groups"]
