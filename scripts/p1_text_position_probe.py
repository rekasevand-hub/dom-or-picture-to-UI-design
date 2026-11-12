# -*- coding: utf-8 -*-
"""P1 evidence: where the text run sits, versus where the reference puts it.

Read-only.  Consumes a finished run directory; never renders, never writes to
Figma, never touches the pipeline.

The native-text gate compares the *rendered* ink box with the *reference* ink
box and allows 2 px.  On the content-review holdout the errors split into two
clusters (``dx`` = -5 on the left column, +2 on the right), so this probe asks
the three questions the handoff left open:

1. **Left slack** -- how far the first glyph starts inside the element box
   (``reference run x - element x``).  If the emitter puts text at the box
   origin, this slack is exactly the error it introduces.
2. **Renderer bearing** -- how far the first glyph starts inside the emitted
   node (``rendered run x - element x``).
3. **Is the slack constant per container?**  If it were, one constant per card
   would fix the page; if it is not, the correction has to be per element.

It then runs the proposed meter (``_text_run_box``) on both images and checks
that ``reference - rendered`` reproduces ``-deltaX/-deltaY`` from the gate,
which is what a per-element correction would apply.

Usage:
  python scripts/p1_text_position_probe.py --run-dir output/_p21_weight2 \
      --label holdout4 [--json out.json]
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Mapping

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.app.services.structure.fidelity.text_calibration import (  # noqa: E402
    _text_run_box,
)

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _gray(path: Path) -> np.ndarray:
    with Image.open(path) as source:
        return np.asarray(source.convert("L"), dtype=np.int16)


def _discover(run_dir: Path) -> tuple[Path, Path]:
    acceptance = _load(run_dir / "acceptance.json")
    reference = Path(str((acceptance.get("visual") or {}).get("reference") or ""))
    export = (acceptance.get("artifacts") or {}).get("export") or ""
    rendered = run_dir / str(export).replace("\\", "/")
    if not reference.is_file():
        raise SystemExit(f"reference image missing: {reference}")
    if not rendered.is_file():
        raise SystemExit(f"rendered image missing: {rendered}")
    return reference, rendered


def _box(element: Mapping[str, Any]) -> list[float] | None:
    try:
        x = float(element.get("x") or 0)
        y = float(element.get("y") or 0)
        width = float(element.get("width") or 0)
        height = float(element.get("height") or 0)
    except (TypeError, ValueError):
        return None
    if width <= 0 or height <= 0:
        return None
    return [x, y, width, height]


def _container_of(
    element: Mapping[str, Any], containers: list[Mapping[str, Any]]
) -> str:
    try:
        cx = float(element.get("x") or 0) + float(element.get("width") or 0) / 2
        cy = float(element.get("y") or 0) + float(element.get("height") or 0) / 2
    except (TypeError, ValueError):
        return "-"
    inside = []
    for holder in containers:
        box = _box(holder)
        if box is None:
            continue
        if box[0] <= cx <= box[0] + box[2] and box[1] <= cy <= box[1] + box[3]:
            inside.append(
                (box[2] * box[3], str(holder.get("name") or holder.get("id")))
            )
    if not inside:
        return "-"
    return min(inside)[1]


def _verdict(
    reference_run: tuple[int, int, int, int] | None,
    rendered_run: tuple[int, int, int, int] | None,
    size: float,
) -> tuple[str, tuple[int, int] | None]:
    if reference_run is None or rendered_run is None:
        return "no-run", None
    if reference_run[2] < 0.6 * size or rendered_run[2] < 0.6 * size:
        # A run narrower than a glyph is a fragment of a stroke or a rule.
        return "run-too-short", None
    if abs(reference_run[3] - rendered_run[3]) > max(3.0, 0.3 * size):
        return "height-mismatch", None
    delta_x = reference_run[0] - rendered_run[0]
    delta_y = reference_run[1] - rendered_run[1]
    if abs(delta_x) > 0.75 * size or abs(delta_y) > 0.75 * size:
        return "delta-too-large", (delta_x, delta_y)
    if abs(delta_x) < 0.5 and abs(delta_y) < 0.5:
        return "aligned", (delta_x, delta_y)
    return "move", (delta_x, delta_y)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--label", default="")
    parser.add_argument("--json", default="")
    args = parser.parse_args()

    run_dir = Path(args.run_dir).resolve()
    reference_path, rendered_path = _discover(run_dir)
    reference = _gray(reference_path)
    rendered = _gray(rendered_path)

    design = _load(run_dir / "figma_design.json")
    elements = [item for item in design.get("elements") or [] if isinstance(item, dict)]
    by_ref = {
        str(item.get("contentRef")): item for item in elements if item.get("contentRef")
    }
    containers = [
        item for item in elements if str(item.get("type")) in {"container", "rectangle"}
    ]
    quality = _load(run_dir / "native_text_quality.json")
    owners = [
        owner
        for owner in quality.get("owners") or []
        if isinstance(owner, dict) and owner.get("ownerScope") == "critical-gate"
    ]

    rows: list[dict[str, Any]] = []
    for owner in owners:
        element = by_ref.get(str(owner.get("contentRef")))
        if not element or str(element.get("type")) != "text":
            continue
        box = _box(element)
        if box is None:
            continue
        size = float((element.get("style") or {}).get("fontSize") or 16)
        reference_run = _text_run_box(reference, box, size)
        rendered_run = _text_run_box(rendered, box, size)
        verdict, delta = _verdict(reference_run, rendered_run, size)
        slack = None if reference_run is None else reference_run[0] - int(round(box[0]))
        bearing = None if rendered_run is None else rendered_run[0] - int(round(box[0]))
        rows.append(
            {
                "text": str(owner.get("text") or "")[:28],
                "container": _container_of(element, containers),
                "box": [round(value) for value in box],
                "size": size,
                "gate": [owner.get("deltaX"), owner.get("deltaY")],
                "slack": slack,
                "bearing": bearing,
                "reference_run": list(reference_run) if reference_run else None,
                "rendered_run": list(rendered_run) if rendered_run else None,
                "delta": list(delta) if delta else None,
                "verdict": verdict,
            }
        )

    print(f"== {args.label or run_dir.name}")
    print(f"   reference {reference_path}")
    print(f"   rendered  {rendered_path}")
    print(
        "%-26s %-10s %3s %7s %7s %9s  %-16s %s"
        % (
            "text",
            "container",
            "fs",
            "slack",
            "bearing",
            "pred dxy",
            "verdict",
            "gate dxy",
        )
    )
    for row in rows:
        print(
            "%-26s %-10s %3.0f %7s %7s %9s  %-16s %s"
            % (
                row["text"],
                row["container"][:10],
                row["size"],
                row["slack"],
                row["bearing"],
                row["delta"],
                row["verdict"],
                row["gate"],
            )
        )

    buckets: dict[str, list[int]] = defaultdict(list)
    for row in rows:
        if row["slack"] is not None:
            buckets[row["container"]].append(int(row["slack"]))
    print("\n-- 左侧 slack 按容器分组（问题 3：是否 per-container 常量）")
    for name, values in sorted(buckets.items()):
        spread = max(values) - min(values)
        print(
            "   %-12s n=%2d  %s  极差 %d" % (name, len(values), sorted(values), spread)
        )

    moving = [row for row in rows if row["verdict"] == "move"]
    blocked = [row for row in rows if row["verdict"] not in {"move", "aligned"}]
    print(
        "\n-- 可修 %d / %d 条；拒绝 %d 条 (%s)"
        % (
            len(moving),
            len(rows),
            len(blocked),
            ", ".join(sorted({row["verdict"] for row in blocked})) or "-",
        )
    )
    residual = 0
    for row in moving:
        predicted = [
            (row["gate"][0] or 0) + row["delta"][0],
            (row["gate"][1] or 0) + row["delta"][1],
        ]
        residual += 1
        print(
            "   %-26s 平移 %s → 预计 dx/dy %s" % (row["text"], row["delta"], predicted)
        )
    print(f"   合计平移 {residual} 条")

    if args.json:
        Path(args.json).write_text(
            json.dumps(
                {"label": args.label, "rows": rows}, ensure_ascii=False, indent=1
            ),
            encoding="utf-8",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
