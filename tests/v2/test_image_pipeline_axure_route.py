"""`--route physical --tool axure`: the production branch, end to end.

The image pipeline used to hand the design straight to the Axure adapter.  It now
goes through the IR gate first, then re-reads the emitted `.rp` with
`evidence.py` — the same两 checks the standalone script had, on the entry people
actually run.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def _script():
    path = _ROOT / "scripts/image_figma_mvp.py"
    spec = importlib.util.spec_from_file_location("image_figma_mvp_axure", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _design() -> dict:
    return {
        "name": "axure branch fixture",
        "canvas": {"width": 320, "height": 180, "background": "#f5f5f5"},
        "elements": [
            {
                "id": "card:1",
                "type": "container",
                "role": "card",
                "x": 20,
                "y": 20,
                "width": 280,
                "height": 140,
                "layout": {"mode": "VERTICAL", "itemSpacing": 10, "source": "geometry"},
                "layoutChildren": [{"id": "t1"}, {"id": "t2"}],
                "style": {"fillColor": "#ffffff"},
            },
            {
                "id": "t1",
                "type": "text",
                "x": 32,
                "y": 32,
                "width": 120,
                "height": 20,
                "text": "标题",
                "style": {"fontSize": 14, "textColor": "#111111"},
            },
            {
                "id": "t2",
                "type": "text",
                "x": 32,
                "y": 64,
                "width": 160,
                "height": 20,
                "text": "正文",
                "style": {"fontSize": 14, "textColor": "#333333"},
            },
        ],
    }


def test_the_axure_branch_gates_then_self_checks(tmp_path: Path) -> None:
    module = _script()
    module._write_json(tmp_path / "figma_design.json", _design())
    gate = module._gate(
        dsn=_design(),
        output=tmp_path,
        tool="axure",
        strict=False,
        source_kind="image",
        reference=None,
    )

    code = module._emit_axure(
        design=_design(),
        output=tmp_path,
        sample_id="fixture",
        gate=gate,
        generate_twice=True,
        strict=False,
    )

    assert code == 0
    assert (tmp_path / "prototype.rp").is_file()
    assert (tmp_path / "prototype.repeat.rp").is_file()
    assert (tmp_path / "13_design_ir.json").is_file()
    assert (tmp_path / "13_degradations.json").is_file()
    report = json.loads((tmp_path / "artifact_report.json").read_text(encoding="utf-8"))
    assert report["self_check"]["ok"] is True
    assert report["integrity"]["ok"] is True
    assert report["comparison"]["ok"] is True
    assert report["determinism"]["identical"] is True
    ledger = json.loads((tmp_path / "13_degradations.json").read_text(encoding="utf-8"))
    assert [row["feature"] for row in ledger["degradations"]] == ["auto-layout"]


def test_strict_ir_blocks_before_anything_is_rendered(tmp_path: Path) -> None:
    module = _script()
    broken = _design()
    broken["elements"][1]["width"] = 0

    try:
        module._gate(
            dsn=broken,
            output=tmp_path,
            tool="axure",
            strict=True,
            source_kind="image",
            reference=None,
        )
    except SystemExit as exit_code:
        assert exit_code.code == 3
    else:  # pragma: no cover - the assertion below is the point
        raise AssertionError("strict gate did not block")

    assert not (tmp_path / "prototype.rp").exists()
    assert (tmp_path / "ir_gate.json").is_file()
