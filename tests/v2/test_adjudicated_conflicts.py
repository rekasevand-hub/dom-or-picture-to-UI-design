from __future__ import annotations

import json
from pathlib import Path

from src.app.services.structure.fidelity.calibration_strategies import (
    CalibrationContext,
    _adjudicated_conflicts,
)
from src.app.services.structure.fidelity.text_calibration import (
    apply_adjudicated_conflicts,
)


def _design(text: str = "工时管理", x: float = 35.0, y: float = 134.0) -> dict:
    return {
        "elements": [
            {
                "type": "text",
                "contentRef": "text:owner",
                "text": text,
                "x": x,
                "y": y,
                "width": 100.0,
                "height": 30.0,
            }
        ]
    }


def _move_decision(agreement: bool) -> dict:
    return {
        "kept": "工时管理",
        "conflict": "输入关键字过滤菜单",
        "bbox": [35.0, 134.0, 146.0, 157.0],
        "agreement": agreement,
        "status": "move",
        "move_text": "工时管理",
        "move_to": [77.6, 290.0, 184.4, 38.2],
    }


def test_benchmark_keyed_decision_file_is_not_loaded(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """A decision file keyed by benchmark family name must never be picked up.

    The old branch parsed ``benchmark_families/<family>`` out of the image path
    and loaded ``output/_conflict_decisions/<family>.json``; that file carried
    gold-tree coordinates.  Keeping the file in place and still getting
    ``not-needed`` is the regression guard.
    """
    monkeypatch.chdir(tmp_path)
    family_dir = tmp_path / "benchmark_families" / "light-table"
    family_dir.mkdir(parents=True)
    image = family_dir / "reference.png"
    image.write_bytes(b"")

    decisions_dir = tmp_path / "output" / "_conflict_decisions"
    decisions_dir.mkdir(parents=True)
    (decisions_dir / "light-table.json").write_text(
        json.dumps(
            {
                "decisions": [
                    {
                        "status": "apply",
                        "drop": "工时管理",
                        "bbox": [0, 0, 10, 10],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    context = CalibrationContext(
        design=_design(),
        image=str(image),
        run_root=tmp_path / "run",
        readback={},
        ocr_supplement={},
    )

    _, report = _adjudicated_conflicts(context)

    assert report["status"] == "not-needed"
    assert report["adjusted_count"] == 0


def test_run_scoped_decision_file_is_still_consumed(tmp_path: Path) -> None:
    run_root = tmp_path / "run"
    out_dir = run_root / "conflict_adjudication"
    out_dir.mkdir(parents=True)
    (out_dir / "decisions.json").write_text(
        json.dumps(
            {
                "decisions": [
                    {
                        "status": "apply",
                        "drop": "工时管理",
                        "bbox": [35.0, 134.0, 146.0, 157.0],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    context = CalibrationContext(
        design=_design(),
        image=str(tmp_path / "reference.png"),
        run_root=run_root,
        readback={},
        ocr_supplement={},
    )

    design, report = _adjudicated_conflicts(context)

    assert report["status"] == "applied"
    assert design["elements"] == []


def test_move_is_ignored_unless_the_adjudicator_agreed() -> None:
    """Four critical labels were relocated on ``status == "move"`` alone."""
    design, report = apply_adjudicated_conflicts(
        _design(), [_move_decision(agreement=False)]
    )

    assert design["elements"][0]["x"] == 35.0
    assert design["elements"][0]["y"] == 134.0
    assert report["status"] == "not-needed"
    assert report["adjusted_count"] == 0


def test_move_applies_when_the_adjudicator_agreed() -> None:
    design, report = apply_adjudicated_conflicts(
        _design(), [_move_decision(agreement=True)]
    )

    assert design["elements"][0]["x"] == 77.6
    assert design["elements"][0]["y"] == 290.0
    assert report["adjusted_count"] == 1
