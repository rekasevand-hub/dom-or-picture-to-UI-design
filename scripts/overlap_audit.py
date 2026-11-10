"""Deterministic overlap audit: find the "jarring" defects VLM judges report.

The aesthetic report (``vlm_aesthetic_report.py``) keeps flagging overlaps that
the numeric gate never sees: a search placeholder painted across a nav label, a
price sitting inside a card title, a status button on top of a user name.  Those
are geometry, not semantics, so they do not need a model -- this script finds
them from the design layer alone, at zero token cost, and freezes the result
next to the run.

Severity is deliberately conservative:

* ``overlap`` -- two sibling owners cover >= 30 % of the smaller box;
* ``overflow`` -- a text box is narrower than its estimated glyph run by 25 %,
  which is how a 58 px input ended up painting 22 characters over its
  neighbours.

Containers are excluded (they are parents by design), as are images covering
more than 5 % of the canvas (backgrounds sit *behind* text on purpose).  The
report is advisory: overlap can be intentional, so each pair is listed for a
human or the VLM judge to confirm.

Usage::

    python scripts/overlap_audit.py --family dark-card-grid
    python scripts/overlap_audit.py --family light-table --min-ratio 0.5
"""

from __future__ import annotations

import argparse
import itertools
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
FAMILIES = ROOT / "tests/fixtures/benchmark_families"
TEXT_TYPES = {"text", "button", "input", "link"}


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _design_path(family: str, run: str | None) -> Path:
    if run:
        run_dir = Path(run)
    elif (ROOT / "output/_benchmark_families/rerun" / family).is_dir():
        run_dir = ROOT / "output/_benchmark_families/rerun" / family
    else:
        meta = _read_json(FAMILIES / family / "family.json")
        run_dir = ROOT / str(meta.get("pipeline_run") or "")
    for name in ("pipeline/12_design.json", "figma_design.json"):
        path = run_dir / name
        if path.is_file():
            return path
    raise SystemExit(f"no design under {run_dir}")


def _readback_path(family: str, run: str | None) -> Path | None:
    """The rendered tree is the truth after calibration.

    ``pipeline/12_design.json`` is the *prepared* design: a strategy that drops
    a phantom owner changes the written design, not this file.  Auditing the
    prepared file keeps reporting defects that the render no longer has.
    """
    if run:
        run_dir = Path(run)
    elif (ROOT / "output/_benchmark_families/rerun" / family).is_dir():
        run_dir = ROOT / "output/_benchmark_families/rerun" / family
    else:
        meta = _read_json(FAMILIES / family / "family.json")
        run_dir = ROOT / str(meta.get("pipeline_run") or "")
    preferred = run_dir / "figma_ink_converged/readback.json"
    if preferred.is_file():
        return preferred
    candidates = sorted(run_dir.glob("figma*/readback.json"))
    return candidates[-1] if candidates else None


def _elements_from_readback(path: Path) -> list[dict[str, Any]]:
    """Flatten a readback tree into canvas-space boxes."""
    tree = _read_json(path)
    origin = tree.get("absolute") or {}
    ox = float(origin.get("x") or 0)
    oy = float(origin.get("y") or 0)
    elements: list[dict[str, Any]] = []

    def walk(node: dict[str, Any]) -> None:
        box = node.get("absolute") or {}
        x = float(box.get("x") or 0) - ox
        y = float(box.get("y") or 0) - oy
        width = float(box.get("width") or 0)
        height = float(box.get("height") or 0)
        node_type = str(node.get("type") or "")
        if node_type == "TEXT" and str(node.get("characters") or "").strip():
            elements.append(
                {
                    "type": "text",
                    "text": str(node.get("characters") or ""),
                    "x": x,
                    "y": y,
                    "width": width,
                    "height": height,
                    "style": {"fontSize": node.get("fontSize")},
                }
            )
        elif any(
            str(fill.get("type") or "") == "IMAGE" for fill in node.get("fills") or []
        ):
            elements.append(
                {
                    "type": "image",
                    "text": "",
                    "x": x,
                    "y": y,
                    "width": width,
                    "height": height,
                }
            )
        for child in node.get("children") or []:
            if isinstance(child, dict):
                walk(child)

    walk(tree)
    return elements


def _rect(element: dict[str, Any]) -> tuple[float, float, float, float]:
    x = float(element.get("x") or 0)
    y = float(element.get("y") or 0)
    return x, y, x + float(element.get("width") or 0), y + float(element.get("height") or 0)


def _area(rect: tuple[float, float, float, float]) -> float:
    return max(0.0, rect[2] - rect[0]) * max(0.0, rect[3] - rect[1])


def _intersection(
    a: tuple[float, float, float, float], b: tuple[float, float, float, float]
) -> float:
    return max(0.0, min(a[2], b[2]) - max(a[0], b[0])) * max(
        0.0, min(a[3], b[3]) - max(a[1], b[1])
    )


def _glyph_width(text: str, font_size: float) -> float:
    """Rough advance width: CJK ~1.0 em, latin ~0.55 em."""
    total = 0.0
    for char in text:
        total += 1.0 if ord(char) > 0x2E80 else 0.55
    return total * font_size


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--family", required=True)
    parser.add_argument("--run", default=None)
    parser.add_argument("--min-ratio", type=float, default=0.3)
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    design_path = _design_path(args.family, args.run)
    design = _read_json(design_path)
    canvas = design.get("canvas") or {}
    canvas_area = float(canvas.get("width") or 0) * float(canvas.get("height") or 0)
    readback_path = _readback_path(args.family, args.run)
    if readback_path is not None:
        elements = _elements_from_readback(readback_path)
        source_path = readback_path
        source_kind = "readback"
    else:
        elements = [
            element
            for element in design.get("elements") or []
            if isinstance(element, dict)
            and element.get("width")
            and element.get("height")
            and str(element.get("type") or "") in TEXT_TYPES | {"image"}
        ]
        source_path = design_path
        source_kind = "design"

    overlaps: list[dict[str, Any]] = []
    for left, right in itertools.combinations(elements, 2):
        box_left, box_right = _rect(left), _rect(right)
        area = _intersection(box_left, box_right)
        if area <= 0:
            continue
        smaller = min(_area(box_left), _area(box_right))
        if smaller <= 0:
            continue
        ratio = area / smaller
        if ratio < args.min_ratio:
            continue
        left_text = str(left.get("text") or "").strip()
        right_text = str(right.get("text") or "").strip()
        left_type = str(left.get("type") or "")
        right_type = str(right.get("type") or "")
        if left_type == "image" or right_type == "image":
            image = left if left_type == "image" else right
            other = right if image is left else left
            if not str(other.get("text") or "").strip():
                continue
            if canvas_area and _area(_rect(image)) > 0.05 * canvas_area:
                continue
            kind = "image-over-text"
        elif left_text and right_text:
            kind = "text-over-text"
        else:
            continue
        overlaps.append(
            {
                "kind": kind,
                "ratio": round(ratio, 3),
                "left": {
                    "type": left_type,
                    "text": left_text[:32] or None,
                    "bbox": [round(value, 1) for value in box_left],
                },
                "right": {
                    "type": right_type,
                    "text": right_text[:32] or None,
                    "bbox": [round(value, 1) for value in box_right],
                },
            }
        )

    overflows: list[dict[str, Any]] = []
    for element in elements:
        if str(element.get("type") or "") not in TEXT_TYPES:
            continue
        text = str(element.get("text") or "").strip()
        if not text:
            continue
        style = element.get("style") or {}
        size = style.get("fontSize")
        if not isinstance(size, (int, float)) or size <= 0:
            continue
        width = float(element.get("width") or 0)
        expected = _glyph_width(text, float(size))
        if width <= 0 or expected <= 0:
            continue
        if expected / width >= 1.25:
            overflows.append(
                {
                    "text": text[:32],
                    "bbox": [round(value, 1) for value in _rect(element)],
                    "box_width": round(width, 1),
                    "expected_width": round(expected, 1),
                    "ratio": round(expected / width, 2),
                    "font_size": round(float(size), 2),
                    "type": str(element.get("type") or ""),
                }
            )

    overlaps.sort(key=lambda item: item["ratio"], reverse=True)
    overflows.sort(key=lambda item: item["ratio"], reverse=True)
    report = {
        "schema_version": "overlap-audit/1.0",
        "family": args.family,
        "design": str(design_path),
        "source": {"kind": source_kind, "path": str(source_path)},
        "min_ratio": args.min_ratio,
        "counts": {
            "overlaps": len(overlaps),
            "text_over_text": sum(1 for item in overlaps if item["kind"] == "text-over-text"),
            "image_over_text": sum(
                1 for item in overlaps if item["kind"] == "image-over-text"
            ),
            "overflows": len(overflows),
        },
        "overlaps": overlaps,
        "overflows": overflows,
    }
    out_dir = Path(args.out) if args.out else design_path.parents[1] / "overlap_audit"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "report.json"
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(
        f"{args.family}: overlaps={report['counts']['overlaps']} "
        f"(text/text {report['counts']['text_over_text']}, "
        f"image/text {report['counts']['image_over_text']}) "
        f"overflows={report['counts']['overflows']}"
    )
    for item in overlaps[:6]:
        left = item["left"]
        right = item["right"]
        print(
            f"  {item['ratio']:.2f} {left['type']}:{(left['text'] or '-')[:14]!r} "
            f"x {right['type']}:{(right['text'] or '-')[:14]!r}"
        )
    for item in overflows[:4]:
        print(
            f"  overflow {item['ratio']:.2f} {item['type']}:{item['text'][:14]!r} "
            f"box={item['box_width']} expected={item['expected_width']}"
        )
    print(f"report: {out_path}")


if __name__ == "__main__":
    main()
