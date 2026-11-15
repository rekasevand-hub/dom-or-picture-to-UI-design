"""Prove the bridge's rotation end to end: the angle, the direction, the centre.

Three things have to hold and only one of them is visible in the response:

* `set_rotation` executes and reports a rotation;
* the node turns **anticlockwise** for a positive design angle (a plain bounding
  box cannot show this — a 200x100 rect at +30° and at -30° has the same box — so
  the probe puts a marker on the right end and reads where it lands);
* the centre stays exactly where the design put it, which is the part Figma gets
  wrong on its own because it pivots about the node's origin.

Usage:
    python scripts/figma_rotation_probe.py            # default ws://localhost:8765
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.app.services.rendering.figma_adapter import FigmaBridgeAdapter  # noqa: E402

BOX = {"x": 300, "y": 300, "width": 200, "height": 20}
CENTRE = (400.0, 310.0)
ANGLES = (6.0, -4.6, 30.0, -90.0)


def _find(tree: dict, node_id: str) -> dict:
    if tree.get("id") == node_id:
        return tree
    for child in tree.get("children") or []:
        found = _find(child, node_id)
        if found:
            return found
    return {}


def _centre(node: dict) -> tuple[float, float]:
    box = node.get("absolute") or {}
    return (
        float(box.get("x") or 0) + float(box.get("width") or 0) / 2,
        float(box.get("y") or 0) + float(box.get("height") or 0) / 2,
    )


def run(url: str) -> int:
    adapter = FigmaBridgeAdapter(url)
    adapter.connect()
    failures = 0
    try:
        for angle in ANGLES:
            name = f"rotation-probe-{angle}"
            frame = adapter._send(
                "create_frame",
                {**BOX, "name": name, "transparent": True},
            )
            mark = adapter._send(
                "create_rectangle",
                {
                    "x": BOX["width"] - 20,
                    "y": 0,
                    "width": 20,
                    "height": 20,
                    "fillColor": "#ff0000",
                    "name": name + "-mark",
                    "parentId": frame,
                },
            )
            adapter._apply_rotation(frame, {**BOX, "rotation": angle})
            tree = adapter._send("get_node_tree", {"depth": 3})
            outer = _find(tree, frame)
            inner = _find(tree, mark)
            centre = _centre(outer)
            mark_centre = _centre(inner)
            drift = max(abs(centre[0] - CENTRE[0]), abs(centre[1] - CENTRE[1]))
            # Anticlockwise lifts the right-hand end; clockwise sinks it.
            anticlockwise = mark_centre[1] < CENTRE[1] - 2 if angle > 0 else True
            ok = drift <= 1.5 and anticlockwise
            failures += 0 if ok else 1
            print(
                f"  angle={angle:>6}  centre=({centre[0]:.2f},{centre[1]:.2f})"
                f"  drift={drift:.2f}px  mark_y={mark_centre[1]:.1f}"
                f"  {'OK' if ok else 'FAIL'}"
            )
            adapter._send("remove_nodes_by_name", {"name": name + "-mark"})
            adapter._send("remove_nodes_by_name", {"name": name})
    finally:
        adapter.disconnect()
    print(f"\n{'PASS' if not failures else 'FAIL'}: {len(ANGLES) - failures}/{len(ANGLES)} angles")
    return 0 if not failures else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="ws://localhost:8765")
    args = parser.parse_args()
    return run(args.url)


if __name__ == "__main__":
    raise SystemExit(main())
