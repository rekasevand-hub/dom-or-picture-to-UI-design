from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = REPO_ROOT / "tests" / "fixtures" / "fixed_canvas_mentor_contract.json"
LIVE_AUDIT_PATH = (
    REPO_ROOT
    / "output"
    / "_mentor_distillation_round2"
    / "agent_outputs"
    / "FLEXWEAVER"
    / "candidate_audit.json"
)


def _contract() -> dict:
    return json.loads(CONTRACT_PATH.read_text("utf-8"))


def test_mentor_contract_requires_unique_occurrence_ownership() -> None:
    contract = _contract()
    owners = contract["owner_contract"]

    assert owners["declared_owners"] == owners["mapped_owners"] == 138
    assert owners["missing_nodes"] == 0
    assert owners["type_mismatches"] == 0
    assert owners["declared_text_owners"] == owners["live_text_nodes"] == 79
    assert owners["text_value_mismatches"] == 0


def test_mentor_contract_keeps_structural_table_identity() -> None:
    table = _contract()["table_contract"]

    assert table["header_cells"] == 7
    assert table["visible_body_rows"] == 5
    assert table["body_cells"] == 35
    assert set(table["repeated_values"]) == {"auto", "2"}


def test_mentor_contract_rejects_duplicate_owner_and_underlay() -> None:
    contract = _contract()

    assert contract["duplicate_contract"]["overlapping_text_owners"] == 0
    structure = contract["native_structure"]
    assert structure["image_fill_names"] == [
        "logo_tetuo_auto",
        "account_avatar",
    ]
    assert structure["full_screenshot_underlay"] is False
    assert structure["fixed_size_text_allowed"] is True
    assert structure["auto_resize_required"] is False


def test_mentor_contract_regions_and_global_visual_thresholds() -> None:
    visual = _contract()["visual_contract"]

    assert visual["within30_pct"] >= 90.0
    assert visual["bad_pixel_ratio"] <= 0.05
    assert all(ratio <= 0.05 for ratio in visual["truth_regions"].values())


def test_mentor_contract_uses_font_priors_not_global_hardcoding() -> None:
    style = _contract()["style_priors"]

    assert style["cjk_family"] == "Noto Sans SC"
    assert style["latin_family"] == "Open Sans"
    assert style["table_header"]["alignment"] == "center"
    assert style["table_body"]["alignment"] == "left"


def test_live_audit_matches_contract_when_retained() -> None:
    if not LIVE_AUDIT_PATH.is_file():
        return
    audit = json.loads(LIVE_AUDIT_PATH.read_text("utf-8"))
    contract = _contract()

    assert audit["manifest"]["owners_present"] == 138
    assert audit["manifest"]["live_text_nodes"] == 79
    assert audit["duplicate_audit"]["rendered_text_overlap_count"] == 0
    assert (
        audit["visual"]["within30_pct"] == contract["visual_contract"]["within30_pct"]
    )
