"""Regression tests for the inventory emission contract.

These lock down the two defects that made critical text disappear without a
named blocker: geometric-overlap suppression of *different* text, and silent
skipping of native owners without measurable ink evidence.
"""

from __future__ import annotations

import copy
from typing import Any

import pytest

from src.app.services.structure.fidelity.emission_contract import (
    LEGACY_SUPPRESSION_ENV,
    SCHEMA_VERSION,
    UNMEASURABLE_STATUS,
    audit_emission,
    legacy_overlap_suppression_enabled,
    register_unmeasured_owners,
    suppression_allowed,
    suppression_text_equivalent,
)
from src.app.services.structure.fidelity.scene_plan import (
    _suppress_overlapping_text_owners,
)


def _inventory(items: list[dict[str, Any]]) -> dict[str, Any]:
    return {"items": items}


def _item(ref: str, text: str, kind: str = "text") -> dict[str, Any]:
    return {"id": ref, "kind": kind, "text": text, "bbox": [0, 0, 10, 10]}


def _plan(
    nodes: list[dict[str, Any]], suppressed: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    return {"nodes": nodes, "suppressed": suppressed or []}


def _node(ref: str, text: str) -> dict[str, Any]:
    return {"content_ref": ref, "type": "text", "text": text, "bbox": [0, 0, 10, 10]}


def _design(elements: list[dict[str, Any]]) -> dict[str, Any]:
    return {"elements": elements}


def _element(ref: str, text: str, kind: str = "text") -> dict[str, Any]:
    return {"contentRef": ref, "type": kind, "text": text}


def _quality(owners: list[dict[str, Any]], missing: list[str] | None = None):
    return {
        "owners": owners,
        "gate": {"criticalText": {"missing": missing or []}},
    }


def _owner(ref: str, text: str) -> dict[str, Any]:
    return {"contentRef": ref, "text": text, "status": "fail", "checks": {}}


# ---------------------------------------------------------------------------
# equivalence judgement
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("left", "right", "expected"),
    [
        ("数据看板", "数据看板", True),
        ("9 月 3 日创建", "9月3日创建", True),
        ("ＡＰＩ", "API", True),
        ("本期好价 折扣都按官方价实时算", "折扣都按官方价实时算", False),
        ("数据看板", "API 密钥", False),
        ("¥4.64", "DeepSeek V4.1 Flash", False),
        ("", "数据看板", False),
        ("数据看板", "", False),
    ],
)
def test_suppression_equivalence_is_strict(left: str, right: str, expected: bool):
    assert suppression_text_equivalent(left, right) is expected


def test_normalization_does_not_hide_a_lost_label():
    # Containment is deliberately NOT equivalence: the visible label
    # '本期好价' would otherwise be silently dropped.
    assert not suppression_text_equivalent(
        "本期好价 折扣都按官方价实时算", "折扣都按官方价实时算"
    )


@pytest.mark.parametrize(
    ("suppressed", "replacement", "expected"),
    [
        # Two different grounded labels must both survive.
        (
            {"text": "数据看板", "authority": "grounding"},
            {"text": "API 密钥", "authority": "grounding"},
            False,
        ),
        # A grounded label must not be replaced by a longer grounded string
        # that merely contains it.
        (
            {"text": "本期好价 折扣都按官方价实时算", "authority": "grounding"},
            {"text": "折扣都按官方价实时算", "authority": "grounding"},
            False,
        ),
        # Exact duplicates are safe to merge.
        (
            {"text": "社区", "authority": "grounding"},
            {"text": "社区 ", "authority": "grounding"},
            True,
        ),
        # OCR variants of the same string may be absorbed by the owner.
        (
            {"text": "执行#间", "authority": "ocr"},
            {"text": "执行时间", "authority": "image-enrichment"},
            True,
        ),
        (
            {"text": "Wauto用户身份执行", "authority": "ocr"},
            {"text": "auto用户身份执行", "authority": "grounding"},
            True,
        ),
        # An OCR row that reads as unrelated text is NOT a variant.
        (
            {"text": "钱包", "authority": "ocr"},
            {"text": "推荐官", "authority": "grounding"},
            False,
        ),
    ],
)
def test_suppression_allowed_separates_ocr_noise_from_real_labels(
    suppressed, replacement, expected
):
    assert suppression_allowed(suppressed, replacement) is expected


# ---------------------------------------------------------------------------
# audit
# ---------------------------------------------------------------------------


def test_clean_pipeline_passes_every_invariant():
    item = _item("text:a", "数据看板")
    report = audit_emission(
        inventory=_inventory([item]),
        scene_plan=_plan([_node("text:a", "数据看板")]),
        design=_design([_element("text:a", "数据看板")]),
        quality=_quality([_owner("text:a", "数据看板")]),
    )
    assert report["schema_version"] == SCHEMA_VERSION
    assert report["status"] == "pass"
    assert report["violations"] == []
    assert all(row["status"] == "pass" for row in report["invariants"])
    assert report["counts"]["textBearingItems"] == 1


def test_unequivalent_suppression_is_reported_with_its_replacement():
    report = audit_emission(
        inventory=_inventory([_item("text:a", "数据看板"), _item("text:b", "API 密钥")]),
        scene_plan=_plan(
            [_node("text:b", "API 密钥")],
            suppressed=[
                {
                    "content_ref": "text:a",
                    "reason": "overlapping-text-owner",
                    "replacement_ref": "text:b",
                }
            ],
        ),
        design=_design([_element("text:b", "API 密钥")]),
        quality=_quality(
            [_owner("text:b", "API 密钥")], missing=["数据看板"]
        ),
    )
    violation = next(
        row for row in report["violations"]
        if row["type"] == "unequivalent-suppression"
    )
    assert violation["contentRef"] == "text:a"
    assert violation["replacementText"] == "API 密钥"
    assert report["criticalMissingCorrelation"] == ["数据看板"]
    assert report["status"] == "violations-detected"


def test_equivalent_suppression_is_allowed():
    report = audit_emission(
        inventory=_inventory([_item("text:a", "社区"), _item("text:b", "社区")]),
        scene_plan=_plan(
            [_node("text:b", "社区")],
            suppressed=[
                {
                    "content_ref": "text:a",
                    "reason": "control-value-owner-authoritative",
                    "replacement_ref": "text:b",
                }
            ],
        ),
        design=_design([_element("text:b", "社区")]),
        quality=_quality([_owner("text:b", "社区")]),
    )
    assert report["status"] == "pass"


def test_missing_replacement_and_unaccounted_item_are_separate_defects():
    report = audit_emission(
        inventory=_inventory([_item("text:a", "钱包"), _item("text:b", "概览")]),
        scene_plan=_plan(
            [], suppressed=[{"content_ref": "text:a", "replacement_ref": "text:gone"}]
        ),
        design=_design([]),
        quality=_quality([]),
    )
    types = {row["type"] for row in report["violations"]}
    assert "suppression-replacement-missing" in types
    assert "unaccounted-inventory-item" in types


def test_unregistered_native_owner_is_not_silent():
    report = audit_emission(
        inventory=_inventory([_item("text:a", "复制模型 ID", kind="control")]),
        scene_plan=_plan([_node("text:a", "复制模型 ID")]),
        design=_design([_element("text:a", "复制模型 ID", kind="button")]),
        quality=_quality([], missing=["复制模型 ID"]),
    )
    violation = next(
        row for row in report["violations"]
        if row["type"] == "unregistered-native-owner"
    )
    assert violation["contentRef"] == "text:a"
    assert "复制模型 ID" in report["criticalMissingCorrelation"]


def test_duplicate_emission_is_detected_per_layer():
    report = audit_emission(
        inventory=_inventory([_item("text:a", "状态")]),
        scene_plan=_plan([_node("text:a", "状态")]),
        design=_design([_element("text:a", "状态"), _element("text:a", "状态")]),
        quality=_quality([_owner("text:a", "状态")]),
    )
    duplicates = [
        row for row in report["violations"] if row["type"] == "duplicate-emission"
    ]
    assert duplicates and duplicates[0]["layer"] == "designElements"
    assert report["invariants"][0]["status"] == "fail"


def test_asset_items_are_not_counted_as_text_bearing():
    report = audit_emission(
        inventory=_inventory([{"id": "asset:a", "kind": "asset", "text": ""}]),
        scene_plan=_plan([{"content_ref": "asset:a", "type": "image", "text": ""}]),
        design=_design([{"contentRef": "asset:a", "type": "image", "text": ""}]),
        quality=_quality([]),
    )
    assert report["counts"]["textBearingItems"] == 0
    assert report["status"] == "pass"


# ---------------------------------------------------------------------------
# registration repair (diagnostic copy)
# ---------------------------------------------------------------------------


def test_registration_repair_adds_owners_without_recomputing_gate():
    quality = _quality([_owner("text:a", "状态")], missing=["复制模型 ID"])
    design = _design(
        [
            _element("text:a", "状态"),
            _element("text:b", "复制模型 ID", kind="button"),
        ]
    )
    readback = {
        "type": "FRAME",
        "children": [{"type": "TEXT", "characters": "复制模型 ID"}],
    }
    repaired, summary = register_unmeasured_owners(quality, design, readback)
    assert summary["addedCount"] == 1
    assert summary["gateRecomputed"] is False
    assert repaired["registrationRepair"]["gateRecomputed"] is False
    added = repaired["owners"][-1]
    assert added["status"] == UNMEASURABLE_STATUS
    assert added["nativeText"] is True
    assert "checks" not in added
    # The original object must be untouched.
    assert len(quality["owners"]) == 1
    assert repaired["gate"] == quality["gate"]


def test_registration_repair_without_readback_does_not_guess_native_text():
    repaired, summary = register_unmeasured_owners(
        _quality([]), _design([_element("text:b", "钱包")]), None
    )
    assert summary["addedCount"] == 1
    assert repaired["owners"][-1]["nativeText"] is None


def test_registration_repair_does_not_duplicate_existing_owners():
    quality = _quality([_owner("text:a", "状态")])
    repaired, summary = register_unmeasured_owners(
        quality, _design([_element("text:a", "状态")]), None
    )
    assert summary["addedCount"] == 0
    assert len(repaired["owners"]) == 1


# ---------------------------------------------------------------------------
# scene planner uses the same equivalence criterion
# ---------------------------------------------------------------------------


def _text_node(ref: str, text: str, bbox: list[int]) -> dict[str, Any]:
    return {
        "id": ref,
        "content_ref": ref,
        "type": "text",
        "role": "",
        "authority": "grounding",
        "text": text,
        "bbox": bbox,
        "source_ref": f"graph.elements[{ref}]",
        "children": [],
    }


def test_planner_keeps_different_text_even_when_boxes_overlap(monkeypatch):
    monkeypatch.delenv(LEGACY_SUPPRESSION_ENV, raising=False)
    first = _text_node("text:a", "API 密钥", [0, 0, 100, 20])
    second = _text_node("text:b", "数据看板", [0, 0, 100, 20])
    suppressed: list[dict[str, Any]] = []
    kept = _suppress_overlapping_text_owners([first, second], suppressed)
    assert {node["content_ref"] for node in kept} == {"text:a", "text:b"}
    assert suppressed == []


def test_planner_still_merges_equivalent_text(monkeypatch):
    monkeypatch.delenv(LEGACY_SUPPRESSION_ENV, raising=False)
    first = _text_node("text:a", "社区", [0, 0, 100, 20])
    second = _text_node("text:b", "社区 ", [0, 0, 100, 20])
    suppressed: list[dict[str, Any]] = []
    kept = _suppress_overlapping_text_owners([first, second], suppressed)
    assert len(kept) == 1
    assert suppressed and suppressed[0]["reason"] == "overlapping-text-owner"


def test_planner_absorbs_ocr_variant_but_keeps_grounded_labels(monkeypatch):
    monkeypatch.delenv(LEGACY_SUPPRESSION_ENV, raising=False)
    header = _text_node("table-header:time", "执行时间", [0, 0, 100, 20])
    header["authority"] = "image-enrichment"
    noise = _text_node("text:ocr-noise", "执行#间", [0, 0, 100, 20])
    noise["authority"] = "ocr"
    label = _text_node("text:label", "数据看板", [0, 0, 100, 20])
    suppressed: list[dict[str, Any]] = []
    kept = _suppress_overlapping_text_owners([header, noise, label], suppressed)
    refs = {node["content_ref"] for node in kept}
    assert "table-header:time" in refs
    assert "text:label" in refs
    assert "text:ocr-noise" not in refs


def test_legacy_flag_reproduces_old_behaviour(monkeypatch):
    monkeypatch.setenv(LEGACY_SUPPRESSION_ENV, "1")
    assert legacy_overlap_suppression_enabled() is True
    first = _text_node("text:a", "API 密钥", [0, 0, 100, 20])
    second = _text_node("text:b", "数据看板", [0, 0, 100, 20])
    suppressed: list[dict[str, Any]] = []
    kept = _suppress_overlapping_text_owners([first, second], suppressed)
    assert len(kept) == 1
    assert suppressed[0]["content_ref"] in {"text:a", "text:b"}


def test_audit_does_not_mutate_inputs():
    inventory = _inventory([_item("text:a", "数据看板")])
    plan = _plan([_node("text:a", "数据看板")])
    design = _design([_element("text:a", "数据看板")])
    quality = _quality([_owner("text:a", "数据看板")])
    snapshots = tuple(copy.deepcopy(x) for x in (inventory, plan, design, quality))
    audit_emission(
        inventory=inventory, scene_plan=plan, design=design, quality=quality
    )
    assert (inventory, plan, design, quality) == snapshots
