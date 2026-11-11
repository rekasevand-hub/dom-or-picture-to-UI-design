"""Read-only rotation evidence for the three benchmark families.

Answers three questions before anything writes a ``rotation`` field:

1. **Is there anything to rotate?**  The gold trees carry no ``rotation``
   field, but a rotated node is still detectable: Figma reports the node's own
   ``width/height`` *and* its axis-aligned ``absolute`` box, and for a tilt of
   ``t`` those differ by ``w·cos t + h·sin t``.  So the pair is an oracle.
2. **Can the tilt be read off the reference pixels?**  ``5.8折`` is one design
   element covering two tilted lines -- the shape that defeats
   ``minAreaRect`` and second moments.  The projection-profile estimator in
   ``measure_element_rotation`` has to survive it.
3. **How noisy is it on upright text?**  A estimator that nudges straight text
   by a degree would rotate the whole page, so the false-positive rate on the
   other two families matters more than the accuracy on the two tilted ones.

Run:
    python scripts/p1_text_rotation_evidence.py
    python scripts/p1_text_rotation_evidence.py --families dark-card-grid

Writes ``output/_p1_text_rotation_evidence/evidence.json``.  Read-only: no
pipeline code runs, no Figma write is issued.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any, Sequence

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.app.services.structure.fidelity.text_calibration import (  # noqa: E402
    measure_element_rotation,
    measure_text_block_lines,
)

FIXTURES = ROOT / "tests" / "fixtures" / "benchmark_families"
OUT = ROOT / "output" / "_p1_text_rotation_evidence"
FAMILIES = ("dark-card-grid", "light-form", "light-table")


def solve_tilt(node_width: float, node_height: float, box_width: float, box_height: float) -> float | None:
    """Tilt implied by a node's own size versus its axis-aligned box.

    For a rotation of ``t``::

        box_w = w·cos t + h·sin t
        box_h = w·sin t + h·cos t

    The pair only fixes ``|t|``: ``cos`` is even, so ``+t`` and ``-t`` give the
    same box.  Direction has to come from the pixels, which is exactly the
    division of labour this probe is checking.

    Args:
        node_width: Node's own width, before rotation.
        node_height: Node's own height, before rotation.
        box_width: Width of the axis-aligned bounding box.
        box_height: Height of the axis-aligned bounding box.

    Returns:
        ``|t|`` in degrees, or ``None`` when the two disagree by less than a
        pixel (i.e. the node is not rotated).
    """
    if node_width <= 2 or node_height <= 2:
        return None
    if abs(box_width - node_width) <= 1.5 and abs(box_height - node_height) <= 1.5:
        return None
    best: tuple[float, float] | None = None
    for hundredths in range(0, 4501):
        degrees = hundredths / 100.0
        radians = math.radians(degrees)
        residual = abs(
            node_width * math.cos(radians) + node_height * math.sin(radians) - box_width
        ) + abs(
            node_width * math.sin(radians) + node_height * math.cos(radians) - box_height
        )
        if best is None or residual < best[0]:
            best = (residual, degrees)
    if best is None:
        return None
    return round(best[1], 2) if best[1] <= 45.0 else None


def gold_rotations(tree: dict[str, Any]) -> list[dict[str, Any]]:
    """Every TEXT node whose own size disagrees with its axis-aligned box."""
    found: list[dict[str, Any]] = []

    def walk(node: dict[str, Any]) -> None:
        if node.get("type") == "TEXT":
            box = node.get("absolute")
            if isinstance(box, dict):
                tilt = solve_tilt(
                    float(node.get("width") or 0),
                    float(node.get("height") or 0),
                    float(box.get("width") or 0),
                    float(box.get("height") or 0),
                )
                if tilt is not None:
                    found.append(
                        {
                            "text": str(node.get("characters") or "")[:24],
                            "tilt_abs": tilt,
                            "node_box": [
                                round(float(node.get("width") or 0), 1),
                                round(float(node.get("height") or 0), 1),
                            ],
                            "absolute_box": [
                                round(float(box.get("width") or 0), 1),
                                round(float(box.get("height") or 0), 1),
                            ],
                        }
                    )
        for child in node.get("children") or []:
            walk(child)

    walk(tree)
    return found


def measure_family(family: str) -> dict[str, Any]:
    """Gold truth, pixel estimates and the mismatch between them, one family."""
    fixture = FIXTURES / family
    meta = json.loads((fixture / "family.json").read_text(encoding="utf-8"))
    run = ROOT / str(meta.get("pipeline_run") or "")
    design_path = run / "pipeline" / "12_design.json"
    if not design_path.is_file():
        return {"family": family, "status": "missing-run"}
    gold = json.loads((fixture / "gold_tree.json").read_text(encoding="utf-8"))
    design = json.loads(design_path.read_text(encoding="utf-8"))
    reference = np.asarray(Image.open(fixture / "reference.png").convert("RGB")).astype(
        np.int16
    )

    estimates: list[dict[str, Any]] = []
    for element in design.get("elements") or []:
        if not isinstance(element, dict):
            continue
        if str(element.get("type") or "") not in {"text", "button"}:
            continue
        if not str(element.get("text") or "").strip():
            continue
        box = [
            float(element.get("x") or 0),
            float(element.get("y") or 0),
            float(element.get("width") or 0),
            float(element.get("height") or 0),
        ]
        if box[2] < 8 or box[3] < 8:
            continue
        measured = measure_element_rotation(reference, box)
        if measured is None:
            continue
        item = {"text": str(element.get("text"))[:24], "box": box, **measured}
        estimates.append(item)
    rotated = [item for item in estimates if abs(item["angle"]) >= 2.5]
    for item in rotated:
        # A tilted multi-line block reports one band until it is levelled, so
        # the line count is measured after deskewing, not from the raw box.
        item["lines"] = measure_text_block_lines(
            reference, item["box"], rotation=item["angle"]
        )
    upright = [abs(item["raw"]) for item in estimates if abs(item["angle"]) < 2.5]
    return {
        "family": family,
        "status": "measured",
        "gold_rotated_nodes": gold_rotations(gold),
        "measured_texts": len(estimates),
        "detected": rotated,
        "upright_abs_tilt": {
            "n": len(upright),
            "max": round(max(upright), 2) if upright else 0.0,
            "p90": round(float(np.percentile(upright, 90)), 2) if upright else 0.0,
        },
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--families",
        nargs="*",
        default=list(FAMILIES),
        help=f"families to probe (default: {' '.join(FAMILIES)})",
    )
    parser.add_argument("--json", default=str(OUT / "evidence.json"))
    args = parser.parse_args(argv)

    report = [measure_family(family) for family in args.families]
    OUT.mkdir(parents=True, exist_ok=True)
    Path(args.json).write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8"
    )

    for family in report:
        if family.get("status") != "measured":
            print(f"{family['family']}: {family.get('status')}")
            continue
        gold = family["gold_rotated_nodes"]
        print(f"\n== {family['family']}")
        print(
            f"   gold: {len(gold)} 个被旋转的 TEXT -> "
            + ", ".join(f"{node['text']}({node['tilt_abs']}°)" for node in gold)
            if gold
            else "   gold: 0 个被旋转的 TEXT"
        )
        print(f"   可测文本 {family['measured_texts']} 条")
        for item in family["detected"]:
            lines = item.get("lines") or {}
            bands = " + ".join(
                f"{band['width']}x{band['height']}" for band in lines.get("bands") or []
            )
            print(
                f"   检测: {item['text']!r} {item['angle']:+.2f}° "
                f"(gain {item['gain']}, ink {item['ink']}) -> "
                f"{lines.get('line_count', '?')} 行: {bands or '不可测'}"
            )
        quiet = family["upright_abs_tilt"]
        print(
            f"   直立文本 {quiet['n']} 条，raw |角度| max {quiet['max']} p90 {quiet['p90']}"
        )
    print(f"\n[out] {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
