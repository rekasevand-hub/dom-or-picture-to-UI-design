"""Suppression split (Phase 3a): a suppressed owner's leftover text survives.

When one text owner is suppressed in favour of an overlapping owner, the
suppressed text may carry visible copy beyond the replacement — the classic
shape is a merged title+subtitle label replaced by the subtitle alone, which
used to silently drop the title (``本期好价`` in the dark-card-grid family).
The scene planner now splits that leftover into a derived owner on the
uncovered part of the suppressed box, and the emission audit accepts such a
suppression only while the split owner really survives.
"""

from __future__ import annotations

import copy

from src.app.services.structure.fidelity.emission_contract import audit_emission
from src.app.services.structure.fidelity.scene_plan import (
    _split_remaining_bbox,
    _suppressed_leftover_text,
    build_scene_plan,
)


def _graph() -> dict:
    return {
        "image": "fixture.png",
        "image_w": 800,
        "image_h": 600,
        "route": "grounding",
        "containers": [],
        "elements": [],
        "tables": [],
        "provenance": {"route": "grounding"},
    }


def _geometry() -> dict:
    return {
        "schema_version": "grounding-geometry-manifest/1.0",
        "image_size": [800, 600],
        "coordinate_basis": "source-pixel-top-left",
        "items": [
            {
                "id": "geometry:page",
                "kind": "page",
                "role": "page",
                "bbox": [0, 0, 800, 600],
                "content_ref": None,
            },
        ],
    }


def _inventory(merged: dict, subtitle: dict) -> dict:
    return {
        "schema_version": "grounding-content-inventory/1.0",
        "image_size": [800, 600],
        "items": [merged, subtitle],
        "tables": [],
    }


def _merged_owner() -> dict:
    return {
        "id": "text:merged",
        "kind": "text",
        "text": "本期好价 折扣都按官方价实时算",
        "bbox": [90, 486, 509, 72],
        "role": "",
        "source_ref": "graph.elements[16]",
        "authority": "ocr",
    }


def _subtitle_owner() -> dict:
    return {
        "id": "text:subtitle",
        "kind": "text",
        "text": "折扣都按官方价实时算",
        "bbox": [321, 513, 590, 32],
        "role": "",
        "source_ref": "graph.elements[17]",
        "authority": "grounding",
    }


def test_suppressed_merged_owner_splits_leftover_text() -> None:
    plan = build_scene_plan(
        _graph(),
        _inventory(_merged_owner(), _subtitle_owner()),
        _geometry(),
    )

    split = next(
        (node for node in plan["nodes"] if str(node["content_ref"]).endswith(":split")),
        None,
    )
    assert split is not None, "leftover text must survive as a derived owner"
    assert split["text"] == "本期好价"
    # The subtitle sits right of the merged box centre: the leftover keeps the
    # left band [90, 486, 321-90, 72].
    assert split["bbox"] == [90, 486, 231, 72]

    record = next(
        row
        for row in plan["suppressed"]
        if row["content_ref"] == "text:merged"
    )
    assert record["reason"] == "overlapping-text-owner-split"
    assert record["split_ref"] == split["content_ref"]
    assert record["leftover_text"] == "本期好价"
    # The subtitle owner survives untouched.
    assert any(
        node["content_ref"] == "text:subtitle" for node in plan["nodes"]
    )


def test_split_uses_right_band_when_replacement_sits_left() -> None:
    # The replacement text is a *prefix* of the merged text, so the leftover
    # sits on the side the replacement occupies (left) and the split keeps
    # the right band.  Prefix containment keeps the OCR-variant similarity
    # at exactly 0.8 so the suppression (and thus the split) fires.
    merged = {
        "id": "text:merged",
        "kind": "text",
        "text": "底部说明文字和标题",
        "bbox": [100, 100, 600, 60],
        "role": "",
        "source_ref": "graph.elements[0]",
        "authority": "ocr",
    }
    subtitle = {
        "id": "text:subtitle",
        "kind": "text",
        "text": "底部说明文字",
        "bbox": [120, 115, 200, 30],
        "role": "",
        "source_ref": "graph.elements[1]",
        "authority": "grounding",
    }
    plan = build_scene_plan(_graph(), _inventory(merged, subtitle), _geometry())

    split = next(
        node for node in plan["nodes"] if str(node["content_ref"]).endswith(":split")
    )
    assert split["text"] == "和标题"
    # Replacement on the left: leftover keeps the right band.
    assert split["bbox"] == [320, 100, 380, 60]


def test_equivalent_suppression_does_not_split() -> None:
    merged = {
        "id": "text:a",
        "kind": "text",
        "text": "相同文本",
        "bbox": [100, 100, 200, 40],
        "role": "",
        "source_ref": "graph.elements[0]",
        "authority": "ocr",
    }
    duplicate = {
        "id": "text:b",
        "kind": "text",
        "text": "相同文本",
        "bbox": [105, 102, 200, 40],
        "role": "",
        "source_ref": "graph.elements[1]",
        "authority": "grounding",
    }
    plan = build_scene_plan(_graph(), _inventory(merged, duplicate), _geometry())

    # Equivalent texts are deduplicated earlier (duplicate-text-owner); no
    # leftover exists, so no split owner may appear.
    assert not any(
        str(node["content_ref"]).endswith(":split") for node in plan["nodes"]
    )
    assert len(
        [node for node in plan["nodes"] if node.get("text") == "相同文本"]
    ) == 1


def test_single_character_leftover_does_not_split() -> None:
    merged = {
        "id": "text:a",
        "kind": "text",
        "text": "5.80 元",
        "bbox": [100, 100, 200, 40],
        "role": "",
        "source_ref": "graph.elements[0]",
        "authority": "ocr",
    }
    replacement = {
        "id": "text:b",
        "kind": "text",
        "text": "5.80",
        "bbox": [105, 102, 100, 40],
        "role": "",
        "source_ref": "graph.elements[1]",
        "authority": "grounding",
    }
    plan = build_scene_plan(_graph(), _inventory(merged, replacement), _geometry())

    # Leftover "元" is a single character: keep the plain suppression.
    assert not any(
        str(node["content_ref"]).endswith(":split") for node in plan["nodes"]
    )


def test_noise_variant_without_containment_does_not_split() -> None:
    # The pre-existing OCR-noise behaviour ('执行#间' vs '执行时间') must not
    # change: no containment, no leftover, plain suppression.
    noisy = {
        "id": "text:noise",
        "kind": "text",
        "text": "执行#间",
        "bbox": [30, 96, 100, 20],
        "role": "",
        "source_ref": "graph.elements[0]",
        "authority": "ocr",
    }
    clean = {
        "id": "text:clean",
        "kind": "text",
        "text": "执行时间",
        "bbox": [20, 88, 170, 40],
        "role": "",
        "source_ref": "graph.elements[1]",
        "authority": "image-enrichment",
    }
    plan = build_scene_plan(_graph(), _inventory(noisy, clean), _geometry())

    assert not any(
        str(node["content_ref"]).endswith(":split") for node in plan["nodes"]
    )
    assert any(
        row["content_ref"] == "text:noise"
        and row["reason"] == "overlapping-text-owner"
        for row in plan["suppressed"]
    )


def test_split_remaining_bbox_prefers_dominant_axis() -> None:
    # Vertical stacking: replacement in the lower half splits off the top band.
    assert _split_remaining_bbox([0, 0, 100, 100], [10, 60, 80, 20]) == [
        0,
        0,
        100,
        60,
    ]
    # Horizontal side-by-side: replacement right splits off the left band.
    assert _split_remaining_bbox([0, 0, 100, 100], [60, 40, 30, 20]) == [
        0,
        0,
        60,
        100,
    ]


def test_leftover_text_requires_containment_with_margin() -> None:
    assert (
        _suppressed_leftover_text("本期好价 折扣都按官方价实时算", "折扣都按官方价实时算")
        == "本期好价"
    )
    assert _suppressed_leftover_text("相同文本", "相同文本") == ""
    assert _suppressed_leftover_text("abc", "xyz") == ""
    assert _suppressed_leftover_text("5.80 元", "5.80") == ""
    assert _suppressed_leftover_text("", "x") == ""


def _design_with_split(plan: dict) -> dict:
    return {
        "elements": [
            {
                "contentRef": node["content_ref"],
                "type": str(node["type"]),
                "text": str(node.get("text") or ""),
            }
            for node in plan["nodes"]
            if node.get("type") in {"text", "control"}
        ]
    }


def _quality_with_split(plan: dict) -> dict:
    return {
        "owners": [
            {"contentRef": node["content_ref"], "status": "pass"}
            for node in plan["nodes"]
            if node.get("type") == "text"
        ]
    }


def test_audit_accepts_split_suppression_while_leftover_survives() -> None:
    inventory = _inventory(_merged_owner(), _subtitle_owner())
    plan = build_scene_plan(_graph(), inventory, _geometry())
    report = audit_emission(
        inventory=inventory,
        scene_plan=plan,
        design=_design_with_split(plan),
        quality=_quality_with_split(plan),
    )

    split_violations = [
        violation
        for violation in report.get("violations") or []
        if violation.get("contentRef") == "text:merged"
    ]
    assert not any(
        violation["type"] == "unequivalent-suppression"
        for violation in split_violations
    ), split_violations


def test_audit_flags_split_suppression_when_leftover_disappears() -> None:
    inventory = _inventory(_merged_owner(), _subtitle_owner())
    plan = build_scene_plan(_graph(), inventory, _geometry())
    # Drop the split node from every downstream layer: the suppression now
    # loses visible copy and the audit must flag it.
    broken = copy.deepcopy(plan)
    broken["nodes"] = [
        node
        for node in broken["nodes"]
        if not str(node["content_ref"]).endswith(":split")
    ]
    report = audit_emission(
        inventory=inventory,
        scene_plan=broken,
        design=_design_with_split(broken),
        quality=_quality_with_split(broken),
    )

    assert any(
        violation.get("type") == "unequivalent-suppression"
        and violation.get("contentRef") == "text:merged"
        for violation in report.get("violations") or []
    )
