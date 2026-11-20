"""The production gate: one exit, two artefacts, no silent pass.

Every design that leaves for a target goes through `design-ir/2.0`.  The files are
written before the target renders, so a failed emission still leaves the contract
behind; ``--strict-ir`` turns a violation into a stop, everything else records and
continues.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.app.services.contracts.production_gate import (  # noqa: E402
    IR_NAME,
    LEDGER_NAME,
    DesignIRGateError,
    gate_design_for_output,
)
from src.app.services.rendering.axure_route import plan_axure_route  # noqa: E402


def _design(*, with_layout: bool = True) -> dict:
    frame = {
        "id": "card:1",
        "type": "container",
        "role": "card",
        "x": 20,
        "y": 20,
        "width": 300,
        "height": 200,
        "style": {"fillColor": "#ffffff"},
    }
    if with_layout:
        frame["layout"] = {
            "mode": "VERTICAL",
            "itemSpacing": 12,
            "paddingTop": 8,
            "source": "geometry",
        }
        frame["layoutChildren"] = [{"id": "t1"}, {"id": "t2"}]
    return {
        "name": "gate fixture",
        "canvas": {"width": 340, "height": 240, "background": "#f5f5f5"},
        "elements": [
            frame,
            {
                "id": "t1",
                "type": "text",
                "x": 32,
                "y": 32,
                "width": 120,
                "height": 20,
                "text": "第一行",
                "style": {"fontSize": 14, "textColor": "#111111"},
            },
            {
                "id": "t2",
                "type": "text",
                "x": 32,
                "y": 64,
                "width": 160,
                "height": 20,
                "text": "第二行",
                "style": {"fontSize": 14, "textColor": "#111111"},
            },
        ],
    }


def test_the_gate_writes_both_artefacts(tmp_path: Path) -> None:
    report = gate_design_for_output(
        _design(), target="axure", source_kind="image", out_dir=tmp_path
    )

    assert report["status"] == "pass"
    assert (tmp_path / IR_NAME).is_file()
    ledger = json.loads((tmp_path / LEDGER_NAME).read_text(encoding="utf-8"))
    assert ledger["target"] == "axure"
    assert ledger["status"] == "pass"
    # 帧带布局规格 → Axure 只能排固定坐标，这条必须记账。
    features = [row["feature"] for row in ledger["degradations"]]
    assert features == ["auto-layout"]
    assert "card:1" in ledger["degradations"][0]["source_node_ids"]
    # 目标端不支持但本稿没用到的能力也要列出来，空账本不能读成"没检查"。
    gaps = [row["feature"] for row in ledger["target_gaps"]]
    assert "clip" in gaps and "letter-spacing" in gaps


def test_figma_needs_nothing_degraded_but_still_lists_its_gaps(tmp_path: Path) -> None:
    report = gate_design_for_output(
        _design(), target="figma", source_kind="image", out_dir=tmp_path
    )

    ledger = json.loads((tmp_path / LEDGER_NAME).read_text(encoding="utf-8"))
    assert report["status"] == "pass"
    assert ledger["degradations"] == []
    assert ledger["can_claim_complete"] is True
    gaps = [row["feature"] for row in ledger["target_gaps"]]
    assert "multi-page" in gaps and "interaction" in gaps


def test_strict_mode_blocks_a_broken_contract(tmp_path: Path) -> None:
    design = _design()
    design["elements"][1]["width"] = 0  # invalid-geometry

    with pytest.raises(DesignIRGateError) as error:
        gate_design_for_output(
            design, target="figma", source_kind="image", out_dir=tmp_path, strict=True
        )

    assert "invalid-geometry" in str(error.value)
    # 阻断之前先把 IR 与账本落盘：证据不能因为失败而丢。
    assert (tmp_path / IR_NAME).is_file()
    ledger = json.loads((tmp_path / LEDGER_NAME).read_text(encoding="utf-8"))
    assert ledger["status"] == "invalid"


def test_a_non_strict_gate_records_and_continues(tmp_path: Path) -> None:
    design = _design()
    design["elements"][1]["width"] = 0

    report = gate_design_for_output(
        design, target="axure", source_kind="image", out_dir=tmp_path
    )

    assert report["status"] == "invalid"
    assert report["issues"]
    assert (tmp_path / LEDGER_NAME).is_file()


def test_an_ungated_target_is_not_dressed_up_as_passed(tmp_path: Path) -> None:
    report = gate_design_for_output(
        _design(), target="svg", source_kind="image", out_dir=tmp_path
    )

    assert report["status"] == "not-gated"
    assert not (tmp_path / IR_NAME).exists()


def test_the_gate_and_the_axure_route_share_one_ledger(tmp_path: Path) -> None:
    design = _design()
    route = plan_axure_route(design, source_kind="image")
    gate_design_for_output(
        design, target="axure", source_kind="image", out_dir=tmp_path, ir=route["ir"]
    )

    ledger = json.loads((tmp_path / LEDGER_NAME).read_text(encoding="utf-8"))
    assert ledger["degradations"] == route["degradations"]
    assert ledger["document_id"] == route["document_id"]
