from __future__ import annotations

import json

from src.app.services.structure.semantic_merge import (
    build_semantic_components,
    merge_semantic_candidates,
    persist_semantic_components,
)


def _dom_component(
    role: str,
    bbox: list[int],
    *,
    explicit: bool = True,
    confidence: float = 0.95,
) -> dict:
    evidence = (
        [{"kind": "tag", "value": role, "weight": 1.0}]
        if explicit
        else [{"kind": "repeated-child-count", "value": 3, "weight": 1.0}]
    )
    return {
        "id": f"semantic-{role}",
        "role": role,
        "confidence": confidence,
        "sourceDomIndices": [4],
        "bbox": bbox,
        "evidence": evidence,
    }


def _semantic(*components: dict) -> dict:
    return {
        "schema_version": "dom-component-patterns/1.0",
        "components": list(components),
        "groups": {},
        "componentSignatures": {},
    }


def _external(
    role: str,
    bbox: list[int],
    *,
    candidate_id: str = "det-1",
    confidence: float = 0.92,
    title: str = "",
) -> dict:
    return {
        "id": candidate_id,
        "role": role,
        "bbox": bbox,
        "confidence": confidence,
        "source": "detector",
        **({"title": title} if title else {}),
    }


def test_detector_cannot_override_explicit_dom_link_with_button_guess() -> None:
    dom = _semantic(_dom_component("link", [10, 10, 100, 40]))

    result = merge_semantic_candidates(
        dom,
        [_external("button", [10, 10, 100, 40])],
    )

    component = result["components"][0]
    assert component["role"] == "link"
    assert component["authority"] == "dom-explicit"
    assert result["rejected"][0]["reason"] == "explicit-dom-role-conflict"


def test_detector_cannot_override_inferred_dom_navigation() -> None:
    dom = _semantic(
        _dom_component(
            "navigation",
            [0, 0, 500, 48],
            explicit=False,
            confidence=0.88,
        )
    )

    result = merge_semantic_candidates(
        dom,
        [_external("button", [0, 0, 500, 48])],
    )

    component = result["components"][0]
    assert component["role"] == "navigation"
    assert component["authority"] == "dom-inferred"


def test_detector_card_fills_unknown_dom_node_at_low_confidence() -> None:
    dom = _semantic(_dom_component("unknown", [10, 10, 100, 80], confidence=0.2))

    result = merge_semantic_candidates(
        dom,
        [_external("card", [10, 10, 100, 80], confidence=0.95)],
    )

    component = result["components"][0]
    assert component["role"] == "card"
    assert component["domRole"] == "unknown"
    assert component["authority"] == "detector-match"
    assert component["confidence"] <= 0.55


def test_exact_same_role_match_preserves_dom_authority_and_vlm_title_evidence() -> None:
    dom = _semantic(_dom_component("card", [20, 30, 180, 120]))

    result = merge_semantic_candidates(
        dom,
        [
            _external(
                "card",
                [20, 30, 180, 120],
                confidence=0.98,
                title="Featured story",
            )
        ],
    )

    component = result["components"][0]
    assert component["role"] == "card"
    assert component["authority"] == "dom-explicit"
    assert component["detectorMatch"] is True
    assert any(
        item.get("kind") == "detector-title"
        and item.get("value") == "Featured story"
        for item in component["evidence"]
    )


def test_partial_overlap_is_review_required_instead_of_merged() -> None:
    dom = _semantic(_dom_component("card", [10, 10, 100, 40]))

    result = merge_semantic_candidates(
        dom,
        [_external("card", [43, 10, 100, 40])],
    )

    assert result["components"][0]["role"] == "card"
    assert len(result["reviewRequired"]) == 1
    assert result["reviewRequired"][0]["authority"] == "review-required"
    assert result["reviewRequired"][0]["overlap"] < 0.94


def test_persists_deterministic_semantic_merge_artifact(tmp_path) -> None:
    dom = _semantic(
        _dom_component("card", [10, 10, 100, 80]),
        _dom_component("navigation", [0, 0, 300, 40], explicit=False),
    )
    result = merge_semantic_candidates(
        dom,
        [
            _external("card", [10, 10, 100, 80]),
            _external("button", [400, 20, 80, 40], candidate_id="det-only"),
        ],
    )

    path = persist_semantic_components(tmp_path, result)
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert path.name == "20_semantic_components.json"
    assert payload["schema_version"] == "dom-semantic-merge/1.0"
    assert payload["components"]
    assert payload["detectorOnly"]
    assert payload["merged"]
    assert payload["roleCounts"]
    assert payload["authorityCounts"]


def test_merge_preserves_pattern_groups_and_component_signatures() -> None:
    dom = _semantic(_dom_component("button", [10, 10, 100, 40]))
    dom["groups"] = {
        "button-set-0": {
            "id": "button-set-0",
            "role": "button",
            "members": [4, 5],
            "structuralSignature": "visual:0|text:1|interactive:0",
        }
    }
    dom["componentSignatures"] = {
        "button-set-0": "tag:button|role:button|visual:0|text:1|interactive:0"
    }

    result = merge_semantic_candidates(dom, [])

    assert result["groups"] == dom["groups"]
    assert result["componentSignatures"] == dom["componentSignatures"]


def test_semantic_pipeline_builds_component_artifact_from_dom(tmp_path) -> None:
    nodes = [
        {"tag": "div", "x": 0, "y": 0, "w": 320, "h": 80},
        {
            "tag": "button",
            "x": 20,
            "y": 20,
            "w": 100,
            "h": 40,
            "pIdx": 0,
            "text": "Save",
            "interactive": True,
        },
        {
            "tag": "button",
            "x": 140,
            "y": 20,
            "w": 100,
            "h": 40,
            "pIdx": 0,
            "text": "Cancel",
            "interactive": True,
        },
    ]

    result = build_semantic_components(nodes)
    path = persist_semantic_components(tmp_path, result)
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert "button-set-0" in payload["groups"]
    assert payload["componentSignatures"]
